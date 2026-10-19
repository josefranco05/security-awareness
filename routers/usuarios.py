from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import models
from schemas.usuarios import UserCreate, UserResponse, UserUpdate
from database.async_database import get_db
from utils.validaciones import validar_usuario, validar_email_usuario, validar_usuario_por_id


router = APIRouter()


@router.get(
        "",
        response_model=UserResponse
)
async def get_usuarios(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.User)
    )
    empleados = result.all()
    return empleados


@router.get(
        "/{uid}",
        response_model=UserResponse
)
async def get_usuario(
    uid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    empleado = await db.scalar(
        select(models.User)
        .where(models.User.uid == uid)
    )
    return empleado


@router.post(
        "",
        response_model=UserResponse,
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
        email=user.email
    )

    db.add(nuevo_usuario)
    await db.commit()
    await db.refresh(nuevo_usuario)

    return nuevo_usuario


@router.patch(
    "/{uid}",
    response_model=UserResponse
)
async def actualizar_usuario(
    uid: int,
    usuario: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    usuario_a_cambiar = await validar_usuario_por_id(uid, db)
    cambios = usuario.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se detecto ningun cambio en los datos del usuario."
        )

    if cambios.get("email") is not None:
        await validar_email_usuario(cambios["email"], db, uid)

    for campo, valor in cambios.items():
            setattr(usuario_a_cambiar, campo, valor)
    
    await db.commit()
    await db.refresh(usuario_a_cambiar)
    return usuario_a_cambiar


@router.delete(
     "/{uid}",
     status_code=status.HTTP_204_NO_CONTENT
)
async def eliminar_usuario(
    uid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    usuario_a_eliminar = await validar_usuario_por_id(uid, db)

    await db.delete(usuario_a_eliminar)
    await db.commit()