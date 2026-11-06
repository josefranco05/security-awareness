"""
Security Awareness — app.py
Sirve los templates Jinja2 y los archivos estáticos de la carpeta "html files".

Ejecutar:
    pip install fastapi uvicorn jinja2 python-multipart itsdangerous
    uvicorn main:app --reload        # luego abrir http://127.0.0.1:8000
"""
from __future__ import annotations

import contextvars
import hashlib
from functools import lru_cache
from pathlib import Path
import os
from dotenv import load_dotenv
from typing import Optional, Annotated, Literal
from contextlib import asynccontextmanager

from pydantic import ValidationError

from fastapi import FastAPI, Form, Request, HTTPException, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError

from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy import select, func, ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

import models
from database.async_database import Base, engine, get_db
from routers import campañas as campañas_router, empleados, phishing, simulaciones, webhooks, usuarios
from core.auth import get_current_user, CurrentUser, OptionalUser
from core.config import settings
from core.fechas import fecha_local
from core.limites import LimiteTamañoPeticion
from ml.inferencia import cargar_modelo
from services.dashboard import resumen_dashboard


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
    # Sin modelo válido la app no arranca: un pickle incompatible predeciría mal sin avisar.
    _app.state.modelo_phishing = cargar_modelo()
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(
    lifespan=lifespan,
    title="Sentinel - The Plague",
)


# Sesión en cookie (para los mensajes flash)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Comprime HTML, JSON, CSS y JS. Las respuestas pequeñas no compensan.
app.add_middleware(GZipMiddleware, minimum_size=500)

# Archivos estáticos (CSS, imágenes, JS propios)
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory="templates")


@lru_cache(maxsize=128)
def _hash_estatico(ruta: str, mtime_ns: int) -> str:
    # mtime_ns forma parte de la clave: si el archivo cambia, se recalcula.
    return hashlib.sha256((STATIC_DIR / ruta).read_bytes()).hexdigest()[:12]


def static_url(ruta: str) -> str:
    """URL versionada por contenido: cambia sola cuando cambia el archivo."""
    mtime_ns = (STATIC_DIR / ruta).stat().st_mtime_ns
    return f"/static/{ruta}?v={_hash_estatico(ruta, mtime_ns)}"


templates.env.globals["static_url"] = static_url

# Rutas protegidas: requieren un JWT válido en la cookie HttpOnly de sesión
auth_required = [Depends(get_current_user)]
app.include_router(simulaciones.router, prefix="/api/simulaciones", tags=["simulaciones"], dependencies=auth_required)
app.include_router(empleados.router, prefix="/api/empleados", tags=["empleados"], dependencies=auth_required)
app.include_router(campañas_router.router, prefix="/api/campañas", tags=["campañas"], dependencies=auth_required)
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["usuarios"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(phishing.router, prefix="/api/phishing", tags=["phishing"])


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
# Event Grid llama servidor a servidor, sin cabecera Origin. La extensión llega con
# Origin chrome-extension:// y se autentica con bearer token, no con la cookie: no aplica CSRF.
RUTAS_SIN_ORIGEN = ("/api/webhooks/", phishing.RUTA_ANALISIS)


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
        # Con ?v=<hash> (static_url) la URL cambia con el contenido: se cachea
        # un año sin revalidar. Sin versión se revalida siempre (304 por ETag),
        # así tras un deploy nadie se queda con un auth.js viejo.
        versionado = "v" in request.query_params and response.status_code == 200
        response.headers.setdefault(
            "Cache-Control",
            "public, max-age=31536000, immutable" if versionado else "no-cache",
        )
    else:
        # Páginas y API nunca se almacenan: tras el logout, "Atrás" vuelve a
        # pedir la página al servidor y este redirige a /login.
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# Se añade después de los demás para quedar por fuera: corta antes de que nadie lea el cuerpo.
app.add_middleware(
    LimiteTamañoPeticion,
    ruta=phishing.RUTA_ANALISIS,
    max_bytes=phishing.MAX_BYTES_PETICION,
)


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("_flashes", []).append((category, message))


def get_flashed_messages(with_categories: bool = False):
    request = _request_ctx.get()
    messages = request.session.pop("_flashes", [])
    return messages if with_categories else [m for _, m in messages]


templates.env.globals["get_flashed_messages"] = get_flashed_messages


# Tema claro/oscuro: vive en una cookie del navegador y el servidor lo pinta en
# <html data-theme>, así la página llega ya con el tema correcto (sin parpadeo).
TEMA_COOKIE = "tema"
Tema = Literal["light", "dark"]


def tema_actual() -> str:
    tema = _request_ctx.get().cookies.get(TEMA_COOKIE)
    return tema if tema in ("light", "dark") else "light"


templates.env.globals["tema_actual"] = tema_actual


# RUTAS
@app.get("/", name="home", include_in_schema=False)
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/dashboard", name="dashboard", include_in_schema=False)
async def dashboard(request: Request, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await resumen_dashboard(db, current_user.uid),
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

MAX_DETECCIONES_PAGINA = 100


@app.get("/deteccion", name="deteccion", include_in_schema=False)
async def deteccion(request: Request, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    propias = models.Deteccion.owner == current_user.uid

    # Se cuenta en SQL: los indicadores cubren todo el historial, no solo la tabla.
    filas = await db.execute(
        select(models.Deteccion.nivel, func.count()).where(propias).group_by(models.Deteccion.nivel)
    )
    por_nivel = {nivel: total for nivel, total in filas.all()}
    alto, medio = por_nivel.get("alto", 0), por_nivel.get("medio", 0)
    analizados = sum(por_nivel.values())

    recientes = await db.scalars(
        select(models.Deteccion)
        .where(propias)
        .order_by(models.Deteccion.fecha.desc(), models.Deteccion.id.desc())
        .limit(MAX_DETECCIONES_PAGINA)
    )
    detecciones = [
        {
            "fecha": fecha_local(d.fecha),
            "etiqueta": d.etiqueta,
            "nivel": d.nivel,
            "probabilidad": d.probabilidad,
            "reglas": d.reglas,
            "razones": d.razones,
        }
        for d in recientes
    ]
    return templates.TemplateResponse(
        request,
        "deteccion.html",
        {
            "stats": {"analizados": analizados, "detectados": alto + medio, "riesgo_alto": alto, "riesgo_medio": medio},
            "detections": detecciones,
        },
    )


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


@app.get("/cuenta", name="cuenta", include_in_schema=False)
async def cuenta(request: Request, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    # Conteos para que el modal de borrado diga exactamente qué se pierde.
    campañas = await db.scalar(
        select(func.count())
        .select_from(models.Campaña)
        .where(models.Campaña.owner == current_user.uid)
    )
    empleados = await db.scalar(
        select(func.count())
        .select_from(models.Empleados)
        .where(models.Empleados.owner == current_user.uid)
    )
    simulaciones = await db.scalar(
        select(func.count())
        .select_from(models.Simulaciones)
        .join(models.Simulaciones.campana)
        .where(models.Campaña.owner == current_user.uid)
    )
    detecciones = await db.scalar(
        select(func.count())
        .select_from(models.Deteccion)
        .where(models.Deteccion.owner == current_user.uid)
    )
    token_creado = await db.scalar(
        select(models.TokenExtension.creado).where(models.TokenExtension.owner == current_user.uid)
    )
    return templates.TemplateResponse(
        request,
        "cuenta.html",
        {
            "usuario": current_user,
            "conteos": {
                "campanas": campañas,
                "empleados": empleados,
                "simulaciones": simulaciones,
                "detecciones": detecciones,
            },
            "token_creado": token_creado,
        },
    )


@app.post("/cuenta/tema", name="cambiar_tema", include_in_schema=False)
async def cambiar_tema(request: Request, current_user: CurrentUser, tema: Annotated[Tema, Form()]):
    # Un valor fuera de light/dark lo rechaza la validación (422).
    response = RedirectResponse(str(request.url_for("cuenta")), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        TEMA_COOKIE,
        tema,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


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
    # El 422 por defecto repite `input`: aquí sería el contenido del correo.
    if request.url.path == phishing.RUTA_ANALISIS:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": [
                {"type": e["type"], "loc": e["loc"], "msg": e["msg"]}
                for e in exception.errors()
            ]},
        )

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