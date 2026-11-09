from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=100)
    apellidos: str = Field(min_length=1, max_length=100)
    email: EmailStr  # email-validator ya limita a 254, el largo de la columna


class UserCreate(UserBase):
    password: str = Field(min_length=15)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: UUID
    username: str
    nombre: str
    apellidos: str

class UserPrivate(UserPublic):
    email: EmailStr


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=50)
    email: EmailStr | None = None
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    apellidos: str | None = Field(default=None, min_length=1, max_length=100)


class Token(BaseModel):
    access_token: str
    token_type: str