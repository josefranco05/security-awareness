# security-awareness
Plataforma de simulación y detección de phishing dirigida a pequeñas y medianas empresas colombianas, sin embargo puede ser usado por empresas de todos los paises.

## Desarrollo local

Requisitos: Python 3.14, [uv](https://docs.astral.sh/uv/) y Docker.

```sh
docker compose up -d                   # PostgreSQL (127.0.0.1:5433) y Redis (127.0.0.1:6379)
cp .env.example .env                   # completa los secretos
uv sync
uv run alembic upgrade head            # crea o actualiza el esquema
uv run python -m scripts.seed          # opcional: cuenta "demo" con datos de ejemplo
uv run uvicorn main:app --reload       # http://127.0.0.1:8000
```

La app no crea tablas al arrancar: el esquema lo definen las migraciones de `migrations/`.
Tras cambiar `models/`, genera y **revisa** la migración:

```sh
uv run alembic revision --autogenerate -m "describe el cambio"
```

## Contenedores

Una sola imagen ([Dockerfile](Dockerfile)) para web, worker de Celery, beat y migraciones;
cambia solo el comando. Para levantar todo como en producción, con la cola real en Redis:

```sh
docker compose --profile app up --build     # http://127.0.0.1:8000
```

`migrate` aplica las migraciones y termina; después arrancan `web`, `worker` y `beat`.
En local los correos nunca se envían (`EMAIL_BACKEND=log`), aunque `.env` diga otra cosa.

Sondas: `/healthz` (el proceso responde) y `/readyz` (la base responde y está migrada).

## Pruebas

```sh
uv run pytest                          # necesita docker compose up -d
node --test "extension/tests/*.test.js"
```

Cada ejecución crea una base PostgreSQL desechable, le aplica las migraciones y la borra al
terminar; nunca toca la de desarrollo. Para usar otro servidor: `TEST_POSTGRES_URL`.
Un test falla si los modelos y las migraciones no coinciden.
