"""Tareas de envío de simulaciones.

Idempotencia: la unidad de trabajo es la fila de `simulaciones`. Antes de
enviar, cada fila se reclama con una actualización condicional
(`pending -> sending`). Si dos workers procesan la misma campaña, solo uno
obtiene `rowcount == 1` para cada fila, de modo que ningún correo se envía dos
veces aunque el mensaje de la cola se entregue repetido.

El reclamo no basta si el worker muere (o falla el commit) DESPUÉS de que el
proveedor aceptó el correo: `recuperar_colgadas` devuelve la fila a `pending`
y se reenvía. Para ese caso, el reclamo asigna un `proveedor_id` (Operation-Id
de ACS) que se conserva entre intentos; el reenvío usa el mismo id y ACS no
crea un segundo correo.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from celery import Task

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import OperationalError

import models
from worker.celery_app import celery_app
from core.config import settings
from services.email import ErrorPermanente, ErrorTransitorio, enviar_email
from database.worker_db import SessionLocal

logger = logging.getLogger(__name__)

# Reintentos del UPDATE posterior al envío (p. ej. SQLite bloqueado).
GUARDAR_INTENTOS = 3


def tarea(**opciones: Any) -> Callable[[Callable[..., Any]], Task]:
    """`celery_app.task` con tipo: sin stubs, el analizador cree que el
    decorador devuelve la función y no ve `.delay` ni `.apply_async`."""
    return cast(Callable[[Callable[..., Any]], Task], celery_app.task(**opciones))


def _reclamar(db, sim_id: int) -> bool:
    """Marca la fila como `sending` solo si seguía en `pending`.

    En el primer reclamo fija el `proveedor_id`; los siguientes lo conservan.
    """
    # Un UPDATE devuelve CursorResult (con rowcount); execute() se tipa como Result.
    resultado = cast(CursorResult, db.execute(
        update(models.Simulaciones)
        .where(
            models.Simulaciones.id == sim_id,
            models.Simulaciones.status == "pending",
        )
        .values(
            status="sending",
            locked_at=datetime.now(UTC),
            intentos=models.Simulaciones.intentos + 1,
            proveedor_id=func.coalesce(
                models.Simulaciones.proveedor_id, str(uuid.uuid4())
            ),
        )
        .execution_options(synchronize_session=False)
    ))
    db.commit()
    return resultado.rowcount == 1


def _guardar(db, sim_id: int, **valores) -> bool:
    """Guarda el resultado del envío si la fila sigue en `sending`.

    Si no se logra, la fila queda en `sending` con su `proveedor_id`:
    `recuperar_colgadas` la devolverá a `pending` y el reenvío reutilizará el
    mismo Operation-Id, así que no hay correo duplicado.
    """
    for intento in range(1, GUARDAR_INTENTOS + 1):
        try:
            db.execute(
                update(models.Simulaciones)
                .where(
                    models.Simulaciones.id == sim_id,
                    models.Simulaciones.status == "sending",
                )
                .values(locked_at=None, **valores)
                .execution_options(synchronize_session=False)
            )
            db.commit()
            return True
        except OperationalError:
            db.rollback()
            logger.warning(
                "simulacion %s: no se pudo guardar el resultado (intento %s/%s)",
                sim_id, intento, GUARDAR_INTENTOS,
            )
            time.sleep(intento)
    logger.error(
        "simulacion %s: resultado sin guardar; queda en 'sending' para recuperación",
        sim_id,
    )
    return False


@tarea(name="tasks.enviar_campaña", ignore_result=True)
def enviar_campaña(camid: int) -> dict:
    enviados = fallidos = reintentables = omitidas = 0

    with SessionLocal() as db:
        filas = db.scalars(
            select(models.Simulaciones)
            .where(
                models.Simulaciones.campana_id == camid,
                models.Simulaciones.status == "pending",
            )
            .order_by(models.Simulaciones.id)
        ).all()

        for sim in filas:
            if not _reclamar(db, sim.id):
                omitidas += 1
                continue

            db.refresh(sim)  # estado, intentos y proveedor_id tras el reclamo

            try:
                if not sim.proveedor_id:  # el reclamo siempre lo asigna
                    raise ErrorPermanente("La simulación no tiene proveedor_id")
                enviar_email(sim, sim.proveedor_id)
                valores = {
                    "status": "sent",
                    "fecha_envio": datetime.now(UTC),
                    "error": None,
                }
                enviados += 1
            except ErrorTransitorio as exc:
                logger.warning("simulacion %s: error transitorio: %s", sim.id, exc)
                if sim.intentos >= settings.EMAIL_MAX_INTENTOS:
                    valores = {"status": "failed", "error": str(exc)}
                    fallidos += 1
                else:
                    # el barrido lo reintentará con el mismo proveedor_id
                    valores = {"status": "pending", "error": str(exc)}
                    reintentables += 1
            except ErrorPermanente as exc:
                logger.error("simulacion %s: error permanente: %s", sim.id, exc)
                valores = {"status": "failed", "error": str(exc)}
                fallidos += 1
            except Exception as exc:  # inesperado: no reintentar en bucle
                logger.exception("simulacion %s: error inesperado", sim.id)
                valores = {"status": "failed", "error": f"Error inesperado: {exc}"}
                fallidos += 1

            _guardar(db, sim.id, **valores)

    if filas:
        logger.info(
            "campaña %s: enviados=%s fallidos=%s reintentables=%s omitidas=%s",
            camid, enviados, fallidos, reintentables, omitidas,
        )

    return {
        "camid": camid,
        "enviados": enviados,
        "fallidos": fallidos,
        "reintentables": reintentables,
        "omitidas": omitidas,
    }


@tarea(name="tasks.barrer_pendientes", ignore_result=True)
def barrer_pendientes(limite: int = 50) -> int:
    """Red de seguridad: encola campañas con filas pendientes.

    Cubre el caso de un broker caído en el momento del alta, o un despacho
    perdido.
    """
    with SessionLocal() as db:
        camids = db.scalars(
            select(models.Simulaciones.campana_id)
            .where(models.Simulaciones.status == "pending")
            .distinct()
            .limit(limite)
        ).all()

    for camid in camids:
        enviar_campaña.delay(camid)

    if camids:
        logger.info("barrido: %s campañas encoladas", len(camids))
    return len(camids)


@tarea(name="tasks.recuperar_colgadas", ignore_result=True)
def recuperar_colgadas() -> int:
    """Devuelve a `pending` las filas atascadas en `sending`.

    Ocurre si el worker muere a mitad de un envío.
    """
    corte = datetime.now(UTC) - timedelta(
        minutes=settings.EMAIL_LOCK_TIMEOUT_MINUTOS
    )

    with SessionLocal() as db:
        resultado = cast(CursorResult, db.execute(
            update(models.Simulaciones)
            .where(
                models.Simulaciones.status == "sending",
                models.Simulaciones.locked_at.is_not(None),
                models.Simulaciones.locked_at < corte,
            )
            .values(status="pending", locked_at=None)
            .execution_options(synchronize_session=False)
        ))
        db.commit()

    if resultado.rowcount:
        logger.warning("recuperadas %s simulaciones colgadas", resultado.rowcount)
    return resultado.rowcount
