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

    simulaciones: Mapped[list[Simulacion]] = relationship("Simulacion", back_populates="user")


class Simulacion(Base):
    __tablename__ = "simulaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.uid"),
        nullable=False,
        index=True
    )
    campana: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha_envio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    fecha_respuesta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    aprobado: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    user: Mapped[User] = relationship("User", back_populates="simulaciones")


