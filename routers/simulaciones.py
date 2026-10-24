from typing import Annotated

from fastapi import APIRouter, Depends

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.async_database import get_db
from schemas.simulaciones import SimulacionResponse
import models
from utils.validaciones import validar_campaña


router = APIRouter()


@router.get(
    "",
    response_model=list[SimulacionResponse],
)
async def get_all_simulaciones(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Simulaciones)
        .options(selectinload(models.Simulaciones.empleados))
        .order_by(models.Simulaciones.fecha_envio.desc())
    )
    simulaciones = result.all()
    return simulaciones


@router.get(
    "/{camid}",
    response_model=list[SimulacionResponse],
)
async def get_simulaciones_por_campaña(
    camid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await validar_campaña(camid, db)

    result = await db.scalars(
        select(models.Simulaciones).where(models.Simulaciones.campana_id == camid)
    )
    simulaciones = result.all()
    return simulaciones




