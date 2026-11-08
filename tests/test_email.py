"""Backend de correo: qué se envía a ACS y cómo se clasifican sus errores."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import azure.communication.email
import pytest
from azure.core.exceptions import ResourceExistsError

from services import email
from services.email import ErrorPermanente, ErrorTransitorio, enviar_email

SIM = SimpleNamespace(
    id=1,
    empleados=SimpleNamespace(email="empleado@example.com"),
    campana=SimpleNamespace(asunto="Bono", cuerpo="<p>Hola</p>", remitente="ceo@empresa-falsa.com"),
)


class _ErrorHttp(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _ClienteFalso:
    enviados: list[dict] = []
    error: Exception | None = None

    @classmethod
    def from_connection_string(cls, conexion, **opciones):
        return cls()

    def begin_send(self, mensaje, **opciones):
        type(self).enviados.append({"mensaje": mensaje, **opciones})
        if type(self).error:
            raise type(self).error


@pytest.fixture
def acs(monkeypatch):
    _ClienteFalso.enviados, _ClienteFalso.error = [], None
    monkeypatch.setattr(azure.communication.email, "EmailClient", _ClienteFalso)
    monkeypatch.setattr(email.settings, "EMAIL_BACKEND", "acs")
    monkeypatch.setattr(email.settings, "ACS_CONNECTION_STRING", "endpoint=https://x;accesskey=y")
    monkeypatch.setattr(email.settings, "ACS_SENDER", "DoNotReply@sentinel.test")
    monkeypatch.setattr(email.settings, "ACS_REPLY_TO", "")
    return _ClienteFalso


def test_backend_log_no_envia_nada(caplog):
    with caplog.at_level(logging.INFO, logger=email.logger.name):
        assert enviar_email(SIM, "op-1") == "op-1"
    assert "empleado@example.com" in caplog.text


def test_backend_desconocido_es_permanente(monkeypatch):
    monkeypatch.setattr(email.settings, "EMAIL_BACKEND", "smtp")
    with pytest.raises(ErrorPermanente):
        enviar_email(SIM, "op-1")


def test_acs_envia_desde_el_remitente_verificado(acs):
    assert enviar_email(SIM, "op-1") == "op-1"
    [envio] = acs.enviados
    mensaje = envio["mensaje"]
    # Nunca Campaña.remitente: es texto libre y no está verificado en ACS.
    assert mensaje["senderAddress"] == "DoNotReply@sentinel.test"
    assert "ceo@empresa-falsa.com" not in str(mensaje)
    assert mensaje["recipients"] == {"to": [{"address": "empleado@example.com"}]}
    assert mensaje["content"] == {"subject": "Bono", "html": "<p>Hola</p>"}
    assert "replyTo" not in mensaje
    assert envio["operation_id"] == "op-1" and envio["polling"] is False


def test_acs_reply_to_opcional(acs, monkeypatch):
    monkeypatch.setattr(email.settings, "ACS_REPLY_TO", "soporte@sentinel.test")
    enviar_email(SIM, "op-1")
    assert acs.enviados[0]["mensaje"]["replyTo"] == [{"address": "soporte@sentinel.test"}]


@pytest.mark.parametrize("ajuste", ["ACS_CONNECTION_STRING", "ACS_SENDER"])
def test_acs_sin_configurar_es_permanente(acs, monkeypatch, ajuste):
    monkeypatch.setattr(email.settings, ajuste, "")
    with pytest.raises(ErrorPermanente):
        enviar_email(SIM, "op-1")
    assert acs.enviados == []


def test_operacion_repetida_no_es_error(acs):
    acs.error = ResourceExistsError("409")
    assert enviar_email(SIM, "op-1") == "op-1"


@pytest.mark.parametrize("error", [
    _ErrorHttp(429), _ErrorHttp(500), _ErrorHttp(503), TimeoutError("timeout"), ConnectionError("dns"),
])
def test_errores_reintentables(acs, error):
    acs.error = error
    with pytest.raises(ErrorTransitorio):
        enviar_email(SIM, "op-1")


@pytest.mark.parametrize("codigo", [400, 401, 403, 404, 422])
def test_errores_del_cliente_son_permanentes(acs, codigo):
    acs.error = _ErrorHttp(codigo)
    with pytest.raises(ErrorPermanente):
        enviar_email(SIM, "op-1")
