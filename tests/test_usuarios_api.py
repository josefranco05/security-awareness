"""Registro y CRUD de la cuenta propia."""
from __future__ import annotations

import pytest

from core.config import settings
from database.worker_db import SessionLocal
import models
from tests.conftest import ORIGEN, crear_usuario, sesion

URL = "/api/usuarios"
NUEVO = {
    "username": "carla", "nombre": "Carla", "apellidos": "Gómez",
    "email": "Carla@Example.com", "password": "una-contraseña-bastante-larga",
}


def _registrar(cliente, **cambios):
    return cliente.post(URL, headers={"Origin": ORIGEN}, json={**NUEVO, **cambios})


def _usuarios() -> list[models.User]:
    with SessionLocal() as db:
        return db.query(models.User).all()


# --- registro ---------------------------------------------------------------------------

def test_registro_crea_la_cuenta(anonimo):
    r = _registrar(anonimo)
    assert r.status_code == 201
    datos = r.json()
    assert set(datos) == {"uid", "username", "nombre", "apellidos", "email"}
    assert datos["email"] == "carla@example.com"
    [usuario] = _usuarios()
    assert usuario.email == "carla@example.com"


@pytest.mark.parametrize("cambios", [
    {"username": "CARLA", "email": "otra@example.com"},
    {"username": "otra", "email": "CARLA@example.com"},
])
def test_registro_rechaza_duplicados_sin_importar_mayusculas(anonimo, cambios):
    assert _registrar(anonimo).status_code == 201
    assert _registrar(anonimo, **cambios).status_code == 400
    assert len(_usuarios()) == 1


@pytest.mark.parametrize("cambios", [
    {"password": "corta"},
    {"password": "a" * 14},
    {"email": "no-es-un-email"},
    {"username": ""},
    {"username": "a" * 51},
    {"nombre": ""},
])
def test_registro_valida_los_campos(anonimo, cambios):
    assert _registrar(anonimo, **cambios).status_code == 422
    assert _usuarios() == []


def test_el_422_no_repite_la_contraseña(anonimo):
    r = _registrar(anonimo, email="mal", password="Secreta-de-15-chars")
    assert r.status_code == 422 and "Secreta-de-15-chars" not in r.text


def test_registro_exige_origen(anonimo):
    assert anonimo.post(URL, json=NUEVO).status_code == 403
    assert _usuarios() == []


# --- solo la cuenta propia --------------------------------------------------------------

def test_leer_la_cuenta_propia_no_muestra_el_email(anonimo):
    uid, _ = crear_usuario("ana")
    r = anonimo.get(f"{URL}/{uid}", headers=sesion(uid))
    assert r.status_code == 200
    assert r.json() == {"uid": uid, "username": "ana", "nombre": "a", "apellidos": "b"}


@pytest.mark.parametrize("metodo, cuerpo", [("get", None), ("patch", {"nombre": "x"}), ("delete", None)])
def test_la_cuenta_de_otro_da_404(anonimo, metodo, cuerpo):
    uid, _ = crear_usuario("ana")
    otro, _ = crear_usuario("beto")
    kwargs = {"json": cuerpo} if cuerpo else {}
    r = anonimo.request(metodo.upper(), f"{URL}/{otro}", headers=sesion(uid), **kwargs)
    assert r.status_code == 404
    with SessionLocal() as db:
        assert db.get(models.User, otro).nombre == "a"


def test_un_id_inexistente_tambien_da_404(anonimo):
    uid, _ = crear_usuario()
    assert anonimo.get(f"{URL}/{uid + 999}", headers=sesion(uid)).status_code == 404


@pytest.mark.parametrize("metodo", ["get", "patch", "delete"])
def test_el_crud_exige_sesion(anonimo, metodo):
    uid, _ = crear_usuario()
    r = anonimo.request(metodo.upper(), f"{URL}/{uid}", headers={"Origin": ORIGEN}, json={"nombre": "x"})
    assert r.status_code == 401


# --- actualizar -------------------------------------------------------------------------

def test_actualizar_cambia_solo_lo_enviado(anonimo):
    uid, _ = crear_usuario("ana")
    r = anonimo.patch(f"{URL}/{uid}", headers=sesion(uid), json={"nombre": "Ana María", "email": "NUEVO@example.com"})
    assert r.status_code == 200
    assert r.json() == {
        "uid": uid, "username": "ana", "nombre": "Ana María", "apellidos": "b", "email": "nuevo@example.com",
    }


def test_actualizar_sin_cambios_da_400(anonimo):
    uid, _ = crear_usuario()
    assert anonimo.patch(f"{URL}/{uid}", headers=sesion(uid), json={}).status_code == 400


@pytest.mark.parametrize("cambios", [{"username": "BETO"}, {"email": "Beto@example.com"}])
def test_actualizar_a_un_dato_de_otro_da_400(anonimo, cambios):
    uid, _ = crear_usuario("ana")
    crear_usuario("beto")
    assert anonimo.patch(f"{URL}/{uid}", headers=sesion(uid), json=cambios).status_code == 400


def test_actualizar_a_sus_propios_datos_no_es_duplicado(anonimo):
    uid, _ = crear_usuario("ana")
    r = anonimo.patch(f"{URL}/{uid}", headers=sesion(uid), json={"username": "ANA", "email": "ana@example.com"})
    assert r.status_code == 200 and r.json()["username"] == "ANA"


def test_actualizar_no_cambia_la_contraseña(anonimo):
    uid, _ = crear_usuario()
    r = anonimo.patch(f"{URL}/{uid}", headers=sesion(uid), json={"password_hash": "pwned", "nombre": "x"})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.get(models.User, uid).password_hash == "x"


# --- borrar -----------------------------------------------------------------------------

def test_borrar_la_cuenta_borra_todos_sus_datos_y_la_sesion(anonimo):
    uid, _ = crear_usuario("ana")
    otro, _ = crear_usuario("beto")
    with SessionLocal() as db:
        for owner in (uid, otro):
            empleado = models.Empleados(owner=owner, nombre="e", email="e@example.com", riesgo=0, empresa="x")
            campaña = models.Campaña(owner=owner, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
            db.add_all([empleado, campaña])
            db.flush()
            db.add(models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid))
        db.commit()

    r = anonimo.delete(f"{URL}/{uid}", headers=sesion(uid))
    assert r.status_code == 204
    assert r.headers["set-cookie"].startswith(f"{settings.AUTH_COOKIE_NAME}=")

    with SessionLocal() as db:
        assert db.get(models.User, uid) is None
        for modelo in (models.Empleados, models.Campaña):
            assert [f.owner for f in db.query(modelo).all()] == [otro]
        assert db.query(models.Simulaciones).count() == 1
        assert db.query(models.TokenExtension).filter_by(owner=uid).count() == 0
