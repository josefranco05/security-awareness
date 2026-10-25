from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


SimulacionStatus = Literal[
    "pending",
    "sent",
    "sending",
    "failed",
    "opened",
    "clicked",
    "completed",
]


class SimulacionBase(BaseModel):
    campana_id: int
    status: SimulacionStatus
    # Nullable: solo se llena cuando el correo se envía de verdad.
    fecha_envio: datetime | None = None


class SimulacionCreate(SimulacionBase):
    ee_id: int


class SimulacionResponse(SimulacionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ee_id: int
    fecha_respuesta: datetime | None
    aprobado: bool
    intentos: int = 0
    error: str | None = None
