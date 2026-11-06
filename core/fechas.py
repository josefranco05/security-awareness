"""Fechas para mostrar. Se guardan en UTC y se muestran en hora de Colombia."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

# Colombia no tiene horario de verano. Sin convertir, un correo analizado a las
# 8 p. m. aparecería con la fecha del día siguiente.
ZONA_COLOMBIA = timezone(timedelta(hours=-5))


def fecha_local(fecha: datetime) -> datetime:
    # SQLite devuelve las fechas sin zona, aunque se guardaron en UTC.
    return (fecha if fecha.tzinfo else fecha.replace(tzinfo=UTC)).astimezone(ZONA_COLOMBIA)
