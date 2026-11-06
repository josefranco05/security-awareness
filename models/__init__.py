from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, Float, JSON, String, Integer, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.async_database import Base


class User(Base):
    __tablename__ = "users"

    uid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
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

    camid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[int] = mapped_column(ForeignKey("users.uid"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    remitente: Mapped[str] = mapped_column(String, nullable=False)
    asunto: Mapped[str] = mapped_column(String, nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="campanas")
    simulaciones: Mapped[list[Simulaciones]] = relationship(back_populates="campana", cascade="all, delete-orphan")


class Empleados(Base):
    __tablename__ = "empleados"
    # El email es único por dueño, no global: evita revelar empleados de otros usuarios.
    __table_args__ = (UniqueConstraint("owner", "email"),)

    eeid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[int] = mapped_column(ForeignKey("users.uid"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(50), nullable=False)
    riesgo: Mapped[int] = mapped_column(Integer, nullable=False)
    empresa: Mapped[str] = mapped_column(String(100), nullable=False)
    cargo: Mapped[str] = mapped_column(String(50), nullable=True)
    estado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship("User", back_populates="empleados")
    simulaciones: Mapped[list[Simulaciones]] = relationship(back_populates="empleados", cascade="all, delete-orphan")


class Simulaciones(Base):
    __tablename__ = "simulaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.camid"), nullable=False, index=True)
    ee_id: Mapped[int] = mapped_column(ForeignKey("empleados.eeid"), nullable=False, index=True)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[int] = mapped_column(ForeignKey("users.uid"), nullable=False, index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    etiqueta: Mapped[str] = mapped_column(String(20), nullable=False)
    # Nivel final, después de las reglas. Es el que se muestra.
    nivel: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # Salida cruda del modelo, antes de las reglas: no sirve para derivar el nivel.
    probabilidad: Mapped[float] = mapped_column(Float, nullable=False)
    reglas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Puede citar hasta 3 términos del correo; solo debe verlo su dueño.
    razones: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    user: Mapped[User] = relationship("User", back_populates="detecciones")


class TokenExtension(Base):
    """Token de la extensión del navegador: uno por usuario, y solo se guarda su hash."""

    __tablename__ = "tokens_extension"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[int] = mapped_column(ForeignKey("users.uid"), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship("User", back_populates="token_extension")


