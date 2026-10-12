from fastapi import HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models

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