"""Acceso síncrono a datos, para el worker de Celery y los endpoints `def`.

El motor de database/async_database.py es ASÍNCRONO y está atado al event loop donde se creó.
Reutilizarlo desde código síncrono provoca "attached to a different loop", así que
aquí hay un motor síncrono sobre la misma base de datos.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import settings

engine = create_engine(
    settings.WORKER_DATABASE_URL.get_secret_value(),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
)


SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)
