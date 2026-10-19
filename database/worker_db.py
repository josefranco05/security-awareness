"""Acceso a datos para el worker de Celery.

El motor de database/async_database.py es ASÍNCRONO y está atado al event loop donde se creó.
Reutilizarlo desde una tarea síncrona provoca "attached to a different loop",
así que el worker tiene su propio motor síncrono sobre la misma base de datos.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import settings

# timeout: espera hasta 30 s si la web tiene la base bloqueada.
engine = create_engine(
    settings.WORKER_DATABASE_URL,
    connect_args={"timeout": 30, "check_same_thread": False},
)


SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)
