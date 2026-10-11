from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    uid: int


class CampañaBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    fecha: datetime


class CampañaCreate(CampañaBase):
    remitente: str
    asunto: str
    cuerpo: str

class CampañaResponse(CampañaBase):
    model_config = ConfigDict(from_attributes=True)
    
    camid: int


class EmpleadosBase(BaseModel):
    nombre: str
    email: EmailStr
    empresa: str = Field(min_length=1)
    riesgo: int
    cargo: str | None

class EmpleadosCreate(EmpleadosBase):
    estado: bool = True

class EmpleadosResponse(EmpleadosBase):
    model_config = ConfigDict(from_attributes=True)

    eeid: int


class SimulacionBase(BaseModel):
    campana_id: int
    status: str = Field(min_length=1, max_length=20)
    fecha_envio: datetime

class SimulacionCreate(SimulacionBase):
    ee_id: int # TEMPORAL

class SimulacionResponse(SimulacionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ee_id: int
    fecha_respuesta: datetime | None
    aprobado: bool