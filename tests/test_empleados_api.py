"""CRUD de empleados: solo los propios, email único por dueño."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from database.worker_db import SessionLocal
import models
from tests.conftest import ORIGEN, crear_usuario, sesion

URL = "/api/empleados"
EMPLEADO = {"nombre": "Luis", "email": "luis@example.com", "empresa": "Acme", "cargo": "Contador"}


@pytest.fixture
def uid(anonimo) -> int:
    return crear_usuario("ana")[0]


def _crear(cliente, uid, **cambios):
    return cliente.post(URL, headers=sesion(uid), json={**EMPLEADO, **cambios})


def _en_base(eeid: str | UUID) -> models.Empleados | None:
    """Acepta el id tal como lo devuelve la API (texto)."""
    with SessionLocal() as db:
        return db.get(models.Empleados, UUID(str(eeid)))


# --- crear ------------------------------------------------------------------------------

def test_crear_empleado(anonimo, uid):
    r = _crear(anonimo, uid)
    assert r.status_code == 201
    datos = r.json()
    assert {k: datos[k] for k in EMPLEADO} == EMPLEADO
    fila = _en_base(datos["eeid"])
    assert fila.owner == uid and fila.riesgo == 100 and fila.estado is True


def test_el_dueño_sale_de_la_sesion_no_del_cuerpo(anonimo, uid):
    otro, _ = crear_usuario("beto")
    r = _crear(anonimo, uid, owner=str(otro))
    assert _en_base(r.json()["eeid"]).owner == uid


def test_email_repetido_del_mismo_dueño_da_400(anonimo, uid):
    assert _crear(anonimo, uid).status_code == 201
    assert _crear(anonimo, uid, email="LUIS@example.com").status_code == 400


def test_otro_dueño_puede_usar_el_mismo_email(anonimo, uid):
    otro, _ = crear_usuario("beto")
    assert _crear(anonimo, uid).status_code == 201
    assert _crear(anonimo, otro).status_code == 201


@pytest.mark.parametrize("cambios", [
    {"riesgo": -1},
    {"riesgo": 101},
    {"email": "no-es-email"},
    {"empresa": ""},
])
def test_crear_valida_los_campos(anonimo, uid, cambios):
    assert _crear(anonimo, uid, **cambios).status_code == 422


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_exige_sesion(anonimo, metodo):
    assert anonimo.request(metodo.upper(), URL, headers={"Origin": ORIGEN}, json=EMPLEADO).status_code == 401


# --- leer -------------------------------------------------------------------------------

def test_listar_solo_los_propios_ordenados_por_riesgo(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _crear(anonimo, otro, email="ajeno@example.com", riesgo=100)
    bajo = _crear(anonimo, uid, email="bajo@example.com", riesgo=10).json()["eeid"]
    alto = _crear(anonimo, uid, email="alto@example.com", riesgo=90).json()["eeid"]
    medio = _crear(anonimo, uid, email="medio@example.com", riesgo=50).json()["eeid"]
    r = anonimo.get(URL, headers=sesion(uid))
    assert r.status_code == 200
    assert [e["eeid"] for e in r.json()] == [alto, medio, bajo]


def test_leer_uno_propio(anonimo, uid):
    eeid = _crear(anonimo, uid).json()["eeid"]
    r = anonimo.get(f"{URL}/{eeid}", headers=sesion(uid))
    assert r.status_code == 200 and r.json()["eeid"] == eeid


# --- de otro: 404 en todo ---------------------------------------------------------------

@pytest.mark.parametrize("metodo, cuerpo", [
    ("get", None),
    ("put", {**EMPLEADO, "nombre": "Cambiado"}),
    ("patch", {"nombre": "Cambiado"}),
    ("delete", None),
])
def test_el_empleado_de_otro_da_404(anonimo, uid, metodo, cuerpo):
    otro, _ = crear_usuario("beto")
    eeid = _crear(anonimo, otro).json()["eeid"]
    kwargs = {"json": cuerpo} if cuerpo else {}
    assert anonimo.request(metodo.upper(), f"{URL}/{eeid}", headers=sesion(uid), **kwargs).status_code == 404
    fila = _en_base(eeid)
    assert fila is not None and fila.nombre == "Luis"


def test_un_id_inexistente_da_404(anonimo, uid):
    assert anonimo.get(f"{URL}/{uuid4()}", headers=sesion(uid)).status_code == 404


def test_un_id_que_no_es_uuid_da_422(anonimo, uid):
    assert anonimo.get(f"{URL}/1", headers=sesion(uid)).status_code == 422


# --- reemplazar (PUT) -------------------------------------------------------------------

def test_reemplazar_cambia_todo(anonimo, uid):
    eeid = _crear(anonimo, uid).json()["eeid"]
    nuevo = {"nombre": "Luisa", "email": "luisa@example.com", "empresa": "Otra", "cargo": None, "riesgo": 5, "estado": False}
    r = anonimo.put(f"{URL}/{eeid}", headers=sesion(uid), json=nuevo)
    assert r.status_code == 200
    fila = _en_base(eeid)
    assert (fila.nombre, fila.email, fila.empresa, fila.riesgo, fila.estado) == ("Luisa", "luisa@example.com", "Otra", 5, False)
    assert fila.cargo is None and r.json()["cargo"] is None


def test_reemplazar_con_su_propio_email_no_es_duplicado(anonimo, uid):
    eeid = _crear(anonimo, uid).json()["eeid"]
    assert anonimo.put(f"{URL}/{eeid}", headers=sesion(uid), json={**EMPLEADO, "nombre": "X"}).status_code == 200


def test_reemplazar_con_el_email_de_otro_empleado_da_400(anonimo, uid):
    _crear(anonimo, uid, email="ocupado@example.com")
    eeid = _crear(anonimo, uid).json()["eeid"]
    r = anonimo.put(f"{URL}/{eeid}", headers=sesion(uid), json={**EMPLEADO, "email": "ocupado@example.com"})
    assert r.status_code == 400
    assert _en_base(eeid).email == "luis@example.com"


# --- editar (PATCH) ---------------------------------------------------------------------

def test_editar_cambia_solo_lo_enviado(anonimo, uid):
    eeid = _crear(anonimo, uid, riesgo=40).json()["eeid"]
    r = anonimo.patch(f"{URL}/{eeid}", headers=sesion(uid), json={"estado": False})
    assert r.status_code == 200
    fila = _en_base(eeid)
    assert fila.estado is False and fila.riesgo == 40 and fila.nombre == "Luis"


def test_editar_sin_cambios_da_400(anonimo, uid):
    eeid = _crear(anonimo, uid).json()["eeid"]
    assert anonimo.patch(f"{URL}/{eeid}", headers=sesion(uid), json={}).status_code == 400


def test_editar_al_email_de_otro_empleado_da_400(anonimo, uid):
    _crear(anonimo, uid, email="ocupado@example.com")
    eeid = _crear(anonimo, uid).json()["eeid"]
    assert anonimo.patch(f"{URL}/{eeid}", headers=sesion(uid), json={"email": "Ocupado@example.com"}).status_code == 400


def test_editar_no_cambia_el_dueño(anonimo, uid):
    otro, _ = crear_usuario("beto")
    eeid = _crear(anonimo, uid).json()["eeid"]
    anonimo.patch(f"{URL}/{eeid}", headers=sesion(uid), json={"owner": str(otro), "nombre": "X"})
    assert _en_base(eeid).owner == uid


# --- borrar -----------------------------------------------------------------------------

def test_borrar_el_empleado_borra_sus_simulaciones(anonimo, uid):
    eeid = _crear(anonimo, uid).json()["eeid"]
    with SessionLocal() as db:
        campaña = models.Campaña(owner=uid, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
        db.add(campaña)
        db.flush()
        db.add(models.Simulaciones(campana_id=campaña.camid, ee_id=UUID(eeid)))
        db.commit()
    assert anonimo.delete(f"{URL}/{eeid}", headers=sesion(uid)).status_code == 204
    assert _en_base(eeid) is None
    with SessionLocal() as db:
        assert db.query(models.Simulaciones).count() == 0
        assert db.query(models.Campaña).count() == 1


# --- página -----------------------------------------------------------------------------

def test_la_pagina_cuenta_solo_los_propios(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _crear(anonimo, otro, nombre="Empleado Ajeno")
    _crear(anonimo, uid, email="a@example.com", riesgo=80)
    _crear(anonimo, uid, email="b@example.com", riesgo=10, estado=False)
    r = anonimo.get("/empleados", headers=sesion(uid))
    assert r.status_code == 200
    assert "Empleado Ajeno" not in r.text
    assert "a@example.com" in r.text and "b@example.com" in r.text
    assert "2 registros" in r.text
