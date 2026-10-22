from __future__ import annotations

from typing import Annotated
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

import models
from core.config import settings
from schemas.usuarios import Token, UserCreate, UserPublic, UserPrivate, UserUpdate
from database.async_database import get_db
from core.auth import (
    autenticar_usuario,
    CurrentUser,
    create_access_token, 
    hash_password,
    _credentials_exception)
from utils.validaciones import validar_usuario, validar_email_usuario


router = APIRouter()


# AUTENTICACIÓN
@router.get(
        "/me",
        response_model=UserPrivate
)
async def get_usuario_actual(current_user: CurrentUser):
    return current_user


@router.post(
        "/token",
        response_model=Token
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    usuario = await autenticar_usuario(db, form_data.username, form_data.password)
    if usuario is None:
        raise _credentials_exception
    return create_access_token(subject=usuario.uid)


# CRUD
@router.get(
        "",
        response_model=list[UserPublic]
)
async def get_usuarios(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.User)
    )
    usuarios = result.all()
    return usuarios


@router.get(
        "/{uid}",
        response_model=UserPublic
)
async def get_usuario(
    uid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    usuario = await db.scalar(
        select(models.User)
        .where(models.User.uid == uid)
    )
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró un usuario con id {uid}"
        )
    return usuario


@router.post(
        "",
        response_model=UserPrivate,
        status_code=status.HTTP_201_CREATED
)
async def crear_usuario(
    user: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await validar_usuario(user.username, db)
    await validar_email_usuario(user.email, db)

    nuevo_usuario = models.User(
        username=user.username,
        nombre=user.nombre,
        apellidos=user.apellidos,
        email=user.email.lower(),
        password_hash=hash_password(user.password)
    )

    db.add(nuevo_usuario)
    await db.commit()
    await db.refresh(nuevo_usuario)

    return nuevo_usuario


@router.patch(
    "/{uid}",
    response_model=UserPrivate
)
async def actualizar_usuario(
    uid: int,
    usuario: UserUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    _verificar_propietario(uid, current_user)
    cambios = usuario.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se detecto ningun cambio en los datos del usuario."
        )

    if cambios.get("email") is not None:
        await validar_email_usuario(cambios["email"], db, uid)

    for campo, valor in cambios.items():
            setattr(current_user, campo, valor)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.delete(
     "/{uid}",
     status_code=status.HTTP_204_NO_CONTENT
)
async def eliminar_usuario(
    uid: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    _verificar_propietario(uid, current_user)

    await db.delete(current_user)
    await db.commit()

# HELPER PARA PERMISOS DE MODIFICAR USUARIOS
def _verificar_propietario(uid: int, current_user: models.User) -> None:
    if current_user.uid != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar este usuario."
        )