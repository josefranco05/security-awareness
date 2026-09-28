"""
Security Awareness — app.py
Sirve los templates Jinja2 y los archivos estáticos de la carpeta "html files".

Ejecutar:
    pip install fastapi uvicorn jinja2 python-multipart itsdangerous
    uvicorn app:app --reload        # luego abrir http://127.0.0.1:8000
"""
from __future__ import annotations

import contextvars
from pathlib import Path
import os
from dotenv import load_dotenv
from typing import Optional, Annotated
from datetime import datetime

from pydantic import ValidationError

from fastapi import FastAPI, Form, Request, HTTPException, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy import select, func, ScalarResult
from sqlalchemy.orm import Session

from schemas import SimulacionCreate, SimulacionResponse, EmpleadosCreate, EmpleadosResponse
import models
from database import Base, engine, get_db 

BASE_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    raise ValueError("SECRET_KEY is not setup. Please set environment variable.")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plataforma de Security Awareness")

# Sesión en cookie (para los mensajes flash)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Archivos estáticos (CSS, imágenes, JS propios)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")



# Flash messages, exponen get_flashed_messages() dentro de los templates
_request_ctx: contextvars.ContextVar[Request] = contextvars.ContextVar("_request")


@app.middleware("http")
async def request_context(request: Request, call_next):
    token = _request_ctx.set(request)
    try:
        return await call_next(request)
    finally:
        _request_ctx.reset(token)


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("_flashes", []).append((category, message))


def get_flashed_messages(with_categories: bool = False):
    request = _request_ctx.get()
    messages = request.session.pop("_flashes", [])
    return messages if with_categories else [m for _, m in messages]


templates.env.globals["get_flashed_messages"] = get_flashed_messages


# RUTAS
@app.get("/", name="home", include_in_schema=False)
@app.get("/home", name="dashboard", include_in_schema=False)
async def dashboard(request: Request):
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


@app.get("/deteccion", name="deteccion")
async def deteccion(request: Request):
    return templates.TemplateResponse(request, "deteccion.html", {})


@app.get("/simulacion", name="simulacion")
async def simulacion(request: Request):
    return templates.TemplateResponse(request, "campaigns.html", {})


@app.get("/empleados", name="empleados", include_in_schema=False)
async def empleados(
    request: Request, 
    db: Annotated[Session, Depends(get_db)]
    ):

    total_ees = db.scalar(select(func.count()).select_from(models.Empleados))
    high_risk = db.scalar(select(func.count()).select_from(models.Empleados).where(models.Empleados.riesgo >= 70))
    activos = db.scalar(select(func.count()).select_from(models.Empleados).where(models.Empleados.estado == True))
        
    all_ees = db.scalars(select(models.Empleados)).all()
    stats = {
        "total": total_ees,
        "riesgo_alto": high_risk,
        "clics": 15,
        "activos": activos
    }
    return templates.TemplateResponse(request, "empleados.html", {"employees": all_ees, "stats": stats, "record_count": total_ees})

@app.get("/empleados/empleado_nuevo", name="empleado_nuevo")
async def empleado_nuevo(request: Request):
    return templates.TemplateResponse(request, "empleado_nuevo.html", {})


@app.get("/recuperar-contrasena", name="forgot_password")
async def forgot_password(request: Request):
    pass


@app.get("/login", name="login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    flash(request, f"Sesión iniciada como «{username}» (demo).", "success")
    return RedirectResponse("/", status_code=303)


@app.post("/enviar-campana", name="enviar_campana")
async def enviar_campana(
    request: Request,
    nombre: str = Form(),
    remitente: str = Form(),
    asunto: str = Form(),
    cuerpo: str = Form(),
):
    flash(
        request,
        f"Campaña «{nombre or 'Sin nombre'}» creada (demo). Envío pendiente.",
        ".alert-success",
    )
    return RedirectResponse("/simulacion", status_code=303)


@app.post("/empleado-nuevo", name="empleado_manual")
async def ingresar__nuevo_empleado(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    nombre: Annotated[str, Form()],
    email: Annotated[str, Form()],
    empresa: Annotated[str, Form()],
    cargo: Annotated[str, Form()] = ""
):
    

    payload = EmpleadosCreate(
        nombre=nombre,
        email=email,
        empresa=empresa,
        cargo=cargo,
        riesgo=100
    )    

    user = db.scalars(select(models.Empleados).where(models.Empleados.email == payload.email)).first()
        
    if user:
        flash(
            request,
            f"Ya existe un empleado «{nombre or 'Sin nombre'} con correo {email}». Intenta nuevamente.",
            "error",
        )
        return RedirectResponse("/empleados", status_code=status.HTTP_303_SEE_OTHER)

    entry = models.Empleados(**payload.model_dump())

    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    flash(
        request,
        f"Empleado «{nombre or 'Failed to load EE name'}» ingresado exitosamente.",
        "success",
    )
    return RedirectResponse("/empleados", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/empleado-importar", name="empleado_importar")
async def importar_empleado(
    request: Request,
    archivo: UploadFile = File(),
):
    flash(
        request,
        f"Archivo CSV «{archivo.filename or 'Sin nombre'}» importado exitosamente.",
        "success",
    )
    return RedirectResponse("/empleados", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
    error_message = (
        exception.detail if exception.detail else "Ha ocurrido un error. Por favor verifica tu solicitud e intenta nuevamente."
    )

    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exception.status_code,
            content={"detail": error_message}
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
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": exception.errors()}   
        )
    
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status.HTTP_422_UNPROCESSABLE_CONTENT, 
         "error_title": status.HTTP_422_UNPROCESSABLE_CONTENT,
         "error_message": "Solicitud invalida. Revisa tu solicitud e intenta nuevamente."
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )