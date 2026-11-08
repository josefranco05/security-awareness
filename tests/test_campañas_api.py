"""Campañas y simulaciones: alta, envío, permisos y borrado.

Los tests corren con Celery en modo eager y EMAIL_BACKEND=log: crear la campaña la envía en el acto.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from database.worker_db import SessionLocal
import models
from tests.conftest import ORIGEN, crear_usuario, sesion
from worker import tasks

URL = "/api/campañas"
URL_SIMULACIONES = "/api/simulaciones"


@pytest.fixture
def uid(anonimo) -> int:
    return crear_usuario("ana")[0]


def _empleado(owner, email="e@example.com", estado=True) -> UUID:
    with SessionLocal() as db:
        empleado = models.Empleados(owner=owner, nombre="e", email=email, riesgo=50, empresa="x", estado=estado)
        db.add(empleado)
        db.commit()
        return empleado.eeid


def _datos(destinatarios, **cambios):
    return {
        "nombre": "Mayo", "remitente": "rrhh@example.com", "asunto": "Bono", "cuerpo": "<p>Hola</p>",
        "destinatarios": [str(d) for d in destinatarios], **cambios,
    }


def _crear(cliente, uid, destinatarios, **cambios):
    return cliente.post(URL, headers=sesion(uid), json=_datos(destinatarios, **cambios))


def _camid(r) -> UUID:
    return UUID(r.json()["camid"])


def _simulaciones(camid: UUID | None = None) -> list[models.Simulaciones]:
    with SessionLocal() as db:
        consulta = db.query(models.Simulaciones)
        if camid is not None:
            consulta = consulta.filter_by(campana_id=camid)
        return consulta.order_by(models.Simulaciones.id).all()


def _campaña_pendiente(owner, n=1) -> UUID:
    """Campaña con `n` simulaciones en pending, creada sin pasar por la API (no se envía)."""
    with SessionLocal() as db:
        campaña = models.Campaña(owner=owner, nombre="Pendiente", remitente="r@example.com", asunto="a", cuerpo="c")
        db.add(campaña)
        db.flush()
        for i in range(n):
            empleado = models.Empleados(owner=owner, nombre="e", email=f"p{campaña.camid}-{i}@example.com", riesgo=0, empresa="x")
            db.add(empleado)
            db.flush()
            db.add(models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid))
        db.commit()
        return campaña.camid


@pytest.fixture
def encolados(monkeypatch) -> list[str]:
    """Sustituye el encolado: registra el camid (como viaja por la cola: texto) en vez de enviar."""
    llamadas: list[str] = []
    monkeypatch.setattr(tasks.enviar_campaña, "delay", llamadas.append)
    return llamadas


@pytest.fixture
def broker_caido(monkeypatch):
    def fallar(*_):
        raise ConnectionError("redis no responde")

    monkeypatch.setattr(tasks.enviar_campaña, "delay", fallar)


# --- crear ------------------------------------------------------------------------------

def test_crear_campaña_crea_una_simulacion_por_destinatario_y_la_envia(anonimo, uid):
    a, b = _empleado(uid, "a@example.com"), _empleado(uid, "b@example.com")
    r = _crear(anonimo, uid, [a, b])
    assert r.status_code == 201
    camid = _camid(r)
    assert set(r.json()) == {"camid", "nombre", "fecha"}
    sims = _simulaciones(camid)
    assert sorted(s.ee_id for s in sims) == sorted([a, b])
    assert all(s.status == "sent" and s.fecha_envio and s.intentos == 1 and s.proveedor_id for s in sims)
    with SessionLocal() as db:
        assert db.get(models.Campaña, camid).owner == uid


def test_destinatarios_repetidos_cuentan_una_vez(anonimo, uid, encolados):
    a = _empleado(uid)
    camid = _camid(_crear(anonimo, uid, [a, a, a]))
    assert len(_simulaciones(camid)) == 1
    assert encolados == [str(camid)]


def test_sin_destinatarios_da_400(anonimo, uid):
    assert _crear(anonimo, uid, []).status_code == 400
    with SessionLocal() as db:
        assert db.query(models.Campaña).count() == 0


@pytest.mark.parametrize("caso", ["ajeno", "inactivo", "inexistente"])
def test_destinatario_no_valido_da_400_y_no_crea_nada(anonimo, uid, caso):
    propio = _empleado(uid, "propio@example.com")
    otro, _ = crear_usuario("beto")
    malo = {
        "ajeno": lambda: _empleado(otro, "ajeno@example.com"),
        "inactivo": lambda: _empleado(uid, "inactivo@example.com", estado=False),
        "inexistente": uuid4,
    }[caso]()
    assert _crear(anonimo, uid, [propio, malo]).status_code == 400
    with SessionLocal() as db:
        assert db.query(models.Campaña).count() == 0
    assert _simulaciones() == []


@pytest.mark.parametrize("cambios", [{"nombre": ""}, {"nombre": "a" * 101}, {"remitente": "no-es-email"}])
def test_crear_valida_los_campos(anonimo, uid, cambios):
    assert _crear(anonimo, uid, [_empleado(uid)], **cambios).status_code == 422


@pytest.mark.parametrize("destinatarios", [[1], ["abc"], [None]])
def test_destinatarios_que_no_son_uuid_dan_422(anonimo, uid, destinatarios):
    r = anonimo.post(URL, headers=sesion(uid), json={**_datos([]), "destinatarios": destinatarios})
    assert r.status_code == 422


def test_con_el_broker_caido_la_campaña_se_crea_igual(anonimo, uid, broker_caido, caplog):
    r = _crear(anonimo, uid, [_empleado(uid)])
    assert r.status_code == 201
    [sim] = _simulaciones(_camid(r))
    assert sim.status == "pending"  # el barrido la enviará
    assert "No se pudo encolar" in caplog.text


def test_crear_exige_sesion(anonimo, uid):
    r = anonimo.post(URL, headers={"Origin": ORIGEN}, json=_datos([_empleado(uid)]))
    assert r.status_code == 401


# --- enviar ahora -----------------------------------------------------------------------

def test_enviar_encola_las_pendientes(anonimo, uid, encolados):
    camid = _campaña_pendiente(uid, n=2)
    r = anonimo.post(f"{URL}/{camid}/enviar", headers=sesion(uid))
    assert r.status_code == 200
    assert r.json() == {"camid": str(camid), "pendientes": 2, "encolado": True}
    assert encolados == [str(camid)]


def test_enviar_sin_pendientes_da_409(anonimo, uid, encolados):
    camid = _camid(_crear(anonimo, uid, [_empleado(uid)]))
    encolados.clear()
    with SessionLocal() as db:
        db.query(models.Simulaciones).update({"status": "sent"})
        db.commit()
    assert anonimo.post(f"{URL}/{camid}/enviar", headers=sesion(uid)).status_code == 409
    assert encolados == []


def test_enviar_con_el_broker_caido_da_503(anonimo, uid, broker_caido):
    camid = _campaña_pendiente(uid)
    assert anonimo.post(f"{URL}/{camid}/enviar", headers=sesion(uid)).status_code == 503


# --- leer y borrar ----------------------------------------------------------------------

def test_listar_solo_las_propias_mas_recientes_primero(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _crear(anonimo, otro, [_empleado(otro)], nombre="Ajena")
    _crear(anonimo, uid, [_empleado(uid, "a@example.com")], nombre="Vieja", fecha="2026-01-01T00:00:00Z")
    _crear(anonimo, uid, [_empleado(uid, "b@example.com")], nombre="Nueva", fecha="2026-06-01T00:00:00Z")
    r = anonimo.get(URL, headers=sesion(uid))
    assert [c["nombre"] for c in r.json()] == ["Nueva", "Vieja"]


@pytest.mark.parametrize("metodo, ruta", [
    ("GET", "{url}/{camid}"),
    ("DELETE", "{url}/{camid}"),
    ("POST", "{url}/{camid}/enviar"),
    ("GET", "/api/simulaciones/{camid}"),
])
def test_la_campaña_de_otro_da_404(anonimo, uid, encolados, metodo, ruta):
    otro, _ = crear_usuario("beto")
    camid = _campaña_pendiente(otro)
    r = anonimo.request(metodo, ruta.format(url=URL, camid=camid), headers=sesion(uid))
    assert r.status_code == 404
    assert encolados == []
    with SessionLocal() as db:
        assert db.get(models.Campaña, camid) is not None


def test_borrar_la_campaña_borra_sus_simulaciones_pero_no_los_empleados(anonimo, uid):
    eeid = _empleado(uid)
    camid = _camid(_crear(anonimo, uid, [eeid]))
    assert anonimo.delete(f"{URL}/{camid}", headers=sesion(uid)).status_code == 204
    assert _simulaciones() == []
    with SessionLocal() as db:
        assert db.get(models.Campaña, camid) is None
        assert db.get(models.Empleados, eeid) is not None


# --- simulaciones -----------------------------------------------------------------------

def test_listar_simulaciones_solo_las_de_mis_campañas(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _campaña_pendiente(otro, n=2)
    propia = _campaña_pendiente(uid, n=3)
    r = anonimo.get(URL_SIMULACIONES, headers=sesion(uid))
    assert r.status_code == 200
    assert len(r.json()) == 3 and {s["campana_id"] for s in r.json()} == {str(propia)}


def test_simulaciones_de_una_campaña(anonimo, uid):
    camid = _campaña_pendiente(uid, n=2)
    _campaña_pendiente(uid, n=1)
    r = anonimo.get(f"{URL_SIMULACIONES}/{camid}", headers=sesion(uid))
    assert r.status_code == 200
    assert [s["campana_id"] for s in r.json()] == [str(camid)] * 2
    assert all(s["status"] == "pending" and s["fecha_envio"] is None for s in r.json())


def test_simulaciones_exige_sesion(anonimo):
    assert anonimo.get(URL_SIMULACIONES).status_code == 401


# --- página -----------------------------------------------------------------------------

def test_la_pagina_muestra_solo_mis_campañas(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _crear(anonimo, otro, [_empleado(otro)], nombre="Campaña Ajena")
    _crear(anonimo, uid, [_empleado(uid)], nombre="Campaña Propia")
    r = anonimo.get("/campañas", headers=sesion(uid))
    assert r.status_code == 200
    assert "Campaña Propia" in r.text and "Campaña Ajena" not in r.text
