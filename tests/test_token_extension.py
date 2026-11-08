"""Generación, revocación y verificación del token de la extensión."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from core import auth
from core.auth import create_access_token, hash_token_extension
from core.config import settings
from database.worker_db import SessionLocal
import models
from routers import phishing
from tests.conftest import crear_usuario

URL_TOKEN = "/api/usuarios/me/token-extension"
URL_ANALISIS = phishing.RUTA_ANALISIS
CORREO = {"subject": "Reunión", "body": "Hola, te confirmo la reunión del viernes a las diez en la sala tres."}


def _sesion(uid: UUID) -> dict[str, str]:
    jwt = create_access_token(subject=uid).access_token
    return {"Cookie": f"{settings.AUTH_COOKIE_NAME}={jwt}", "Origin": "http://testserver"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tokens(uid: UUID) -> list[models.TokenExtension]:
    with SessionLocal() as db:
        return db.query(models.TokenExtension).filter_by(owner=uid).all()


def _detecciones() -> list[models.Deteccion]:
    with SessionLocal() as db:
        return db.query(models.Deteccion).all()


@pytest.fixture
def uid(anonimo) -> int:
    """Usuario sin token todavía."""
    uid, _ = crear_usuario("beto")
    with SessionLocal() as db:
        db.query(models.TokenExtension).filter_by(owner=uid).delete()
        db.commit()
    return uid


# --- generación -------------------------------------------------------------------------

def test_genera_un_token_y_solo_guarda_su_hash(anonimo, uid):
    r = anonimo.post(URL_TOKEN, headers=_sesion(uid))
    assert r.status_code == 201
    assert r.headers["Cache-Control"] == "no-store"
    token = r.json()["token"]
    assert token.startswith("snt_") and len(token) >= 40

    [fila] = _tokens(uid)
    assert fila.token_hash == hash_token_extension(token)
    assert token not in fila.token_hash


def test_dos_tokens_generados_son_distintos(anonimo, uid):
    uno = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    dos = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    assert uno != dos


def test_generar_otro_invalida_el_anterior(anonimo, uid):
    viejo = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    nuevo = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    assert len(_tokens(uid)) == 1
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(viejo)).status_code == 401
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(nuevo)).status_code == 200


def test_revocar_lo_invalida(anonimo, uid):
    token = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    assert anonimo.delete(URL_TOKEN, headers=_sesion(uid)).status_code == 204
    assert _tokens(uid) == []
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token)).status_code == 401


def test_revocar_sin_token_no_falla(anonimo, uid):
    assert anonimo.delete(URL_TOKEN, headers=_sesion(uid)).status_code == 204


@pytest.mark.parametrize("metodo", ["post", "delete"])
def test_gestionarlo_exige_sesion(anonimo, metodo):
    r = getattr(anonimo, metodo)(URL_TOKEN, headers={"Origin": "http://testserver"})
    assert r.status_code == 401


@pytest.mark.parametrize("metodo", ["post", "delete"])
def test_gestionarlo_exige_origen_permitido(anonimo, uid, metodo):
    # El token de la extensión no sirve para esto: es solo para analizar.
    cabeceras = {**_sesion(uid), "Origin": "https://evil.example"}
    assert getattr(anonimo, metodo)(URL_TOKEN, headers=cabeceras).status_code == 403
    assert _tokens(uid) == []


def test_el_token_de_extension_no_abre_otras_rutas(client):
    r = client.post(URL_TOKEN, headers={"Origin": "http://testserver"})
    assert r.status_code == 401


# --- verificación -----------------------------------------------------------------------

@pytest.mark.parametrize("cabeceras", [
    {},
    {"Authorization": "Bearer "},
    {"Authorization": "Bearer snt_inventado"},
    {"Authorization": "Bearer otro"},
    {"Authorization": "snt_sin_esquema"},
])
def test_analizar_sin_token_valido_da_401(anonimo, cabeceras):
    r = anonimo.post(URL_ANALISIS, json=CORREO, headers=cabeceras)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert _detecciones() == []


def test_otro_esquema_no_sirve(client):
    uid, token = crear_usuario("ceci")
    r = client.post(URL_ANALISIS, json=CORREO, headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 401


def test_la_sesion_no_sirve_para_analizar(anonimo, uid):
    # Esta ruta no exige Origin: aceptar la cookie abriría CSRF.
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_sesion(uid)).status_code == 401


def test_el_jwt_no_sirve_como_token(anonimo, uid):
    jwt = create_access_token(subject=uid).access_token
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(jwt)).status_code == 401


def test_el_hash_robado_no_sirve_como_token(anonimo, uid):
    anonimo.post(URL_TOKEN, headers=_sesion(uid))
    [fila] = _tokens(uid)
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(fila.token_hash)).status_code == 401
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer("snt_" + fila.token_hash)).status_code == 401


def test_cada_token_guarda_a_nombre_de_su_dueño(anonimo):
    uid_a, token_a = crear_usuario("ana")
    uid_b, token_b = crear_usuario("beto")
    anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token_a))
    anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token_b))
    assert sorted(d.owner for d in _detecciones()) == sorted([uid_a, uid_b])


def test_el_limite_de_peticiones_es_por_dueño_del_token(anonimo, monkeypatch):
    monkeypatch.setattr(phishing.settings, "ANALISIS_POR_MINUTO", 1)
    _, token_a = crear_usuario("ana")
    _, token_b = crear_usuario("beto")
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token_a)).status_code == 200
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token_a)).status_code == 429
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token_b)).status_code == 200


def test_sin_token_no_se_gasta_el_limite(client, monkeypatch):
    monkeypatch.setattr(phishing.settings, "ANALISIS_POR_MINUTO", 1)
    assert client.post(URL_ANALISIS, json=CORREO, headers={"Authorization": "Bearer snt_x"}).status_code == 401
    assert client.post(URL_ANALISIS, json=CORREO).status_code == 200


def test_si_la_base_falla_no_deja_pasar(client, monkeypatch):
    def fallar():
        raise OperationalError("select", {}, Exception("database is locked"))

    monkeypatch.setattr(auth, "SessionLocal", fallar)
    assert client.post(URL_ANALISIS, json=CORREO).status_code == 503
    assert _detecciones() == []


# --- ciclo de vida ----------------------------------------------------------------------

def test_borrar_la_cuenta_borra_token_y_detecciones(anonimo):
    uid, token = crear_usuario("ana")
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token)).status_code == 200

    assert anonimo.delete(f"/api/usuarios/{uid}", headers=_sesion(uid)).status_code == 204

    assert _tokens(uid) == [] and _detecciones() == []
    assert anonimo.post(URL_ANALISIS, json=CORREO, headers=_bearer(token)).status_code == 401


# --- página -----------------------------------------------------------------------------

def test_cuenta_sin_token(anonimo, uid):
    r = anonimo.get("/cuenta", headers=_sesion(uid))
    assert r.status_code == 200
    assert "Aún no has generado un token." in r.text
    assert 'id="btnRevocarToken" hidden' in r.text


def test_cuenta_con_token_no_muestra_el_token(anonimo, uid):
    token = anonimo.post(URL_TOKEN, headers=_sesion(uid)).json()["token"]
    [fila] = _tokens(uid)
    r = anonimo.get("/cuenta", headers=_sesion(uid))
    assert "Token activo desde" in r.text
    assert token not in r.text and fila.token_hash not in r.text
