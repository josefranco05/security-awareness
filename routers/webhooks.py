"""Webhook de eventos de Azure Communication Services (Event Grid).

Los informes de entrega NO vuelven por Celery: llegan aquí. Este endpoint
traduce el resultado de ACS al estado interno de la simulación.

Nota de concurrencia: si el informe llegara antes de que la tarea guarde el
`proveedor_id` (ventana de milisegundos), la fila aún no es localizable y el
evento se ignora en lugar de fallar. El estado de envío no se ve afectado.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database.async_database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

EVENTO_VALIDACION = "Microsoft.EventGrid.SubscriptionValidationEvent"
EVENTO_ENTREGA = "Microsoft.Communication.EmailDeliveryReportReceived"

# Solo "Delivered" cuenta como entregado. Cualquier otro valor (rebote,
# supresión, cuarentena) significa que el correo no llegó.
MAPA_ENTREGA = {"Delivered": "sent"}

# Si la simulación ya avanzó a interacción, el webhook no la sobreescribe.
ESTADOS_SOBREESCRIBIBLES = ("sending", "sent")


@router.post("/acs", name="acs_eventos")
async def acs_eventos(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        cuerpo = await request.json()
    except Exception:
        logger.warning("webhook ACS: el cuerpo no es JSON válido")
        return {"ok": False}

    eventos = cuerpo if isinstance(cuerpo, list) else [cuerpo]

    for evento in eventos:
        if not isinstance(evento, dict):
            continue

        tipo = evento.get("eventType")

        # Handshake de suscripción: sin esta respuesta Event Grid reintenta indefinidamente.
        if tipo == EVENTO_VALIDACION:
            codigo = (evento.get("data") or {}).get("validationCode")
            return {"validationResponse": codigo}

        if tipo != EVENTO_ENTREGA:
            continue

        datos = evento.get("data") or {}
        proveedor_id = datos.get("messageId")
        entrega = datos.get("deliveryStatus") or ""

        if not proveedor_id:
            continue

        nuevo_estado = MAPA_ENTREGA.get(entrega, "failed")

        await db.execute(
            update(models.Simulaciones)
            .where(
                models.Simulaciones.proveedor_id == proveedor_id,
                models.Simulaciones.status.in_(ESTADOS_SOBREESCRIBIBLES),
            )
            .values(status=nuevo_estado)
        )

        logger.info(
            "webhook ACS: proveedor_id=%s -> %s (deliveryStatus=%s)",
            proveedor_id, nuevo_estado, entrega,
        )

    await db.commit()
    return {"ok": True}
