"""Autorización: qué recursos puede tocar el usuario autenticado.

Un modelo es "propio" de un usuario si su columna `owner` es el uid del usuario.
Las rutas no llaman a `validar_propietario` directamente: declaran la
dependencia del recurso, p. ej.:

    from core.permisos import CampañaPropia

    @router.delete("/{camid}")
    async def eliminar(campaña: CampañaPropia): ...

Si el recurso no existe o es de otro usuario se responde 404 en ambos casos,
para no revelar qué ids existen.
"""
from __future__ import annotations

from typing import Annotated, Any, ClassVar, Protocol, TypeVar

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper

import models
from core.auth import CurrentUser
from database.async_database import get_db


class ConPropietario(Protocol):
    """Cualquier modelo mapeado con columna `owner` (FK a users.uid)."""
    __mapper__: ClassVar[Mapper[Any]]
    owner: Mapped[int]


Modelo = TypeVar("Modelo", bound=ConPropietario)


async def validar_propietario(
    db: AsyncSession,
    modelo: type[Modelo],
    id_recurso: int,
    current_user: models.User,
) -> Modelo:
    """Devuelve el recurso si existe y pertenece al usuario; si no, 404."""
    pk = modelo.__mapper__.primary_key[0]
    recurso = await db.scalar(
        select(modelo).where(pk == id_recurso, modelo.owner == current_user.uid)
    )
    if recurso is None:
        raise _no_encontrado
    return recurso


# CAMPAÑAS
async def get_campaña_propia(
    camid: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> models.Campaña:
    return await validar_propietario(db, models.Campaña, camid, current_user)


CampañaPropia = Annotated[models.Campaña, Depends(get_campaña_propia)]


# EMPLEADOS
async def get_empleado_propio(
    eeid: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> models.Empleados:
    return await validar_propietario(db, models.Empleados, eeid, current_user)


EmpleadoPropio = Annotated[models.Empleados, Depends(get_empleado_propio)]


# USUARIOS
async def get_usuario_propio(uid: int, current_user: CurrentUser) -> models.User:
    """Un usuario solo puede leer o modificar su propia cuenta."""
    if current_user.uid != uid:
        raise _no_encontrado
    return current_user


UsuarioPropio = Annotated[models.User, Depends(get_usuario_propio)]


_no_encontrado = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Recurso no encontrado.",
)
