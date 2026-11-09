"""Datos de demostración: una cuenta con empleados, campañas terminadas y detecciones.

    uv run python -m scripts.seed --username demo

La contraseña sale de SEED_PASSWORD o se pide por consola; nunca se imprime ni se guarda
en el repo. Si la cuenta ya existe no se toca nada.

No crea simulaciones en `pending`/`sending`: el barrido periódico las enviaría de verdad.
Los correos usan example.com, un dominio reservado que no entrega a nadie.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

import models
from core.auth import hash_password
from database.worker_db import SessionLocal

LARGO_MINIMO_PASSWORD = 15  # el mismo que exige el registro (schemas.usuarios.UserCreate)
DOMINIO = "example.com"
EMPRESA = "Acme Andina S.A.S."

EMPLEADOS = [
    # nombre, cargo, riesgo, activo
    ("Laura Gómez", "Contadora", 82, True),
    ("Andrés Rodríguez", "Analista de compras", 74, True),
    ("Camila Martínez", "Asistente administrativa", 61, True),
    ("Santiago López", "Desarrollador", 35, True),
    ("Valentina Herrera", "Jefe de talento humano", 48, True),
    ("Julián Castro", "Ejecutivo comercial", 90, True),
    ("Daniela Ramírez", "Coordinadora de logística", 22, True),
    ("Felipe Moreno", "Auxiliar contable", 55, False),
]

CAMPAÑAS = [
    # nombre, remitente, asunto, hace_dias, estado por empleado (en el orden de EMPLEADOS activos)
    (
        "Actualización de nómina", f"nomina@acme-andina.{DOMINIO}", "Confirme sus datos bancarios antes del viernes",
        21, ["clicked", "clicked", "opened", "sent", "completed", "clicked", "failed"],
    ),
    (
        "Paquete retenido en aduana", f"envios@courier-express.{DOMINIO}", "Su paquete está retenido: pague el arancel",
        7, ["opened", "sent", "sent", "sent", "clicked", "opened", "sent"],
    ),
]

DETECCIONES = [
    # hace_dias, nivel, probabilidad, reglas, razón
    (1, "alto", 0.97, ["dmarc=fail", "dkim=fail"], "Pide verificar la cuenta con urgencia y el remitente no supera DMARC."),
    (2, "medio", 0.58, ["spf=fail"], "El dominio del remitente no autoriza al servidor que envió el correo."),
    (3, "bajo", 0.08, [], "Sin señales de phishing."),
    (5, "alto", 0.91, [], "Enlace a un dominio que imita al de un banco."),
    (8, "bajo", 0.12, [], "Sin señales de phishing."),
    (11, "medio", 0.44, ["dkim=fail"], "La firma DKIM del mensaje no es válida."),
    (15, "alto", 0.88, ["dmarc=fail"], "Solicita datos bancarios y amenaza con bloquear la cuenta."),
    (19, "bajo", 0.05, [], "Sin señales de phishing."),
    (24, "medio", 0.63, [], "Usa lenguaje de urgencia y un enlace acortado."),
    (28, "alto", 0.95, ["dmarc=fail", "spf=fail"], "Suplanta a la DIAN y pide descargar un archivo."),
]

ETIQUETAS = {"alto": "phishing", "medio": "sospechoso", "bajo": "legitimo"}


def _password() -> str:
    password = os.environ.get("SEED_PASSWORD") or getpass.getpass("Contraseña de la cuenta demo: ")
    if len(password) < LARGO_MINIMO_PASSWORD:
        sys.exit(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")
    return password


def sembrar(username: str, password: str, ahora: datetime | None = None) -> models.User | None:
    """Crea la cuenta demo con sus datos. Devuelve None si el username ya existe."""
    ahora = ahora or datetime.now(UTC)
    with SessionLocal() as db:
        if db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower())):
            return None

        usuario = models.User(
            username=username, nombre="Cuenta", apellidos="Demo",
            email=f"{username.lower()}@{DOMINIO}", password_hash=hash_password(password),
        )
        db.add(usuario)
        db.flush()

        empleados = [
            models.Empleados(
                owner=usuario.uid, nombre=nombre, cargo=cargo, riesgo=riesgo, estado=activo, empresa=EMPRESA,
                email=f"{nombre.split()[0].lower()}.{i}@{DOMINIO}",
            )
            for i, (nombre, cargo, riesgo, activo) in enumerate(EMPLEADOS, start=1)
        ]
        db.add_all(empleados)
        db.flush()
        activos = [e for e in empleados if e.estado]

        for nombre, remitente, asunto, hace_dias, estados in CAMPAÑAS:
            fecha = ahora - timedelta(days=hace_dias)
            campaña = models.Campaña(
                owner=usuario.uid, nombre=nombre, remitente=remitente, asunto=asunto, fecha=fecha,
                cuerpo=f"<p>{asunto}.</p><p><a href=\"#\">Ingrese aquí</a></p>",
            )
            db.add(campaña)
            db.flush()
            for empleado, estado in zip(activos, estados, strict=True):
                db.add(models.Simulaciones(
                    campana_id=campaña.camid, ee_id=empleado.eeid, status=estado, intentos=1,
                    fecha_envio=None if estado == "failed" else fecha + timedelta(minutes=5),
                    fecha_respuesta=fecha + timedelta(hours=3) if estado in ("opened", "clicked", "completed") else None,
                    error="Buzón inexistente" if estado == "failed" else None,
                ))

        db.add_all(
            models.Deteccion(
                owner=usuario.uid, fecha=ahora - timedelta(days=hace_dias, hours=hace_dias % 7),
                nivel=nivel, etiqueta=ETIQUETAS[nivel], probabilidad=probabilidad, reglas=reglas, razones=[razon],
            )
            for hace_dias, nivel, probabilidad, reglas, razon in DETECCIONES
        )
        db.commit()
        return usuario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", default="demo")
    args = parser.parse_args()

    usuario = sembrar(args.username, _password())
    if usuario is None:
        sys.exit(f"La cuenta {args.username!r} ya existe: no se modificó nada.")
    print(
        f"Cuenta {usuario.username!r} creada: {len(EMPLEADOS)} empleados, "
        f"{len(CAMPAÑAS)} campañas y {len(DETECCIONES)} detecciones."
    )


if __name__ == "__main__":
    main()
