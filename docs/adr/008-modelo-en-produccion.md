# ADR-008: Cómo llega el modelo a producción
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
La API corre en Railway (F13) y carga el `Predictor` de I4 desde `AVM_MODEL_DIR`. El modelo lo entrega Oscar como `models/<version>/` (`docs/interfaces.md`, I4), que no se versiona (`.gitignore`, AGENTS.md). ADR-007 dice que los datos (`data/`) no van a Railway ni a Vercel y que `models/` "solo contiene parámetros y metadatos, sin contenido de avisos". Falta decidir cómo viaja ese artefacto a la API, y el deploy tiene que quedar andando antes de que el modelo exista.

## Decisión
1. **El artefacto de producción se versiona en `deploy/model/`.** Es el contenido de `models/<version>/` copiado tal cual (`model.*`, `calibration.json`, `gazetteer.csv`, `geo_features.csv`, `metadata.json`), **sin subcarpeta de versión**: I4 hace `Predictor.load(model_dir)` sobre esa carpeta. La versión vive en `metadata.json` y el historial en git. Solo se publica la versión final.
2. **Mientras no haya modelo, `deploy/model/` no existe.** La API arranca igual: `/live` da 200 (healthcheck de Railway), `/health`, `/predict`, `/barrios` y `/model-info` dan 503 con un mensaje claro. Cuando se copie la carpeta y se haga push, Railway redeploya y la API pasa a servir sin cambios de código.
3. **Guardia automática** (`scripts/check_deploy_model.py`, corre en `pytest` y por CLI): falla si `deploy/model/` tiene archivos fuera de la lista cerrada, subcarpetas, columnas de CSV fuera de I2/I3, claves de aviso en JSON (`listing_key`, `source_id`, `cluster_id`, `url`, `title`, precios por aviso…), valores con URL, email, teléfono, forma de `listing_key` (`<fuente>:<id>`) o textos largos. Los umbrales son heurísticos, no medidas del dominio.
4. **Límite de la guardia:** los `model.*` son opacos. Se valida nombre y extensión (y, si son texto, URLs/emails/teléfonos), no el contenido de un binario. La revisión de Oscar sobre qué contiene el modelo es el control real; un modelo que memorice filas (por ejemplo vecinos más cercanos con datos de avisos) no se puede publicar.
5. **Este ADR afina ADR-007 (pto. 4):** lo que no va a Railway es `data/`; el modelo sí. AGENTS.md pasa a decir "salvo `deploy/model/` (ADR-008)".
6. **OpenStreetMap.** `gazetteer.csv` y `geo_features.csv` derivan de OSM (ODbL): `deploy/model/` lleva un `ATTRIBUTION.md` con "© OpenStreetMap contributors" y la web ya lo muestra en el pie. Si se publica el repositorio, hay que revisar la obligación de share-alike sobre esa base derivada.
7. **Agregados con pocos avisos.** Un agregado por barrio calculado sobre muy pocos avisos equivale a publicar el precio de uno. Se respeta el umbral `pocos_datos` que declara `metadata.json` (I4) y no se publican estadísticas por barrio por debajo de él.

## Consecuencias
- Un solo origen de verdad (git) y deploy = push, auditable, sin infraestructura ni secretos nuevos.
- "Sin tocar código" vale solo si el `Predictor` ya está en `main` y sus dependencias (lightgbm, pandas, etc.) entraron antes con `uv add` y `uv.lock`; si no, `/health` sigue en 503 con "el módulo avm.model.predictor todavía no está disponible".
- Cada modelo nuevo queda en el historial de git (binarios incluidos): conviene publicar pocas versiones.
- El hook `check-added-large-files` (500 KB) puede frenar un modelo grande, y `.gitignore` ignora `*.joblib` y `*.pkl`. Se decide cuando exista el artefacto (excepción acotada a `deploy/model/`); no se relaja ahora.

## Alternativas descartadas
- **Volume de Railway con subida manual:** estado fuera de git, no reproducible, depende de operar la CLI o el dashboard.
- **Descargar de un bucket o Release al arrancar:** agrega infraestructura, credenciales y código nuevo (rompe "sin tocar código") y una dependencia externa en el arranque.
- **`railway up` desde la máquina local:** sube el directorio de trabajo sin trazabilidad y con riesgo de mandar `data/`.
- **Incluir `models/` entero:** mezcla versiones de prueba con la final; se prefiere publicar solo la versión final y explícita.

## Preguntas abiertas para Oscar
- ¿El formato del modelo (`model.*`) es LightGBM `.txt` o joblib? Define si hace falta la excepción de `.gitignore`.
- ¿Confirma que `metadata.json` incluye el umbral de `pocos_datos` y que el modelo no contiene filas de avisos?
