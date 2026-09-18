"""
Security Awareness — app.py
Sirve los templates Jinja2 y los archivos estáticos de la carpeta "html files".

Ejecutar:
    pip install fastapi uvicorn jinja2 python-multipart itsdangerous
    uvicorn app:app --reload        # luego abrir http://127.0.0.1:8000
"""

import contextvars
from pathlib import Path
import os
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, Form, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    raise ValueError("SECRET_KEY is not setup. Please set environment variable.")

app = FastAPI(title="Plataforma de Security Awareness")

# Sesión en cookie (para los mensajes flash)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Archivos estáticos (CSS, imágenes, JS propios)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Flash messages: exponen get_flashed_messages() dentro de los templates
# ---------------------------------------------------------------------------
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


def placeholder_html(title: str) -> str:
    """Página temporal para las rutas cuyo template aún no existe."""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Security Awareness</title>
</head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#070f1c;color:#e8eef7;font-family:'Segoe UI',system-ui,sans-serif">
<div style="text-align:center;padding:2rem">
<h1 style="margin:0 0 .5rem">{title}</h1>
<p style="color:#6f88a6;margin:0 0 1.25rem">Página en construcción</p>
<a href="/" style="color:#38bdf8">← Volver al dashboard</a>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@app.get("/", name="dashboard")
async def dashboard(request: Request):
    stats = {
        "empleados": 48,
        "campanas_activas": 2,
        "correos_detectados": 132,
        "tasa_clics": 18,
    }
    return templates.TemplateResponse(request, "dashboard.html", {"stats": stats})


@app.get("/deteccion", name="deteccion")
async def deteccion(request: Request):
    return templates.TemplateResponse(request, "deteccion.html", {})


@app.get("/simulacion", name="simulacion")
async def simulacion(request: Request):
    return templates.TemplateResponse(request, "campaigns.html", {})


@app.get("/empleados", name="empleados")
async def empleados(request: Request):
    empleados = [{
        "nombre": "Jose Miguel Franco",
        "email": "email@email.com",
        "empresa": "Prueba",
        "riesgo": 50,
        "clics": 12,
        "activo": True
    }]
    return templates.TemplateResponse(request, "empleados.html", {"employees": empleados})

@app.get("/empleados/empleado_nuevo", name="empleado_nuevo")
async def empleado_nuevo(request: Request):
    return templates.TemplateResponse(request, "empleado_nuevo.html", {})


@app.get("/empresas", name="empresas")
async def empresas(request: Request):
    return HTMLResponse(placeholder_html("Empresas"))


@app.get("/recuperar-contrasena", name="forgot_password")
async def forgot_password(request: Request):
    return HTMLResponse(placeholder_html("Recuperar contraseña"))


@app.get("/login", name="login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    # TODO: autenticación real
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
    # TODO: guardar la campaña y enviar los correos de simulación
    flash(
        request,
        f"Campaña «{nombre or 'Sin nombre'}» creada (demo). Envío pendiente de implementar.",
        "success",
    )
    return RedirectResponse("/simulacion", status_code=303)


@app.post("/empleado-nuevo", name="empleado_nuevo")
async def ingresar__nuevo_empleado(
    request: Request,
    nombre: str = File(),
    email: str = File(),
    empresa: str = File(),
    cargo: str = File(),
):
    # TODO: guardar la campaña y enviar los correos de simulación
    flash(
        request,
        f"Empleado «{nombre or 'Failed to load EE name'}» ingresado exitosamente.",
        "success",
    )
    return RedirectResponse("/empleados", status_code=303)


@app.post("/empleado-importar", name="empleado_importar")
async def importar_empleado(
    request: Request,
    archivo: UploadFile = File(),
):
    # TODO: guardar la campaña y enviar los correos de simulación
    flash(
        request,
        f"Archivo CSV «{archivo.filename or 'Sin nombre'}» importado exitosamente.",
        "success",
    )
    return RedirectResponse("/empleados", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
