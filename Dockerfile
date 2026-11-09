# syntax=docker/dockerfile:1
# Una sola imagen para web, worker, beat y migraciones; cambia solo el comando:
#   web       gunicorn -c gunicorn.conf.py main:app            (CMD por defecto)
#   worker    celery -A worker.celery_app.celery_app worker --loglevel=info
#   beat      celery -A worker.celery_app.celery_app beat --loglevel=info --schedule /tmp/celerybeat-schedule
#   migrar    alembic upgrade head

ARG PYTHON_VERSION=3.14

# --- build: dependencias y estáticos --------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

# Bytecode compilado en la imagen (arranque más rápido) y copia en vez de enlaces
# (la caché de uv no existe en la etapa final). Sin descargas de Python: usa el de la imagen.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY . .

# El repo guarda el CSS legible; la imagen lo lleva minificado. rcssmin solo existe en esta etapa.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run --no-project --with rcssmin==1.3.0 python -c "import pathlib, rcssmin; p = pathlib.Path('static/css/style.css'); antes = p.stat().st_size; p.write_text(rcssmin.cssmin(p.read_text(encoding='utf-8')), encoding='utf-8'); print(f'style.css: {antes} -> {p.stat().st_size} bytes')"

# --- final: solo lo necesario para ejecutar --------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie

# Usuario sin privilegios y sin shell de login.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# root es dueño del código: el proceso (app) no puede modificarlo aunque lo comprometan.
COPY --from=build /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    # Solo el ingress de Container Apps llega al contenedor: se confía en sus X-Forwarded-*.
    FORWARDED_ALLOW_IPS="*"

USER app

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
