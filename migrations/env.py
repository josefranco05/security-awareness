"""Entorno de Alembic. Usa el motor síncrono (psycopg) sobre WORKER_DATABASE_URL.

    alembic upgrade head                              # aplica las migraciones
    alembic revision --autogenerate -m "descripción"  # genera una a partir de los modelos

Revisa siempre lo autogenerado: Alembic no detecta todo (p. ej. cambios de tipo o
renombres los interpreta como borrar y crear).
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import models  # noqa: F401 - registra las tablas en Base.metadata
from core.config import settings
from database.async_database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Las pruebas pasan su propia base en config.attributes["url"] (o una conexión en "connection").
    return config.attributes.get("url") or settings.WORKER_DATABASE_URL.get_secret_value()


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (alembic upgrade head --sql)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conectable = config.attributes.get("connection")
    if conectable is not None:
        _ejecutar(conectable)
        return

    motor = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with motor.connect() as conexion:
        _ejecutar(conexion)


def _ejecutar(conexion) -> None:
    context.configure(connection=conexion, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
