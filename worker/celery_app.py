"""Instancia de Celery compartida por la web y el worker.

Sin Redis el sistema sigue funcionando: con CELERY_TASK_ALWAYS_EAGER=true la
tarea se ejecuta dentro del proceso web (modo desarrollo / demo). Para usar la
cola real, poner CELERY_TASK_ALWAYS_EAGER=false y levantar el worker.
"""
from __future__ import annotations

from celery import Celery

from core.config import settings

celery_app = Celery(
    "sentinel_fish",
    broker=settings.CELERY_BROKER_URL,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    # En modo eager no queremos que un fallo de la tarea rompa la petición.
    task_eager_propagates=False,
    task_store_eager_result=False,
    # La base de datos es la fuente de verdad: no guardamos resultados.
    task_ignore_result=True,
    # Entrega al menos una vez; la idempotencia la da el reclamo atómico.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "barrer-pendientes": {
            "task": "tasks.barrer_pendientes",
            "schedule": 300.0,
        },
        "recuperar-colgadas": {
            "task": "tasks.recuperar_colgadas",
            "schedule": 300.0,
        },
    },
)
