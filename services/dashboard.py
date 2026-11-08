"""Cifras del dashboard, siempre de un solo usuario.

Cada correo cuenta una vez y por su estado actual: una simulación es una fila,
y sus reintentos en la cola no suman nada.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.fechas import ZONA_COLOMBIA, fecha_local
import models

DIAS_GRAFICA = 30
MAX_CAMPAÑAS_GRAFICA = 8
MAX_ALERTAS = 5
NIVELES_AMENAZA = ("alto", "medio")

# DATO DE PRUEBA: sin el píxel de seguimiento (HU-42, HU-43) nada marca una simulación
# como "completed", y ninguna campaña terminaría nunca. Mientras tanto, un correo enviado
# hace más de estos días se da por completado. Al tener el píxel, se borra esto y la
# condición que lo usa en _campañas_activas, junto con la insignia de dashboard.html.
DIAS_COMPLETADA_PRUEBA = 7

ESTADOS_ENTREGADOS = ("sent", "opened", "clicked", "completed")
ESTADOS_PENDIENTES = ("pending", "sending")
ESTADO_FALLIDO = "failed"
# Un fallo definitivo tampoco se completará: no debe dejar la campaña activa para siempre.
ESTADOS_TERMINADOS = ("completed", ESTADO_FALLIDO)

# De la señal más fuerte a la más débil: un correo que falla varias cuenta solo en la primera.
SEÑALES = (("dmarc=fail", "DMARC"), ("spf=fail", "SPF"), ("dkim=fail", "DKIM"))
SIN_SEÑAL = "Solo contenido"


def _ahora() -> datetime:
    return datetime.now(UTC)


async def _campañas_activas(db: AsyncSession, uid: UUID, ahora: datetime) -> int:
    """Una campaña sigue activa hasta que termina su última simulación."""
    limite_prueba = ahora - timedelta(days=DIAS_COMPLETADA_PRUEBA)
    total = await db.scalar(
        select(func.count(models.Campaña.camid.distinct()))
        .join(models.Campaña.simulaciones)
        .where(
            models.Campaña.owner == uid,
            models.Simulaciones.status.notin_(ESTADOS_TERMINADOS),
            or_(
                models.Simulaciones.status != "sent",
                models.Simulaciones.fecha_envio.is_(None),
                models.Simulaciones.fecha_envio >= limite_prueba,
            ),
        )
    )
    return total or 0


async def _tasa_entrega(db: AsyncSession, uid: UUID) -> int | None:
    """Porcentaje de entregados entre los que ya tienen resultado; None si aún no hay ninguno."""
    filas = await db.execute(
        select(models.Simulaciones.status, func.count())
        .join(models.Simulaciones.campana)
        .where(models.Campaña.owner == uid)
        .group_by(models.Simulaciones.status)
    )
    por_estado = dict(filas.all())
    entregados = sum(por_estado.get(e, 0) for e in ESTADOS_ENTREGADOS)
    con_resultado = entregados + por_estado.get(ESTADO_FALLIDO, 0)
    return round(entregados * 100 / con_resultado) if con_resultado else None


async def _detecciones_por_dia(db: AsyncSession, uid: UUID, ahora: datetime) -> dict:
    hoy = fecha_local(ahora).date()
    dias = [hoy - timedelta(days=n) for n in range(DIAS_GRAFICA - 1, -1, -1)]
    inicio = datetime.combine(dias[0], time.min, ZONA_COLOMBIA).astimezone(UTC)

    filas = await db.execute(
        select(models.Deteccion.fecha, models.Deteccion.nivel)
        .where(models.Deteccion.owner == uid, models.Deteccion.fecha >= inicio)
    )
    # El día se calcula aquí y no en SQL: depende de la zona horaria, y SQL varía según el motor.
    conteo = Counter((fecha_local(fecha).date(), nivel) for fecha, nivel in filas.all())
    return {
        "dias": [d.strftime("%d/%m") for d in dias],
        "alto": [conteo[(d, "alto")] for d in dias],
        "medio": [conteo[(d, "medio")] for d in dias],
        "bajo": [conteo[(d, "bajo")] for d in dias],
        "total": sum(conteo.values()),
    }


async def _resultados_campañas(db: AsyncSession, uid: UUID) -> dict:
    campañas = (await db.execute(
        select(models.Campaña.camid, models.Campaña.nombre)
        .where(models.Campaña.owner == uid)
        # El id solo desempata para que el orden sea estable: un UUID4 no indica cuál es más nuevo.
        .order_by(models.Campaña.fecha.desc(), models.Campaña.camid.desc())
        .limit(MAX_CAMPAÑAS_GRAFICA)
    )).all()
    filas = await db.execute(
        select(models.Simulaciones.campana_id, models.Simulaciones.status, func.count())
        .where(models.Simulaciones.campana_id.in_([camid for camid, _ in campañas]))
        .group_by(models.Simulaciones.campana_id, models.Simulaciones.status)
    )
    conteo = {(camid, estado): total for camid, estado, total in filas.all()}

    def sumar(camid: UUID, estados: tuple[str, ...]) -> int:
        return sum(conteo.get((camid, e), 0) for e in estados)

    return {
        "nombres": [nombre for _, nombre in campañas],
        "entregados": [sumar(camid, ESTADOS_ENTREGADOS) for camid, _ in campañas],
        "pendientes": [sumar(camid, ESTADOS_PENDIENTES) for camid, _ in campañas],
        "fallidos": [sumar(camid, (ESTADO_FALLIDO,)) for camid, _ in campañas],
    }


def _señal_principal(reglas: list[str]) -> str:
    return next((nombre for regla, nombre in SEÑALES if regla in reglas), SIN_SEÑAL)


async def _alertas(db: AsyncSession, uid: UUID) -> list[dict]:
    recientes = await db.scalars(
        select(models.Deteccion)
        .where(models.Deteccion.owner == uid, models.Deteccion.nivel.in_(NIVELES_AMENAZA))
        .order_by(models.Deteccion.fecha.desc(), models.Deteccion.id.desc())
        .limit(MAX_ALERTAS)
    )
    return [
        {
            "fecha": fecha_local(d.fecha),
            "nivel": d.nivel,
            "etiqueta": d.etiqueta,
            "razon": d.razones[0] if d.razones else "",
        }
        for d in recientes
    ]


async def resumen_dashboard(db: AsyncSession, uid: UUID) -> dict:
    ahora = _ahora()
    empleados = await db.scalar(
        select(func.count()).select_from(models.Empleados).where(models.Empleados.owner == uid)
    )
    # Una fila por correo: la suma de las señales coincide con las amenazas detectadas.
    reglas = await db.scalars(
        select(models.Deteccion.reglas)
        .where(models.Deteccion.owner == uid, models.Deteccion.nivel.in_(NIVELES_AMENAZA))
    )
    señales = Counter(_señal_principal(r) for r in reglas)
    nombres_señales = [nombre for _, nombre in SEÑALES] + [SIN_SEÑAL]

    return {
        "stats": {
            "empleados": empleados or 0,
            "campanas_activas": await _campañas_activas(db, uid, ahora),
            "correos_detectados": sum(señales.values()),
            "tasa_entrega": await _tasa_entrega(db, uid),
        },
        "graficas": {
            "detecciones": await _detecciones_por_dia(db, uid, ahora),
            "campanas": await _resultados_campañas(db, uid),
            "senales": {"nombres": nombres_señales, "totales": [señales[n] for n in nombres_señales]},
        },
        "alertas": await _alertas(db, uid),
    }
