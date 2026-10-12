from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.campañas import CampañaCreate, CampañaResponse
from schemas.simulaciones import SimulacionResponse
import models
from utils.validaciones_campañas import validar_campaña


router = APIRouter()


@router.get(
    "/{cam_id}",
    response_model=list[SimulacionResponse],
)
async def get_simulaciones(
    cam_id: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await validar_campaña(cam_id, db)

    result = await db.scalars(
        select(models.Simulaciones).where(models.Simulaciones.campana_id == cam_id)
    )
    simulaciones = result.all()
    return simulaciones


@router.post(
    "",
    response_model=CampañaResponse, 
    status_code=status.HTTP_201_CREATED
)
async def crear_simulacion(
    campaña: CampañaCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    ee_ids = list(dict.fromkeys(u_id for u_id in campaña.destinatarios))
    if not ee_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Simulacion invalida. Ningun empleado ha sido seleccionado."
        )

    current_user_id = 1

    result = await db.scalars(
        select(models.Empleados)
        .where(models.Empleados.eeid.in_(ee_ids),
               models.Empleados.estado.is_(True))
    )
    target_empleados = result.all()
    usuarios_encontrados = {empleado.eeid for empleado in target_empleados}
    if usuarios_encontrados != set(ee_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uno o mas destinatarios no existen o estan inactivos."
        )

    datos_campaña = campaña.model_dump(exclude={"destinatarios"})
    nueva_campaña = models.Campaña(
        owner=current_user_id,
        **datos_campaña,
    )

    try:
        db.add(nueva_campaña)
        await db.flush()

        db.add_all([
            models.Simulaciones(
                campana_id=nueva_campaña.camid,
                ee_id=empleado.eeid
            ) for empleado in target_empleados
        ])
        await db.commit()

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear la simulacion. Details: {e}"
        )
    return nueva_campaña

