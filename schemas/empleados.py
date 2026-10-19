from pydantic import BaseModel, ConfigDict, Field, EmailStr
from typing import Annotated


class EmpleadoBase(BaseModel):
    nombre: str
    email: EmailStr
    empresa: str = Field(min_length=1)
    cargo: str | None


class EmpleadoCreate(EmpleadoBase):
    riesgo: Annotated[int, Field(ge=0, le=100)] = 100
    estado: bool = True


class EmpleadoUpdate(BaseModel):
    nombre: str | None = None
    email: EmailStr | None = None
    empresa: str | None = Field(default=None, min_length=1)
    cargo: str | None = None
    estado: bool | None = None


class EmpleadoResponse(EmpleadoBase):
    model_config = ConfigDict(from_attributes=True)

    eeid: int