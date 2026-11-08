from uuid import UUID

from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import models


# VALIDACIONES DE EMPLEADO
async def validar_email_empleado(
        email: str,
        owner_id: UUID,
        db: AsyncSession,
        id_excluir: UUID | None = None
    ):
    query = select(models.Empleados).where(
        models.Empleados.owner == owner_id,
        func.lower(models.Empleados.email) == email.lower(),
    )
    
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
        uid_excluir: UUID | None = None
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
        db: AsyncSession,
        uid_excluir: UUID | None = None
):
    query = select(models.User).where(func.lower(models.User.username) == username.lower())

    if uid_excluir is not None:
        query = query.where(models.User.uid != uid_excluir)

    if await db.scalar(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con username {username} ya existe."
        )
    return None