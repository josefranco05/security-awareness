"""Entorno de pruebas. Va antes de importar la app: core.config lee el entorno al importarse.

Las variables reales prevalecen sobre el .env, así que las pruebas usan una base
temporal y nunca tocan la base local de desarrollo.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

_base = Path(tempfile.mkdtemp(prefix="sentinel-tests-")) / "test.db"

os.environ.update({
    "SECRET_KEY": "test-only",
    "SECRET_KEY_AUTH": "test-only-secret-of-at-least-32-bytes",
    "ACS_WEBHOOK_SECRET": "test-only",
    "DATABASE_URL": f"sqlite+aiosqlite:///{_base.as_posix()}",
    "WORKER_DATABASE_URL": f"sqlite:///{_base.as_posix()}",
    "CELERY_BROKER_URL": "memory://",
    "CELERY_TASK_ALWAYS_EAGER": "true",
    "EMAIL_BACKEND": "log",
    "EMAIL_MAX_INTENTOS": "3",
    "EMAIL_LOCK_TIMEOUT_MINUTOS": "15",
    "AUTH_COOKIE_SECURE": "true",
    "ALLOWED_ORIGINS": '["http://testserver"]',
    "ANALISIS_POR_MINUTO": "30",
})

import pytest
from fastapi.testclient import TestClient

from core.auth import create_access_token, nuevo_token_extension
from core.config import settings
from database.worker_db import SessionLocal
import main
import models
from routers import phishing


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
    with TestClient(main.app):  # ejecuta lifespan: crea las tablas y carga el modelo
        yield main.app


@pytest.fixture
def anonimo(_app_iniciada):
    """Cliente sin credenciales, sobre una base limpia."""
    phishing.limite_analisis.reiniciar()
    with SessionLocal() as db:
        for modelo in (
            models.Deteccion, models.TokenExtension, models.Simulaciones,
            models.Campaña, models.Empleados, models.User,
        ):
            db.query(modelo).delete()
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
