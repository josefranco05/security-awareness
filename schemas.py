from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr

class UserCreate(BaseModel):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: int


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
    


