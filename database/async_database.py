from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

# pool_pre_ping: descarta conexiones que la red cerró (p. ej. tras un reinicio o failover de la base).
engine = create_async_engine(
    settings.DATABASE_URL.get_secret_value(),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    # Sin esto asyncpg espera 60 s a una base que no responde (y /readyz con él).
    connect_args={"timeout": settings.DB_CONNECT_TIMEOUT},
)


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    # Nombres fijos para índices y restricciones: Alembic los necesita para poder
    # modificarlos o borrarlos en migraciones futuras.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
