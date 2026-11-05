# Plan de entrega y prompts de Brian

Estado al 2026-11-03: `main` = merge del PR #7 (piloto). Hecho: F0 (casi), F1, F3.1–F3.4, F8.2
(utilidades), F10.1. **No llegó al repo** la sesión de superficie por tags (`f3.4-superficie-tags`
no existe en GitHub): se rehace en S2. Falta todo lo que va de "datos limpios" a "demo desplegada".

## La estrategia en una frase
El dataset del piloto (227 avisos, ~100 con target) no alcanza para entrenar nada defendible. **Esta
noche corre un crawl grande desatendido** (~8 h a 1 request cada ~7 s) y mientras tanto los dos
construyen todo contra el **dataset sintético**, que tiene la misma forma que el real. Cuando llega
el dato real, se cambia una ruta y se regeneran resultados.

## Quién hace qué
| | Brian (Claude Code) | Oscar (Codex) |
|---|---|---|
| Datos | S1 crawl grande · S2 limpieza → `dataset.csv` (I1) | — |
| Geo | consume `gazetteer.csv` | O1 gazetteer (I2) · O2 features (I3) |
| Modelo | — | O3 baseline + Predictor · O4 modelos + ablation · O5 intervalos |
| Producto | S3 API + web · S4 deploy | entrega `models/<version>/` (I4) |
| Defensa | S5 metodología datos/producto, demo | metodología geo/modelo, resultados |

Contratos entre los dos: `docs/interfaces.md` (I1–I4). Nadie edita la carpeta del otro.

## Cronograma (ajustalo a la fecha real de entrega)
| Día | Brian | Oscar |
|---|---|---|
| D0 (hoy) | Setup + S1 → lanzar el crawl antes de dormir | Setup + leer docs |
| D1 | S2 (sobre la caché del piloto, después sobre la del crawl) | O1, O2 |
| D2 | S3 (API + web contra el baseline sintético) | O3 (baseline + Predictor) → se lo pasa a Brian |
| D3 | Pasar `dataset.csv` real a Oscar · S4 deploy | O4 con datos reales |
| D4 | S5 docs y demo | O5 + resultados finales |
| D5 | Ensayo de defensa juntos, últimos ajustes | ídem |

**Si hay menos días, se corta en este orden** (de lo primero que se sacrifica a lo último): OLS (F8.4)
→ leave-barrio-out → Random Forest → deploy (se hace la demo en local) → rango por cuantiles en vez
de CQR. **Nunca se corta:** baseline, LightGBM, ablation geo, intervalo, la aclaración de "precio de
oferta" y las limitaciones. Eso es la tesis.

**Recortado de entrada (va a "trabajo futuro" en la defensa):** F2 completo (queda solo el
sintético de interfaces), F3.6, F3.8, F5.2 cross-portal (hay una sola fuente), F6.6, F8.7 (Optuna),
holdout temporal (hay un solo snapshot), F11.4 comparables, F14.2/F14.3, InfoCasas.

---

## D0: setup (15 min, en PowerShell)

```powershell
cd $HOME\proyectos\avm-gran-asuncion
git switch main
git pull --ff-only
git switch -c chore-handoff
# Copiá acá el contenido del zip (AGENTS.md, docs/, scripts/, tests/) respetando las carpetas
uv run pytest tests/scripts -q
git add AGENTS.md docs/interfaces.md docs/handoff scripts/make_synthetic_dataset.py tests/scripts/test_make_synthetic_dataset.py
git commit -m "chore: AGENTS.md, interfaces I1-I4, handoff y dataset sintético"
git push -u origin chore-handoff
gh pr create --fill --base main
```
Mergealo vos desde el navegador. Después invitá a Oscar:
```powershell
gh api -X PUT repos/brianleckie/avm-gran-asuncion/collaborators/<usuario-de-oscar> -f permission=push
```
Y mandale: el link del repo + "leé `docs/handoff/OSCAR.md` y arrancá por O1".

**Antes de lanzar el crawl:** que la PC no se duerma en toda la noche.
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```
(Mañana lo volvés con `powercfg /change standby-timeout-ac 30`.) Enchufada y con red por cable si
podés.

---

## S1 (hoy): crawl grande — Claude Code Desktop, carpeta local, plan mode

```
Respondé en español. Leé CLAUDE.md, AGENTS.md, docs/interfaces.md, src/avm/scraping/ (en especial crawl.py y run.py), docs/pilot/2026-10-06.md y docs/sources.md.

Contexto: tengo pocos días para entregar. El piloto (seed 42, página 1 + 1 aleatoria por búsqueda) dio 227 avisos; necesito un snapshot ~15 veces más grande, con un crawl desatendido de una noche (~8 h). Esta sesión NO corre el crawl: lo dejo corriendo yo en otra terminal.

REGLAS: NO mergees ni apruebes PRs. Cero requests a portales en esta sesión (todo con MockTransport). La única red es PyPI si hiciera falta. No toques src/avm/contract/ ni la cortesía de BaseScraper (6 s + jitter, robots.txt, corte total ante 403/429/challenge).

PASO 0 (solo lectura): git status y git log -3 (main al día, con el merge de chore-handoff), just check en verde. Reportá y presentá el plan.

TAREA (rama f3.3-crawl-ampliado):
1. Nuevo parámetro OBLIGATORIO --pages-per-target K en run.py y crawl.py: por búsqueda, se pide la página 1 y K-1 páginas más elegidas al azar SIN reposición en [2, last_page] con el rng por target que ya existe. Si last_page <= K, se piden todas. El pool es la unión (merge_refs) y se muestrean hasta --per-target detalles sin reposición, como hoy. El piloto equivale a --pages-per-target 2: verificá con un test que con K=2 el plan es IDÉNTICO al de antes para el mismo seed (mismas páginas, mismos source_id).
2. Orden de requests: primero todos los listados de todas las búsquedas, después los detalles en round-robin entre búsquedas (como hoy). Así un corte deja todas las combinaciones representadas.
3. Pre-vuelo: antes de la primera request imprimí requests máximas planificadas (listados + detalles + robots), duración estimada con 7,4 s por request (la media medida en el piloto: 6,5 s de espera + 0,9 s de latencia) y la hora estimada de fin. Si las requests planificadas superan --budget, avisalo en el pre-vuelo (el presupuesto sigue siendo tope duro).
4. Progreso cada 50 requests como hoy, más la hora estimada de fin.
5. Actualizá la receta `just scrape` con el parámetro nuevo (5 parámetros obligatorios, sin defaults, una sola línea válida en PowerShell y Ubuntu) y el docstring del módulo.
6. Tests sin red: K páginas sin reposición y dentro de rango, last_page <= K pide todas, compatibilidad K=2 con el plan viejo, orden listados-antes-que-detalles, presupuesto nunca excedido, corte limpio ante BlockedError a mitad de los listados.
7. Usando last_page y total_results por búsqueda del crawl_manifest.json del piloto (data/interim/2026-10-06/clasipar/), calculá y mostrame una TABLA con requests de listado y detalles esperados por búsqueda para --pages-per-target 30 --per-target 400, el total y la duración estimada. Si el total pasa de ~3.900 requests (~8 h), proponé un --per-target menor que entre en 8 h.

CIERRE: commits "F3.3: ...", just check y pre-commit en verde, contract-guardian sobre el diff, PR hacia main sin mergear. Al final dame: la tabla del punto 7 y el COMANDO EXACTO para correr el crawl desde una terminal aparte, con --seed 11 y el --budget recomendado.
```

Cuando termine: revisás y mergeás el PR, `git pull`, y en **otra ventana de PowerShell** (no dentro
de Claude Code, para que no se corte si cerrás la app):
```powershell
cd $HOME\proyectos\avm-gran-asuncion
just scrape clasipar <budget> 30 <per-target> 11
```
Si sale con código 3 (bloqueo), no lo relances: mañana lo hablamos y se trabaja con lo que haya.

---

## S2 (D1): superficie por tags + `dataset.csv` (I1) — plan mode

Mientras corre o después del crawl. La sesión trabaja primero sobre la caché del piloto
(`2026-10-06`) y deja todo listo para correr sobre el snapshot nuevo.

**Antes de abrirla:** buscá en bcp.gov.py la cotización USD/PYG (comprador o vendedor, elegí una y
anotá cuál) de la fecha del crawl. Esa cifra la ponés vos en el comando; el agente no la inventa.

```
Respondé en español. Leé CLAUDE.md, AGENTS.md, docs/interfaces.md (sobre todo I1), docs/adr/ (004, 005 y 006), docs/sources.md, docs/pilot/2026-10-06.md, src/avm/contract/, src/avm/pipeline/parsing.py y src/avm/scraping/sources/clasipar.py.

REGLAS: NO mergees. Cero red (todo sobre la caché sanitizada local de data/raw/<fecha>/clasipar/ y data/interim/<fecha>/clasipar/). No toques src/avm/contract/; si hace falta, FRENÁ y explicame. Nada de data/ al repo. Ningún texto de avisos en el chat ni en docs: solo agregados. Ningún número de "mercado" inventado.

PASO 0: git status, git log -3, just check, y listame qué snapshots hay en data/raw/ y data/interim/ (solo nombres y conteos de archivos). Presentá el plan.

PARTE A (rama f3.4-superficie-tags): en parse_detail de Clasipar, mapeá el tag "Superficie construida" → built_area_raw y "Superficie de terreno m2" → land_area_raw (comparación con casefold; valor crudo pasado por _scrub; la etiqueta mapeada sale de attributes_raw). Ninguna otra etiqueta. Fixture nuevo tests/fixtures/clasipar/detalle_4.html desde un detalle cacheado con ambos tags, con título, descripción, zona y <meta> reemplazados por texto neutro inventado (estructura real, cero texto real; verificá 0 coincidencias de 6 palabras con la caché). Valores esperados escritos A MANO leyendo ese HTML. Anotá en docs/sources.md que content_hash cambia en los avisos con tag. Commit y seguí en la misma rama.

PARTE B (misma rama): `just build-dataset` → src/avm/pipeline/ + scripts/build_dataset.py con parámetros OBLIGATORIOS: --snapshot <fecha>, --fx-pyg-per-usd <número>, --fx-source "<texto: BCP, tipo y fecha>", --gazetteer <ruta o "none">. Produce data/processed/<snapshot>/dataset.csv con EXACTAMENTE las columnas de I1, más data/processed/<snapshot>/quality_report.md (solo agregados).
1. RawListing → Listing (el del contrato): precio con parse_price (USD tal cual; PYG ÷ cotización, registrando fx_rate y fx_date); avisos con is_from_price, currency=None o precio 0 se descartan y se cuentan.
2. m² construidos: precedencia tag > texto con kind=construida. Si ambos existen y difieren más de 10 %, se descarta el aviso y se cuenta (no se elige uno). kind=None NO se acepta como construido (decisión por plazo; queda en limitaciones). built_area_source = tag/texto.
3. Barrio: neighborhood_raw (Zona) normalizado (minúscula, sin tildes, sin "barrio"/"b°") contra los aliases de I2: exacto → alias → fuzzy con rapidfuzz (umbral explícito, ≥ 90) → si no, sin_match y neighborhood vacío. Con --gazetteer none, todo queda sin_match y geo_precision=ciudad. Si el barrio es igual a la ciudad, también ciudad.
4. Amenities tri-estado por regex sobre título+descripción (piscina, quincho, a estrenar, barrio cerrado/condominio, ascensor; calle pavimento/empedrado/tierra): mención positiva → 1, negación explícita ("sin piscina") → 0, si no vacío. Tests con frases sintéticas.
5. Dormitorios/baños/cocheras: de los campos raw; si no, vacío.
6. Outliers (F4.6): proponeme reglas A PRIORI (rangos de USD/m² y de m² por tipo) con su justificación ANTES de implementarlas; no las calibres mirando la distribución del dataset. Cada descarte se cuenta por regla.
7. Dedup (F5.1 + F5.3 simple): mismo source_id → una fila (la más reciente). Casi-duplicados dentro de Clasipar (mismo city, property_type, neighborhood, built_area_m2 redondeado a entero y price_usd a ±1 %) → mismo cluster_id; el resto, cluster propio. Se dejan todas las filas del cluster (I1).
8. Si existen varios snapshots (piloto + crawl), --snapshot acepta una lista y se unen antes del dedup.
9. quality_report.md: embudo de descartes (cuántos entran, cuántos salen por cada regla), % de target disponible por tipo y ciudad, % de barrio matcheado por ciudad, tamaño de clusters. Solo números.
10. Tests: sobre RawListing sintéticos construidos en el test (nada de datos reales en tests/).
Corré build-dataset sobre el piloto con --gazetteer none y mostrame SOLO el embudo del quality_report.

CIERRE: commits "F3.4: ..." y "F4.x: ...", just check y pre-commit en verde, contract-guardian y leakage-auditor sobre el diff, PR hacia main sin mergear. Dame el embudo y el comando exacto para correrlo sobre el snapshot del crawl.
```

Después: corrés el comando sobre el snapshot nuevo (con el gazetteer de Oscar cuando llegue) y le
pasás `dataset.csv` a Oscar por Drive/WhatsApp, **no por git**.

---

## S3 (D2): API + web — plan mode

Necesita la carpeta `models/<version>/` del baseline que te pasa Oscar (O3). Si todavía no llegó,
la sesión construye todo y la prueba con un predictor falso solo en los tests.

```
Respondé en español. Leé CLAUDE.md, AGENTS.md, docs/interfaces.md (I2 e I4), src/avm/contract/prediction.py y el ROADMAP F11 y F12.

REGLAS: NO mergees. No toques src/avm/contract/ ni src/avm/model/ (es de Oscar: si el Predictor no existe todavía en main, definí un Protocol con la firma de I4 en src/avm/api/ y testeá con un fake). No inventes métricas: la web muestra solo lo que venga de /model-info.

PASO 0: git status, git log -3, just check, y si existe models/ local decime qué versiones hay (solo nombres). Presentá el plan.

PARTE A, API (rama f11-api): FastAPI en src/avm/api/ (agregá fastapi y uvicorn con uv).
- POST /predict (PredictionRequest → PredictionResponse, vía Predictor.predict), GET /barrios?ciudad=, GET /model-info (metadata sin rutas locales), GET /health.
- El modelo se carga una vez al arrancar desde la variable de entorno AVM_MODEL_DIR. Si falta o no carga, /health devuelve 503 y /predict también, con mensaje claro.
- CORS solo para el origen de la variable AVM_CORS_ORIGIN. Rate limit simple en memoria para /predict (por IP, número explícito en config).
- `just serve` → uvicorn (una línea válida en PowerShell y Ubuntu).
- Tests con TestClient y un predictor falso: validación (ciudad fuera de alcance → 422), warnings de barrio desconocido, health sin modelo.

PARTE B, web (misma rama o f12-web): React + Vite + TypeScript en web/. Mobile first.
- Formulario: ciudad → barrio dependiente (de /barrios), tipo, m² construidos (obligatorio), terreno, dormitorios, baños, cocheras, amenities como "sí / no / no sé" (tri-estado, "no sé" = null).
- Resultado: USD/m², valor total, el intervalo dibujado como barra (p_low–p_high con el estimado marcado), la cobertura nominal en palabras ("en 8 de cada 10 casos el precio de oferta cae en este rango") y la leyenda "precio de oferta estimado" SIEMPRE visible. Warnings visibles.
- Página "Metodología y limitaciones" con texto en español: fuente (Clasipar), scraping ético, precio publicado ≠ transacción, geo a nivel barrio, una sola fuente y un solo snapshot, atribución "© OpenStreetMap contributors". Los números (n, métricas) vienen de /model-info, no hardcodeados.
- URL de la API por VITE_API_URL. Sin librerías de UI pesadas.
- Que `npm run build` pase.

CIERRE: commits "F11.x: ..." / "F12.x: ...", just check, npm run build y pre-commit en verde, contract-guardian, PR sin mergear. Dame los comandos para levantar API y web en local con el modelo de Oscar.
```

---

## S4 (D3): deploy — plan mode

```
Respondé en español. Leé CLAUDE.md, AGENTS.md, docs/interfaces.md (I4), docs/adr/007-privacidad-cache.md, src/avm/api/ y web/.

REGLAS: NO mergees. Nunca subas data/ (ni dataset.csv ni la caché). Antes de publicar el artefacto del modelo, VERIFICÁ que models/<version>/ no contiene filas de avisos (ni textos, ni source_id, ni URLs): listame los archivos y qué contiene cada uno.

TAREA (rama f13-deploy):
1. ADR-008 corto: cómo llega el modelo a producción. Propuesta: copiar SOLO la versión final a deploy/model/ y versionarla (son parámetros y agregados por barrio, más gazetteer y features derivados de OSM con atribución), con un test que falle si en deploy/model/ aparece algo con forma de aviso. Si encontrás una opción mejor, explicámela antes.
2. API en Railway: Dockerfile o config de uv, AVM_MODEL_DIR=deploy/model, AVM_CORS_ORIGIN con el dominio de Vercel, healthcheck en /health.
3. Web en Vercel: root web/, VITE_API_URL a la URL de Railway.
4. Smoke test (scripts/smoke.py <url>): /health, /barrios y un /predict de ejemplo.
5. Decime qué tengo que hacer YO en los dashboards de Railway y Vercel (variables, dominio) paso a paso; no asumas que los conectores están autenticados.
CIERRE: just check, npm run build, contract-guardian, PR sin mergear.
```

---

## S5 (D4): documentación y defensa — plan mode

```
Respondé en español. Leé CLAUDE.md, ROADMAP.md, docs/ completo (adr, sources, pilot, geo, results, interfaces) y el quality_report del snapshot final.

REGLAS: NO mergees. Ningún número que no esté en docs/ o en los reportes generados: citá de qué archivo sale cada cifra. NO generes bibliografía: dejá un bloque [REFERENCIAS — completar a mano] con los temas que necesitan cita. Nada de "valor de mercado" ni "precio real".

TAREA (rama f15-docs):
1. docs/metodologia.md (F15.1): fuentes y por qué InfoCasas no (ToS), ética del scraping (6 s, robots, sanitizado, solo agregados), pipeline y embudo de descartes, dedup, geo (resumen de docs/geo.md), modelos, splits sin leakage, intervalos. Marcá con [OSCAR] las secciones de geo y modelo que tiene que revisar él.
2. docs/limitaciones.md (F15.2): precio de oferta, una fuente, un snapshot, sesgo de portal y de página 1, geo por barrio, m² ambiguos descartados en departamentos, cobertura desigual por ciudad.
3. docs/defensa.md (F15.5): guion de 10 minutos de demo + las 15 preguntas más probables del tribunal con respuesta corta y el archivo que la respalda.
4. README.md: qué es, cómo correr todo (just scrape / build-dataset / train / evaluate / serve), link a la demo.
5. ROADMAP: marcá lo hecho; lo recortado va con la nota "→ fuera de alcance por plazo; trabajo futuro".
CIERRE: PR sin mergear y un resumen de qué secciones quedaron [OSCAR] o [REFERENCIAS].
```

---

## Pendientes chicos (cuando haya un hueco)
- CI: Settings → Billing and plans. Si hay un pago fallido de algo pago, resolvelo; si no, el gate
  real sigue siendo `just check` en local antes de cada merge.
- Cuando Oscar revise los ADR 002–007, cambiar su estado a "aceptado" (un PR de él).
- Al cerrar cada día: anotar en Trello qué avanzaste y qué quedó pendiente.
