import logging
from typing import Annotated

from fastapi import APIRouter, status, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from core.auth import CurrentUser
from core.permisos import CampañaPropia
from database.async_database import get_db
from schemas.campañas import CampañaCreate, CampañaResponse
from worker.tasks import enviar_campaña
import models


logger = logging.getLogger(__name__)

router =  APIRouter()


@router.get(
        "",
        response_model=list[CampañaResponse]
)
async def get_all_campañas(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.Campaña)
        .options(selectinload(models.Campaña.simulaciones))
        .where(models.Campaña.owner == current_user.uid)
        .order_by(models.Campaña.fecha.desc())
    )
    campañas = result.all()
    return campañas


@router.get(
        "/{camid}",
        response_model=CampañaResponse
)
async def get_campaña_por_id(campaña: CampañaPropia):
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
               models.Empleados.owner == current_user.uid,
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

    except Exception as exc:
        await db.rollback()
        # El detalle (SQL, tablas, restricciones) va al log, nunca al cliente.
        logger.exception("No se pudo crear la campaña del usuario %s. Error: %s", current_user.uid, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear la campaña. Intenta nuevamente."
        ) from exc

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
    campaña: CampañaPropia,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Dispara manualmente el envío de las simulaciones pendientes."""
    camid = campaña.camid

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
    campaña: CampañaPropia,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    await db.delete(campaña)
    await db.commit()