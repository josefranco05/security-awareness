"""
Security Awareness — app.py
Sirve los templates Jinja2 y los archivos estáticos de la carpeta "html files".

Ejecutar:
    pip install fastapi uvicorn jinja2 python-multipart itsdangerous
    uvicorn main:app --reload        # luego abrir http://127.0.0.1:8000
"""
from __future__ import annotations

import contextvars
from pathlib import Path
import os
from dotenv import load_dotenv
from typing import Optional, Annotated
from datetime import datetime, UTC
from contextlib import asynccontextmanager

from pydantic import ValidationError

from fastapi import FastAPI, Form, Request, HTTPException, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError

from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy import select, func, ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

import models
from database.async_database import Base, engine, get_db
from routers import campañas as campañas_router, empleados, simulaciones, webhooks, usuarios
from core.auth import get_current_user, CurrentUser, OptionalUser
from core.config import settings


BASE_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    raise ValueError("SECRET_KEY is not setup. Please set environment variable.")

# Muestra también los logger.info de la app (p. ej. el resumen de envío de
# worker/tasks.py en modo eager). Por defecto Python solo muestra WARNING+.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(
    lifespan=lifespan,
    title="Sentinel - The Plague",
)


# Sesión en cookie (para los mensajes flash)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Archivos estáticos (CSS, imágenes, JS propios)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# Rutas protegidas: requieren un JWT válido en la cookie HttpOnly de sesión
auth_required = [Depends(get_current_user)]
app.include_router(simulaciones.router, prefix="/api/simulaciones", tags=["simulaciones"], dependencies=auth_required)
app.include_router(empleados.router, prefix="/api/empleados", tags=["empleados"], dependencies=auth_required)
app.include_router(campañas_router.router, prefix="/api/campañas", tags=["campañas"], dependencies=auth_required)
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["usuarios"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])


# Flash messages, exponen get_flashed_messages() dentro de los templates
_request_ctx: contextvars.ContextVar[Request] = contextvars.ContextVar("_request")


@app.middleware("http")
async def request_context(request: Request, call_next):
    token = _request_ctx.set(request)
    try:
        return await call_next(request)
    finally:
        _request_ctx.reset(token)


# Protección CSRF: los métodos que modifican estado solo se aceptan desde
# nuestros propios orígenes. SameSite=Lax no basta porque los subdominios de
# sentinel.world cuentan como el mismo "site".
METODOS_INSEGUROS = {"POST", "PUT", "PATCH", "DELETE"}
# Event Grid llama servidor a servidor, sin cabecera Origin.
RUTAS_SIN_ORIGEN = ("/api/webhooks/",)


@app.middleware("http")
async def verificar_origen(request: Request, call_next):
    # Sin Origin (o con "null") también se rechaza: los navegadores siempre lo
    # envían en estos métodos, así que su ausencia no es una petición legítima del frontend.
    if (
        request.method in METODOS_INSEGUROS
        and not request.url.path.startswith(RUTAS_SIN_ORIGEN)
        and request.headers.get("origin") not in settings.ALLOWED_ORIGINS
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Origen de la solicitud no permitido."},
        )
    return await call_next(request)


@app.middleware("http")
async def cabeceras_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        # Se guardan pero se revalidan siempre (304 por ETag si no cambiaron):
        # tras un deploy nadie se queda con un auth.js viejo.
        response.headers.setdefault("Cache-Control", "no-cache")
    else:
        # Páginas y API nunca se almacenan: tras el logout, "Atrás" vuelve a
        # pedir la página al servidor y este redirige a /login.
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("_flashes", []).append((category, message))


def get_flashed_messages(with_categories: bool = False):
    request = _request_ctx.get()
    messages = request.session.pop("_flashes", [])
    return messages if with_categories else [m for _, m in messages]


templates.env.globals["get_flashed_messages"] = get_flashed_messages


# RUTAS
@app.get("/", name="home", include_in_schema=False)
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/dashboard", name="dashboard", include_in_schema=False)
async def dashboard(request: Request, current_user: CurrentUser):
    stats = {
        "empleados": 48,
        "campanas_activas": 2,
        "correos_detectados": 132,
        "tasa_clics": 18,
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"stats": stats}
    )

@app.get("/empleados", name="empleados", include_in_schema=False)
async def ver_empleados(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
    ):

    propios = models.Empleados.owner == current_user.uid

    total_ees = await db.scalar(
        select(func.count()).select_from(models.Empleados).where(propios)
        )
    high_risk = await db.scalar(
        select(func.count())
        .select_from(models.Empleados)
        .where(propios, models.Empleados.riesgo >= 70)
        )
    activos = await db.scalar(
        select(func.count())
        .select_from(models.Empleados)
        .where(propios, models.Empleados.estado == True)
        )
    inactivos = await db.scalar(
        select(func.count())
        .select_from(models.Empleados)
        .where(propios, models.Empleados.estado == False)
        )

    result = await db.scalars(select(models.Empleados).where(propios))
    all_ees = result.all()
    stats = {
        "total": total_ees,
        "riesgo_alto": high_risk,
        "activos": activos,
        "inactivos": inactivos
    }
    return templates.TemplateResponse(
        request, 
        "empleados.html", 
        {"employees": all_ees, "stats": stats, "record_count": total_ees}
    )

@app.get("/campañas", name="campañas", include_in_schema=False)
async def campañas(request: Request, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.scalars(
        select(models.Campaña)
        .options(
            selectinload(models.Campaña.simulaciones)
            .selectinload(models.Simulaciones.empleados)
        )
        .where(models.Campaña.owner == current_user.uid)
        .order_by(models.Campaña.fecha.desc())
    )
    campanas = result.all()
    simulaciones = [
        {
            "id": simulacion.id,
            "campana_id": campana.camid,
            "campana_nombre": campana.nombre,
            "campana_fecha": campana.fecha,
            "empleado_nombre": simulacion.empleados.nombre,
            "empleado_email": simulacion.empleados.email,
            "fecha_envio": simulacion.fecha_envio,
            "fecha_respuesta": simulacion.fecha_respuesta,
            "status": simulacion.status,
            "aprobado": simulacion.aprobado,
        }
        for campana in campanas
        for simulacion in campana.simulaciones
    ]

    return templates.TemplateResponse(
        request,
        "campañas.html",
        {"campanas": campanas, "simulaciones": simulaciones},
    )

@app.get("/deteccion", name="deteccion", include_in_schema=False)
async def deteccion(request: Request, current_user: CurrentUser):
    return templates.TemplateResponse(request, "deteccion.html", {})


@app.get(
        "/simulacion", 
        name="simulacion", 
        include_in_schema=False
        )
async def simulacion(request: Request, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    results = await db.scalars(
        select(models.Empleados).where(
            models.Empleados.owner == current_user.uid,
            models.Empleados.estado == True,
        )
    )
    empleados = results.all()
    return templates.TemplateResponse(request, "simulacion.html", {"employees": empleados})


@app.get("/recuperar-contrasena", name="forgot_password", include_in_schema=False)
async def forgot_password(request: Request):
    pass


@app.get("/login", name="login_page", include_in_schema=False)
async def login_usuarios(request: Request, current_user: OptionalUser):
    if current_user:
        return RedirectResponse(str(request.url_for("dashboard")), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/registro", name="register_page", include_in_schema=False)
async def registro_usuarios(request: Request, current_user: OptionalUser):
    if current_user:
        return RedirectResponse(str(request.url_for("dashboard")), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "register.html", {})


@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(
    request: Request, 
    exception: StarletteHTTPException
):
    if request.url.path.startswith("/api"):
        return await http_exception_handler(request, exception)

    # Páginas HTML sin sesión válida: se envía al login en vez de mostrar el error.
    if exception.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(
            str(request.url_for("login_page")),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    error_message = (
            exception.detail 
            if exception.detail 
            else "Ha ocurrido un error. Por favor verifica tu solicitud e intenta nuevamente."
        )
    
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exception.status_code, 
         "error_title": exception.status_code,
        "error_message": error_message
        },
        status_code=exception.status_code
    )

@app.exception_handler(RequestValidationError)
async def general_validation_error(request: Request, exception: RequestValidationError): 
    if request.url.path.startswith("/api"):
        return await request_validation_exception_handler(request, exception)
    
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status.HTTP_422_UNPROCESSABLE_CONTENT, 
         "error_title": status.HTTP_422_UNPROCESSABLE_CONTENT,
         "error_message": "Solicitud invalida. Revisa tu solicitud e intenta nuevamente."
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )