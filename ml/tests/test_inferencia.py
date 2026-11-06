"""Pruebas de ml.inferencia: muestras fijas, capa de reglas y carga del modelo.

Las pruebas de 413/422 y del límite de peticiones van en la app, junto al modelo de Pydantic.
"""
from __future__ import annotations

import pytest

from ml.inferencia import (
    REGLAS,
    Nivel,
    ResultadoAuth,
    analizar,
    aplicar_reglas,
    cargar_modelo,
    normalizar_auth,
)

PHISHING = [
    ("Su cuenta será suspendida",
     "Estimado cliente, detectamos actividad inusual en su cuenta bancaria. Verifique sus datos en las "
     "próximas 24 horas en http://bbva-seguridad.xyz/login o su cuenta será bloqueada."),
    ("Tu paquete está detenido",
     "Tienes (1) paquete pendiente de entrega. Paga el costo de envío de $29 MXN para recibirlo: "
     "https://correos-mx-envio.top"),
]
LEGITIMOS = [
    ("Reunión del viernes",
     "Hola Ana, te confirmo la reunión del viernes a las 10 en la sala 3 para revisar el avance del "
     "proyecto. Saludos, Carlos"),
    ("Cambio de contraseña del portal",
     "Buen día, les recuerdo que el portal de nómina pedirá cambio de contraseña el lunes. Pueden hacerlo "
     "desde https://intranet.empresa.com.mx como siempre. Atte. Recursos Humanos"),
]
TODO_PASS = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}


@pytest.fixture(scope="module")
def modelo():
    return cargar_modelo()


# --- muestras fijas -------------------------------------------------------------------

@pytest.mark.parametrize("asunto,cuerpo", PHISHING)
def test_phishing_sale_alto(modelo, asunto, cuerpo):
    r = analizar(modelo, asunto, cuerpo)
    assert r.nivel == Nivel.ALTO and r.etiqueta == "phishing"
    assert r.razones and "«" in r.razones[0]


@pytest.mark.parametrize("asunto,cuerpo", LEGITIMOS)
def test_legitimo_sale_bajo(modelo, asunto, cuerpo):
    r = analizar(modelo, asunto, cuerpo)
    assert r.nivel == Nivel.BAJO and r.etiqueta == "legitimo"
    assert r.reglas == ()


def test_entradas_vacias_y_urls(modelo):
    r = analizar(modelo, "", "", urls=[{"text": "aquí", "href": "hxxp://malo[.]com"}, "http://otro.com"])
    assert 0.0 <= r.probabilidad <= 1.0


# --- capa de reglas sobre el modelo real --------------------------------------------------

def test_dmarc_fail_sube_el_nivel(modelo):
    asunto, cuerpo = LEGITIMOS[0]
    base = analizar(modelo, asunto, cuerpo)
    con_fallo = analizar(modelo, asunto, cuerpo, auth_results={"dmarc": "fail"})
    assert con_fallo.probabilidad == base.probabilidad
    assert _indice(con_fallo.nivel) == _indice(base.nivel) + 1
    assert con_fallo.reglas == ("dmarc=fail",)
    assert any("suplantado" in x for x in con_fallo.razones)


@pytest.mark.parametrize("asunto,cuerpo", PHISHING + LEGITIMOS)
def test_todo_pass_no_baja_el_nivel(modelo, asunto, cuerpo):
    assert analizar(modelo, asunto, cuerpo, auth_results=TODO_PASS) == analizar(modelo, asunto, cuerpo)


@pytest.mark.parametrize("valor", ["unknown", "none", None])
def test_unknown_y_none_no_cambian_nada(modelo, valor):
    asunto, cuerpo = PHISHING[1]
    auth = {"spf": valor, "dkim": valor, "dmarc": valor}
    assert analizar(modelo, asunto, cuerpo, auth_results=auth) == analizar(modelo, asunto, cuerpo)


# --- capa de reglas, con probabilidades fijas ----------------------------------------------

def _auth(**campos):
    return normalizar_auth(campos)


def _indice(nivel):
    return list(Nivel).index(nivel)


@pytest.mark.parametrize("campo", ["dmarc", "spf"])
@pytest.mark.parametrize("p,esperado", [(0.2, Nivel.MEDIO), (0.5, Nivel.ALTO), (0.9, Nivel.ALTO)])
def test_dmarc_o_spf_fail_sube_un_escalon(campo, p, esperado):
    nivel, activadas = aplicar_reglas(p, _auth(**{campo: "fail"}))
    assert nivel == esperado
    assert [r.campo for r in activadas] == [campo]


def test_dmarc_y_spf_fail_juntos_suben_un_solo_escalon():
    nivel, activadas = aplicar_reglas(0.2, _auth(dmarc="fail", spf="fail"))
    assert nivel == Nivel.MEDIO and len(activadas) == 2


def test_dkim_fail_es_un_empujon_menor():
    assert aplicar_reglas(0.35, _auth(dkim="fail"))[0] == Nivel.MEDIO  # 0.35 + 0.10 cruza 0.4
    assert aplicar_reglas(0.10, _auth(dkim="fail"))[0] == Nivel.BAJO   # pero no sube un escalón entero


@pytest.mark.parametrize("p", [0.05, 0.39, 0.41, 0.69, 0.71, 0.99])
def test_pass_unknown_none_nunca_cambian_el_nivel(p):
    sin_auth = aplicar_reglas(p, _auth())
    for valor in ("pass", "unknown", "none"):
        assert aplicar_reglas(p, _auth(spf=valor, dkim=valor, dmarc=valor)) == sin_auth


def test_solo_hay_reglas_para_fail():
    assert all(r.valor == ResultadoAuth.FAIL for r in REGLAS)
    assert all(r.subir_niveles >= 0 and r.sumar_probabilidad >= 0 for r in REGLAS)


@pytest.mark.parametrize("auth", [{"dmarc": "falla"}, {"spf": "PASS"}, {"dkimm": "pass"}])
def test_auth_invalido_lanza_value_error(auth):
    with pytest.raises(ValueError):
        normalizar_auth(auth)


# --- carga ---------------------------------------------------------------------------

def test_cargar_modelo_falla_si_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError, match="python ml/train.py"):
        cargar_modelo(tmp_path / "no_existe.joblib")
