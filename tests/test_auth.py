"""Sesión: JWT, login, logout y qué pasa con una sesión inválida."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from core.auth import create_access_token, verify_access_token
from core.config import settings
from database.worker_db import SessionLocal
import models
from tests.conftest import ORIGEN, crear_usuario, sesion

URL_LOGIN = "/api/usuarios/token"
URL_LOGOUT = "/api/usuarios/logout"
URL_ME = "/api/usuarios/me"
PASSWORD = "una-contraseña-bastante-larga"


def _registrar(cliente, username="ana", password=PASSWORD) -> int:
    r = cliente.post("/api/usuarios", headers={"Origin": ORIGEN}, json={
        "username": username, "nombre": "Ana", "apellidos": "Pérez",
        "email": f"{username}@example.com", "password": password,
    })
    assert r.status_code == 201
    return r.json()["uid"]


def _login(cliente, username, password):
    return cliente.post(URL_LOGIN, headers={"Origin": ORIGEN}, data={"username": username, "password": password})


def _con_cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"{settings.AUTH_COOKIE_NAME}={token}"}


def _firmar(payload: dict, clave: str | None = None, algoritmo: str = "HS256") -> str:
    clave = settings.SECRET_KEY_AUTH.get_secret_value() if clave is None else clave
    return jwt.encode(payload, clave, algorithm=algoritmo)


def _exp(minutos: int = 5) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutos)


# --- JWT --------------------------------------------------------------------------------

def test_el_jwt_lleva_el_uid():
    assert verify_access_token(create_access_token(subject=42).access_token) == "42"


@pytest.mark.parametrize("token", [
    pytest.param(lambda: create_access_token(1, expires_delta=timedelta(seconds=-1)).access_token, id="expirado"),
    pytest.param(lambda: _firmar({"sub": "1", "exp": _exp()}, clave="otra-clave-de-al-menos-32-bytes!!"), id="otra-clave"),
    pytest.param(lambda: _firmar({"sub": "1", "exp": _exp()}, clave="", algoritmo="none"), id="alg-none"),
    pytest.param(lambda: _firmar({"sub": "1"}), id="sin-exp"),
    pytest.param(lambda: _firmar({"exp": _exp()}), id="sin-sub"),
    pytest.param(lambda: create_access_token(1).access_token[:-2] + "xx", id="firma-alterada"),
    pytest.param(lambda: "no-es-un-jwt", id="basura"),
])
def test_jwt_invalido_no_da_uid(token):
    assert verify_access_token(token()) == ""


# --- login ------------------------------------------------------------------------------

def test_login_pone_la_cookie_de_sesion(anonimo):
    uid = _registrar(anonimo)
    r = _login(anonimo, "ana", PASSWORD)
    assert r.status_code == 204
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith(f"{settings.AUTH_COOKIE_NAME}=")
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "secure" in cookie
    # El JWT no viaja en el cuerpo: el frontend nunca lo ve.
    assert not r.content
    token = r.cookies[settings.AUTH_COOKIE_NAME]
    assert verify_access_token(token) == str(uid)


def test_login_ignora_mayusculas_del_username(anonimo):
    _registrar(anonimo)
    assert _login(anonimo, "ANA", PASSWORD).status_code == 204


def test_usuario_inexistente_y_contraseña_mala_responden_igual(anonimo):
    _registrar(anonimo)
    mala = _login(anonimo, "ana", PASSWORD + "x")
    inexistente = _login(anonimo, "nadie", PASSWORD)
    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json()
    assert "set-cookie" not in mala.headers


def test_la_contraseña_no_se_guarda_en_claro(anonimo):
    uid = _registrar(anonimo)
    with SessionLocal() as db:
        guardado = db.get(models.User, uid).password_hash
    assert PASSWORD not in guardado and guardado.startswith("$argon2")


def test_login_exige_origen_permitido(anonimo):
    _registrar(anonimo)
    r = anonimo.post(URL_LOGIN, headers={"Origin": "https://evil.example"}, data={"username": "ana", "password": PASSWORD})
    assert r.status_code == 403


# --- logout -----------------------------------------------------------------------------

def _borra_la_cookie(r) -> bool:
    cookie = r.headers.get("set-cookie", "").lower()
    return cookie.startswith(f"{settings.AUTH_COOKIE_NAME}=") and ("max-age=0" in cookie or "expires=" in cookie)


def test_logout_borra_la_cookie(anonimo):
    uid, _ = crear_usuario()
    r = anonimo.post(URL_LOGOUT, headers=sesion(uid))
    assert r.status_code == 204 and _borra_la_cookie(r)


def test_logout_funciona_con_la_sesion_expirada(anonimo):
    expirado = create_access_token(1, expires_delta=timedelta(seconds=-1)).access_token
    r = anonimo.post(URL_LOGOUT, headers={**_con_cookie(expirado), "Origin": ORIGEN})
    assert r.status_code == 204 and _borra_la_cookie(r)


# --- sesión inválida --------------------------------------------------------------------

def test_me_devuelve_la_cuenta_propia(anonimo):
    uid, _ = crear_usuario("ana")
    r = anonimo.get(URL_ME, headers=sesion(uid))
    assert r.status_code == 200
    assert r.json() == {"uid": uid, "username": "ana", "nombre": "a", "apellidos": "b", "email": "ana@example.com"}


@pytest.mark.parametrize("cabeceras", [
    pytest.param(lambda: {}, id="sin-cookie"),
    pytest.param(lambda: _con_cookie("basura"), id="basura"),
    pytest.param(lambda: _con_cookie(create_access_token(1, expires_delta=timedelta(seconds=-1)).access_token), id="expirado"),
    pytest.param(lambda: _con_cookie(create_access_token("abc").access_token), id="sub-no-numerico"),
    pytest.param(lambda: {"Authorization": f"Bearer {create_access_token(1).access_token}"}, id="jwt-en-bearer"),
])
def test_sin_sesion_valida_la_api_da_401_y_la_pagina_redirige(anonimo, cabeceras):
    crear_usuario()
    assert anonimo.get(URL_ME, headers=cabeceras()).status_code == 401
    r = anonimo.get("/dashboard", headers=cabeceras(), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_el_jwt_de_un_usuario_borrado_no_sirve(anonimo):
    uid, _ = crear_usuario()
    cabeceras = sesion(uid)
    with SessionLocal() as db:
        db.delete(db.get(models.User, uid))
        db.commit()
    assert anonimo.get(URL_ME, headers=cabeceras).status_code == 401
    assert anonimo.get("/dashboard", headers=cabeceras, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("pagina", ["/dashboard", "/empleados", "/campañas", "/deteccion", "/simulacion", "/cuenta"])
def test_las_paginas_privadas_exigen_sesion(anonimo, pagina):
    r = anonimo.get(pagina, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


@pytest.mark.parametrize("pagina", ["/login", "/registro"])
def test_login_y_registro_redirigen_si_ya_hay_sesion(anonimo, pagina):
    uid, _ = crear_usuario()
    r = anonimo.get(pagina, headers=sesion(uid), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/dashboard")
    assert anonimo.get(pagina, headers=_con_cookie("basura")).status_code == 200
