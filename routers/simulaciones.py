from typing import Annotated

from fastapi import APIRouter, Depends

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import CurrentUser
from core.permisos import CampañaPropia
from database.async_database import get_db
from schemas.simulaciones import SimulacionResponse
import models


router = APIRouter()


@router.get(
    "",
    response_model=list[SimulacionResponse],
)
async def get_all_simulaciones(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Las simulaciones no tienen owner propio: pertenecen al dueño de su campaña.
    result = await db.scalars(
        select(models.Simulaciones)
        .join(models.Simulaciones.campana)
        .options(selectinload(models.Simulaciones.empleados))
        .where(models.Campaña.owner == current_user.uid)
        .order_by(models.Simulaciones.fecha_envio.desc())
    )
    simulaciones = result.all()
    return simulaciones


@router.get(
    "/{camid}",
    response_model=list[SimulacionResponse],
)
async def get_simulaciones_por_campaña(
    campaña: CampañaPropia,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Simulaciones).where(models.Simulaciones.campana_id == campaña.camid)
    )
    simulaciones = result.all()
    return simulaciones




