from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy.ext.asyncio import AsyncSession

import models
from core.permisos import UsuarioPropio
from schemas.usuarios import UserCreate, UserPublic, UserPrivate, UserUpdate
from database.async_database import get_db
from core.auth import (
    autenticar_usuario,
    CurrentUser,
    create_access_token,
    hash_password,
    set_auth_cookie,
    clear_auth_cookie,
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
        status_code=status.HTTP_204_NO_CONTENT
)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    usuario = await autenticar_usuario(db, form_data.username, form_data.password)
    if usuario is None:
        raise _credentials_exception
    token = create_access_token(subject=usuario.uid)
    set_auth_cookie(response, token.access_token)


# Sin CurrentUser a propósito: con el token expirado también debe poder borrarse la cookie.
@router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT
)
async def logout(response: Response):
    clear_auth_cookie(response)


# CRUD
@router.get(
        "/{uid}",
        response_model=UserPublic
)
async def get_usuario(usuario: UsuarioPropio):
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
    cambios_usuario: UserUpdate,
    usuario: UsuarioPropio,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    cambios = cambios_usuario.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se detecto ningun cambio en los datos del usuario."
        )

    if cambios.get("username") is not None:
        await validar_usuario(cambios["username"], db, usuario.uid)

    if cambios.get("email") is not None:
        await validar_email_usuario(cambios["email"], db, usuario.uid)

    for campo, valor in cambios.items():
        if campo == "email":
            setattr(usuario, campo, valor.lower())
        else:
            setattr(usuario, campo, valor)

    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.delete(
     "/{uid}",
     status_code=status.HTTP_204_NO_CONTENT
)
async def eliminar_usuario(
    usuario: UsuarioPropio,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Borra en cascada sus campañas, empleados y simulaciones (ver models.User).
    await db.delete(usuario)
    await db.commit()
    clear_auth_cookie(response)