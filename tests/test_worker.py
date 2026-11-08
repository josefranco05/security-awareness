"""Tareas de envío: reclamo atómico, reintentos, recuperación y barrido."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from core.config import settings
from database.worker_db import SessionLocal
import models
from services.email import ErrorPermanente, ErrorTransitorio
from tests.conftest import crear_usuario
from worker import tasks


@pytest.fixture
def uid(anonimo) -> int:
    return crear_usuario()[0]


def _campaña(owner, estados=("pending",), **extra) -> tuple[UUID, list[UUID]]:
    with SessionLocal() as db:
        campaña = models.Campaña(owner=owner, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
        db.add(campaña)
        db.flush()
        ids = []
        for i, estado in enumerate(estados):
            empleado = models.Empleados(owner=owner, nombre="e", email=f"{campaña.camid}-{i}@example.com", riesgo=0, empresa="x")
            db.add(empleado)
            db.flush()
            sim = models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid, status=estado, **extra)
            db.add(sim)
            db.flush()
            ids.append(sim.id)
        db.commit()
        return campaña.camid, ids


def _sim(sim_id) -> models.Simulaciones:
    with SessionLocal() as db:
        return db.get(models.Simulaciones, sim_id)


@pytest.fixture
def envios(monkeypatch) -> list[tuple[int, str]]:
    """Sustituye el proveedor: registra (sim_id, operation_id) de cada envío."""
    llamadas: list[tuple[int, str]] = []
    monkeypatch.setattr(tasks, "enviar_email", lambda sim, op: llamadas.append((sim.id, op)) or op)
    return llamadas


def _proveedor_que_falla(monkeypatch, error: Exception) -> list[str]:
    operaciones: list[str] = []

    def fallar(sim, op):
        operaciones.append(op)
        raise error

    monkeypatch.setattr(tasks, "enviar_email", fallar)
    return operaciones


# --- enviar_campaña ---------------------------------------------------------------------

def test_envia_las_pendientes(uid, envios):
    camid, [a, b] = _campaña(uid, ["pending", "pending"])
    # Por la cola el id llega como texto.
    assert tasks.enviar_campaña(str(camid)) == {
        "camid": str(camid), "enviados": 2, "fallidos": 0, "reintentables": 0, "omitidas": 0,
    }
    for sim_id in (a, b):
        sim = _sim(sim_id)
        assert (sim.status, sim.intentos, sim.error, sim.locked_at) == ("sent", 1, None, None)
        assert sim.fecha_envio is not None and sim.proveedor_id
    # Cada envío usa el proveedor_id de su fila como Operation-Id.
    assert sorted(envios) == sorted((s, _sim(s).proveedor_id) for s in (a, b))
    assert _sim(a).proveedor_id != _sim(b).proveedor_id


def test_solo_toca_las_pendientes_de_esa_campaña(uid, envios):
    camid, ids = _campaña(uid, ["sent", "failed", "sending", "opened"])
    otra, [otra_sim] = _campaña(uid)
    tasks.enviar_campaña(camid)
    assert envios == []
    assert [_sim(i).status for i in ids] == ["sent", "failed", "sending", "opened"]
    assert _sim(otra_sim).status == "pending"


def test_ejecutarla_dos_veces_no_reenvia(uid, envios):
    camid, _ = _campaña(uid)
    tasks.enviar_campaña(camid)
    tasks.enviar_campaña(camid)
    assert len(envios) == 1


def test_el_reclamo_es_atomico(uid):
    _, [sim_id] = _campaña(uid)
    with SessionLocal() as db:
        assert tasks._reclamar(db, sim_id) is True
        assert tasks._reclamar(db, sim_id) is False
    sim = _sim(sim_id)
    assert sim.status == "sending" and sim.intentos == 1 and sim.locked_at is not None


def test_si_otro_worker_la_reclamo_primero_se_omite(uid, envios, monkeypatch):
    camid, [sim_id] = _campaña(uid)
    original = tasks._reclamar

    def otro_worker_se_adelanta(db, id_):
        with SessionLocal() as otra_sesion:
            original(otra_sesion, id_)
        return original(db, id_)

    monkeypatch.setattr(tasks, "_reclamar", otro_worker_se_adelanta)
    assert tasks.enviar_campaña(camid)["omitidas"] == 1
    assert envios == []


def test_error_transitorio_reintenta_con_el_mismo_id_hasta_el_maximo(uid, monkeypatch):
    camid, [sim_id] = _campaña(uid)
    operaciones = _proveedor_que_falla(monkeypatch, ErrorTransitorio("429"))

    for intento in range(1, settings.EMAIL_MAX_INTENTOS):
        assert tasks.enviar_campaña(camid)["reintentables"] == 1
        sim = _sim(sim_id)
        assert (sim.status, sim.intentos, sim.error, sim.locked_at) == ("pending", intento, "429", None)

    assert tasks.enviar_campaña(camid)["fallidos"] == 1
    sim = _sim(sim_id)
    assert (sim.status, sim.intentos) == ("failed", settings.EMAIL_MAX_INTENTOS)
    # Mismo Operation-Id en todos los intentos: ACS no crea un segundo correo.
    assert len(operaciones) == settings.EMAIL_MAX_INTENTOS and set(operaciones) == {sim.proveedor_id}


def test_error_permanente_falla_sin_reintentar(uid, monkeypatch):
    camid, [sim_id] = _campaña(uid)
    _proveedor_que_falla(monkeypatch, ErrorPermanente("dirección inválida"))
    assert tasks.enviar_campaña(camid)["fallidos"] == 1
    sim = _sim(sim_id)
    assert (sim.status, sim.error, sim.intentos) == ("failed", "dirección inválida", 1)


def test_error_inesperado_falla_sin_reintentar(uid, monkeypatch):
    camid, [sim_id] = _campaña(uid)
    _proveedor_que_falla(monkeypatch, KeyError("x"))
    assert tasks.enviar_campaña(camid)["fallidos"] == 1
    sim = _sim(sim_id)
    assert sim.status == "failed" and sim.error.startswith("Error inesperado")


def test_un_fallo_no_detiene_al_resto(uid, monkeypatch):
    camid, [a, b] = _campaña(uid, ["pending", "pending"])

    def falla_la_primera(sim, op):
        if sim.id == a:
            raise ErrorPermanente("no")
        return op

    monkeypatch.setattr(tasks, "enviar_email", falla_la_primera)
    tasks.enviar_campaña(camid)
    assert (_sim(a).status, _sim(b).status) == ("failed", "sent")


def test_conserva_el_proveedor_id_previo(uid, envios):
    camid, [sim_id] = _campaña(uid, proveedor_id="op-previa")
    tasks.enviar_campaña(camid)
    assert envios == [(sim_id, "op-previa")] and _sim(sim_id).proveedor_id == "op-previa"


# --- _guardar ---------------------------------------------------------------------------

class _BaseBloqueada:
    def __init__(self, fallos):
        self.fallos, self.commits = fallos, 0

    def execute(self, _):
        if self.fallos:
            self.fallos -= 1
            raise OperationalError("update", {}, Exception("database is locked"))

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_guardar_reintenta_si_la_base_esta_bloqueada(monkeypatch):
    esperas = []
    monkeypatch.setattr(tasks.time, "sleep", esperas.append)
    db = _BaseBloqueada(fallos=tasks.GUARDAR_INTENTOS - 1)
    assert tasks._guardar(db, uuid4(), status="sent") is True
    assert db.commits == 1 and esperas == list(range(1, tasks.GUARDAR_INTENTOS))


def test_guardar_se_rinde_y_lo_deja_para_la_recuperacion(monkeypatch, caplog):
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)
    assert tasks._guardar(_BaseBloqueada(fallos=99), uuid4(), status="sent") is False
    assert "queda en 'sending'" in caplog.text


def test_guardar_no_pisa_una_fila_que_ya_no_esta_en_sending(uid):
    _, [sim_id] = _campaña(uid, ["opened"])
    with SessionLocal() as db:
        tasks._guardar(db, sim_id, status="sent")
    assert _sim(sim_id).status == "opened"


# --- recuperar_colgadas -----------------------------------------------------------------

def test_recupera_solo_las_colgadas_hace_tiempo(uid):
    ahora = datetime.now(UTC)
    vieja = ahora - timedelta(minutes=settings.EMAIL_LOCK_TIMEOUT_MINUTOS + 1)
    reciente = ahora - timedelta(minutes=settings.EMAIL_LOCK_TIMEOUT_MINUTOS - 1)
    _, [colgada] = _campaña(uid, ["sending"], locked_at=vieja, proveedor_id="op-1")
    _, [en_curso] = _campaña(uid, ["sending"], locked_at=reciente)
    _, [sin_lock] = _campaña(uid, ["sending"])
    _, [enviada] = _campaña(uid, ["sent"], locked_at=vieja)

    assert tasks.recuperar_colgadas() == 1
    sim = _sim(colgada)
    assert (sim.status, sim.locked_at, sim.proveedor_id) == ("pending", None, "op-1")
    assert [_sim(i).status for i in (en_curso, sin_lock, enviada)] == ["sending", "sending", "sent"]


def test_la_recuperada_se_reenvia_con_el_mismo_id(uid, envios):
    vieja = datetime.now(UTC) - timedelta(minutes=settings.EMAIL_LOCK_TIMEOUT_MINUTOS + 1)
    camid, [sim_id] = _campaña(uid, ["sending"], locked_at=vieja, proveedor_id="op-1", intentos=1)
    tasks.recuperar_colgadas()
    tasks.enviar_campaña(camid)
    assert envios == [(sim_id, "op-1")]
    assert _sim(sim_id).intentos == 2


# --- barrer_pendientes ------------------------------------------------------------------

def test_barrido_encola_cada_campaña_con_pendientes_una_vez(uid, monkeypatch):
    encoladas = []
    monkeypatch.setattr(tasks.enviar_campaña, "delay", encoladas.append)
    con_pendientes, _ = _campaña(uid, ["pending", "pending", "sent"])
    otra, _ = _campaña(uid, ["pending"])
    _campaña(uid, ["sent", "failed"])
    assert tasks.barrer_pendientes() == 2
    # Se encola texto: un UUID no es serializable en JSON.
    assert sorted(encoladas) == sorted([str(con_pendientes), str(otra)])


def test_barrido_respeta_el_limite(uid, monkeypatch):
    encoladas = []
    monkeypatch.setattr(tasks.enviar_campaña, "delay", encoladas.append)
    for _ in range(3):
        _campaña(uid)
    assert tasks.barrer_pendientes(limite=2) == 2 and len(encoladas) == 2
