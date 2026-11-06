"""Inferencia del clasificador de phishing para la API.

Expone lo que necesita ``routers/phishing.py``: ``cargar_modelo()`` una vez al
arrancar (en ``lifespan``) y ``analizar()`` en cada petición. La capa de reglas
sobre ``auth_results`` vive aquí, en una tabla pequeña (``REGLAS``), para poder
probarla y explicarla sin levantar la API.

Este módulo no registra nada: el contenido del correo nunca sale de ``analizar()``.
``analizar()`` es CPU-bound (~10-30 ms) y segura entre hilos; llámala desde un
endpoint ``def`` (no ``async def``) o con ``run_in_threadpool``.
"""
from __future__ import annotations

import re
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.exceptions import InconsistentVersionWarning # type: ignore
from sklearn.pipeline import Pipeline

from ml.features import texto_vectorizador

RUTA_MODELO_PREDETERMINADA = Path(__file__).resolve().parent / "artifacts" / "model.joblib"

# Límites de entrada que el modelo de Pydantic de la API debe imponer (413/422).
# El pipeline igual recorta lo que exceda, pero la API debe rechazarlo antes.
MAX_BYTES_CUERPO = 100_000
MAX_CARACTERES_ASUNTO = 500
MAX_URLS = 50
MAX_CARACTERES_URL = 2048

# Niveles de riesgo de la Fase 0: p <= BAJO_MAX bajo, p <= ALTO_MIN medio, p > ALTO_MIN alto.
BAJO_MAX, ALTO_MIN = 0.4, 0.7
MAX_TERMINOS_RAZON = 3


class Nivel(str, Enum):
    BAJO = "bajo"
    MEDIO = "medio"
    ALTO = "alto"


_ORDEN_NIVELES = list(Nivel)
_ETIQUETA_POR_NIVEL = {Nivel.BAJO: "legitimo", Nivel.MEDIO: "sospechoso", Nivel.ALTO: "phishing"}


class ResultadoAuth(str, Enum):
    """Valores aceptados para spf/dkim/dmarc. La extensión mapea softfail, neutral, etc. a estos."""

    PASS = "pass"
    FAIL = "fail"
    NONE = "none"
    UNKNOWN = "unknown"


CAMPOS_AUTH = ("spf", "dkim", "dmarc")


@dataclass(frozen=True)
class Regla:
    campo: str
    valor: ResultadoAuth
    subir_niveles: int         # escalones de nivel que sube (se toma el máximo, no la suma)
    sumar_probabilidad: float  # se suma a la probabilidad antes de calcular el nivel
    razon: str


# Solo hay reglas para "fail": un "pass" nunca baja el riesgo (los atacantes pasan
# SPF/DKIM/DMARC con sus propios dominios) y "none"/"unknown" no cambian nada.
REGLAS = (
    Regla("dmarc", ResultadoAuth.FAIL, 1, 0.0,
          "El remitente podría estar suplantado: su dominio no superó la verificación DMARC."),
    Regla("spf", ResultadoAuth.FAIL, 1, 0.0,
          "El remitente podría estar suplantado: el servidor que envió el correo no está autorizado "
          "por su dominio (SPF)."),
    Regla("dkim", ResultadoAuth.FAIL, 0, 0.10,
          "La firma digital del correo (DKIM) no es válida: pudo ser alterado en el camino o falsificado."),
)

# Términos que no le dicen nada a una persona: palabras vacías, fragmentos de URL. Ya sin acentos.
_PALABRAS_VACIAS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi cada como con contra cual cuando
de del desde donde durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estan
estas este esto estos fue ha han hay he hemos hasta la las le les lo los me mi mis mas muy nada ni
no nos o otra otras otro otros para pero poco por porque que quien se sea ser si sin sobre son su
sus tambien te ti todo todos tu tus un una unas uno unos usted ustedes y ya yo
http https www com mx net org html php
""".split())


@dataclass(frozen=True)
class Resultado:
    etiqueta: str            # "legitimo" | "sospechoso" | "phishing", derivada de ``nivel``
    nivel: Nivel             # nivel final, después de las reglas
    probabilidad: float      # salida cruda del modelo, antes de las reglas
    razones: tuple[str, ...]
    reglas: tuple[str, ...]  # reglas activadas, p. ej. ("dmarc=fail",); útil para registrar metadatos


@dataclass(frozen=True)
class ModeloPhishing:
    pipeline: Pipeline
    coef_palabras: np.ndarray
    terminos: np.ndarray
    columnas_palabras: slice
    patron_token: re.Pattern


def cargar_modelo(ruta: Path | str = RUTA_MODELO_PREDETERMINADA) -> ModeloPhishing:
    """Carga el modelo y lo calienta. Falla con un error claro si falta o no es compatible."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró el modelo de phishing en {ruta}; genéralo con `python ml/train.py`.")
    with warnings.catch_warnings():
        # Un pickle de otra versión de scikit-learn puede predecir mal sin avisar; mejor no arrancar.
        warnings.simplefilter("error", InconsistentVersionWarning)
        try:
            pipeline = joblib.load(ruta)
        except InconsistentVersionWarning as e:
            raise RuntimeError(f"El modelo en {ruta} se entrenó con scikit-learn {e.original_sklearn_version}, "
                               f"pero está instalada la {e.current_sklearn_version}. Instala esa versión o "
                               "vuelve a entrenar.") from e

    ct = pipeline.named_steps["caracteristicas"]
    columnas = ct.output_indices_["palabras"]
    vectorizador = ct.named_transformers_["palabras"]
    modelo = ModeloPhishing(
        pipeline=pipeline,
        coef_palabras=pipeline.named_steps["clasificador"].coef_.ravel()[columnas],
        terminos=vectorizador.get_feature_names_out(),
        columnas_palabras=columnas,
        patron_token=re.compile(vectorizador.token_pattern),
    )
    analizar(modelo, "Prueba", "Texto de prueba para calentar el modelo.")
    return modelo


def nivel_por_probabilidad(p: float) -> Nivel:
    if p <= BAJO_MAX:
        return Nivel.BAJO
    return Nivel.MEDIO if p <= ALTO_MIN else Nivel.ALTO


def normalizar_auth(auth_results: Mapping | None) -> dict[str, ResultadoAuth]:
    """Campos ausentes -> unknown. Campos o valores inválidos -> ValueError."""
    auth_results = dict(auth_results or {})
    desconocidos = set(auth_results) - set(CAMPOS_AUTH)
    if desconocidos:
        raise ValueError(f"campos de auth_results no válidos: {sorted(desconocidos)}")
    return {c: ResultadoAuth(auth_results.get(c) or ResultadoAuth.UNKNOWN) for c in CAMPOS_AUTH}


def aplicar_reglas(probabilidad: float, auth: Mapping[str, ResultadoAuth]) -> tuple[Nivel, list[Regla]]:
    activadas = [r for r in REGLAS if auth.get(r.campo) == r.valor]
    p = min(1.0, probabilidad + sum(r.sumar_probabilidad for r in activadas))
    indice = _ORDEN_NIVELES.index(nivel_por_probabilidad(p)) + max((r.subir_niveles for r in activadas), default=0)
    return _ORDEN_NIVELES[min(indice, len(_ORDEN_NIVELES) - 1)], activadas


def analizar(modelo: ModeloPhishing, subject: str, body: str, urls: Iterable | None = None,
             auth_results: Mapping | None = None) -> Resultado:
    auth = normalizar_auth(auth_results)
    df = pd.DataFrame([{"subject": subject or "", "body": body or "", "urls": list(urls or [])}])
    pasos = modelo.pipeline.named_steps
    preprocesado = pasos["preproceso"].transform(df)
    X = pasos["caracteristicas"].transform(preprocesado)
    probabilidad = float(pasos["clasificador"].predict_proba(X)[0, 1])

    nivel, activadas = aplicar_reglas(probabilidad, auth)
    razones = [r.razon for r in activadas]
    if nivel_por_probabilidad(probabilidad) != Nivel.BAJO:
        razones.insert(0, _razon_terminos(modelo, X, preprocesado["texto"].iloc[0]))
    elif not razones:
        razones.append("No se encontraron señales claras de phishing.")
    return Resultado(
        etiqueta=_ETIQUETA_POR_NIVEL[nivel],
        nivel=nivel,
        probabilidad=round(probabilidad, 4),
        razones=tuple(razones),
        reglas=tuple(f"{r.campo}={r.valor.value}" for r in activadas),
    )


def _razon_terminos(modelo: ModeloPhishing, X, texto: str) -> str:
    """Los n-gramas con mayor aporte (coef × tfidf) hacia phishing, escritos como en el correo."""
    fila = X[:, modelo.columnas_palabras].tocsr()
    aportes = fila.data * modelo.coef_palabras[fila.indices]
    formas = _formas_originales(texto, modelo.patron_token)
    elegidos, vistos = [], set()
    for i in np.argsort(-aportes):
        if aportes[i] <= 0 or len(elegidos) == MAX_TERMINOS_RAZON:
            break
        tokens = modelo.terminos[fila.indices[i]].split() # type: ignore
        utiles = {t for t in tokens if t not in _PALABRAS_VACIAS and not any(c.isdigit() for c in t)}
        if not utiles or utiles & vistos:
            continue
        vistos |= utiles
        termino = " ".join(tokens)
        elegidos.append(f"«{formas.get(termino, termino)}»")
    if not elegidos:
        return "El texto se parece a correos de phishing conocidos."
    lista = elegidos[0] if len(elegidos) == 1 else ", ".join(elegidos[:-1]) + " y " + elegidos[-1]
    return f"El texto se parece a correos de phishing conocidos; por ejemplo, usa {lista}."


def _formas_originales(texto: str, patron_token: re.Pattern) -> dict[str, str]:
    """n-grama normalizado (sin acentos, dígitos enmascarados) -> cómo aparece en el correo."""
    tokens = []
    for original in patron_token.findall(texto.lower()):
        normalizado = texto_vectorizador(original)
        if patron_token.fullmatch(normalizado):
            tokens.append((normalizado, original))
    formas: dict[str, str] = {}
    for (n1, o1), (n2, o2) in zip(tokens, tokens[1:] + [("", "")]):
        formas.setdefault(n1, o1)
        if n2:
            formas.setdefault(f"{n1} {n2}", f"{o1} {o2}")
    return formas
