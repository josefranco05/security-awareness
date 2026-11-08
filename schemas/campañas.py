from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, EmailStr


class CampañaBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    fecha: datetime = Field(default_factory=partial(datetime.now, UTC))


class CampañaCreate(CampañaBase):
    remitente: EmailStr
    asunto: str
    cuerpo: str
    destinatarios: list[UUID] = Field(default_factory=list)

class CampañaResponse(CampañaBase):
    model_config = ConfigDict(from_attributes=True)
    
    camid: UUID