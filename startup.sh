#!/bin/bash

# Con CELERY_TASK_ALWAYS_EAGER=true (por defecto) la tarea de envío se ejecuta
# dentro del proceso web: no hace falta worker ni Redis.
# Con CELERY_TASK_ALWAYS_EAGER=false se levantan worker y beat aquí mismo.
if [ "${CELERY_TASK_ALWAYS_EAGER:-true}" != "true" ]; then
  echo "Iniciando worker y beat de Celery"
  celery -A worker.celery_app.celery_app worker --loglevel=info --concurrency=1 &
  celery -A worker.celery_app.celery_app beat --loglevel=info &
fi

# Sin -w, gunicorn toma el número de workers de WEB_CONCURRENCY (App Setting).
exec gunicorn -k uvicorn_worker.UvicornWorker main:app --bind 0.0.0.0:${PORT:-8000}
