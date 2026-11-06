# Clasificador de phishing (español)

N-gramas TF-IDF de palabras (1–2) y de caracteres (3–5) → `LogisticRegression(class_weight="balanced", C=3)`.
Entrenado solo con correo en español.

## Datos

Coloca los CSV en `data/` en la raíz del repositorio (o pasa `--raw-dir` a `prepare.py`).

| Archivo | Origen | Uso |
|---|---|---|
| `Spaphish dataset - DiB.csv` | SpaPhish (Universidad Iberoamericana, *Data in Brief* 2026; [Mendeley Data](https://data.mendeley.com/datasets/hz2d6gz7pc)). Bandejas reales 2014–2025, anotado por tres personas | ambas clases (`subject`, `body`, `Label`) |
| `SpearPhishMX_dataset_publico.csv` | SpearPhishMX (separado por `;`) | **solo phishing**, ver abajo |

**Las etiquetas de SpearPhishMX no significan phishing vs. legítimo**, así que la mayor parte del archivo se descarta:

- `etiqueta = 0` incluye ~290 correos de *phishing* de SpaPhish (estafas de paquetería y de cuentas) con un
  saludo `Hola <nombre>,` antepuesto. **Se descartan todas las filas con etiqueta 0.**
- `etiqueta = 1`, `id_original` 1–1707: señuelos sintéticos de spear-phishing más algo de phishing real. **Se conservan.**
- `etiqueta = 1`, `id_original` ≥ 1708: un bloque de correo real de bandeja, casi todo legítimo
  (boletines, revisiones de tesis, avisos institucionales). **Se descarta.**
- Las filas conservadas que reutilizan un correo de SpaPhish se descartan, porque la etiqueta de SpaPhish es más confiable.

El resultado tiene 3,021 filas. El correo legítimo (664 filas) proviene solo de SpaPhish.

## Ejecución

```sh
python ml/train.py      # genera ml/data/clean.parquet si falta (o con --rebuild-data), selecciona y entrena
python ml/evaluate.py   # escribe ml/artifacts/metrics.json
```

`python ml/prepare.py` regenera `ml/data/clean.parquet` por sí solo. El entrenamiento tarda unos 2 min.

Salidas en `ml/artifacts/`: `model.joblib`, `metrics.json`, `top_terms.json`, `train_report.json`.

## Particiones y controles contra fugas

- **Prueba:** un 20% estratificado (por fuente × etiqueta), nunca usado para entrenar ni para seleccionar.
- **Selección del modelo:** CV estratificada de 5 pliegues sobre la partición de entrenamiento, evaluada
  **solo en las filas de SpaPhish**. Evaluar en SpearPhishMX, que es todo phishing, premiaría "parecerse a SpearPhishMX".
- La deduplicación se hace sobre el texto normalizado de ambas fuentes, antes de particionar.
- Atajos eliminados (`features.py`, que corre dentro del pipeline, así que también se aplica al servir):
  - Los seudónimos de anonimización de SpaPhish: `Pablito`, `Missxtranger`, `Pancracio`, `Miguelina` y
    `Ezequiela` aparecen solo en phishing, y `MyOwn`/`myownp.mx` solo en correo legítimo.
  - Los marcadores de SpearPhishMX (`<TELEFONO>`, `<EMAIL>`, `<RFC>`) y los escapes `_x000D_`.
  - Las URLs desactivadas se reactivan: `hxxp://malo[.]com` → `http://malo.com`.
- Los saludos iniciales (`Hola …,` / `Estimada/o …,`) se quitan de los cuerpos de entrenamiento. SpearPhishMX
  los inyecta y su redacción seguía a su etiqueta.
- Los dígitos se enmascaran antes de vectorizar.

## Resultados actuales (ver `metrics.json`)

| Partición de prueba | Precisión | Exhaustividad | F1 | ROC-AUC |
|---|---|---|---|---|
| **Solo SpaPhish (principal, ambas clases)** | 1.000 | 0.925 | **0.961** | 0.997 |
| Todas las fuentes | 1.000 | 0.975 | 0.987 | 0.999 |

El objetivo del MVP (F1 ≥ 0.90) se cumple en la prueba de SpaPhish. En esa prueba, 0 de 133 correos legítimos se marcan.
Se escapan 11 de 146 correos de phishing: 7 puntúan menos de 0.4 y 4 entre 0.4 y 0.5. Con un corte en 0.4, el F1 es 0.972
(P 0.993 / R 0.952). La partición de prueba es pequeña (279 filas de SpaPhish), así que hay que esperar unos puntos de variación.

## Integración con la API (Fase 3)

`ml/inferencia.py` es lo que usa `routers/phishing.py`. La app necesita el paquete `ml` importable
con ese nombre, porque el pickle hace referencia a `ml.features`. Basta con `ml/__init__.py`,
`ml/features.py`, `ml/inferencia.py` y `ml/artifacts/model.joblib`. Fija `scikit-learn==1.9.1` en la app.

```python
from ml.inferencia import cargar_modelo, analizar

modelo = cargar_modelo()   # en lifespan; lanza FileNotFoundError / RuntimeError si falta o no es compatible
r = analizar(modelo, subject, body, urls=urls, auth_results={"spf": "pass", "dkim": "fail", "dmarc": "fail"})
r.etiqueta, r.nivel, r.probabilidad, r.razones, r.reglas
# ("sospechoso", Nivel.MEDIO, 0.2449, ("El remitente podría estar suplantado: …", …), ("dmarc=fail", "dkim=fail"))
```

- **Resultado:** `nivel` (`bajo`/`medio`/`alto`) es el nivel final, después de las reglas. `etiqueta` se deriva de él
  (`legitimo`/`sospechoso`/`phishing`). `probabilidad` es la salida cruda del modelo. `reglas` sirve para
  registrar metadatos. El resultado no contiene el cuerpo.
- **Para el modelo de Pydantic:** `MAX_BYTES_CUERPO` (100 KB), `MAX_CARACTERES_ASUNTO` (500), `MAX_URLS` (50),
  `MAX_CARACTERES_URL`, y el enum `ResultadoAuth` (`pass`/`fail`/`none`/`unknown`). Usarlo como tipo de los
  campos de `auth_results` da el 422 automáticamente. La extensión debe mapear los valores crudos a esos cuatro:

  | Valor crudo (sin distinguir mayúsculas) | Se envía como |
  |---|---|
  | `pass` | `pass` |
  | `fail`, `hardfail` | `fail` |
  | `neutral`, `none`, `bestguesspass` | `none` |
  | `softfail`, `temperror`, `permerror`, `policy`, ausente o desconocido | `unknown` |

  Solo `fail` cambia el resultado. `softfail` no cuenta como `fail` porque `~all` es muy común y el reenvío lo provoca,
  y `spf=fail` sube un nivel entero; la suplantación la detecta DMARC si el dominio publica la política. Hay que leer solo la cabecera
  `Authentication-Results` que añadió el servidor receptor, porque el remitente puede falsificar las inferiores.
  Si hay varios resultados de DKIM, gana cualquier `pass`.
- **Capa de reglas (`REGLAS`):**

  | Señal | Efecto | Razón para el usuario |
  |---|---|---|
  | `dmarc=fail` | sube 1 nivel | el remitente podría estar suplantado (DMARC) |
  | `spf=fail` | sube 1 nivel | el servidor no está autorizado por el dominio (SPF) |
  | `dkim=fail` | +0.10 a la probabilidad | la firma digital no es válida (DKIM) |
  | `pass` / `none` / `unknown` | nada | — |

  Si fallan DMARC y SPF juntos, el nivel sube un solo escalón (es la misma evidencia) y se dan ambas razones.
  `pass` nunca baja el riesgo, porque los atacantes pasan SPF/DKIM/DMARC con sus propios dominios.
- **Razones del contenido:** si el modelo por sí solo da `medio` o `alto`, la primera razón cita los 3 n-gramas que
  más aportan (coef × tfidf), escritos como aparecen en el correo, sin contar palabras vacías ni fragmentos de URL.
- **Rendimiento:** carga en ~0.15 s y ocupa ~10 MB en memoria por worker. Cada análisis tarda ~3 ms con un correo
  normal y ~30 ms con uno de 100 KB. Es CPU-bound: llámalo desde un endpoint `def`, no `async def`.
- **Pruebas:** `python -m pytest ml/tests`. Los casos de 413/422 y del límite de peticiones van en la app.

Pasa texto crudo: el pipeline hace su propia limpieza.

## Limitaciones conocidas

- **Solo español**, y sobre todo correo académico e institucional de México. Los ejemplos legítimos vienen de unas
  pocas bandejas de SpaPhish (universidades, centros de investigación), así que el correo legítimo corporativo o comercial
  está poco representado.
- El 78% de las filas de phishing son plantillas sintéticas de SpearPhishMX (`… Consultar en: http://… Plazo: dd/mm/aaaa`).
  Algunas palabras de esas plantillas (`plazo`, `en http`) pesan por eso.
- `http` se inclina a phishing y `https` a legítimo. En parte es real y en parte se debe a que todos los señuelos de
  SpearPhishMX usan `hxxp`.
- No hay una validación con un corpus independiente: solo SpaPhish tiene correo legítimo, así que la partición de prueba
  comparte su distribución.
- `auth_results`, texto del enlace ≠ href y reply-to ≠ remitente no están en ninguno de los dos datasets, así que
  pertenecen a la capa de reglas.
