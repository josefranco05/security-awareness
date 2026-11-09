"""Sondas para el orquestador (Azure Container Apps / docker compose).

/healthz  liveness: el proceso responde. No toca la base: si la base cae, reiniciar
          la app no lo arregla y solo añadiría reinicios en cadena.
/readyz   readiness: la base responde y su esquema está en la revisión de las
          migraciones de esta imagen. Mientras no, no se le envía tráfico.

Las respuestas no dan detalles (versiones, errores): son rutas públicas.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.async_database import get_db

logger = logging.getLogger(__name__)

MIGRACIONES = Path(__file__).resolve().parent.parent / "migrations"

router = APIRouter(include_in_schema=False)


@lru_cache(maxsize=1)
def revision_esperada() -> str | None:
    """La última migración incluida en esta imagen."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRACIONES))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _no_lista(motivo: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": motivo})


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        actual = await db.scalar(text("SELECT version_num FROM alembic_version"))
    except (SQLAlchemyError, OSError) as exc:
        # Sin la tabla alembic_version también cae aquí: nunca se migró.
        logger.warning("readyz: la base no responde (%s)", type(exc).__name__)
        return _no_lista("sin base de datos")
    if actual != revision_esperada():
        logger.warning("readyz: esquema en %s, la imagen espera %s", actual, revision_esperada())
        return _no_lista("migraciones pendientes")
    return {"status": "ok"}
