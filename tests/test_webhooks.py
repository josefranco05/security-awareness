"""Webhook de ACS / Event Grid: secreto, handshake y traducción del informe de entrega."""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from database.worker_db import SessionLocal
import models
from routers import webhooks
from routers.webhooks import EVENTO_ENTREGA, EVENTO_VALIDACION
from tests.conftest import crear_usuario

URL = "/api/webhooks/acs"
SECRETO = {"X-Webhook-Secret": "test-only"}


@pytest.fixture
def sim(anonimo) -> int:
    """Simulación ya enviada a ACS, esperando el informe de entrega."""
    uid, _ = crear_usuario()
    with SessionLocal() as db:
        empleado = models.Empleados(owner=uid, nombre="e", email="e@example.com", riesgo=0, empresa="x")
        campaña = models.Campaña(owner=uid, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
        db.add_all([empleado, campaña])
        db.flush()
        fila = models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid, status="sent", proveedor_id="op-1")
        db.add(fila)
        db.commit()
        return fila.id


def _estado(sim_id) -> tuple[str, str | None]:
    with SessionLocal() as db:
        fila = db.get(models.Simulaciones, sim_id)
        return fila.status, fila.error


def _poner_estado(sim_id, status):
    with SessionLocal() as db:
        db.get(models.Simulaciones, sim_id).status = status
        db.commit()


def _entrega(estado, message_id="op-1", detalle=None) -> dict:
    datos = {"messageId": message_id, "status": estado}
    if detalle:
        datos["deliveryStatusDetails"] = {"statusMessage": detalle}
    return {"eventType": EVENTO_ENTREGA, "data": datos}


def _enviar(cliente, cuerpo, cabeceras=SECRETO):
    return cliente.post(URL, json=cuerpo, headers=cabeceras)


# --- secreto ----------------------------------------------------------------------------

@pytest.mark.parametrize("cabeceras", [{}, {"X-Webhook-Secret": ""}, {"X-Webhook-Secret": "test-onlY"}, {"X-Webhook-Secret": "test-only "}])
def test_sin_el_secreto_correcto_da_401_y_no_cambia_nada(anonimo, sim, cabeceras):
    r = _enviar(anonimo, [_entrega("Bounced")], cabeceras)
    assert r.status_code == 401
    assert _estado(sim) == ("sent", None)


def test_sin_secreto_configurado_rechaza_todo(anonimo, monkeypatch):
    monkeypatch.setattr(webhooks.settings, "ACS_WEBHOOK_SECRET", SecretStr(""))
    assert _enviar(anonimo, [], {"X-Webhook-Secret": ""}).status_code == 401


def test_no_exige_origin(anonimo):
    assert _enviar(anonimo, []).status_code == 200


# --- handshake --------------------------------------------------------------------------

def test_responde_el_handshake_de_suscripcion(anonimo):
    evento = {"eventType": EVENTO_VALIDACION, "data": {"validationCode": "abc-123"}}
    r = _enviar(anonimo, [evento])
    assert r.status_code == 200 and r.json() == {"validationResponse": "abc-123"}


def test_el_handshake_tambien_exige_secreto(anonimo):
    evento = {"eventType": EVENTO_VALIDACION, "data": {"validationCode": "abc-123"}}
    assert _enviar(anonimo, [evento], {}).status_code == 401


# --- informe de entrega -----------------------------------------------------------------

def test_delivered_queda_como_enviado(anonimo, sim):
    _poner_estado(sim, "sending")
    assert _enviar(anonimo, [_entrega("Delivered")]).json() == {"ok": True}
    assert _estado(sim) == ("sent", None)


@pytest.mark.parametrize("estado", ["Bounced", "Suppressed", "Quarantined", "FilteredSpam", "Failed", "Desconocido"])
def test_cualquier_otro_estado_es_fallido(anonimo, sim, estado):
    _enviar(anonimo, [_entrega(estado)])
    assert _estado(sim) == ("failed", estado)


def test_el_fallo_guarda_el_motivo(anonimo, sim):
    _enviar(anonimo, [_entrega("Bounced", detalle="Buzón inexistente")])
    assert _estado(sim) == ("failed", "Buzón inexistente")


def test_un_objeto_suelto_tambien_se_procesa(anonimo, sim):
    _enviar(anonimo, _entrega("Bounced"))
    assert _estado(sim)[0] == "failed"


@pytest.mark.parametrize("evento", [
    _entrega("Expanded"),
    _entrega("Bounced", message_id=None),
    _entrega("Bounced", message_id="otra-operacion"),
    {"eventType": "Microsoft.Communication.EmailEngagementTrackingReportReceived", "data": {"messageId": "op-1"}},
    {"data": {"messageId": "op-1", "status": "Bounced"}},
    "no-es-un-objeto",
    None,
])
def test_eventos_que_no_aplican_se_ignoran(anonimo, sim, evento):
    r = _enviar(anonimo, [evento])
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _estado(sim) == ("sent", None)


@pytest.mark.parametrize("avanzado", ["opened", "clicked", "completed", "pending"])
def test_no_sobreescribe_estados_que_no_son_de_envio(anonimo, sim, avanzado):
    _poner_estado(sim, avanzado)
    _enviar(anonimo, [_entrega("Bounced")])
    assert _estado(sim) == (avanzado, None)


def test_procesa_varios_eventos_de_una_vez(anonimo, sim):
    with SessionLocal() as db:
        original = db.get(models.Simulaciones, sim)
        otra = models.Simulaciones(campana_id=original.campana_id, ee_id=original.ee_id, status="sent", proveedor_id="op-2")
        db.add(otra)
        db.commit()
        otra_id = otra.id
    _enviar(anonimo, [_entrega("Expanded"), _entrega("Bounced"), _entrega("Delivered", message_id="op-2")])
    assert _estado(sim)[0] == "failed"
    assert _estado(otra_id) == ("sent", None)


def test_cuerpo_que_no_es_json_no_falla(anonimo, sim):
    r = anonimo.post(URL, content=b"{roto", headers={**SECRETO, "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"ok": False}
    assert _estado(sim) == ("sent", None)
