"""Análisis de correos para la extensión del navegador.

Todo aquí es `def`, no `async def`: analizar() es CPU-bound y bloquearía el event
loop, así que corre en el threadpool. Por eso guarda con la sesión síncrona.

Del correo no se registra ni se guarda nada. `razones` tampoco va al log: cita
términos del correo. Debe devolverse y guardarse solo para su dueño.
"""
from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

import models
from core.auth import require_extension_token
from core.config import settings
from core.limites import LimiteVentana
from database.worker_db import SessionLocal
from ml.inferencia import MAX_BYTES_CUERPO, analizar
from schemas.phishing import AnalisisRequest, AnalisisResponse

logger = logging.getLogger(__name__)

RUTA_ANALISIS = "/api/phishing/analizar"
# Sobre del JSON: el cuerpo (100 KB), el asunto, 50 enlaces y los escapes de JSON.
MAX_BYTES_PETICION = 512_000

limite_analisis = LimiteVentana()


def limitar_peticiones(uid: Annotated[int, Depends(require_extension_token)]) -> int:
    espera = limite_analisis.comprobar(uid, settings.ANALISIS_POR_MINUTO)
    if espera:
        logger.warning("análisis rechazado: uid=%s motivo=limite espera_s=%s", uid, espera)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados análisis. Intenta de nuevo en un momento.",
            headers={"Retry-After": str(espera)},
        )
    return uid


def _guardar_deteccion(uid: int, resultado) -> None:
    """Un fallo aquí no le quita el resultado al usuario: se registra y se sigue."""
    try:
        with SessionLocal() as db:
            db.add(models.Deteccion(
                owner=uid,
                etiqueta=resultado.etiqueta,
                nivel=resultado.nivel.value,
                probabilidad=resultado.probabilidad,
                reglas=list(resultado.reglas),
                razones=list(resultado.razones),
            ))
            db.commit()
    except SQLAlchemyError as e:
        logger.error("no se pudo guardar la detección: uid=%s error=%s", uid, type(e).__name__)


router = APIRouter()


@router.post("/analizar", response_model=AnalisisResponse, name="analizar_correo")
def analizar_correo(
    datos: AnalisisRequest,
    request: Request,
    uid: Annotated[int, Depends(limitar_peticiones)],
):
    bytes_cuerpo = len(datos.body.encode("utf-8"))
    if bytes_cuerpo > MAX_BYTES_CUERPO:
        logger.warning("análisis rechazado: uid=%s motivo=tamaño bytes=%s", uid, bytes_cuerpo)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="El correo es demasiado grande para analizarlo.",
        )

    inicio = time.perf_counter()
    resultado = analizar(
        request.app.state.modelo_phishing,
        datos.subject,
        datos.body,
        urls=[enlace.model_dump() for enlace in datos.urls],
        auth_results=datos.auth_results.model_dump(),
    )
    ms = (time.perf_counter() - inicio) * 1000

    _guardar_deteccion(uid, resultado)
    logger.info(
        "análisis: uid=%s nivel=%s etiqueta=%s probabilidad=%.4f reglas=%s bytes=%s urls=%s ms=%.1f",
        uid, resultado.nivel.value, resultado.etiqueta, resultado.probabilidad,
        ",".join(resultado.reglas) or "-", bytes_cuerpo, len(datos.urls), ms,
    )
    return resultado
