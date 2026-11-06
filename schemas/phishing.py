"""Contrato de POST /api/phishing/analizar.

`body` no lleva límite aquí: excederlo es 413, no 422, y lo comprueba el endpoint.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ml.inferencia import (
    MAX_CARACTERES_ASUNTO,
    MAX_CARACTERES_URL,
    MAX_URLS,
    Nivel,
    ResultadoAuth,
)


def _reemplazar_sustitutos(texto: str) -> str:
    # JSON admite sustitutos sueltos ("\ud83d") y no se pueden codificar en UTF-8. Se reemplazan
    # en vez de rechazarlos: si no, un solo carácter roto en el correo evitaría el análisis.
    return texto.encode("utf-8", "replace").decode("utf-8")


Texto = Annotated[str, AfterValidator(_reemplazar_sustitutos)]


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Enlace(_Estricto):
    # Sin HttpUrl: los enlaces desactivados (hxxp://malo[.]com) son válidos.
    text: Annotated[Texto, Field(max_length=MAX_CARACTERES_URL)] = ""
    href: Annotated[Texto, Field(max_length=MAX_CARACTERES_URL)]


class AuthResults(_Estricto):
    spf: ResultadoAuth = ResultadoAuth.UNKNOWN
    dkim: ResultadoAuth = ResultadoAuth.UNKNOWN
    dmarc: ResultadoAuth = ResultadoAuth.UNKNOWN


class AnalisisRequest(_Estricto):
    subject: Annotated[Texto, Field(max_length=MAX_CARACTERES_ASUNTO)] = ""
    body: Texto
    urls: Annotated[list[Enlace], Field(max_length=MAX_URLS)] = []
    auth_results: AuthResults = AuthResults()


class TokenExtensionCreado(BaseModel):
    token: str


class AnalisisResponse(BaseModel):
    etiqueta: str
    nivel: Nivel
    probabilidad: float
    razones: list[str]
    reglas: list[str]
