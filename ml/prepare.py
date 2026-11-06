"""Construye ml/data/clean.parquet a partir de los CSV crudos en español.

Uso: python ml/prepare.py [--raw-dir data] [--out ml/data/clean.parquet]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

DIR_ML = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR_ML.parent))
from ml.features import limpiar_asunto, limpiar_cuerpo  # noqa: E402

DIR_CRUDOS_PREDETERMINADO = DIR_ML.parent / "data"
SALIDA_PREDETERMINADA = DIR_ML / "data" / "clean.parquet"

ARCHIVO_SPAPHISH = "Spaphish dataset - DiB.csv"
ARCHIVO_SPEARPHISHMX = "SpearPhishMX_dataset_publico.csv"
PROPORCION_PRUEBA = 0.2
SEMILLA = 42

_NO_PALABRA = re.compile(r"\W+")
# SpearPhishMX antepone una línea sintética "Hola <nombre>," / "Estimada/o <nombre>," cuya
# redacción sigue a su etiqueta. Los saludos iniciales se quitan de todas las fuentes para
# que su presencia no permita distinguirlas.
_SALUDO_INICIAL = re.compile(r"^\s*(?:hola|estimad[oa]s?(?:/o)?|estimad@s|atenci[oó]n)\b[^\n,:]{0,80}[,:]\s*", re.I)
# Las filas de etiqueta 1 de SpearPhishMX a partir de este id son un bloque de correo real de
# bandeja, casi todo legítimo (boletines, revisiones de tesis, avisos institucionales), así que se descartan.
_SPEARPHISHMX_CORREO_REAL_DESDE_ID = 1708
# Longitud del prefijo del cuerpo usada para detectar correos de Spaphish reutilizados en SpearPhishMX.
_CARACTERES_COINCIDENCIA, _MIN_CARACTERES_COINCIDENCIA = 120, 40


def _normalizar(texto: str) -> str:
    return _NO_PALABRA.sub(" ", texto.lower()).strip()


def cargar_spaphish(dir_crudos: Path) -> pd.DataFrame:
    df = pd.read_csv(dir_crudos / ARCHIVO_SPAPHISH, usecols=["subject", "body", "Label"],
                     dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.rename(columns={"Label": "label"})
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df["source"] = "Spaphish"
    return df


def cargar_spearphishmx(dir_crudos: Path, spaphish: pd.DataFrame) -> pd.DataFrame:
    """Solo filas de phishing.

    ``etiqueta`` significa spear-phishing dirigido vs. todo lo demás, no phishing vs.
    legítimo: la etiqueta 0 contiene cientos de correos de *phishing* de Spaphish y la
    etiqueta 1 un bloque de correo real mayormente legítimo, todos con un saludo antepuesto.
    Por eso solo se conservan las filas sintéticas/de phishing con etiqueta 1, menos las que
    reutilizan un correo de Spaphish (gana su etiqueta, anotada por tres personas).
    """
    df = pd.read_csv(dir_crudos / ARCHIVO_SPEARPHISHMX, sep=";",
                     usecols=["id_original", "etiqueta", "asunto", "cuerpo_sanitizado"],
                     dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.rename(columns={"asunto": "subject", "cuerpo_sanitizado": "body", "etiqueta": "label"})
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    n0 = len(df)
    df = df[(df["label"] == 1) & (pd.to_numeric(df["id_original"]) < _SPEARPHISHMX_CORREO_REAL_DESDE_ID)].copy()
    claves = {c for c in (_normalizar(b)[:_CARACTERES_COINCIDENCIA] for b in spaphish["body"])
              if len(c) > _MIN_CARACTERES_COINCIDENCIA}
    reutilizados = df["body"].map(lambda b: any(c in _normalizar(b) for c in claves))
    df = df[~reutilizados]
    df["source"] = "SpearPhishMX"
    print(f"SpearPhishMX: {n0} filas -> {len(df)} (etiqueta 1 con id < {_SPEARPHISHMX_CORREO_REAL_DESDE_ID}, "
          f"{int(reutilizados.sum())} correos reutilizados de Spaphish descartados)")
    return df.drop(columns="id_original")


def cargar_crudos(dir_crudos: Path) -> pd.DataFrame:
    for nombre in (ARCHIVO_SPAPHISH, ARCHIVO_SPEARPHISHMX):
        if not (dir_crudos / nombre).exists():
            raise FileNotFoundError(f"falta {dir_crudos / nombre}; ver ml/README.md para las instrucciones de descarga")
    spaphish = cargar_spaphish(dir_crudos)
    df = pd.concat([spaphish, cargar_spearphishmx(dir_crudos, spaphish)], ignore_index=True)
    df["body"] = df["body"].str.replace(_SALUDO_INICIAL, "", n=1, regex=True)
    return df


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    n0 = len(df)
    df = df[df["label"].isin([0, 1])].copy()
    df["label"] = df["label"].astype(int)
    df["subject"] = df["subject"].map(limpiar_asunto)
    df["body"] = df["body"].map(limpiar_cuerpo)
    df = df[df["body"].str.len() > 0]
    print(f"filas: {n0} crudas -> {len(df)} tras quitar etiquetas inválidas / cuerpos vacíos")

    # Deduplica sobre el texto normalizado de todas las fuentes, antes de particionar, para
    # que ninguna copia de un correo de entrenamiento caiga en la partición de prueba.
    clave = (df["subject"] + " " + df["body"]).map(lambda s: hashlib.sha1(_normalizar(s).encode()).hexdigest())
    en_conflicto = df["label"].groupby(clave).transform("nunique") > 1
    df = df[~en_conflicto]
    df = df[~clave[df.index].duplicated()]
    print(f"filas: {len(df)} tras deduplicar ({int(en_conflicto.sum())} filas con etiquetas en conflicto descartadas)")
    return df.reset_index(drop=True)


def asignar_particiones(df: pd.DataFrame) -> pd.DataFrame:
    df["split"] = "train"
    _, idx_prueba = train_test_split(df.index, test_size=PROPORCION_PRUEBA, random_state=SEMILLA,
                                     stratify=df["source"] + "_" + df["label"].astype(str))
    df.loc[idx_prueba, "split"] = "test"
    return df


def construir(dir_crudos: Path = DIR_CRUDOS_PREDETERMINADO, salida: Path = SALIDA_PREDETERMINADA) -> pd.DataFrame:
    df = asignar_particiones(limpiar(cargar_crudos(dir_crudos)))
    salida.parent.mkdir(parents=True, exist_ok=True)
    df[["subject", "body", "label", "source", "split"]].to_parquet(salida, index=False)
    print(f"escrito {salida}")
    print(df.pivot_table(index=["split", "source"], columns="label", values="body",
                         aggfunc="count", fill_value=0).rename(columns={0: "legitimo", 1: "phishing"}))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=DIR_CRUDOS_PREDETERMINADO)
    ap.add_argument("--out", type=Path, default=SALIDA_PREDETERMINADA)
    args = ap.parse_args()
    construir(args.raw_dir, args.out)
