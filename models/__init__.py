"""Modelos (PostgreSQL). El esquema lo crean las migraciones de Alembic, no la app.

Todas las claves primarias son UUID4 generados en Python: se conoce el id antes del flush.

Los límites de longitud son reales en PostgreSQL: cada `String(n)` tiene su
`max_length` en schemas/, para que un valor largo dé 422 y no un error de la base.
"""
from __future__ import annotations

import uuid
from datetime import datetime, UTC

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.async_database import Base

# Máximo de una dirección de correo (RFC 5321).
LARGO_EMAIL = 254

# Debe coincidir con schemas.simulaciones.SimulacionStatus (lo comprueba un test).
ESTADOS_SIMULACION = ("pending", "sending", "sent", "failed", "opened", "clicked", "completed")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _owner(**opciones) -> Mapped[uuid.UUID]:
    # CASCADE en la base además del cascade del ORM: un DELETE directo tampoco deja huérfanos.
    return mapped_column(ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, **opciones)


class User(Base):
    __tablename__ = "users"

    uid: Mapped[uuid.UUID] = _pk()
    # Únicos sin distinguir mayúsculas: ver los índices sobre lower() al final del módulo.
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(LARGO_EMAIL), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)

    # Al borrar el usuario se borran sus datos (owner es NOT NULL).
    campanas: Mapped[list[Campaña]] = relationship("Campaña", back_populates="user", cascade="all, delete-orphan")
    empleados: Mapped[list[Empleados]] = relationship("Empleados", back_populates="user", cascade="all, delete-orphan")
    detecciones: Mapped[list[Deteccion]] = relationship("Deteccion", back_populates="user", cascade="all, delete-orphan")
    token_extension: Mapped[TokenExtension | None] = relationship(
        "TokenExtension", back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Campaña(Base):
    __tablename__ = "campanas"

    camid: Mapped[uuid.UUID] = _pk()
    owner: Mapped[uuid.UUID] = _owner(index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    remitente: Mapped[str] = mapped_column(String, nullable=False)
    asunto: Mapped[str] = mapped_column(String, nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="campanas")
    simulaciones: Mapped[list[Simulaciones]] = relationship(back_populates="campana", cascade="all, delete-orphan")


class Empleados(Base):
    __tablename__ = "empleados"

    eeid: Mapped[uuid.UUID] = _pk()
    # Sin índice propio: lo cubre uq_empleados_owner_email_lower, que empieza por owner.
    owner: Mapped[uuid.UUID] = _owner()
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    # Único por dueño (no global, para no revelar empleados de otros): ver el índice al final.
    email: Mapped[str] = mapped_column(String(LARGO_EMAIL), nullable=False)
    riesgo: Mapped[int] = mapped_column(Integer, nullable=False)
    empresa: Mapped[str] = mapped_column(String(100), nullable=False)
    cargo: Mapped[str] = mapped_column(String(50), nullable=True)
    estado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship("User", back_populates="empleados")
    simulaciones: Mapped[list[Simulaciones]] = relationship(back_populates="empleados", cascade="all, delete-orphan")


class Simulaciones(Base):
    __tablename__ = "simulaciones"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{e}'" for e in ESTADOS_SIMULACION) + ")", name="status_valido",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    campana_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campanas.camid", ondelete="CASCADE"), nullable=False, index=True,
    )
    ee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("empleados.eeid", ondelete="CASCADE"), nullable=False, index=True,
    )
    # Se marca cuando el correo se envía, no cuando se crea la fila.
    fecha_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_respuesta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    aprobado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Cola de envío
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    proveedor_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empleados: Mapped[Empleados] = relationship(back_populates="simulaciones")
    campana: Mapped[Campaña] = relationship(back_populates="simulaciones")


class Deteccion(Base):
    """Resultado de un análisis. No guarda el correo: ni cuerpo, ni asunto, ni URLs."""

    __tablename__ = "detecciones"

    id: Mapped[uuid.UUID] = _pk()
    owner: Mapped[uuid.UUID] = _owner(index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    etiqueta: Mapped[str] = mapped_column(String(20), nullable=False)
    # Nivel final, después de las reglas. Es el que se muestra.
    nivel: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # Salida cruda del modelo, antes de las reglas: no sirve para derivar el nivel.
    probabilidad: Mapped[float] = mapped_column(Float, nullable=False)
    reglas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Puede citar hasta 3 términos del correo; solo debe verlo su dueño.
    razones: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    user: Mapped[User] = relationship("User", back_populates="detecciones")


class TokenExtension(Base):
    """Token de la extensión del navegador: uno por usuario, y solo se guarda su hash."""

    __tablename__ = "tokens_extension"

    id: Mapped[uuid.UUID] = _pk()
    owner: Mapped[uuid.UUID] = _owner(unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship("User", back_populates="token_extension")


# Unicidad sin distinguir mayúsculas. utils/validaciones.py da el 400 con mensaje claro;
# estos índices impiden el duplicado aunque dos peticiones lleguen a la vez.
Index("uq_users_username_lower", func.lower(User.username), unique=True)
Index("uq_users_email_lower", func.lower(User.email), unique=True)
Index("uq_empleados_owner_email_lower", Empleados.owner, func.lower(Empleados.email), unique=True)

