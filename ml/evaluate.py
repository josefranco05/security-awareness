"""Evalúa el modelo entrenado en la partición de prueba, en total y solo en Spaphish.

Spaphish es la única fuente con correo legítimo, así que sus filas de prueba dan la
cifra principal; la cifra total está inflada por SpearPhishMX, que es solo phishing.

Escribe ml/artifacts/metrics.json. Uso: python ml/evaluate.py
"""
from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

DIR_ML = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR_ML.parent))
from ml import prepare  # noqa: E402
from ml.inferencia import ALTO_MIN, BAJO_MAX  # noqa: E402  (los mismos umbrales que usa la API)
from ml.train import FUENTE_SELECCION  # noqa: E402

ARTEFACTOS = DIR_ML / "artifacts"
OBJETIVO_F1_MVP = 0.90


def puntuar(y, p, umbral: float = 0.5) -> dict:
    pred = p >= umbral
    vn, fp, fn, vp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    salida = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "confusion_matrix": {"tn": int(vn), "fp": int(fp), "fn": int(fn), "tp": int(vp)},
    }
    if y.nunique() == 2:
        salida["roc_auc"] = round(float(roc_auc_score(y, p)), 4)
    return salida


def evaluar_particion(modelo, df: pd.DataFrame) -> dict:
    y, p = df["label"], modelo.predict_proba(df)[:, 1]
    salida = puntuar(y, p)
    salida["at_thresholds"] = {
        f"{u:g}": {k: v for k, v in puntuar(y, p, u).items() if k in ("precision", "recall", "f1")}
        for u in (BAJO_MAX, ALTO_MIN)
    }
    niveles = pd.cut(p, [-0.01, BAJO_MAX, ALTO_MIN, 1.0], labels=["low", "medium", "high"])
    salida["levels_by_label"] = {
        ("phishing" if etiqueta else "legitimate"): pd.Series(niveles[y.to_numpy() == etiqueta]).value_counts().to_dict()
        for etiqueta in (0, 1)
    }
    if df["source"].nunique() > 1:
        salida["by_source"] = {f: puntuar(g["label"], p[(df["source"] == f).to_numpy()]) for f, g in df.groupby("source")}
    return salida


def main() -> None:
    modelo = joblib.load(ARTEFACTOS / "model.joblib")
    df = pd.read_parquet(prepare.SALIDA_PREDETERMINADA)
    reporte = json.loads((ARTEFACTOS / "train_report.json").read_text())

    df_prueba = df[df["split"] == "test"]
    prueba = evaluar_particion(modelo, df_prueba)
    principal = evaluar_particion(modelo, df_prueba[df_prueba["source"] == FUENTE_SELECCION])

    metricas = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "datasets": {f: {"rows": int(len(g)), "splits": g["split"].value_counts().to_dict()}
                     for f, g in df.groupby("source")},
        "model": reporte,
        "thresholds": {"decision": 0.5, "low_max": BAJO_MAX, "high_min": ALTO_MIN},
        "test_spaphish": {"source": FUENTE_SELECCION, **principal},
        "test_all": prueba,
        "mvp_target": {"metric": "test_spaphish.f1", "target": OBJETIVO_F1_MVP,
                       "value": principal["f1"], "met": principal["f1"] >= OBJETIVO_F1_MVP},
    }
    (ARTEFACTOS / "metrics.json").write_text(json.dumps(metricas, indent=2))

    for nombre, m in ((f"prueba ({FUENTE_SELECCION})", principal), ("prueba (todas las fuentes)", prueba)):
        print(f"{nombre}: P={m['precision']} R={m['recall']} F1={m['f1']} AUC={m.get('roc_auc')} CM={m['confusion_matrix']}")
    cumplido = "cumplido" if metricas["mvp_target"]["met"] else "NO cumplido"
    print(f"Objetivo MVP F1>={OBJETIVO_F1_MVP} en prueba de {FUENTE_SELECCION}: {cumplido}")
    print(f"escrito {ARTEFACTOS / 'metrics.json'}")


if __name__ == "__main__":
    main()
