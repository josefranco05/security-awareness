import logging
from typing import Annotated

from fastapi import APIRouter, status, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from core.auth import CurrentUser
from database.async_database import get_db
from schemas.campañas import CampañaCreate, CampañaResponse
from worker.tasks import enviar_campaña
import models
from utils.validaciones import validar_campaña


logger = logging.getLogger(__name__)

router =  APIRouter()


@router.get(
        "",
        response_model=list[CampañaResponse]
)
async def get_all_campañas(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Campaña)
        .options(selectinload(models.Campaña.simulaciones))
        .order_by(models.Campaña.fecha.desc())
    )
    campañas = result.all()
    return campañas


@router.get(
        "/{camid}",
        response_model=CampañaResponse
)
async def get_campaña_por_id(
    camid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    campaña = await db.scalar(
        select(models.Campaña)
        .options(selectinload(models.Campaña.simulaciones))
        .where(models.Campaña.camid == camid)
        .order_by(models.Campaña.fecha.desc())
    )
    return campaña


@router.post(
    "",
    response_model=CampañaResponse, 
    status_code=status.HTTP_201_CREATED
)
async def crear_campaña(
    campaña: CampañaCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    ee_ids = list(dict.fromkeys(u_id for u_id in campaña.destinatarios))
    if not ee_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Simulacion invalida. Ningun empleado ha sido seleccionado."
        )

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
        owner=current_user.uid,
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

    # El encolado va DESPUÉS del commit: si el broker no responde, la campaña
    # queda creada con sus filas en "pending" y el barrido periódico las envía.
    try:
        await run_in_threadpool(enviar_campaña.delay, nueva_campaña.camid)
    except Exception:
        logger.exception(
            "No se pudo encolar el envío de la campaña %s", nueva_campaña.camid
        )

    return nueva_campaña


@router.post(
    "/{camid}/enviar",
    name="enviar_campaña_ahora",
)
async def enviar_campaña_ahora(
    camid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Dispara manualmente el envío de las simulaciones pendientes."""
    await validar_campaña(camid, db)

    pendientes = await db.scalar(
        select(func.count())
        .select_from(models.Simulaciones)
        .where(
            models.Simulaciones.campana_id == camid,
            models.Simulaciones.status == "pending",
        )
    )

    if not pendientes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La campaña no tiene simulaciones pendientes por enviar.",
        )

    try:
        await run_in_threadpool(enviar_campaña.delay, camid)
    except Exception as exc:
        logger.exception("No se pudo encolar la campaña %s", camid)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo encolar el envío. Intenta nuevamente.",
        ) from exc

    return {"camid": camid, "pendientes": pendientes, "encolado": True}


@router.delete(
    "/{camid}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_campaña_por_id(
    camid: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    campaña_a_eliminar = await validar_campaña(camid, db)

    await db.delete(campaña_a_eliminar)
    await db.commit()