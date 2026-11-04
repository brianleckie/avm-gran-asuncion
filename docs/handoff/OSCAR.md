# Oscar: qué hay hecho, qué te toca y cómo arrancar con Codex

## En 60 segundos
- **Repo:** `github.com/brianleckie/avm-gran-asuncion` (privado; Brian te invita como colaborador).
- **Qué es:** calculadora web que estima el **precio de oferta** por m² y el valor total de casas,
  departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la Mora, con un
  intervalo de predicción. Pregunta de investigación: **¿las features geográficas mejoran la
  predicción?** (ablation con y sin geo).
- **Ya hecho (Brian):** contrato de datos (`src/avm/contract/`), scraper ético de Clasipar con caché
  sanitizada, piloto de 227 avisos (`docs/pilot/2026-10-06.md`), métricas (`avm.model.metrics`) y
  splits sin leakage (`avm.model.splits`). InfoCasas quedó descartada por sus Términos de Uso.
- **Te toca:** la parte geo (F6) y todo el modelado (F8, F9, F10). Es la mitad "científica" del
  proyecto y la que más pesa en la defensa.
- **Cómo nos conectamos:** por archivos, no por código. Leé `docs/interfaces.md`: vos producís
  I2 (gazetteer), I3 (features geo) e I4 (modelo + `Predictor`); Brian produce I1 (`dataset.csv`).
  Mientras no esté el dataset real, trabajás con el **sintético**, que tiene la misma forma exacta.

Lectura obligatoria antes de tu primer prompt (20 min): `AGENTS.md`, `docs/interfaces.md`,
`docs/adr/001` a `006`, y en `ROADMAP.md` las fases F6, F8, F9 y F10.

## Setup (una vez)
```powershell
git clone https://github.com/brianleckie/avm-gran-asuncion
cd avm-gran-asuncion
# uv:   winget install --id astral-sh.uv -e --source winget   (Mac/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh)
# just: winget install --id Casey.Just -e --source winget      (o: uv tool install rust-just)
uv sync
uv run pre-commit install
just check
uv run python scripts/make_synthetic_dataset.py --out data/processed/sintetico --n 3000 --seed 7
```
Si `just check` da verde, estás listo. Codex lee `AGENTS.md` solo; no hace falta pegárselo.

## Reglas de trabajo con Codex
- **Una tarea por sesión**, con el ID del ROADMAP. Empezá cada prompt pidiendo un plan y aprobalo
  antes de que escriba código.
- **Rama + PR**, nunca a `main`. Brian revisa y mergea (y vos los de él).
- **No le aceptes números inventados.** Si Codex escribe una cifra, una coordenada o una referencia
  que no salió de los datos o de una fuente citada, borrala. Ya nos pasó con otra IA y es lo primero
  que el tribunal puede tumbar.
- Las dependencias de modelado (`pandas`, `scikit-learn`, `lightgbm`) entran en tu primer PR. Si el
  `uv.lock` da conflicto, tomá el de `main` y corré `uv lock`.

## Tus tareas, en orden (con el prompt para Codex de cada una)

### O1. Geo base: gazetteer, centroides y POIs (F6.1–F6.3) → entrega I2
Es lo primero porque Brian lo necesita para normalizar barrios.

```
Leé AGENTS.md, docs/interfaces.md (I2 e I3), docs/adr/003-geo-a-nivel-barrio.md y la fase F6 del ROADMAP.md. Tarea: F6.1, F6.2 y F6.3. Rama f6-geo-base. Primero presentame un plan y esperá mi OK.

Objetivo: producir data/reference/gazetteer.csv con EXACTAMENTE las columnas de I2, y un snapshot de POIs de OpenStreetMap para las 4 ciudades (Asunción, Luque, San Lorenzo, Fernando de la Mora).

Reglas:
- Fuentes: Overpass API y Nominatim, con httpx (ya es dependencia). User-agent "AVM-GranAsuncion-Academic/0.1 (proyecto universitario; contacto: https://github.com/brianleckie)". Caché en disco de TODAS las respuestas en data/raw/osm/<fecha>/, para no repetir requests. Nominatim: máximo 1 request por segundo y menos de 200 en total; si necesitás más, frená y avisame. Overpass: pocas consultas grandes.
- Primero investigá cómo están modelados los barrios en OSM para cada ciudad (place=neighbourhood/suburb, boundary=administrative con qué admin_level). Puede ser distinto en cada ciudad: documentalo.
- Centroide: polígono → representative_point (cae siempre adentro; usá shapely si hace falta y justificalo); solo punto → ese punto; nada en OSM → Nominatim; nada → sin centroide y al reporte de huecos. Registrá el método en centroid_method.
- aliases: minúscula, sin tildes, separados por "|". Incluí la forma sin tildes y abreviaturas obvias ("v." por "villa", "b°"/"barrio"). NO inventes nombres de barrios ni alias que no tengan base.
- POIs: highway=primary|trunk (vías), shop=mall, amenity=school, amenity=university, amenity=hospital, leisure=park. Bounding box de las 4 ciudades con margen; documentá el bbox. Guardá el crudo en data/raw/osm/<fecha>/ con un manifest (consultas, fecha, conteos por categoría).
- Código en src/avm/geo/ (gazetteer.py, osm.py) y un script de entrada scripts/build_geo.py. Nada de data/ al repo.
- docs/geo.md: modelado de barrios por ciudad, métodos de centroide, cobertura (cuántos barrios por ciudad con polígono, con punto, sin nada), huecos, bbox y la atribución "© OpenStreetMap contributors" (ODbL).
- Tests en tests/geo/ con respuestas de Overpass/Nominatim GUARDADAS como fixtures chicos (nada de red en tests): que el gazetteer tenga las columnas de I2, sin duplicados (city, neighborhood), con centroides dentro del bbox.
Al terminar: just check en verde, PR hacia main sin mergear, y un resumen con la cobertura por ciudad.
```
Cuando termine: pasale a Brian el `gazetteer.csv` (Drive/WhatsApp).

### O2. Features geo por barrio y ciudad (F6.4, F6.7) → entrega I3
```
Leé AGENTS.md, docs/interfaces.md (I3) y docs/geo.md. Tarea: F6.4 y F6.7. Rama f6.4-geo-features. Plan primero.

Generá data/reference/geo_features.csv con EXACTAMENTE las columnas de I3: una fila por barrio del gazetteer y una fila por ciudad (neighborhood vacío, geo_precision=ciudad, calculada desde el centroide de la ciudad).
- dist_<cat>_km: distancia haversine del centroide al POI más cercano de cada categoría (para vías, al vértice o segmento más cercano; documentá cuál).
- n_<cat>_<R>km con los radios de I3.
- dist_cbd_km: distancia a UN punto de referencia del centro de Asunción que tiene que salir de OSM (por ejemplo un nodo con nombre). Documentá cuál elegiste y su id OSM. No escribas coordenadas de memoria.
- Funciones puras en src/avm/geo/features.py, testeadas con POIs sintéticos (distancias calculadas a mano en el test).
- F6.7: sección en docs/geo.md explicando la limitación: son features de barrio, iguales para todas las propiedades del mismo barrio.
Al terminar: just check en verde y PR sin mergear.
```

### O3. Baseline + Predictor mínimo (F8.3 + I4) → la primera entrega del modelo
Hacelo apenas tengas I2 e I3 (aunque sean sintéticos): con esto Brian conecta API y web.
```
Leé AGENTS.md, docs/interfaces.md (I1, I3, I4), src/avm/contract/prediction.py, src/avm/model/metrics.py y src/avm/model/splits.py. Tarea: F8.3 y el Predictor de I4. Rama f8.3-baseline-predictor. Plan primero.

- Agregá con uv: pandas, scikit-learn, lightgbm (todo en este PR, pyproject + uv.lock juntos).
- src/avm/model/data.py: carga I1 + join con I3 por (city, neighborhood); si neighborhood está vacío o no está en I3, usa la fila de ciudad. Devuelve X (solo las columnas marcadas "sí" en I1 + las de I3), y (log_usd_per_m2) y groups (cluster_id). Test de que NINGUNA columna "no" de I1 entra en X.
- src/avm/model/baseline.py: mediana de log USD/m² por barrio con fallback a ciudad (y a tipo+ciudad si hay pocos datos; umbral explícito). Las medianas se calculan SOLO con el train del fold.
- src/avm/model/predictor.py: la clase Predictor EXACTA de I4 (load, predict, neighborhoods, metadata), devolviendo un PredictionResponse válido del contrato, con warnings fallback_ciudad / barrio_desconocido / pocos_datos según I4. Intervalo del baseline: cuantiles empíricos de los residuos en un set de calibración separado.
- scripts/train.py --dataset <ruta I1> --geo <ruta I3> --gazetteer <ruta I2> --model baseline --out models/<version>/ : entrena, escribe la carpeta de I4 con metadata.json (métricas de test con avm.model.metrics usando grouped_kfold de avm.model.splits).
- Conectá just train al script (reemplazá el stub; una línea, que ande en PowerShell y Ubuntu).
- Tests con el dataset sintético generado en tmp_path con scripts/make_synthetic_dataset.py.
Al terminar: just check en verde, PR sin mergear, y pasale a Brian la carpeta models/<version>/ entrenada con el sintético.
```

### O4. Modelos y comparación (F8.4–F8.6, F10.2–F10.4)
```
Leé AGENTS.md, docs/interfaces.md y src/avm/model/. Tarea: F8.4 (OLS hedónico), F8.5 (Random Forest), F8.6 (LightGBM) y F10.2 a F10.4. Rama f8-modelos. Plan primero.

- Mismo X/y/groups de data.py. OLS con one-hot de ciudad/tipo y log(m²); RF y LightGBM con categóricas nativas o one-hot. Target encoding de barrio, si lo usás, SOLO dentro del fold.
- Tuning: nada de Optuna. Como mucho 3-4 combinaciones fijas, elegidas en validación interna del train, nunca mirando test.
- Evaluación (scripts/evaluate.py, conectado a just evaluate): GroupKFold por cluster_id (5 folds, seed fijo) y leave-barrio-out (leave_group_out sobre neighborhood, solo filas con barrio). Métricas sobre USD/m² en escala original: MdAPE, MAPE, PE10, PE20, RMSE log.
- F10.3 ABLATION: cada modelo con y sin las columnas de I3. Es la respuesta a la pregunta de investigación.
- F10.4: error por ciudad, tipo y tercil de precio.
- Salida: docs/results/<fecha>.md con las tablas (generado por el script, números solo del código) y los .csv de resultados en models/ o data/processed/ (no al repo).
- Corrélo primero con el sintético: la ablation TIENE que mostrar que sin geo el error sube (el generador tiene efecto geo, ver ground_truth.json). Si no, hay un bug.
Al terminar: just check en verde y PR sin mergear.
```

### O5. Intervalos con cobertura verificable (F9.1–F9.4) y modelo final para la API
```
Leé AGENTS.md, docs/interfaces.md (I4) y src/avm/model/. Tarea: F9.1 a F9.4. Rama f9-intervalos. Plan primero.

- LightGBM cuantílico (alpha 0.1, 0.5, 0.9) sobre log_usd_per_m2.
- CQR (conformalized quantile regression) con un set de calibración separado del train (split por cluster_id). Cobertura nominal 80 %.
- Reportá cobertura empírica vs nominal y ancho medio (avm.model.metrics.interval_coverage y mean_interval_width), global y por ciudad y tipo. F9.4: verificá que el intervalo es más ancho cuando geo_precision=ciudad o hay pocos datos; si no lo es, investigá.
- El Predictor pasa a usar este modelo (model_version nuevo), misma interfaz I4. El baseline sigue disponible con --model baseline.
- Sumá los resultados a docs/results/<fecha>.md.
Al terminar: just check en verde, PR sin mergear, y la carpeta models/<version>/ final para Brian.
```

## Cuándo usar datos reales
Cuando Brian te pase `dataset.csv` real (I1), corré O4 y O5 contra ese archivo y regenerá los
reportes. El código no cambia: si cambia, hay algo mal en la interfaz y lo hablamos.

## Qué te pido de vuelta
1. `gazetteer.csv` (I2) apenas salga O1.
2. Carpeta `models/<version>/` del baseline sintético apenas salga O3 (para conectar la web).
3. Al final: modelo real + `docs/results/<fecha>.md` + tu parte de la metodología (F15.1: geo y
   modelado) y de limitaciones (F15.2).
