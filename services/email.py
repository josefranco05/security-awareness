"""Envío de los correos de simulación.

Backends seleccionables con la variable EMAIL_BACKEND:

  log  -> no envía nada, solo registra el mensaje. Es el modo por defecto y
          permite probar toda la cola mientras el dominio de ACS sigue en
          verificación.
  acs  -> Azure Communication Services Email.

El remitente SIEMPRE sale de la configuración (ACS_SENDER), nunca de
Campaña.remitente, que es texto libre escrito por el usuario y no es una
dirección verificada en ACS.

Idempotencia: cada simulación tiene un `operation_id` propio que se guarda
ANTES de enviar y se reutiliza en cada reintento. ACS lo recibe como cabecera
Operation-Id, así que reenviar la misma simulación no crea un correo nuevo.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.config import settings

if TYPE_CHECKING:  # pragma: no cover
    import models

logger = logging.getLogger(__name__)

# Límites de red por llamada. Con los reintentos del SDK, un envío no puede
# durar más de unos pocos minutos: muy por debajo de EMAIL_LOCK_TIMEOUT_MINUTOS,
# así que `recuperar_colgadas` no libera una fila cuyo envío sigue en curso.
ACS_CONNECTION_TIMEOUT = 10
ACS_READ_TIMEOUT = 30
ACS_RETRY_TOTAL = 3


class ErrorTransitorio(Exception):
    """Reintentable: límite de tasa, timeout, error del servidor."""


class ErrorPermanente(Exception):
    """No reintentable: dirección inválida, destinatario suprimido, rechazo."""


def enviar_email(sim: "models.Simulaciones", operation_id: str) -> str:
    """Envía un correo y devuelve el identificador de la operación.

    `operation_id` debe ser el mismo en todos los intentos de una simulación.
    """
    backend = settings.EMAIL_BACKEND

    if backend == "log":
        return _enviar_log(sim, operation_id)
    if backend == "acs":
        return _enviar_acs(sim, operation_id)

    raise ErrorPermanente(f"EMAIL_BACKEND no soportado: {backend!r}")


def _destinatario(sim: "models.Simulaciones") -> str:
    return sim.empleados.email


def _enviar_log(sim: "models.Simulaciones", operation_id: str) -> str:
    logger.info(
        "[email:log] simulacion=%s operacion=%s para=%s asunto=%r remitente_usuario=%r",
        sim.id,
        operation_id,
        _destinatario(sim),
        sim.campana.asunto,
        sim.campana.remitente,
    )
    return operation_id


def _enviar_acs(sim: "models.Simulaciones", operation_id: str) -> str:
    try:
        from azure.communication.email import EmailClient
        from azure.core.exceptions import ResourceExistsError
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ErrorPermanente(
            "Falta el paquete azure-communication-email en el entorno"
        ) from exc

    if not settings.ACS_CONNECTION_STRING:
        raise ErrorPermanente("ACS_CONNECTION_STRING no está configurada")
    if not settings.ACS_SENDER:
        raise ErrorPermanente("ACS_SENDER no está configurada")

    mensaje = {
        "senderAddress": settings.ACS_SENDER,
        "content": {
            "subject": sim.campana.asunto,
            "html": sim.campana.cuerpo,
        },
        "recipients": {"to": [{"address": _destinatario(sim)}]},
    }
    if settings.ACS_REPLY_TO:
        mensaje["replyTo"] = [{"address": settings.ACS_REPLY_TO}]

    # begin_send hace el POST y espera el 202 antes de devolver el poller: en
    # ese punto ACS ya aceptó el correo. NO se llama a .result(), que espera el
    # estado final y puede tardar minutos; la entrega llega por el webhook.
    try:
        cliente = EmailClient.from_connection_string(
            settings.ACS_CONNECTION_STRING,
            retry_total=ACS_RETRY_TOTAL,
        )
        cliente.begin_send(
            mensaje,
            operation_id=operation_id,
            connection_timeout=ACS_CONNECTION_TIMEOUT,
            read_timeout=ACS_READ_TIMEOUT,
        )
    except ResourceExistsError:
        # 409: ya existe una operación con este Operation-Id, es decir, un
        # intento anterior llegó a ACS. No se vuelve a enviar.
        logger.info(
            "simulacion %s: la operación %s ya existía en ACS", sim.id, operation_id
        )
    except Exception as exc:
        estado = getattr(exc, "status_code", None)
        # Sin código (timeout, DNS, conexión) o 429/5xx -> reintentar con el
        # mismo operation_id.
        if estado is None or estado == 429 or estado >= 500:
            raise ErrorTransitorio(
                f"ACS {estado or 'sin código'}: {exc}"
            ) from exc
        raise ErrorPermanente(f"ACS {estado}: {exc}") from exc

    return operation_id
