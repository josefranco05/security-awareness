"""Limpieza de correos y extracción de características, compartidas por entrenamiento y servicio.

El pipeline ajustado recibe un DataFrame con las columnas ``subject`` y ``body``
(y opcionalmente ``urls``: una lista de dicts ``{text, href}``, según el contrato
de la API) y hace toda la limpieza por sí mismo, así que se le debe pasar texto crudo.
"""
from __future__ import annotations

import html
import re

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import (
    HashingVectorizer,
    TfidfTransformer,
    TfidfVectorizer,
    strip_accents_unicode,
)
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MAX_CARACTERES_CUERPO = 5000
_MAX_CARACTERES_CRUDOS = 100_000  # acota el trabajo de las regex en entradas patológicas

# HTML -> texto
_INDICIO_HTML = re.compile(r"<\s*/?\s*(?:html|body|div|p|br|a|table|td|span|font)\b", re.I)
_SCRIPT_ESTILO = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_ETIQUETA_BLOQUE = re.compile(r"<\s*/?\s*(?:br|p|div|tr|li|h[1-6])\b[^>]*>", re.I)
_ETIQUETA = re.compile(r"<[^>]{0,2000}>")

# Deshace la tokenización estilo "palabra , palabra" (común en corpus pretokenizados)
# para que el espaciado no identifique la fuente. Solo se toca [ \t] para conservar las líneas.
_RACHA_PUNTUACION = re.compile(r"(?:[-=_*~#][ \t]*){3,}")
_ESPACIO_ANTES = re.compile(r"[ \t]+([.,;:!?%)\]])")
_ESPACIO_DESPUES = re.compile(r"([(\[$])[ \t]+")
_BARRA_ARROBA = re.compile(r"[ \t]*([/@])[ \t]*")
_GUION = re.compile(r"(?<=\w)[ \t]+-[ \t]+(?=\w)")
_CONTRACCION = re.compile(r"(\w)[ \t]*'[ \t]*(s|t|ll|re|ve|d|m)\b", re.I)
_PUNTO_DOMINIO = re.compile(r"(\w)\.[ \t]+(com|net|org|edu|gov|mil|info|biz|co|uk|de|html?|php|aspx?)\b", re.I)
_PUNTO_WWW = re.compile(r"\bwww\.[ \t]+", re.I)

# Restos de encabezados y reenvíos. Las líneas de encabezado deben ser cortas para no
# borrar un cuerpo que quedó aplanado en una sola línea.
_LINEA_ENCABEZADO = re.compile(
    r"^[ \t]*(?:from|to|cc|bcc|date|sent|subject|reply-to|return-path|message-id|"
    r"content-[a-z-]+|mime-version|x-[a-z0-9-]+)[ \t]*:[^\n]{0,200}$",
    re.I | re.M,
)
_ENCABEZADO_EN_LINEA = re.compile(
    r"\b(?:message-id|content-type|content-length|content-transfer-encoding|mime-version)\s*:\s*\S+", re.I
)
_REENVIO = re.compile(
    r"-*[ \t]*(?:original message|begin forwarded message)[ \t]*-*"
    r"|forwarded by\b[^\n]{0,120}?\d{1,2}:[ \t]?\d{2}[ \t]*[ap]m",
    re.I,
)
_FIRMA = re.compile(r"\n-- ?\n.*", re.S)  # delimitador de firma RFC 3676
# Tokens que identifican un corpus y no el phishing: Spaphish reemplaza los nombres de
# destinatarios por seudónimos fijos (solo en phishing) y la institución por "MyOwn"
# (solo en legítimos).
_ARTEFACTOS_CORPUS = re.compile(r"\b(?:pablito|missxtranger|pancracio|miguelina|ezequiela|myown\w*)\b", re.I)
# Marcadores de anonimización de SpearPhishMX y escapes de retorno de carro de Excel.
_MARCADOR = re.compile(r"<(?:TELEFONO|EMAIL|RFC)>|_x000D_", re.I)
# URLs desactivadas (hxxp://malo[.]com) como se publican en datasets de inteligencia de amenazas.
_ESQUEMA_DESACTIVADO = re.compile(r"\bhxxp(s?)(?=:|\[:\])", re.I)
_PUNTO_DESACTIVADO = re.compile(r"\[+\.\]+")
_ESPACIOS = re.compile(r"\s+")
_DIGITOS = re.compile(r"\d+")


def reactivar_urls(texto: str) -> str:
    texto = _ESQUEMA_DESACTIVADO.sub(r"http\1", texto).replace("[:]", ":")
    return _PUNTO_DESACTIVADO.sub(".", texto)


def quitar_html(texto: str) -> str:
    texto = _SCRIPT_ESTILO.sub(" ", texto)
    texto = _ETIQUETA_BLOQUE.sub("\n", texto)
    return _ETIQUETA.sub(" ", texto)


def _normalizar_espaciado(texto: str) -> str:
    texto = _RACHA_PUNTUACION.sub(" ", texto)
    texto = _ESPACIO_ANTES.sub(r"\1", texto)
    texto = _ESPACIO_DESPUES.sub(r"\1", texto)
    texto = _BARRA_ARROBA.sub(r"\1", texto)
    texto = _GUION.sub("-", texto)
    texto = _CONTRACCION.sub(r"\1'\2", texto)
    texto = _PUNTO_DOMINIO.sub(r"\1.\2", texto)
    return _PUNTO_WWW.sub("www.", texto)


def limpiar_cuerpo(texto) -> str:
    if not isinstance(texto, str):
        return ""
    texto = texto[:_MAX_CARACTERES_CRUDOS].replace("\r\n", "\n")
    texto = reactivar_urls(_MARCADOR.sub(" ", texto))
    if _INDICIO_HTML.search(texto):
        texto = quitar_html(texto)
    texto = html.unescape(texto)
    texto = _FIRMA.sub("", texto)
    texto = _normalizar_espaciado(texto)
    texto = _LINEA_ENCABEZADO.sub(" ", texto)
    texto = _ENCABEZADO_EN_LINEA.sub(" ", texto)
    texto = _REENVIO.sub(" ", texto)
    texto = _ARTEFACTOS_CORPUS.sub(" ", texto)
    return _ESPACIOS.sub(" ", texto).strip()[:MAX_CARACTERES_CUERPO]


def limpiar_asunto(texto) -> str:
    if not isinstance(texto, str):
        return ""
    texto = reactivar_urls(_MARCADOR.sub(" ", html.unescape(texto[:1000])))
    texto = _ARTEFACTOS_CORPUS.sub(" ", _normalizar_espaciado(texto))
    return _ESPACIOS.sub(" ", texto).strip()


def texto_vectorizador(texto: str) -> str:
    """Preprocesador del vectorizador: minúsculas, sin acentos, rachas de dígitos colapsadas.

    Años, fechas y prefijos telefónicos codifican sobre todo *cuándo/dónde* se
    recolectó un corpus y no el phishing, así que los números se enmascaran.
    """
    return _DIGITOS.sub("0", strip_accents_unicode(texto.lower()))


def _enlaces(urls) -> list[str]:
    if not isinstance(urls, (list, tuple)):
        return []
    return [reactivar_urls(u.get("href", "") if isinstance(u, dict) else str(u)) for u in urls]


class PreprocesadorCorreo(BaseEstimator, TransformerMixin):
    """``subject``/``body``/``urls`` crudos -> ``texto`` limpio más ``enlaces``."""

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        X = pd.DataFrame(X)
        asunto = X["subject"].map(limpiar_asunto) if "subject" in X else pd.Series("", index=X.index)
        cuerpo = X["body"].map(limpiar_cuerpo)
        enlaces = X["urls"].map(_enlaces) if "urls" in X else pd.Series([[]] * len(X), index=X.index)
        return pd.DataFrame({"texto": asunto + "\n" + cuerpo, "enlaces": enlaces}, index=X.index)


# En español y sin acentos: se comparan contra el texto en minúsculas y sin acentos.
TERMINOS_URGENCIA = (
    "urgente", "inmediatamente", "de inmediato", "verifique", "verifica tu", "confirme", "confirma tu",
    "suspendid", "bloquead", "actividad inusual", "alerta de seguridad", "actualice", "actualiza tu",
    "haga clic", "haz clic", "da clic", "iniciar sesion", "contrasena", "24 horas", "48 horas",
    "tiempo limitado", "caduca", "expira",
)
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
_URL_IP = re.compile(r"^(?:https?://)?\d{1,3}(?:\.\d{1,3}){3}(?:[:/]|$)", re.I)


class CaracteristicasManuales(BaseEstimator, TransformerMixin):
    """Pocas características numéricas calculables del texto del cuerpo (y los enlaces de la petición).

    La discrepancia texto del enlace/href y reply-to/remitente no está aquí: los
    corpus de entrenamiento no traen esos datos, así que pertenecen a la capa de reglas.
    """

    nombres_caracteristicas = ("log_conteo_urls", "tiene_url_ip", "proporcion_http", "log_urgencias")

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        filas = []
        for texto, enlaces in zip(X["texto"], X["enlaces"]):
            urls = list(dict.fromkeys(_URL.findall(texto) + [e for e in enlaces if e]))
            n = len(urls)
            http = sum(u.lower().startswith("http://") for u in urls)
            minusculas = strip_accents_unicode(texto.lower())
            filas.append([
                np.log1p(n),
                float(any(_URL_IP.match(u) for u in urls)),
                http / n if n else 0.0,
                np.log1p(sum(minusculas.count(t) for t in TERMINOS_URGENCIA)),
            ])
        return np.asarray(filas, dtype=float).reshape(-1, len(self.nombres_caracteristicas))

    def get_feature_names_out(self, input_features=None):
        return np.asarray(self.nombres_caracteristicas, dtype=object)


def construir_pipeline(caracteres: bool = False, manuales: bool = False, C: float = 1.0) -> Pipeline:
    transformadores = [(
        "palabras",
        TfidfVectorizer(ngram_range=(1, 2), max_features=50_000, sublinear_tf=True,
                        min_df=2, preprocessor=texto_vectorizador, dtype=np.float32),
        "texto",
    )]
    if caracteres:
        # El hashing mantiene el vocabulario de 3-5 caracteres fuera de memoria y fuera de model.joblib.
        transformadores.append(("caracteres", Pipeline([
            ("hash", HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=2**20,
                                       preprocessor=texto_vectorizador, alternate_sign=False,
                                       norm=None, dtype=np.float32)), # type: ignore
            ("tfidf", TfidfTransformer(sublinear_tf=True)),
        ]), "texto")) # type: ignore
    if manuales:
        transformadores.append(("manuales", Pipeline([("extraer", CaracteristicasManuales()),
                                                      ("escalar", StandardScaler())]),
                                ["texto", "enlaces"])) # type: ignore
    return Pipeline([
        ("preproceso", PreprocesadorCorreo()),
        ("caracteristicas", ColumnTransformer(transformadores)),
        ("clasificador", LogisticRegression(class_weight="balanced", C=C, max_iter=2000)),
    ])
