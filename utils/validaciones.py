from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import models


# VALIDACIONES DE CAMPAÑA
async def validar_campaña(
        cam_id: int,
        db: AsyncSession,
):
    result = await db.scalars(
        select(models.Campaña).where(models.Campaña.camid == cam_id)
    )
    campaña = result.first()
    if not campaña:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró una campaña con id {cam_id}"
        )
    return campaña


# VALIDACIONES DE EMPLEADO
async def validar_empleado_por_id(
        eeid: int, 
        db: AsyncSession
    ):
    result = await db.scalars(
        select(models.Empleados).where(models.Empleados.eeid == eeid)
    )
    empleado = result.first()
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró un empleado con id {eeid}"
        )
    return empleado


async def validar_email_empleado(
        email: str,
        db: AsyncSession,
        id_excluir: int | None = None
    ):
    query = select(models.Empleados).where(func.lower(models.Empleados.email) == email.lower())
    
    if id_excluir is not None:
        query = query.where(models.Empleados.eeid != id_excluir)

    if await db.scalar(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un empleado con email {email}"
        )


# VALIDACIONES DE USUARIO
async def validar_email_usuario(
        email: str,
        db: AsyncSession,
        uid_excluir: int | None = None
    ):
    query = select(models.User).where(func.lower(models.User.email) == email.lower())
    
    if uid_excluir is not None:
        query = query.where(models.User.uid != uid_excluir)

    if await db.scalar(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con email {email}"
        )
    return None


async def validar_usuario(
        username: str,
        db: AsyncSession
):
    result = await db.scalars(
        select(models.User).where(func.lower(models.User.username) == username.lower())
    )
    existing_user = result.first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con username {username} ya existe."
        )
    return existing_user


async def validar_usuario_por_id(
        uid: int,
        db: AsyncSession
):
    result = await db.scalars(
        select(models.User).where(models.User.uid == uid)
    )
    existing_user = result.first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con username {uid} ya existe."
        )
    return existing_user