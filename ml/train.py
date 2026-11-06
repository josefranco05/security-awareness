"""Selecciona un conjunto de características, entrena el modelo final y lo exporta.

La selección del modelo usa predicciones fuera de pliegue de un K-fold estratificado
sobre la partición de entrenamiento, evaluadas solo en las filas de FUENTE_SELECCION
(la única fuente con ambas clases), así que la partición de prueba no se mira hasta evaluate.py.

Uso: python ml/train.py [--rebuild-data]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

DIR_ML = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR_ML.parent))
from ml import prepare  # noqa: E402
from ml.features import CaracteristicasManuales, construir_pipeline  # noqa: E402

ARTEFACTOS = DIR_ML / "artifacts"
# SpearPhishMX es solo phishing; evaluar en él premiaría "parecerse a SpearPhishMX".
FUENTE_SELECCION = "Spaphish"
PLIEGUES_CV = 5
TOP_N_TERMINOS = 40

# Primero la línea base; los componentes extra se conservan solo si la superan en validación.
CANDIDATOS = {
    "palabras": dict(caracteres=False, manuales=False),
    "palabras+caracteres": dict(caracteres=True, manuales=False),
    "palabras+manuales": dict(caracteres=False, manuales=True),
    "palabras+caracteres+manuales": dict(caracteres=True, manuales=True),
}
GANANCIA_MIN = 0.005  # F1 que un modelo más grande debe sumar para preferirse sobre uno más chico
# Fuerzas de regularización probadas para el conjunto elegido (los candidatos usan C=1).
REJILLA_C = (0.3, 3.0)


def cargar_datos(reconstruir: bool) -> pd.DataFrame:
    if reconstruir or not prepare.SALIDA_PREDETERMINADA.exists():
        return prepare.construir()
    return pd.read_parquet(prepare.SALIDA_PREDETERMINADA)


def _validar(params: dict, entrenamiento: pd.DataFrame) -> dict:
    t0 = time.time()
    p = np.zeros(len(entrenamiento))
    pliegues = StratifiedKFold(PLIEGUES_CV, shuffle=True, random_state=prepare.SEMILLA)
    estratos = entrenamiento["source"] + "_" + entrenamiento["label"].astype(str)
    for idx_ajuste, idx_val in pliegues.split(entrenamiento, estratos):
        ajuste = entrenamiento.iloc[idx_ajuste]
        modelo = construir_pipeline(**params).fit(ajuste, ajuste["label"])
        p[idx_val] = modelo.predict_proba(entrenamiento.iloc[idx_val])[:, 1]
    sel = (entrenamiento["source"] == FUENTE_SELECCION).to_numpy()
    y = entrenamiento["label"].to_numpy()[sel]
    return {
        "f1": round(float(f1_score(y, p[sel] >= 0.5)), 4),
        "roc_auc": round(float(roc_auc_score(y, p[sel])), 4),
        "f1_all_sources": round(float(f1_score(entrenamiento["label"], p >= 0.5)), 4),
        "fit_seconds": round(time.time() - t0, 1),
    }


def seleccionar(entrenamiento: pd.DataFrame) -> tuple[dict, dict]:
    resultados = {}
    for nombre, params in CANDIDATOS.items():
        resultados[nombre] = _validar(params, entrenamiento)
        print(f"  {nombre:<30} {resultados[nombre]}")
    # Recorre los candidatos del más chico al más grande; uno mayor gana solo por un margen claro.
    mejor = "palabras"
    for nombre in CANDIDATOS:
        if resultados[nombre]["f1"] >= resultados[mejor]["f1"] + GANANCIA_MIN:
            mejor = nombre

    elegido = {"features": mejor, **CANDIDATOS[mejor], "C": 1.0}
    mejor_f1 = resultados[mejor]["f1"]
    for C in REJILLA_C:
        nombre = f"{mejor} C={C:g}"
        resultados[nombre] = _validar({**CANDIDATOS[mejor], "C": C}, entrenamiento)
        print(f"  {nombre:<30} {resultados[nombre]}")
        if resultados[nombre]["f1"] >= mejor_f1 + GANANCIA_MIN:
            elegido["C"], mejor_f1 = C, resultados[nombre]["f1"]
    return elegido, resultados


def terminos_principales(modelo) -> dict:
    coef = modelo.named_steps["clasificador"].coef_.ravel()
    ct = modelo.named_steps["caracteristicas"]
    palabras = coef[ct.output_indices_["palabras"]]
    nombres = ct.named_transformers_["palabras"].get_feature_names_out()
    orden = np.argsort(palabras)
    salida = {
        "phishing": [[nombres[i], round(float(palabras[i]), 4)] for i in orden[::-1][:TOP_N_TERMINOS]],
        "legitimate": [[nombres[i], round(float(palabras[i]), 4)] for i in orden[:TOP_N_TERMINOS]],
    }
    if "manuales" in ct.output_indices_:
        manuales = coef[ct.output_indices_["manuales"]]
        salida["hand_features"] = dict(zip(CaracteristicasManuales.nombres_caracteristicas,
                                           (round(float(c), 4) for c in manuales)))
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild-data", action="store_true", help="vuelve a ejecutar prepare.py primero")
    args = ap.parse_args()

    df = cargar_datos(args.rebuild_data)
    entrenamiento = df[df["split"] == "train"]
    print(f"seleccionando por CV de {PLIEGUES_CV} pliegues, evaluado en {FUENTE_SELECCION} "
          f"({(entrenamiento['source'] == FUENTE_SELECCION).sum()} de {len(entrenamiento)} filas)")
    elegido, seleccion = seleccionar(entrenamiento)
    print(f"elegido: {elegido}; ajustando sobre toda la partición de entrenamiento ({len(entrenamiento)} filas)")

    params = {k: v for k, v in elegido.items() if k != "features"}
    modelo = construir_pipeline(**params).fit(entrenamiento, entrenamiento["label"])
    # stop_words_ guarda cada n-grama podado; solo sirve para inspección e infla el archivo.
    vectorizador = modelo.named_steps["caracteristicas"].named_transformers_["palabras"]
    if hasattr(vectorizador, "stop_words_"):
        delattr(vectorizador, "stop_words_")

    ARTEFACTOS.mkdir(exist_ok=True)
    joblib.dump(modelo, ARTEFACTOS / "model.joblib", compress=3)
    (ARTEFACTOS / "top_terms.json").write_text(json.dumps(terminos_principales(modelo), indent=2))
    (ARTEFACTOS / "train_report.json").write_text(json.dumps({
        "chosen": elegido,
        "selection_method": f"CV estratificada de {PLIEGUES_CV} pliegues sobre train, evaluada en {FUENTE_SELECCION}",
        "selection": seleccion,
        "train_rows": int(len(entrenamiento)),
        "train_sources": sorted(entrenamiento["source"].unique()),
    }, indent=2))
    print(f"escritos {ARTEFACTOS / 'model.joblib'}, top_terms.json, train_report.json")


if __name__ == "__main__":
    main()
