"""El seed de demostración sigue funcionando con el esquema actual."""
from __future__ import annotations

from database.worker_db import SessionLocal
import models
from scripts import seed
from tests.conftest import ORIGEN, sesion

PASSWORD = "contraseña-demo-de-prueba"


def test_crea_la_cuenta_demo_completa(anonimo):
    usuario = seed.sembrar("demo", PASSWORD)
    with SessionLocal() as db:
        assert db.query(models.Empleados).filter_by(owner=usuario.uid).count() == len(seed.EMPLEADOS)
        assert db.query(models.Campaña).filter_by(owner=usuario.uid).count() == len(seed.CAMPAÑAS)
        assert db.query(models.Deteccion).filter_by(owner=usuario.uid).count() == len(seed.DETECCIONES)
        estados = {s.status for s in db.query(models.Simulaciones).all()}
    # Nada que el barrido periódico pueda enviar.
    assert not estados & {"pending", "sending"}


def test_la_cuenta_demo_puede_entrar(anonimo):
    seed.sembrar("demo", PASSWORD)
    r = anonimo.post("/api/usuarios/token", headers={"Origin": ORIGEN}, data={"username": "demo", "password": PASSWORD})
    assert r.status_code == 204


def test_no_toca_una_cuenta_existente(anonimo):
    primera = seed.sembrar("demo", PASSWORD)
    assert seed.sembrar("DEMO", "otra-contraseña-cualquiera") is None
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.query(models.Campaña).filter_by(owner=primera.uid).count() == len(seed.CAMPAÑAS)


def test_las_paginas_muestran_los_datos_demo(anonimo):
    usuario = seed.sembrar("demo", PASSWORD)
    cabeceras = sesion(usuario.uid)
    dashboard = anonimo.get("/dashboard", headers=cabeceras).text
    assert "Paquete retenido en aduana" in dashboard and "<canvas" in dashboard
    assert "Laura Gómez" in anonimo.get("/empleados", headers=cabeceras).text
    assert "Suplanta a la DIAN" in anonimo.get("/deteccion", headers=cabeceras).text
