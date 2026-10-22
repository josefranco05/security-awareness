"""Autenticación: hash de contraseñas (Argon2) y tokens de acceso (JWT).

Uso previsto desde los routers:

    from core.auth import CurrentUser, authenticate_user, create_access_token

    @router.get("/me")
    async def me(user: CurrentUser): ...

El endpoint que emite tokens debe vivir en `TOKEN_URL` para que el botón
"Authorize" de /docs funcione.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import models
from core.config import settings
from database.async_database import get_db
from schemas.usuarios import Token


password_hash = PasswordHash.recommended()

TOKEN_URL = "/api/usuarios/token"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=TOKEN_URL)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verificar_password(crudo: str, hashed: str) -> bool:
    return password_hash.verify(crudo, hashed)


async def autenticar_usuario(
    db: AsyncSession, username: str, password: str
) -> models.User | None:
    """Devuelve el usuario si las credenciales son correctas, si no None."""
    user = await db.scalar(
        select(models.User).where(func.lower(models.User.username) == username.lower())
     )
    if not user or not verificar_password(password, user.password_hash):
        raise _credentials_exception
    return user


def create_access_token(
    subject: str | int, expires_delta: timedelta | None = None
) -> Token:
    """Firma un JWT cuyo `sub` es el identificador del usuario (su uid)."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + expires_delta,
    }
    encoded = jwt.encode(
        payload,
        settings.SECRET_KEY_AUTH.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    return Token(access_token=encoded, token_type="bearer")


def verify_access_token(token: str) -> str:
    """Valida firma y expiración; devuelve el `sub`.

    Lanza jwt.InvalidTokenError (o una subclase) si el token no es válido.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY_AUTH.get_secret_value(),
            algorithms=[settings.ALGORITHM],  # lista fija: evita el ataque "alg: none"
            options={"require": ["sub", "exp"]},
        )
    except (jwt.InvalidTokenError, ValueError):
        return ""
    else:
        return payload["sub"]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> models.User:
    try:
        uid = int(verify_access_token(token))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise _token_expired

    user = await db.get(models.User, uid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El usuario ingresado no existe.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]


_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No se pudieron validar las credenciales.",
    headers={"WWW-Authenticate": "Bearer"},
)

_token_expired = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Token invalido o expirado.",
    headers={"WWW-Authenticate": "Bearer"},
)