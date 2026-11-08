"""Middlewares y comportamiento transversal de main.py: CSRF, caché, tema y errores."""
from __future__ import annotations

import re

import pytest

import main
from tests.conftest import ORIGEN, crear_usuario, sesion


# --- CSRF: Origin obligatorio en métodos que modifican estado ---------------------------

@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("origen", [None, "null", "https://evil.example", "http://testserver.evil.example", "https://testserver"])
def test_origen_no_permitido_da_403_aunque_haya_sesion(anonimo, metodo, origen):
    uid, _ = crear_usuario()
    cabeceras = {k: v for k, v in sesion(uid).items() if k != "Origin"}
    if origen is not None:
        cabeceras["Origin"] = origen
    r = anonimo.request(metodo, f"/api/usuarios/{uid}", headers=cabeceras, json={"nombre": "x"})
    assert r.status_code == 403
    assert r.json() == {"detail": "Origen de la solicitud no permitido."}


def test_origen_permitido_pasa(anonimo):
    uid, _ = crear_usuario()
    assert anonimo.patch(f"/api/usuarios/{uid}", headers=sesion(uid), json={"nombre": "x"}).status_code == 200


def test_los_get_no_exigen_origin(anonimo):
    uid, _ = crear_usuario()
    headers = {k: v for k, v in sesion(uid).items() if k != "Origin"}
    assert anonimo.get("/api/usuarios/me", headers=headers).status_code == 200


def test_el_formulario_de_tema_tambien_exige_origin(anonimo):
    uid, _ = crear_usuario()
    headers = {k: v for k, v in sesion(uid).items() if k != "Origin"}
    r = anonimo.post("/cuenta/tema", headers=headers, data={"tema": "dark"}, follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_la_excepcion_de_webhooks_no_cubre_rutas_parecidas(anonimo):
    # "/api/webhooks/" lleva "/" final: "/api/webhooksX" no se salta la comprobación.
    assert anonimo.post("/api/webhooksX").status_code == 403


# --- caché ------------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/", "/login", "/api/usuarios/me", "/dashboard"])
def test_paginas_y_api_no_se_almacenan(anonimo, ruta):
    r = anonimo.get(ruta, follow_redirects=False)
    assert r.headers["Cache-Control"] == "no-store"


def test_estatico_versionado_se_cachea_un_año(anonimo):
    url = main.static_url("css/style.css")
    assert re.fullmatch(r"/static/css/style\.css\?v=[0-9a-f]{12}", url)
    r = anonimo.get(url)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_estatico_sin_version_se_revalida(anonimo):
    assert anonimo.get("/static/css/style.css").headers["Cache-Control"] == "no-cache"


def test_un_404_estatico_versionado_no_se_cachea(anonimo):
    assert anonimo.get("/static/no-existe.css?v=abc").headers["Cache-Control"] == "no-cache"


def test_las_paginas_enlazan_el_estatico_versionado(anonimo):
    assert main.static_url("css/style.css") in anonimo.get("/").text


# --- tema -------------------------------------------------------------------------------

def test_cambiar_tema_guarda_la_cookie_y_vuelve_a_la_cuenta(anonimo):
    uid, _ = crear_usuario()
    r = anonimo.post("/cuenta/tema", headers=sesion(uid), data={"tema": "dark"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/cuenta")
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith(f"{main.TEMA_COOKIE}=dark") and "httponly" in cookie and "samesite=lax" in cookie


def test_tema_invalido_da_422(anonimo):
    uid, _ = crear_usuario()
    r = anonimo.post("/cuenta/tema", headers=sesion(uid), data={"tema": "rojo"}, follow_redirects=False)
    assert r.status_code == 422 and "set-cookie" not in r.headers


def test_cambiar_tema_exige_sesion(anonimo):
    r = anonimo.post("/cuenta/tema", headers={"Origin": ORIGEN}, data={"tema": "dark"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


@pytest.mark.parametrize("cookie, tema", [
    ("dark", "dark"),
    ("light", "light"),
    (None, "light"),
    ("azul", "light"),
    ("dark%22%20onload%3D%22alert(1)", "light"),  # la cookie la controla el cliente
])
def test_la_pagina_llega_con_el_tema_de_la_cookie(anonimo, cookie, tema):
    cabeceras = {"Cookie": f"{main.TEMA_COOKIE}={cookie}"} if cookie else {}
    html = anonimo.get("/", headers=cabeceras).text
    assert f'<html lang="es" data-theme="{tema}">' in html


# --- errores ----------------------------------------------------------------------------

def test_404_en_la_api_es_json(anonimo):
    r = anonimo.get("/api/no-existe")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_404_en_una_pagina_es_html(anonimo):
    r = anonimo.get("/no-existe")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")


def test_422_en_una_pagina_no_repite_la_entrada(anonimo):
    uid, _ = crear_usuario()
    r = anonimo.post("/cuenta/tema", headers=sesion(uid), data={"tema": "<script>x</script>"})
    assert r.status_code == 422 and r.headers["content-type"].startswith("text/html")
    assert "<script>x</script>" not in r.text


def test_422_en_la_api_es_json(anonimo):
    r = anonimo.post("/api/usuarios", headers={"Origin": ORIGEN}, json={})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
