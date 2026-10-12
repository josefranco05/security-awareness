from fastapi import HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models


async def validar_email(
        email: str,
        db: AsyncSession,
        id_excluir: int | None = None
    ):
    query = select(models.Empleados).where(models.Empleados.email == email)
    
    if id_excluir is not None:
        query = query.where(models.Empleados.eeid != id_excluir)

    if await db.scalar(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un empleado con email {email}"
        )


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