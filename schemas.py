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
    nombre: str = Field(max_length=100)
    fecha: datetime


class CampañaCreate(CampañaBase):
    pass

class CampañaResponse(CampañaBase):
    model_config = ConfigDict(from_attributes=True)
    
    camid: int


class EmpleadosBase(BaseModel):
    nombre: str
    email: EmailStr
    empresa: str = Field(min_length=1)
    cargo: str | None

class EmpleadosCreate(EmpleadosBase):
    pass

class EmpleadosResponse(EmpleadosBase):
    model_config = ConfigDict(from_attributes=True)

    eeid: int


class SimulacionBase(BaseModel):
    campana: str = Field(min_length=1, max_length=50)
    status: str = Field(min_length=1, max_length=20)
    fecha_envio: datetime

class SimulacionCreate(SimulacionBase):
    user_id: int # TEMPORAL

class SimulacionResponse(SimulacionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    fecha_respuesta: datetime
    aprobado: bool