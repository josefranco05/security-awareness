"""Esquema de PostgreSQL: migraciones al día con los modelos y restricciones que valen sin la app."""
from __future__ import annotations

from typing import get_args
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database.async_database import Base
from database.worker_db import SessionLocal, engine
import models
from schemas.simulaciones import SimulacionStatus
from tests.conftest import _admin, _url, configuracion_alembic, crear_usuario


# --- migraciones ------------------------------------------------------------------------

def test_los_modelos_coinciden_con_las_migraciones():
    # Si falla: falta una migración. alembic revision --autogenerate -m "..."
    with engine.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion, opts={"compare_type": True}), Base.metadata)
    assert diferencias == []


def test_las_migraciones_se_deshacen_y_rehacen():
    nombre = f"sentinel_test_ida_vuelta_{uuid4().hex[:8]}"
    _admin(f'CREATE DATABASE "{nombre}"')
    try:
        cfg = configuracion_alembic(_url("postgresql+psycopg", nombre))
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        motor = create_engine(_url("postgresql+psycopg", nombre))
        try:
            assert set(inspect(motor).get_table_names()) == {"alembic_version"}
        finally:
            motor.dispose()
        command.upgrade(cfg, "head")
    finally:
        _admin(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def test_los_estados_de_la_api_y_de_la_base_coinciden():
    assert set(get_args(SimulacionStatus)) == set(models.ESTADOS_SIMULACION)


# --- restricciones (sin pasar por la API) -----------------------------------------------

def _insertar(*filas):
    with SessionLocal() as db:
        db.add_all(filas)
        db.commit()


def _usuario(username="ana", email="ana@example.com"):
    return models.User(username=username, nombre="a", apellidos="b", email=email, password_hash="x")


@pytest.mark.parametrize("username, email", [("ANA", "otra@example.com"), ("otra", "Ana@Example.COM")])
def test_usuario_unico_sin_distinguir_mayusculas(anonimo, username, email):
    _insertar(_usuario())
    with pytest.raises(IntegrityError):
        _insertar(_usuario(username, email))


def test_email_de_empleado_unico_por_dueño(anonimo):
    ana, _ = crear_usuario("ana")
    beto, _ = crear_usuario("beto")

    def empleado(owner, email):
        return models.Empleados(owner=owner, nombre="e", email=email, riesgo=0, empresa="x")

    _insertar(empleado(ana, "luis@example.com"), empleado(beto, "luis@example.com"))
    with pytest.raises(IntegrityError):
        _insertar(empleado(ana, "LUIS@example.com"))


def test_estado_de_simulacion_invalido(anonimo):
    uid, _ = crear_usuario()
    empleado = models.Empleados(owner=uid, nombre="e", email="e@example.com", riesgo=0, empresa="x")
    campaña = models.Campaña(owner=uid, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
    _insertar(empleado, campaña)
    with pytest.raises(IntegrityError, match="ck_simulaciones_status_valido"):
        _insertar(models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid, status="enviado"))


def test_dueño_inexistente(anonimo):
    with pytest.raises(IntegrityError):
        _insertar(models.Deteccion(owner=uuid4(), etiqueta="phishing", nivel="alto", probabilidad=1.0))


def test_borrar_el_usuario_en_sql_borra_todo_en_cascada(anonimo):
    # Un DELETE directo, sin el cascade del ORM: lo hace la propia base.
    uid, _ = crear_usuario()
    empleado = models.Empleados(owner=uid, nombre="e", email="e@example.com", riesgo=0, empresa="x")
    campaña = models.Campaña(owner=uid, nombre="c", remitente="r@example.com", asunto="a", cuerpo="c")
    _insertar(empleado, campaña)
    _insertar(
        models.Simulaciones(campana_id=campaña.camid, ee_id=empleado.eeid),
        models.Deteccion(owner=uid, etiqueta="phishing", nivel="alto", probabilidad=1.0),
    )
    with SessionLocal() as db:
        db.execute(text("DELETE FROM users WHERE uid = :uid"), {"uid": uid})
        db.commit()
        for tabla in ("campanas", "empleados", "simulaciones", "detecciones", "tokens_extension"):
            assert db.execute(text(f"SELECT count(*) FROM {tabla}")).scalar() == 0, tabla


def test_las_listas_de_la_deteccion_son_jsonb(anonimo):
    uid, _ = crear_usuario()
    _insertar(models.Deteccion(
        owner=uid, etiqueta="phishing", nivel="alto", probabilidad=1.0, reglas=["dmarc=fail"], razones=["Razón."],
    ))
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM detecciones WHERE reglas ? 'dmarc=fail'")).scalar() == 1
