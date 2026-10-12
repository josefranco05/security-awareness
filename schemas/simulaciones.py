from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from datetime import UTC, datetime
from functools import partial


class SimulacionBase(BaseModel):
    campana_id: int
    status: Literal["pending", "sent", "opened", "clicked", "completed"]
    fecha_envio: datetime = Field(default_factory=partial(datetime.now, UTC))

class SimulacionCreate(SimulacionBase):
    ee_id: int

class SimulacionResponse(SimulacionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ee_id: int
    fecha_respuesta: datetime | None
    aprobado: bool