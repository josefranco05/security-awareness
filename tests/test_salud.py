"""Sondas de liveness y readiness."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import main
from database.async_database import get_db
from database.worker_db import SessionLocal
from routers import salud


class _BaseCaida:
    async def scalar(self, *_):
        raise OperationalError("select", {}, Exception("connection refused"))


@pytest.fixture
def base_caida():
    async def sesion():
        yield _BaseCaida()

    main.app.dependency_overrides[get_db] = sesion


def test_lista_con_el_esquema_al_dia(anonimo):
    r = anonimo.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_no_lista_si_faltan_migraciones(anonimo, monkeypatch):
    monkeypatch.setattr(salud, "revision_esperada", lambda: "una-revision-mas-nueva")
    r = anonimo.get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "migraciones pendientes"}


def test_no_lista_sin_base(anonimo, base_caida):
    r = anonimo.get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "sin base de datos"}
    assert "connection refused" not in r.text


def test_viva_aunque_la_base_este_caida(anonimo, base_caida):
    # Reiniciar el contenedor no arregla la base: liveness no debe depender de ella.
    assert anonimo.get("/healthz").status_code == 200


def test_las_sondas_no_piden_sesion_ni_se_cachean(anonimo):
    for ruta in ("/healthz", "/readyz"):
        r = anonimo.get(ruta, follow_redirects=False)
        assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"


def test_la_revision_esperada_es_la_ultima_migracion():
    # conftest migró la base de pruebas a head: deben coincidir.
    with SessionLocal() as db:
        actual = db.scalar(text("SELECT version_num FROM alembic_version"))
    assert actual and salud.revision_esperada() == actual
