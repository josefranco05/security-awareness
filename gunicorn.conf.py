"""Configuración de gunicorn para el contenedor web. Todo se ajusta por variables de entorno."""
from __future__ import annotations

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "uvicorn_worker.UvicornWorker"

# Cada worker carga su propio modelo de detección en memoria: subirlo sube la RAM.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# El análisis de phishing es CPU; 60 s deja margen sin colgar un worker para siempre.
timeout = 60
graceful_timeout = 30

# A stdout/stderr: Container Apps los envía a Log Analytics.
accesslog = "-"
errorlog = "-"

# Sin socket de control (gunicornc): al proceso lo gestiona el orquestador, y el usuario
# del contenedor no tiene home donde crearlo.
control_socket_disable = True

# De qué IPs se aceptan X-Forwarded-Proto/For. Detrás del ingress de Container Apps el
# contenedor no es accesible directamente, así que "*" es seguro allí. Sin esto, los
# redirects (url_for) saldrían con http:// porque el TLS termina en el ingress.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
