# Interfaces entre las partes del proyecto

Este documento es el "contrato de trabajo" entre Brian (datos, API, web) y Oscar (geo, modelo). Cada
uno trabaja contra estas interfaces y no contra el código del otro. Hasta que exista el dato real,
`scripts/make_synthetic_dataset.py` produce I1, I2 e I3 con esta forma exacta:

```powershell
uv run python scripts/make_synthetic_dataset.py --out data/processed/sintetico --n 3000 --seed 7
```

Cambiar una interfaz requiere acuerdo de los dos y una línea en la sección "Historial" de abajo.

| ID | Archivo | Produce | Consume |
|---|---|---|---|
| I1 | `data/processed/<snapshot>/dataset.csv` | Brian (`just build-dataset`) | Oscar (entrenamiento) |
| I2 | `data/reference/gazetteer.csv` | Oscar (F6.1, F6.2) | Brian (normalizar barrios, F4.4) y la API |
| I3 | `data/reference/geo_features.csv` | Oscar (F6.3, F6.4) | Oscar (modelo) y el `Predictor` |
| I4 | `models/<version>/` + `avm.model.predictor.Predictor` | Oscar (F8–F9, F11.1) | Brian (API, F11) |

`data/` y `models/` no se versionan. Lo que se intercambia entre máquinas se pasa por un canal
privado (Drive, WhatsApp), nunca por git.

---

## I1. `dataset.csv`: una fila por aviso válido

UTF-8, separador `,`, encabezado en la primera fila. Vacío = desconocido. Ya vienen aplicados los
filtros del builder: sin `is_from_price`, sin moneda desconocida, sin m² construidos, sin outliers
(reglas de F4.6). Los duplicados exactos (mismo `source` + `source_id`) ya están colapsados; los
casi-duplicados comparten `cluster_id` y **se dejan todas sus filas**: el modelo decide (por ejemplo,
peso 1/tamaño del cluster) y los splits agrupan por `cluster_id`.

| Columna | Tipo | ¿Feature? | Descripción |
|---|---|---|---|
| `listing_key` | str | no | `"<source>:<source_id>"`, único por fila |
| `cluster_id` | str | no | Grupo de duplicados (F5). Obligatorio para los splits |
| `snapshot_date` | fecha ISO | no | Fecha del snapshot (no del scrape de cada aviso) |
| `city` | enum `City` | sí | `asuncion`, `luque`, `san_lorenzo`, `fernando_de_la_mora` |
| `neighborhood` | str | sí | Nombre canónico de I2. Vacío si no matcheó |
| `neighborhood_match` | enum | no | `exacto`, `alias`, `fuzzy`, `manual`, `sin_match` |
| `geo_precision` | enum | sí (flag) | `barrio` si hay `neighborhood`, si no `ciudad` |
| `property_type` | enum | sí | `casa`, `departamento`, `duplex` |
| `price_usd` | float > 0 | no | Precio de oferta en USD (PYG convertido con la cotización del snapshot) |
| `built_area_m2` | float > 0 | sí | Denominador del target (ADR-006, P13) |
| `built_area_source` | `tag` / `texto` | no | De dónde salió el m² construido |
| `land_area_m2` | float | sí | Opcional |
| `bedrooms`, `bathrooms`, `garages` | int | sí | Opcionales |
| `has_pool`, `has_quincho`, `is_new`, `in_gated_community`, `has_elevator` | `1` / `0` / vacío | sí | Tri-estado: vacío = el aviso no lo menciona (no es `0`) |
| `street_surface` | enum | sí | `pavimento`, `empedrado`, `tierra` o vacío |
| `advertiser_type` | enum | **no** | `particular`, `inmobiliaria`. Solo para análisis (no está en el formulario) |
| `is_sponsored` | `0` / `1` | **no** | Solo para análisis |
| `usd_per_m2` | float | **target** | `price_usd / built_area_m2` |
| `log_usd_per_m2` | float | **target** | `ln(usd_per_m2)`. Es el target del modelo (F8.1) |

Regla para no filtrar el target: **features = columnas marcadas "sí" + I3**. Coinciden con los campos
de `PredictionRequest` más la geo, que es lo único que el usuario carga en la calculadora.

## I2. `gazetteer.csv`: barrios canónicos

| Columna | Descripción |
|---|---|
| `city` | enum `City` |
| `neighborhood` | Nombre canónico, con tildes (como lo va a ver el usuario en el desplegable) |
| `aliases` | Variantes separadas por `\|`, en minúscula y sin tildes (`villa morra\|v. morra`) |
| `lat`, `lon` | Centroide (WGS84). Vacío solo si no hay ninguna fuente |
| `centroid_method` | `osm_polygon`, `osm_point`, `nominatim`, `manual` (o `sintetico`) |
| `osm_id` | Id del objeto OSM, si existe |
| `source` | De dónde sale el barrio (OSM, lista municipal, etc.). Documentado en `docs/geo.md` |

Clave única: (`city`, `neighborhood`). Atribución obligatoria: "© OpenStreetMap contributors" (ODbL).

## I3. `geo_features.csv`: features espaciales por barrio y por ciudad

`data/reference/geo_features.csv` es UTF-8 y usa coma como separador. Incluye una fila
por `(city, neighborhood)` del catálogo de O1 y una fila por ciudad con `neighborhood`
vacío. Las claves usan los identificadores de `avm.contract.enums.City` y los nombres
normalizados de O1. `geo_precision` vale `barrio` o `ciudad` según el origen espacial.

Orden de columnas:

1. `city`, `neighborhood`, `geo_precision`, `dist_cbd_km`.
2. `dist_<cat>_km` para `road`, `mall`, `school`, `university`, `hospital`, `park`, en ese orden.
3. `n_<cat>_<R>km` para esas categorías, con `R` igual a `1`, `3` y `5` en cada categoría.

Los radios se proponen para comparar proximidad inmediata y acceso en el entorno ampliado.
Las distancias son números en kilómetros y quedan vacías si el snapshot carece de objetos
utilizables de esa categoría. Los conteos son enteros no negativos. La fila de respaldo usa
el punto representativo del polígono municipal OSM. Para integrar, buscar primero la clave
de barrio y usar la fila con barrio vacío cuando la clave no esté disponible.

La distancia a vías usa el vértice más cercano. Los demás objetos usan su nodo o el punto
representativo del polígono. Se cuenta cada objeto OSM una vez por categoría y radio, incluso
si varios vértices de la misma vía caen dentro del radio. Una institución con varias
representaciones OSM puede aportar varios objetos. Las distancias son en línea geodésica
sobre una esfera, sin red vial ni tiempos de viaje.

`dist_cbd_km` usa el nodo OSM `249854726`, miembro `admin_centre` del límite de Asunción
en el snapshot O1. Es el punto de referencia único pedido para el centro de la capital.

```powershell
uv run python scripts/build_geo_features.py --snapshot data/raw/osm/2026-11-03
```

El comando usa las respuestas O1 guardadas. `geo_features.json` incluye hashes de los
insumos, objetos descartados por geometría y casos expuestos al borde del bbox. Cada
caso indica qué radios pueden estar truncados y en qué categorías la distancia mínima
podría cambiar con una extracción mayor. El CSV conserva las métricas observadas.

## I4. Artefacto del modelo y `Predictor`

Carpeta `models/<version>/` (por ejemplo `models/2026-11-06-lgbm-cqr/`):

```
model.*            # el/los modelos (LightGBM .txt, joblib, lo que corresponda)
calibration.json   # parámetros del conformal (q̂ por segmento, nivel de cobertura)
gazetteer.csv      # copia de I2 con la que se entrenó
geo_features.csv   # copia de I3 con la que se entrenó
metadata.json      # ver abajo
```

`metadata.json` como mínimo: `model_version`, `contract_version`, `snapshot_date`, `trained_at`,
`n_train`, `features` (lista ordenada), `coverage_nominal`, y `metrics`.

`metrics` es un objeto con estas claves exactas (las funciones de `avm.model.metrics`), todas
**fracciones, no porcentajes** (0,12 = 12 %), calculadas sobre test (`n_test` es un entero):

| Clave | Qué es |
|---|---|
| `mdape` | Error porcentual absoluto mediano |
| `pe10`, `pe20` | Fracción de predicciones dentro de ±10 % y ±20 % |
| `interval_coverage` | Cobertura empírica del intervalo |
| `mean_interval_width` | Ancho medio **relativo** del intervalo (`relative=True`: fracción de la predicción, puede superar 1) |
| `n_test` | Cantidad de filas de test (entero, no fracción) |

La web (F12) muestra `metrics` con etiquetas en español para estas claves y las claves desconocidas
tal cual vienen. Un modelo de prueba (por ejemplo el `FakePredictor` de `avm.api.fake`) declara
`"is_test_model": true` en su metadata y no trae `metrics`; un modelo real no necesita el campo.

Interfaz Python (la implementa Oscar en `src/avm/model/predictor.py`, la usa Brian en la API):

```python
class Predictor:
    @classmethod
    def load(cls, model_dir: Path) -> "Predictor": ...

    def predict(self, request: PredictionRequest) -> PredictionResponse: ...

    # - barrio desconocido o ausente → features de la ciudad + warning `fallback_ciudad`
    #   (y `barrio_desconocido` si vino un nombre que no está en el gazetteer)
    # - pocos datos en el barrio → warning `pocos_datos` (umbral documentado en metadata.json)
    # - total_* = usd_per_m2 / p_low / p_high × built_area_m2

    def neighborhoods(self, city: City) -> list[str]: ...  # para GET /barrios?ciudad=

    @property
    def metadata(self) -> dict[str, Any]: ...  # para GET /model-info
```

`PredictionRequest` y `PredictionResponse` ya existen en `avm.contract` y no se cambian.

**Primera entrega de Oscar (cuanto antes):** un `Predictor` con el **baseline** (mediana de USD/m²
por barrio, fallback a ciudad, intervalo por cuantiles empíricos). Con eso Brian conecta API y web
de punta a punta, y después se reemplaza por LightGBM + CQR sin cambiar la interfaz.

---

## Historial
- 2026-11-06: I3 confirma la categoría `road` y radios 1/3/5 km acordados en la entrega geo. I4 incorpora LightGBM/CQR con calibración separada por tipo y score máximo por cluster, parámetros en `calibration.json` y boosters en `model.bin` (JSON comprimido). Los artefactos de desarrollo v2 se declaran `is_test_model=true`; resultados y artefacto finales quedan para v3. Se preserva la carga de los baselines publicados.
- 2026-11-03: versión inicial (I1–I4).
- 2026-11-05: I4 fija el objeto `metrics` de `metadata.json` (`mdape`, `pe10`, `pe20`, `interval_coverage`, `mean_interval_width`, `n_test`; fracciones, con el ancho relativo a la predicción) y el campo opcional `is_test_model`. Propuesto por Brian para la API/web (F11/F12); Oscar tiene que confirmarlo en el PR.

- 2026-11-05: I3 usa `road` (primary y trunk) en lugar de `primary_road`; conteos para las seis categorías en radios 1, 3 y 5 km. Oscar registra el cambio aceptado por Brian y confirma las claves metrics de I4. Brian actualizará el generador sintético. I2 se alinea al formato de main, conserva nombres OSM y tildes, `source` y métodos `osm_polygon`/`osm_point`.
