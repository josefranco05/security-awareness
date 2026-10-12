from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, status, HTTPException
from fastapi import Request, Depends
from sqlalchemy import select, func

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db
from schemas.empleados import EmpleadoResponse, EmpleadoCreate, EmpleadoUpdate
from utils.validaciones_empleados import validar_email, validar_empleado_por_id


router = APIRouter()


@router.get("", response_model=list[EmpleadoResponse])
async def get_empleados(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(select(models.Empleados))
    empleados = result.all()
    return empleados


@router.post(
        "",
        response_model=EmpleadoResponse, 
        status_code=status.HTTP_201_CREATED
    )
async def post_empleado(
    empleado: EmpleadoCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await validar_email(empleado.email, db)

    nuevo_empleado = models.Empleados(
        nombre=empleado.nombre,
        email=empleado.email,
        empresa=empleado.empresa,
        cargo=empleado.cargo,
        riesgo=empleado.riesgo,
        estado=empleado.estado,
    )

    db.add(nuevo_empleado)
    await db.commit()
    await db.refresh(nuevo_empleado)

    return nuevo_empleado


@router.patch(
    "/{eeid}",
    response_model=EmpleadoResponse,
)
async def update_empleado_parcial(
    eeid: int,
    empleado: EmpleadoUpdate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    empleado_a_cambiar = await validar_empleado_por_id(eeid, db)
    cambios = empleado.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se proporcionaron cambios para actualizar el empleado."
        )    
    
    if cambios.get("email") is not None:
        await validar_email(cambios["email"], db, id_excluir=eeid)

    for campo, valor in cambios.items():
        setattr(empleado_a_cambiar, campo, valor)

    await db.commit()
    await db.refresh(empleado_a_cambiar)
    return empleado_a_cambiar


@router.delete(
    "/{eeid}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_empleado(
    eeid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    empleado_a_eliminar = await validar_empleado_por_id(eeid, db)

    await db.delete(empleado_a_eliminar)
    await db.commit()
