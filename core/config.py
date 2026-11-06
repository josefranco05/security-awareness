"""Configuración leída del entorno.

pydantic-settings lee el .env aquí mismo para que no dependa del orden de
importación de main.py: cualquier módulo (web o worker) puede importar
`settings` sin preocuparse de si el .env ya se cargó.

Prioridad: variables de entorno reales > .env > valores por defecto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # raíz del proyecto


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # el .env puede tener variables que no son de aquí
    )

    # --- Base de datos -------------------------------------------------
    # Se pueden sobreescribir para apuntar a una base de pruebas.
    DATABASE_URL: str
    WORKER_DATABASE_URL: str

    # --- Celery --------------------------------------------------------
    CELERY_BROKER_URL: str
    # Sin Redis disponible el sistema funciona igual: la tarea se ejecuta
    # dentro del proceso web. Es el modo de desarrollo/demo.
    CELERY_TASK_ALWAYS_EAGER: bool = True

    # --- Correo --------------------------------------------------------
    # "log"  -> no envía nada, solo registra (sirve sin dominio verificado)
    # "acs"  -> Azure Communication Services Email
    EMAIL_BACKEND: Literal["log", "acs"]
    ACS_CONNECTION_STRING: str = ""
    ACS_SENDER: str = ""
    ACS_REPLY_TO: str = ""
    # Secreto que Event Grid envía en la cabecera X-Webhook-Secret (delivery
    # property de la suscripción). Vacío = el webhook rechaza todo.
    ACS_WEBHOOK_SECRET: SecretStr

    # --- Reintentos ----------------------------------------------------
    EMAIL_MAX_INTENTOS: int = 3
    # Umbral para devolver a "pending" las filas que quedaron en "sending".
    EMAIL_LOCK_TIMEOUT_MINUTOS: int = 15

    # --- Autenticación -------------------------------------------------
    # Obligatoria: sin ella la app no arranca.
    SECRET_KEY_AUTH: SecretStr
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Cookie HttpOnly que transporta el JWT. Si en desarrollo el navegador no
    # guarda la cookie por usar http, poner AUTH_COOKIE_SECURE=false en el .env.
    AUTH_COOKIE_NAME: str = "access_token"
    AUTH_COOKIE_SECURE: bool = True

    # --- Protección CSRF -----------------------------------------------
    # Orígenes desde los que se aceptan POST/PUT/PATCH/DELETE. En el .env va
    # como JSON, p. ej.: ALLOWED_ORIGINS='["https://app.sentinel.world"]'
    ALLOWED_ORIGINS: list[str]

    # --- Análisis de phishing ------------------------------------------
    # Por usuario y por worker de gunicorn: el tope real es este × WEB_CONCURRENCY.
    ANALISIS_POR_MINUTO: int = 30

    @field_validator("EMAIL_BACKEND", mode="before")
    @classmethod
    def _normalizar_backend(cls, valor: object) -> object:
        return valor.strip().lower() if isinstance(valor, str) else valor

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def _normalizar_origenes(cls, valor: list[str]) -> list[str]:
        # El navegador envía el Origin sin "/" final y en minúsculas.
        return [origen.strip().rstrip("/").lower() for origen in valor]

    @field_validator("CELERY_TASK_ALWAYS_EAGER", mode="before")
    @classmethod
    def _aceptar_si(cls, valor: object) -> object:
        # pydantic ya acepta 1/true/yes/on; se añade el "sí" en español.
        if isinstance(valor, str) and valor.strip().lower() in {"si", "sí"}:
            return True
        return valor


settings = Settings()  # pyright: ignore[reportCallIssue]
