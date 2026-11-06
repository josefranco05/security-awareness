"""La página /deteccion muestra las detecciones reales de quien la abre."""
from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from core.auth import create_access_token
from core.config import settings
from database.worker_db import SessionLocal
import main
import models
from tests.conftest import crear_usuario


def _guardar(uid, nivel="bajo", etiqueta="legitimo", probabilidad=0.1, reglas=(), razones=("Sin señales.",), fecha=None):
    with SessionLocal() as db:
        db.add(models.Deteccion(
            owner=uid, nivel=nivel, etiqueta=etiqueta, probabilidad=probabilidad,
            reglas=list(reglas), razones=list(razones), fecha=fecha or datetime.now(UTC),
        ))
        db.commit()


def _abrir(cliente, uid):
    jwt = create_access_token(subject=uid).access_token
    r = cliente.get("/deteccion", headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={jwt}"})
    assert r.status_code == 200
    return r.text


def _indicador(html, nombre):
    return int(re.search(rf'data-stat="{nombre}">(\d+)<', html).group(1))


def _cuerpo_tabla(html):
    return html.split("<tbody>")[1].split("</tbody>")[0]


@pytest.fixture
def uid(anonimo):
    return crear_usuario("ana")[0]


def test_sin_sesion_redirige_al_login(anonimo):
    r = anonimo.get("/deteccion", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_sin_detecciones(anonimo, uid):
    html = _abrir(anonimo, uid)
    assert "Aún no hay detecciones registradas." in html
    assert _indicador(html, "analizados") == 0


def test_indicadores_reales(anonimo, uid):
    _guardar(uid, nivel="alto", etiqueta="phishing")
    _guardar(uid, nivel="alto", etiqueta="phishing")
    _guardar(uid, nivel="medio", etiqueta="sospechoso")
    _guardar(uid)
    html = _abrir(anonimo, uid)
    assert _indicador(html, "analizados") == 4
    assert _indicador(html, "detectados") == 3
    assert _indicador(html, "riesgo_alto") == 2
    assert _indicador(html, "riesgo_medio") == 1
    assert "4 registros" in html


def test_no_muestra_detecciones_de_otros(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _guardar(otro, nivel="alto", etiqueta="phishing", razones=("Razón de otro usuario.",))
    html = _abrir(anonimo, uid)
    assert _indicador(html, "analizados") == 0
    assert "Razón de otro usuario." not in html


def test_el_color_sale_del_nivel_y_no_de_la_probabilidad(anonimo, uid):
    # dmarc=fail sube el nivel, pero la probabilidad del modelo sigue baja.
    _guardar(uid, nivel="medio", etiqueta="sospechoso", probabilidad=0.2449, reglas=("dmarc=fail",))
    tabla = _cuerpo_tabla(_abrir(anonimo, uid))
    assert '<span class="badge risk-medium">Sospechoso</span>' in tabla
    assert "24%" in tabla and "dmarc=fail" in tabla


def test_las_razones_se_escapan(anonimo, uid):
    # Las razones citan términos del correo: los escribe el atacante.
    _guardar(uid, razones=("usa «<script>alert(1)</script>»",))
    html = _abrir(anonimo, uid)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_la_fecha_se_muestra_en_hora_de_colombia(anonimo, uid):
    _guardar(uid, fecha=datetime(2026, 11, 6, 1, 30, tzinfo=UTC))
    assert "05/11/2026 20:30" in _cuerpo_tabla(_abrir(anonimo, uid))


def test_las_mas_recientes_van_primero(anonimo, uid):
    _guardar(uid, razones=("La vieja.",), fecha=datetime(2026, 1, 1, tzinfo=UTC))
    _guardar(uid, razones=("La nueva.",), fecha=datetime(2026, 6, 1, tzinfo=UTC))
    tabla = _cuerpo_tabla(_abrir(anonimo, uid))
    assert tabla.index("La nueva.") < tabla.index("La vieja.")


def test_la_tabla_tiene_tope_pero_los_indicadores_no(anonimo, uid, monkeypatch):
    monkeypatch.setattr(main, "MAX_DETECCIONES_PAGINA", 2)
    for _ in range(3):
        _guardar(uid, nivel="alto", etiqueta="phishing")
    html = _abrir(anonimo, uid)
    assert _cuerpo_tabla(html).count("<tr>") == 2
    assert _indicador(html, "analizados") == 3
    assert "Últimos 2 de 3" in html


def test_una_deteccion_real_llega_a_la_pagina(anonimo):
    uid, token = crear_usuario("ana")
    correo = {
        "subject": "Su cuenta será suspendida",
        "body": "Estimado cliente, detectamos actividad inusual en su cuenta bancaria. Verifique sus datos en las "
                "próximas 24 horas en http://bbva-seguridad.xyz/login o su cuenta será bloqueada.",
        "auth_results": {"dmarc": "fail"},
    }
    r = anonimo.post(main.phishing.RUTA_ANALISIS, json=correo, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    html = _abrir(anonimo, uid)
    assert _indicador(html, "riesgo_alto") == 1
    assert "dmarc=fail" in html and r.json()["razones"][0].split(";")[0] in html
    # El correo en sí no se guarda, así que tampoco puede aparecer aquí.
    assert "bbva-seguridad" not in html and "Su cuenta será suspendida" not in html
