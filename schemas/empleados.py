from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class EmpleadoBase(BaseModel):
    nombre: str = Field(max_length=100)
    email: EmailStr
    empresa: str = Field(min_length=1, max_length=100)
    cargo: str | None = Field(max_length=50)


class EmpleadoCreate(EmpleadoBase):
    riesgo: Annotated[int, Field(ge=0, le=100)] = 100
    estado: bool = True


class EmpleadoUpdate(BaseModel):
    nombre: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    empresa: str | None = Field(default=None, min_length=1, max_length=100)
    cargo: str | None = Field(default=None, max_length=50)
    estado: bool | None = None


class EmpleadoResponse(EmpleadoBase):
    model_config = ConfigDict(from_attributes=True)

    eeid: UUID