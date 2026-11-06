"""El dashboard muestra datos reales de quien lo abre; cada correo cuenta una vez."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from core.auth import create_access_token
from core.config import settings
from database.worker_db import SessionLocal
import models
from services import dashboard
from tests.conftest import crear_usuario


def _campaña(uid, estados=(), nombre="Campaña", enviada_hace=0, fecha=None):
    """Crea una campaña con una simulación por estado. Cada simulación es un correo."""
    ahora = datetime.now(UTC)
    with SessionLocal() as db:
        campaña = models.Campaña(
            owner=uid, nombre=nombre, remitente="r@example.com", asunto="a", cuerpo="c", fecha=fecha or ahora,
        )
        db.add(campaña)
        db.flush()
        for i, estado in enumerate(estados):
            empleado = models.Empleados(
                owner=uid, nombre="e", email=f"{campaña.camid}-{i}@example.com", riesgo=0, empresa="x",
            )
            db.add(empleado)
            db.flush()
            db.add(models.Simulaciones(
                campana_id=campaña.camid, ee_id=empleado.eeid, status=estado,
                fecha_envio=ahora - timedelta(days=enviada_hace) if estado != "pending" else None,
                intentos=3,
            ))
        db.commit()
        return campaña.camid


def _detección(uid, nivel="alto", reglas=(), razones=("Razón.",), fecha=None):
    etiquetas = {"alto": "phishing", "medio": "sospechoso", "bajo": "legitimo"}
    with SessionLocal() as db:
        db.add(models.Deteccion(
            owner=uid, nivel=nivel, etiqueta=etiquetas[nivel], probabilidad=0.5,
            reglas=list(reglas), razones=list(razones), fecha=fecha or datetime.now(UTC),
        ))
        db.commit()


def _abrir(cliente, uid):
    jwt = create_access_token(subject=uid).access_token
    r = cliente.get("/dashboard", headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={jwt}"})
    assert r.status_code == 200
    return r.text


def _indicador(html, nombre):
    return re.search(rf'data-stat="{nombre}">(.*?)<', html, re.S).group(1).strip()


def _graficas(html):
    return json.loads(re.search(r'id="datos-graficas">(.*?)</script>', html, re.S).group(1))


@pytest.fixture
def uid(anonimo):
    return crear_usuario("ana")[0]


def test_sin_sesion_redirige_al_login(anonimo):
    r = anonimo.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_sin_datos(anonimo, uid):
    html = _abrir(anonimo, uid)
    for nombre in ("empleados", "campanas_activas", "correos_detectados"):
        assert _indicador(html, nombre) == "0"
    assert _indicador(html, "tasa_entrega") == "—"
    assert "<canvas" not in html
    assert "Aún no hay campañas." in html and "No hay alertas registradas." in html


def test_no_muestra_datos_de_otros(anonimo, uid):
    otro, _ = crear_usuario("beto")
    _campaña(otro, ["pending"], nombre="Campaña de otro")
    _detección(otro, razones=("Razón de otro.",))
    html = _abrir(anonimo, uid)
    assert _indicador(html, "empleados") == "0"
    assert _indicador(html, "campanas_activas") == "0"
    assert _indicador(html, "correos_detectados") == "0"
    assert "Campaña de otro" not in html and "Razón de otro." not in html


@pytest.mark.parametrize("estados, enviada_hace, activas", [
    (["pending"], 0, 1),
    (["sending"], 0, 1),
    (["sent"], 0, 1),
    (["sent"], dashboard.DIAS_COMPLETADA_PRUEBA + 1, 0),  # dato de prueba: se da por completada
    (["completed"], 0, 0),
    (["failed"], 0, 0),
    (["completed", "pending"], 0, 1),  # sigue activa hasta la última simulación
    (["completed", "failed"], 0, 0),
])
def test_campaña_activa_hasta_terminar_su_ultima_simulacion(anonimo, uid, estados, enviada_hace, activas):
    _campaña(uid, estados, enviada_hace=enviada_hace)
    assert _indicador(_abrir(anonimo, uid), "campanas_activas") == str(activas)


def test_una_campaña_con_varios_correos_activos_cuenta_una_vez(anonimo, uid):
    _campaña(uid, ["pending", "pending", "sending"])
    assert _indicador(_abrir(anonimo, uid), "campanas_activas") == "1"


def test_cada_correo_cuenta_una_vez_por_su_estado_actual(anonimo, uid):
    # Todas las simulaciones tienen intentos=3: los reintentos no deben sumar.
    _campaña(uid, ["sent", "sent", "sent", "failed", "pending", "sending"], nombre="Mayo")
    html = _abrir(anonimo, uid)
    assert '75<span class="unit">%' in html  # 3 entregados de 4 con resultado
    campañas = _graficas(html)["campanas"]
    assert campañas["nombres"] == ["Mayo"]
    assert (campañas["entregados"], campañas["pendientes"], campañas["fallidos"]) == ([3], [2], [1])


def test_la_grafica_muestra_las_ultimas_campañas(anonimo, uid):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    total = dashboard.MAX_CAMPAÑAS_GRAFICA + 1
    for i in range(total):
        _campaña(uid, ["sent"], nombre=f"C{i}", fecha=base + timedelta(days=i))
    nombres = _graficas(_abrir(anonimo, uid))["campanas"]["nombres"]
    assert nombres == [f"C{i}" for i in range(total - 1, 0, -1)]


def test_un_correo_con_varias_señales_cuenta_solo_en_la_mas_fuerte(anonimo, uid):
    _detección(uid, reglas=("spf=fail", "dmarc=fail", "dkim=fail"))
    _detección(uid, nivel="medio", reglas=("spf=fail", "dkim=fail"))
    _detección(uid, reglas=("dkim=fail",))
    _detección(uid)
    _detección(uid, nivel="bajo", reglas=("dkim=fail",))  # no es una amenaza
    html = _abrir(anonimo, uid)
    señales = _graficas(html)["senales"]
    assert dict(zip(señales["nombres"], señales["totales"])) == {"DMARC": 1, "SPF": 1, "DKIM": 1, "Solo contenido": 1}
    assert sum(señales["totales"]) == int(_indicador(html, "correos_detectados")) == 4


def test_las_detecciones_se_agrupan_por_dia_de_colombia(anonimo, uid, monkeypatch):
    ahora = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "_ahora", lambda: ahora)
    _detección(uid, fecha=datetime(2026, 11, 6, 1, 30, tzinfo=UTC))  # 5 nov, 8:30 p. m. en Colombia
    _detección(uid, nivel="bajo", fecha=datetime(2026, 11, 6, 6, 0, tzinfo=UTC))  # 6 nov, 1 a. m.
    detecciones = _graficas(_abrir(anonimo, uid))["detecciones"]
    assert detecciones["alto"][detecciones["dias"].index("05/11")] == 1
    assert detecciones["bajo"][detecciones["dias"].index("06/11")] == 1
    assert detecciones["total"] == 2


def test_la_grafica_cubre_solo_los_ultimos_30_dias(anonimo, uid, monkeypatch):
    ahora = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "_ahora", lambda: ahora)
    _detección(uid, fecha=datetime(2026, 10, 8, 5, 0, tzinfo=UTC))  # 8 oct, 00:00: primer día
    _detección(uid, fecha=datetime(2026, 10, 8, 4, 59, tzinfo=UTC))  # 7 oct, 23:59: fuera
    html = _abrir(anonimo, uid)
    detecciones = _graficas(html)["detecciones"]
    assert len(detecciones["dias"]) == 30 and detecciones["dias"][0] == "08/10" and detecciones["dias"][-1] == "06/11"
    assert detecciones["total"] == 1
    assert _indicador(html, "correos_detectados") == "2"  # el indicador cubre todo el historial


def test_las_alertas_son_las_ultimas_amenazas(anonimo, uid):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _detección(uid, nivel="bajo", razones=("Sin riesgo.",), fecha=base + timedelta(days=30))
    total = dashboard.MAX_ALERTAS + 1
    for i in range(total):
        _detección(uid, razones=(f"Alerta {i}.",), fecha=base + timedelta(days=i))
    html = _abrir(anonimo, uid)
    assert "Sin riesgo." not in html and "Alerta 0." not in html
    assert html.index(f"Alerta {total - 1}.") < html.index("Alerta 1.")


def test_el_contenido_del_atacante_se_escapa(anonimo, uid):
    _detección(uid, razones=("usa «<script>alert(1)</script>»",))
    _campaña(uid, ["sent"], nombre="</script><script>alert(2)</script>")
    html = _abrir(anonimo, uid)
    assert "<script>alert(1)" not in html and "<script>alert(2)" not in html
    assert _graficas(html)["campanas"]["nombres"] == ["</script><script>alert(2)</script>"]


def test_el_indicador_de_prueba_esta_marcado(anonimo, uid):
    assert "Datos de prueba" in _abrir(anonimo, uid)
