"""POST /api/phishing/analizar: contrato, límites, privacidad y persistencia."""
from __future__ import annotations

import inspect
import logging

import pytest
from sqlalchemy.exc import OperationalError

from core.limites import LimiteVentana
from database.worker_db import SessionLocal
from ml.inferencia import MAX_BYTES_CUERPO
import main
import models
from routers import phishing
from tests.conftest import crear_usuario

URL = phishing.RUTA_ANALISIS
EXTENSION = {"Origin": "chrome-extension://abcdefghijklmnop"}
SECRETO = "PalabraSecretaDelCorreo"
PHISHING = {
    "subject": f"Su cuenta será suspendida {SECRETO}",
    "body": "Estimado cliente, detectamos actividad inusual en su cuenta bancaria. Verifique sus datos en las "
            f"próximas 24 horas en http://bbva-seguridad.xyz/login o su cuenta será bloqueada. {SECRETO}",
    "urls": [{"text": "aquí", "href": f"hxxp://malo[.]com/{SECRETO}"}],
    "auth_results": {"spf": "pass", "dkim": "fail", "dmarc": "fail"},
}


def _post(client, json, **kwargs):
    return client.post(URL, json=json, headers=EXTENSION, **kwargs)


def _detecciones():
    with SessionLocal() as db:
        return db.query(models.Deteccion).all()


# --- contrato ---------------------------------------------------------------------------

def test_analiza_y_devuelve_el_resultado(client):
    r = _post(client, PHISHING)
    assert r.status_code == 200
    datos = r.json()
    assert set(datos) == {"etiqueta", "nivel", "probabilidad", "razones", "reglas"}
    assert datos["nivel"] == "alto" and datos["etiqueta"] == "phishing"
    assert datos["reglas"] == ["dmarc=fail", "dkim=fail"]


def test_solo_el_cuerpo_es_obligatorio(client):
    assert _post(client, {"body": "Hola, nos vemos el viernes."}).status_code == 200


def test_el_endpoint_no_es_async():
    assert not inspect.iscoroutinefunction(phishing.analizar_correo)


# --- origen -----------------------------------------------------------------------------

def test_sin_origin_tambien_se_acepta(client):
    assert client.post(URL, json={"body": "hola"}).status_code == 200


def test_las_demas_rutas_siguen_exigiendo_origin(client):
    r = client.post("/api/usuarios/logout", headers=EXTENSION)
    assert r.status_code == 403


# --- 413 --------------------------------------------------------------------------------

def test_cuerpo_en_el_limite_se_acepta(client):
    assert _post(client, {"body": "a" * MAX_BYTES_CUERPO}).status_code == 200


def test_cuerpo_sobre_el_limite_da_413(client):
    assert _post(client, {"body": "a" * (MAX_BYTES_CUERPO + 1)}).status_code == 413


def test_el_limite_cuenta_bytes_no_caracteres(client):
    # 2 bytes por carácter: cabe en caracteres, pero no en bytes.
    assert _post(client, {"body": "ñ" * (MAX_BYTES_CUERPO // 2 + 1)}).status_code == 413
    assert not _detecciones()


def test_peticion_enorme_da_413_antes_de_validar(client):
    grande = b"x" * (phishing.MAX_BYTES_PETICION + 1)  # ni siquiera es JSON
    r = client.post(URL, content=grande, headers={**EXTENSION, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_peticion_chunked_sin_content_length_da_413(client):
    def trozos():
        for _ in range(phishing.MAX_BYTES_PETICION // 65536 + 2):
            yield b"x" * 65536

    r = client.post(URL, content=trozos(), headers={**EXTENSION, "Content-Type": "application/json"})
    assert "content-length" not in r.request.headers
    assert r.status_code == 413


def test_el_limite_no_afecta_a_otras_rutas(client):
    grande = b"x" * (phishing.MAX_BYTES_PETICION + 1)
    r = client.post("/api/webhooks/acs", content=grande)
    assert r.status_code == 401  # lo rechaza su propia verificación, no el límite


# --- 422 --------------------------------------------------------------------------------

@pytest.mark.parametrize("cambios", [
    {"subject": "a" * 501},
    {"urls": [{"href": "http://a.com"}] * 51},
    {"urls": [{"href": "http://a.com/" + "a" * 2048}]},
    {"urls": ["http://sin-objeto.com"]},
    {"urls": [{"text": "sin href"}]},
    {"auth_results": {"spf": "softfail"}},
    {"auth_results": {"dmarc": "FAIL"}},
    {"auth_results": {"arc": "pass"}},
    {"campo_extra": 1},
    {"body": 123},
])
def test_entrada_invalida_da_422(client, cambios):
    assert _post(client, {"body": "hola", **cambios}).status_code == 422
    assert not _detecciones()


@pytest.mark.parametrize("cuerpo", [
    rb'{"body": "hola \ud83d"}',
    rb'{"body": "hola", "subject": "\ud83d"}',
    rb'{"body": "hola", "urls": [{"text": "\ud83d", "href": "http://a.com/\ud83d"}]}',
])
def test_sustituto_suelto_no_evita_el_analisis(client, cuerpo):
    # JSON válido, pero el texto no se puede codificar en UTF-8 tal cual.
    r = client.post(URL, content=cuerpo, headers={**EXTENSION, "Content-Type": "application/json"})
    assert r.status_code == 200
    assert len(_detecciones()) == 1


def test_json_invalido_da_422(client):
    r = client.post(URL, content=b"{no es json", headers={**EXTENSION, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_el_422_no_repite_el_correo(client):
    r = _post(client, {"body": "hola", "subject": SECRETO * 100})
    assert r.status_code == 422
    assert SECRETO not in r.text
    assert all("input" not in e for e in r.json()["detail"])


# --- límite de peticiones ---------------------------------------------------------------

def _limite_de(monkeypatch, maximo):
    monkeypatch.setattr(phishing.settings, "ANALISIS_POR_MINUTO", maximo)


def test_exceder_el_limite_da_429_con_retry_after(client, monkeypatch):
    _limite_de(monkeypatch, 2)
    assert _post(client, {"body": "uno"}).status_code == 200
    assert _post(client, {"body": "dos"}).status_code == 200
    r = _post(client, {"body": "tres"})
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert len(_detecciones()) == 2


def test_el_limite_es_por_usuario(client, monkeypatch):
    _limite_de(monkeypatch, 1)
    usuario = {"uid": crear_usuario("beto")[0]}
    main.app.dependency_overrides[phishing.require_extension_token] = lambda: usuario["uid"]
    assert _post(client, {"body": "uno"}).status_code == 200
    assert _post(client, {"body": "dos"}).status_code == 429
    usuario["uid"] = crear_usuario("ceci")[0]
    assert _post(client, {"body": "tres"}).status_code == 200


def test_las_peticiones_invalidas_tambien_cuentan(client, monkeypatch):
    _limite_de(monkeypatch, 1)
    assert _post(client, {"body": 123}).status_code == 422
    assert _post(client, {"body": "hola"}).status_code == 429


def test_la_ventana_se_libera_y_olvida_a_los_inactivos():
    ahora = [0.0]
    limite = LimiteVentana(ventana_s=60, reloj=lambda: ahora[0])
    assert limite.comprobar(1, 1) == 0
    assert limite.comprobar(1, 1) == 60
    ahora[0] = 59.5
    assert limite.comprobar(1, 1) == 1
    ahora[0] = 60.0
    assert limite.comprobar(2, 1) == 0
    assert 1 not in limite._marcas


# --- autenticación ----------------------------------------------------------------------

def test_el_token_se_comprueba_antes_que_el_cuerpo(client):
    def rechazar():
        raise phishing.HTTPException(status_code=401)

    main.app.dependency_overrides[phishing.require_extension_token] = rechazar
    assert _post(client, {"body": 123}).status_code == 401
    assert _post(client, {"body": "hola"}).status_code == 401
    assert not _detecciones()


# --- registro ---------------------------------------------------------------------------

def test_el_log_solo_lleva_metadatos(client, caplog):
    with caplog.at_level(logging.INFO, logger=phishing.logger.name):
        r = _post(client, PHISHING)
    assert r.status_code == 200
    texto = caplog.text
    assert f"uid={client.uid}" in texto and "nivel=alto" in texto and "reglas=dmarc=fail,dkim=fail" in texto
    assert SECRETO not in texto and SECRETO.lower() not in texto.lower()
    # Las razones citan términos del correo.
    assert "«" not in texto


# --- persistencia -----------------------------------------------------------------------

def test_guarda_el_resultado_para_su_dueño(client):
    dueño, _ = crear_usuario("dueño")
    main.app.dependency_overrides[phishing.require_extension_token] = lambda: dueño
    datos = _post(client, PHISHING).json()
    [d] = _detecciones()
    assert d.owner == dueño
    assert (d.etiqueta, d.nivel, d.probabilidad) == (datos["etiqueta"], datos["nivel"], datos["probabilidad"])
    assert d.reglas == datos["reglas"] and d.razones == datos["razones"]
    assert d.fecha is not None


def test_no_guarda_el_correo(client):
    _post(client, {**PHISHING, "body": f"{PHISHING['body']} NoDebeGuardarse"})
    [d] = _detecciones()
    columnas = {c.name: getattr(d, c.name) for c in models.Deteccion.__table__.columns}
    assert not {"subject", "asunto", "body", "cuerpo", "urls"} & set(columnas)
    assert "NoDebeGuardarse" not in str(columnas)


def test_si_falla_el_guardado_igual_responde(client, monkeypatch, caplog):
    def fallar():
        raise OperationalError("insert", {}, Exception("database is locked"))

    monkeypatch.setattr(phishing, "SessionLocal", fallar)
    r = _post(client, PHISHING)
    assert r.status_code == 200 and r.json()["nivel"] == "alto"
    assert "no se pudo guardar" in caplog.text


def test_borrar_el_usuario_borra_sus_detecciones(client):
    with SessionLocal() as db:
        usuario = models.User(
            username="borrame", nombre="a", apellidos="b", email="b@example.com", password_hash="x",
        )
        db.add(usuario)
        db.flush()
        db.add(models.Deteccion(
            owner=usuario.uid, etiqueta="phishing", nivel="alto", probabilidad=0.9, reglas=[], razones=[],
        ))
        db.commit()
        db.delete(usuario)
        db.commit()
    assert not _detecciones()
