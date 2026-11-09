"""Entorno de pruebas. Va antes de importar la app: core.config lee el entorno al importarse.

Cada sesión crea una base PostgreSQL desechable en el servidor de TEST_POSTGRES_URL
(por defecto, el de docker-compose.yml), le aplica las migraciones y la borra al
terminar. Nunca toca la base de desarrollo. Requiere: docker compose up -d
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

_SERVIDOR = make_url(os.environ.get(
    "TEST_POSTGRES_URL", "postgresql://sentinel:sentinel@127.0.0.1:5433/sentinel",
))
_NOMBRE_BASE = f"sentinel_test_{uuid4().hex[:12]}"


def _url(driver: str, base: str | None) -> str:
    return _SERVIDOR.set(drivername=driver, database=base).render_as_string(hide_password=False)


def _admin(sql: str) -> None:
    # Se conecta a la base del servidor, no a la de pruebas: no se puede crear ni borrar la base en uso.
    with psycopg.connect(_url("postgresql", _SERVIDOR.database), autocommit=True, connect_timeout=5) as conexion:
        conexion.execute(sql)


try:
    _admin(f'CREATE DATABASE "{_NOMBRE_BASE}"')
except psycopg.OperationalError as exc:
    pytest.exit(f"PostgreSQL no responde en {_SERVIDOR.host}:{_SERVIDOR.port}. ¿docker compose up -d? ({exc})", 4)

os.environ.update({
    "SECRET_KEY": "test-only",
    "SECRET_KEY_AUTH": "test-only-secret-of-at-least-32-bytes",
    "ACS_WEBHOOK_SECRET": "test-only",
    "DATABASE_URL": _url("postgresql+asyncpg", _NOMBRE_BASE),
    "WORKER_DATABASE_URL": _url("postgresql+psycopg", _NOMBRE_BASE),
    "CELERY_BROKER_URL": "memory://",
    "CELERY_TASK_ALWAYS_EAGER": "true",
    "EMAIL_BACKEND": "log",
    "EMAIL_MAX_INTENTOS": "3",
    "EMAIL_LOCK_TIMEOUT_MINUTOS": "15",
    "AUTH_COOKIE_SECURE": "true",
    "ALLOWED_ORIGINS": '["http://testserver"]',
    "ANALISIS_POR_MINUTO": "30",
})


def configuracion_alembic(url: str) -> Config:
    """Sin alembic.ini a propósito: su configuración de logging pisaría la de pytest."""
    cfg = Config()
    cfg.set_main_option("script_location", "migrations")
    cfg.attributes["url"] = url
    return cfg


# Mismo camino que en producción: el esquema sale de las migraciones, no de create_all.
command.upgrade(configuracion_alembic(os.environ["WORKER_DATABASE_URL"]), "head")

from fastapi.testclient import TestClient  # noqa: E402 - después de fijar el entorno

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.auth import create_access_token, nuevo_token_extension  # noqa: E402
from core.config import settings  # noqa: E402
from database import async_database  # noqa: E402
from database.async_database import Base  # noqa: E402
from database.worker_db import SessionLocal, engine as motor_sincrono  # noqa: E402
import main  # noqa: E402
import models  # noqa: E402
from routers import phishing  # noqa: E402

# TestClient abre un event loop por petición y una conexión de asyncpg solo sirve en el
# loop que la creó: sin pool, cada sesión abre la suya. En producción hay un solo loop y pool real.
async_database.AsyncSessionLocal.configure(
    bind=create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool),
)


def pytest_sessionfinish(session, exitstatus):
    motor_sincrono.dispose()
    # FORCE cierra las conexiones que aún queden abiertas (p. ej. del pool asíncrono).
    _admin(f'DROP DATABASE IF EXISTS "{_NOMBRE_BASE}" WITH (FORCE)')


def crear_usuario(username: str = "ana") -> tuple[UUID, str]:
    """Crea un usuario con token de extensión y devuelve (uid, token)."""
    token, token_hash = nuevo_token_extension()
    with SessionLocal() as db:
        usuario = models.User(
            username=username, nombre="a", apellidos="b", email=f"{username}@example.com", password_hash="x",
        )
        db.add(usuario)
        db.flush()
        db.add(models.TokenExtension(owner=usuario.uid, token_hash=token_hash))
        db.commit()
        return usuario.uid, token


ORIGEN = "http://testserver"


def sesion(uid: UUID) -> dict[str, str]:
    """Cabeceras de una petición del frontend con sesión iniciada."""
    jwt = create_access_token(subject=uid).access_token
    return {"Cookie": f"{settings.AUTH_COOKIE_NAME}={jwt}", "Origin": ORIGEN}


@pytest.fixture(scope="session")
def _app_iniciada():
    with TestClient(main.app):  # ejecuta lifespan: carga el modelo de detección
        yield main.app


_TABLAS = ", ".join(tabla.name for tabla in Base.metadata.sorted_tables)


@pytest.fixture
def anonimo(_app_iniciada):
    """Cliente sin credenciales, sobre una base limpia."""
    phishing.limite_analisis.reiniciar()
    with SessionLocal() as db:
        db.execute(text(f"TRUNCATE {_TABLAS} CASCADE"))
        db.commit()
    yield TestClient(_app_iniciada)
    _app_iniciada.dependency_overrides.clear()


@pytest.fixture
def client(anonimo, _app_iniciada):
    """Cliente con el token de extensión de un usuario real."""
    uid, token = crear_usuario()
    cliente = TestClient(_app_iniciada, headers={"Authorization": f"Bearer {token}"})
    cliente.uid = uid
    return cliente
