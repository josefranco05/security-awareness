from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, String, Integer, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    uid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    campanas: Mapped[list[Campaña]] = relationship("Campaña", back_populates="user")

    
class Campaña(Base):
    __tablename__ = "campanas"

    camid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[int] = mapped_column(ForeignKey("users.uid"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="campanas")
    simulaciones: Mapped[list[Simulacion]] = relationship("Simulacion", back_populates="campana")


class Empleados(Base):
    __tablename__ = "empleados"

    eeid: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    riesgo: Mapped[int] = mapped_column(Integer, nullable=False)
    empresa: Mapped[str] = mapped_column(String(100), nullable=False)
    cargo: Mapped[str] = mapped_column(String(50), nullable=True)
    estado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    simulaciones: Mapped[list[Simulacion]] = relationship("Simulacion", back_populates="empleados")


class Simulacion(Base):
    __tablename__ = "simulaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.camid"), nullable=False, index=True)
    ee_id: Mapped[int] = mapped_column(ForeignKey("empleados.eeid"), nullable=False, index=True)
    fecha_envio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    fecha_respuesta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    aprobado: Mapped[bool | None] = mapped_column(Boolean, nullable=False, default=None)

    empleados: Mapped[Empleados] = relationship("Empleados", back_populates="simulaciones")
    campana: Mapped[Campaña] = relationship("Campaña", back_populates="simulaciones")


