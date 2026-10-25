from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, status, HTTPException, Depends

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

import models
from core.auth import CurrentUser
from database.async_database import get_db
from schemas.empleados import EmpleadoResponse, EmpleadoCreate, EmpleadoUpdate
from utils.validaciones import validar_email_empleado, validar_empleado_por_id


router = APIRouter()


@router.get(
        "", 
        response_model=list[EmpleadoResponse]
)
async def get_empleados(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Empleados)
        .options(selectinload(models.Empleados.simulaciones))
        .order_by(models.Empleados.riesgo.desc())
    )
    empleados = result.all()
    return empleados


@router.get(
        "/{eeid}", 
        response_model=EmpleadoResponse
)
async def get_empleado(
    eeid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Empleados)
        .options(selectinload(models.Empleados.simulaciones))
        .where(models.Empleados.eeid == eeid)
        .order_by(models.Empleados.riesgo.desc())
    )
    empleado = result.first()
    return empleado


@router.post(
        "",
        response_model=EmpleadoResponse, 
        status_code=status.HTTP_201_CREATED
    )
async def agregar_empleado(
    empleado: EmpleadoCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await validar_email_empleado(empleado.email, current_user.uid, db)

    nuevo_empleado = models.Empleados(
        owner=current_user.uid,
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


@router.put(
    "/{eeid}",
    response_model=EmpleadoResponse,
)
async def remplazar_empleado(
    eeid: int,
    empleado: EmpleadoCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    empleado_a_cambiar = await validar_empleado_por_id(eeid, db)

    await validar_email_empleado(empleado.email, empleado_a_cambiar.owner, db, eeid)

    empleado_a_cambiar.nombre = empleado.nombre
    empleado_a_cambiar.email = empleado.email
    empleado_a_cambiar.empresa = empleado.empresa
    empleado_a_cambiar.cargo = str(empleado.cargo)
    empleado_a_cambiar.riesgo = empleado.riesgo
    empleado_a_cambiar.estado = empleado.estado

    await db.commit()
    await db.refresh(empleado_a_cambiar, attribute_names=["simulaciones"])

    return empleado_a_cambiar    


@router.patch(
    "/{eeid}",
    response_model=EmpleadoResponse,
)
async def editar_empleado(
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
        await validar_email_empleado(cambios["email"], empleado_a_cambiar.owner, db, eeid)

    for campo, valor in cambios.items():
        setattr(empleado_a_cambiar, campo, valor)

    await db.commit()
    await db.refresh(empleado_a_cambiar)
    return empleado_a_cambiar


@router.delete(
    "/{eeid}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def eliminar_empleado(
    eeid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    empleado_a_eliminar = await validar_empleado_por_id(eeid, db)

    await db.delete(empleado_a_eliminar)
    await db.commit()
