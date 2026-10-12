from __future__ import annotations

from typing import Annotated
from unittest import result

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import models
from schemas.usuarios import UserCreate, UserResponse
from database import get_db


router = APIRouter()

@router.post(
        "",
        response_model=UserResponse,
        status_code=status.HTTP_201_CREATED
)
async def crear_usuario(
    user: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.scalars(
        select(models.User).where(models.User.username == user.username)
    )
    existing_user = result.first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con username {user.username} ya existe."
        )

    result = await db.scalars(
        select(models.User).where(models.User.email == user.email)
    )
    existing_email = result.first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con email {user.email} ya existe."
        )

    nuevo_usuario = models.User(
        username=user.username,
        email=user.email
    )
    db.add(nuevo_usuario)
    await db.commit()
    await db.refresh(nuevo_usuario)

    return nuevo_usuario