"""Configuración leída del entorno.

Carga el .env aquí mismo para que no dependa del orden de importación de
main.py: cualquier módulo (web o worker) puede importar `settings` sin
preocuparse de si load_dotenv ya se ejecutó.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # raíz del proyecto
load_dotenv(dotenv_path=BASE_DIR / ".env")

_TRUE = {"1", "true", "yes", "si", "sí", "on"}


def _bool(name: str, default: bool) -> bool:
    valor = os.getenv(name)
    if valor is None:
        return default
    return valor.strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings:
    # --- Base de datos -------------------------------------------------
    # Se pueden sobreescribir para apuntar a una base de pruebas.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./database.db"
    )
    WORKER_DATABASE_URL: str = os.getenv(
        "WORKER_DATABASE_URL", "sqlite:///./database.db"
    )

    # --- Celery --------------------------------------------------------
    CELERY_BROKER_URL: str = os.getenv(
        "CELERY_BROKER_URL", "redis://localhost:6379/0"
    )
    # Sin Redis disponible el sistema funciona igual: la tarea se ejecuta
    # dentro del proceso web. Es el modo de desarrollo/demo.
    CELERY_TASK_ALWAYS_EAGER: bool = _bool("CELERY_TASK_ALWAYS_EAGER", True)

    # --- Correo --------------------------------------------------------
    # "log"  -> no envía nada, solo registra (sirve sin dominio verificado)
    # "acs"  -> Azure Communication Services Email
    EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "log").strip().lower()
    ACS_CONNECTION_STRING: str = os.getenv("ACS_CONNECTION_STRING", "")
    ACS_SENDER: str = os.getenv("ACS_SENDER", "")
    ACS_REPLY_TO: str = os.getenv("ACS_REPLY_TO", "")

    # --- Reintentos ----------------------------------------------------
    EMAIL_MAX_INTENTOS: int = _int("EMAIL_MAX_INTENTOS", 3)
    # Umbral para devolver a "pending" las filas que quedaron en "sending".
    EMAIL_LOCK_TIMEOUT_MINUTOS: int = _int("EMAIL_LOCK_TIMEOUT_MINUTOS", 15)


settings = Settings()
