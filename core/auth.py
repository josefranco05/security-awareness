"""Autenticación: hash de contraseñas (Argon2) y tokens de acceso (JWT).

El JWT viaja únicamente en una cookie HttpOnly: el frontend nunca lo ve.

Uso previsto desde los routers y las páginas:

    from core.auth import CurrentUser

    @router.get("/me")
    async def me(user: CurrentUser): ...

Sin sesión válida se lanza un 401. En /api se responde tal cual; en las
páginas HTML el handler de main.py lo convierte en redirección a /login.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import APIKeyCookie
from pwdlib import PasswordHash
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import models
from core.config import settings
from database.async_database import get_db
from schemas.usuarios import Token


password_hash = PasswordHash.recommended()

# Hash con los mismos parámetros que los reales: se verifica contra él cuando el
# username no existe, para que /token tarde lo mismo y no revele usuarios registrados.
_HASH_FALSO = password_hash.hash("hash-falso-para-igualar-tiempos")

cookie_scheme = APIKeyCookie(name=settings.AUTH_COOKIE_NAME)


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
    if user is None:
        verificar_password(password, _HASH_FALSO)
        raise _credentials_exception
    if not verificar_password(password, user.password_hash):
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


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,   # JavaScript no puede leerla
        samesite="lax",  # no se envía en POST/PUT/PATCH/DELETE cross-site (CSRF)
    )


def clear_auth_cookie(response: Response) -> None:
    # Mismos atributos que al crearla, para que el navegador la reconozca.
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


async def get_current_user(
    token: Annotated[str, Depends(cookie_scheme)],
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
        )
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> models.User | None:
    """Solo para páginas públicas (login, registro) que cambian si ya hay sesión.

    Nunca lanza: sin cookie o con token inválido devuelve None.
    """
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


OptionalUser = Annotated[models.User | None, Depends(get_optional_user)]


_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No se pudieron validar las credenciales.",
)

_token_expired = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Token invalido o expirado.",
)