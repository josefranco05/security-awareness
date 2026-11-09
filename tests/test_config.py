"""Configuración: las URLs de base exigen PostgreSQL y nunca se filtran en los errores."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import Settings

BASE = {
    "SECRET_KEY_AUTH": "x", "ACS_WEBHOOK_SECRET": "x", "CELERY_BROKER_URL": "memory://", "EMAIL_BACKEND": "log",
    "ALLOWED_ORIGINS": ["http://testserver"],
    "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1/b",
    "WORKER_DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1/b",
}


@pytest.mark.parametrize("campo, url", [
    ("DATABASE_URL", "sqlite+aiosqlite:///./database.db"),
    ("DATABASE_URL", "postgresql+psycopg://u:p@h/b"),  # driver equivocado para la web
    ("WORKER_DATABASE_URL", "postgresql+asyncpg://u:p@h/b"),
    ("WORKER_DATABASE_URL", "postgresql://u:p@h/b"),
])
def test_cada_url_exige_su_driver(campo, url):
    with pytest.raises(ValidationError, match=campo):
        Settings(_env_file=None, **{**BASE, campo: url})


def test_el_error_no_muestra_la_contraseña():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **{**BASE, "DATABASE_URL": "postgres://admin:ContraseñaSecreta@db/prod"})
    assert "ContraseñaSecreta" not in str(error.value)


def test_la_url_no_sale_al_imprimir_la_configuracion():
    ajustes = Settings(_env_file=None, **{**BASE, "DATABASE_URL": "postgresql+asyncpg://u:ContraseñaSecreta@h/b"})
    assert "ContraseñaSecreta" not in repr(ajustes)
    assert ajustes.DATABASE_URL.get_secret_value().endswith("@h/b")
