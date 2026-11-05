# ROADMAP — AVM Gran Asunción

> Roadmap completo del proyecto, ordenado por dependencias. Sin fechas.
> Convención: cada tarea tiene un ID (`F3.2`). Claude Code y los commits referencian ese ID.
> Marcar `[x]` al terminar. Responsable: **B** = Brian, **O** = Oscar, **B/O** = compartido.

## Principios no negociables (aplican a todas las fases)

1. **Precio publicado ≠ precio de transacción.** En Paraguay no hay MLS ni registro público de operaciones. Todo output, métrica, UI y texto académico dice "precio de oferta estimado".
2. **No se asumen coordenadas.** La geolocalización base es a nivel barrio. Si una fuente trae lat/lon, se usa como enriquecimiento opcional y nunca como requisito.
3. **Contrato primero.** Los schemas de `src/avm/contract/` son la fuente de verdad. Cambiarlos requiere un ADR.
4. **Cero leakage.** Los splits se hacen por cluster de duplicados. Ninguna feature puede usar información del target fuera del fold.
5. **Scraping ético.** Se respeta robots.txt y los ToS, con rate limit, user-agent identificable y sin datos personales.
6. **Reproducibilidad.** Cada dataset es un snapshot fechado con un manifest. Cada modelo guarda la versión del contrato, el snapshot usado y sus métricas.

---

## F0 — Fundaciones del repo
- [x] F0.1 (B) Monorepo: `src/avm/` (Python, uv), `web/` (React+Vite+TS), `data/` (gitignored), `notebooks/`, `tests/`, `docs/`
- [x] F0.2 (B) Tooling Python: uv, ruff (lint+format), pytest, mypy en `contract/`, pre-commit
- [x] F0.3 (B) Task runner (`justfile` o `Makefile`): `scrape`, `build-dataset`, `train`, `evaluate`, `serve`, `test`
- [ ] F0.4 (B/O) ADRs iniciales en `docs/adr/`: 001 precio publicado · 002 alcance de tipos de inmueble · 003 geo a nivel barrio · 004 normalización de moneda
  → ADR-002 a 005 propuestos, pendiente revisión de Oscar Arce. El 005 (precios sin moneda explícita) no figuraba en la lista original y su decisión queda pendiente de los datos de F3.1. El ADR-002 amplía las exclusiones de F1.1 (locales comerciales, quintas, pozo/preventa): F1.1 queda por alinear si se acepta
- [x] F0.5 (B) CI con GitHub Actions: ruff + pytest en cada PR
- [ ] F0.6 (B/O) Flujo git: `main` protegido, ramas por tarea `f3.2-parser-infocasas`, PRs revisados por el otro

## F1 — Contrato de datos (bloqueante para todo lo demás)
- [ ] F1.1 (B/O) Definir alcance: venta, tipos {casa, departamento, duplex}, ciudades {Asunción, Luque, San Lorenzo, Fernando de la Mora}. Terrenos y alquileres quedan **fuera**
- [ ] F1.2 (B/O) `RawListing`: lo que devuelve el parser, todo opcional y texto crudo, más `fuente`, `url`, `fecha_scrape` y `hash_html`
- [ ] F1.3 (B/O) `Listing`: limpio y tipado (precio_usd, m2_construidos, m2_terreno, dormitorios, baños, cocheras, barrio_norm, ciudad, flags de amenities, lat/lon opcional, `geo_precision ∈ {exacta, aproximada, barrio, ciudad}`)
- [ ] F1.4 (B/O) `FeatureRow`: input del modelo, con columnas y tipos congelados
- [ ] F1.5 (B/O) `PredictionRequest` / `PredictionResponse`: estimación, intervalo [p_low, p_high], nivel de cobertura, warnings, versión del modelo y la leyenda "precio de oferta"
- [ ] F1.6 (B/O) Diccionario de datos en `docs/data_dictionary.md`, generado desde los schemas
- [ ] F1.7 (B) Validación por lotes (pandera o pydantic) y tests de contrato
- [ ] F1.8 (B/O) Versionado: `CONTRACT_VERSION` semántico. Un cambio que rompe compatibilidad requiere ADR más migración

→ v0.1.0 en main (PR #5), pendiente revisión de Oscar
→ v0.1.1 (PATCH, solo documentación): la descripción de `RawListing.content_hash` dice lo que hace el parser (D2); historial en el punto 16 del ADR-006

## F2 — Datos sintéticos (desbloquea modelado en paralelo)
- [ ] F2.1 (O) Gazetteer provisorio de barrios por ciudad, como lista inicial
- [ ] F2.2 (O) Generador: USD/m² lognormal por barrio, efectos hedónicos (m², dormitorios, piscina, a estrenar, pavimento), ruido heteroscedástico
- [ ] F2.3 (O) Inyectar las suciedades reales: nulos, moneda mixta, precios "consultar", outliers con un cero de más, m² intercambiados, **duplicados cross-portal**
- [ ] F2.4 (O) Emitir en formato `RawListing` para testear el pipeline completo, no solo el modelo
- [ ] F2.5 (O) Seed fijo y "ground truth" guardado, para verificar que el pipeline recupera los efectos conocidos

## F3 — Scraping
- [x] F3.1 (B) Reconocimiento por fuente (InfoCasas, Clasipar, otras): robots.txt, ToS, paginación, si existe JSON embebido (`__NEXT_DATA__`, JSON-LD) o API interna. Documentar en `docs/sources.md`
  → los ToS de InfoCasas (cláusula XVII) prohíben bots y scrapers: se frenó tras 19 requests, sin fixtures, y queda descartada salvo permiso escrito. Se prioriza Clasipar (ToS sin cláusula anti-bot, pero prohíben reproducir contenido: no publicar el crudo). "Otras" fuentes no se relevaron. Cliente de reconocimiento en `scripts/recon/` (6 s entre requests, tope de 25 por fuente)
- [x] F3.2 (B) `BaseScraper`: httpx, rate limit de 1 req cada 6 s más jitter, retries con backoff, user-agent identificable, caché de HTML en disco (sanitizado)
  → `src/avm/scraping/base.py`. Una request a la vez con 6 s más un jitter de 0 a 1 s (solo configurable hacia más conservador), presupuesto de requests obligatorio y duro, robots.txt con `urllib.robotparser` (no entiende comodines `*` ni `$`: Clasipar no los usa), 403, 429 o challenge detienen la corrida, reintentos solo de timeouts y 5xx (máximo 2). Decisiones: **D1** la caché se escribe sanitizada (sin teléfonos, emails, WhatsApp, nombres de anunciantes, slugs `/empresa/`, logos ni links a sitios de terceros), nunca HTML crudo; falla cerrado. **D3** el parser sanitiza antes de construir el `RawListing` (el contrato queda de red de seguridad). **D4** `httpx` y `selectolax` son dependencias de runtime. El registro (`requests.jsonl`) y el `manifest.json` son por fuente y snapshot: `data/raw/<fecha>/<fuente>/`
  → F3.3 suma `duration_s` (lo que tardó el intercambio HTTP, sin la demora) a cada línea de `requests.jsonl` y expone `counts` y `latencies_s` en `BaseScraper`
- [ ] F3.3 (B) Crawler de listados → URLs de avisos, filtrados por venta, tipo y ciudad
  → hecha la parte pura (`search_urls`, `page_url` y `merge_refs` en `sources/clasipar.py`); el loop que recorre las páginas con `BaseScraper` es el modo piloto de abajo. **D5**: las tarjetas patrocinadas se incluyen, se deduplican por `source_id` dentro de la corrida y se marcan en `attributes_raw` con `patrocinado` = `si`
  → modo piloto (muestreo) hecho; crawl exhaustivo pendiente. `src/avm/scraping/crawl.py` y `python -m avm.scraping.run` (`just scrape <fuente> <presupuesto> <páginas_por_búsqueda> <por_búsqueda> <seed>`, los 5 obligatorios): por búsqueda, la página 1 más `páginas_por_búsqueda - 1` páginas aleatorias sin reposición (el piloto fue 2: UNA aleatoria), muestreo sin reposición con un rng por búsqueda derivado del seed y detalles intercalados (round-robin). `BlockedError` corta todo y sale con código 3. Piloto del 2026-10-06 (seed 42, 12 búsquedas × 19): 253 requests, 227 de 228 detalles válidos, ningún 403, 429 ni challenge, 31,0 min, latencia media de 0,90 s por request. Reporte, solo con agregados: `docs/pilot/2026-10-06.md`. Falta recorrer todas las páginas; el modo incremental es F3.6
  → crawl ampliado (`--pages-per-target K`, rama `f3.3-crawl-ampliado`): con K=2 el plan es idéntico al del piloto para el mismo seed (test contra el algoritmo anterior y contra las páginas del reporte del piloto). Orden: robots, todos los listados y luego los detalles en round-robin. Pre-vuelo con requests máximas (cota), duración y hora de fin estimadas a 7,4 s por request (6,5 s de espera + 0,9 s de latencia media del piloto); el plan exacto sale en `[plan]` al terminar los listados. Corte limpio con `stopped="network"` (código 4) tras 20 pedidos seguidos sin respuesta de red. Estimación (no medida) para `--pages-per-target 30 --per-target 400` con los `last_page` y `total_results` del piloto: 204 listados + 3.588 detalles + 1 robots = 3.793 requests, unas 7 h 48 min; los datos del piloto tienen 4 semanas y no cuentan patrocinadas ni duplicados entre búsquedas. Comando: `just scrape clasipar 3900 30 400 11`
- [x] F3.4 (B) Parser por fuente → `RawListing`. **Tests con fixtures HTML guardados**, porque los selectores se rompen
  → solo Clasipar (InfoCasas descartada): `src/avm/scraping/sources/clasipar.py`, con selectores en `docs/sources.md` §2.8 y 3 fixtures de detalle y 1 de listado. El detalle no trae la operación ni el tipo de anunciante del aviso (son de los relacionados): se toman de la tarjeta (`ListingRef`). **D2**: `content_hash` = sha256 de un JSON canónico del contenido, sin `scraped_at` ni atributos volátiles. Los tests usan valores escritos a mano desde el HTML. Crudo local borrado (`docs/sources.md` §8.3)
  → seguimiento (piloto F3.3): el detalle trae `Superficie construida` y `Superficie de terreno m2` como `span.ads_tag` (23,8 % y 22,5 % de 227 avisos, con el número solo). El parser los deja en `attributes_raw` y debería llevarlos a `built_area_raw` y `land_area_raw`, que el contrato ya tiene (ver `docs/pilot/2026-10-06.md` §6 y §7)
  → S2 (2026-11-05): los dos tags pasan a `built_area_raw` y `land_area_raw` (comparación con `casefold`, valor por `_scrub`, la etiqueta mapeada sale de `attributes_raw`; ninguna otra). `content_hash` cambia una vez en los avisos con tag (`docs/sources.md` §2.8). `detalle_4.html` es un detalle del crawl con la estructura real y todo el texto inventado.
- [ ] F3.5 (B) Excluir datos personales: teléfonos, nombres de agentes y emails no se persisten
  → cubierto en lo esencial por D1 y D3 (caché y `RawListing` sanitizados). Pendiente: nombres de personas en texto libre (título o descripción), dominios sin esquema ("sitio.com.py") y los falsos negativos del regex (por ejemplo "981 123 456", sin el `0`)
  → piloto F3.3 (227 avisos, solo conteos): 1 descripción con un indicio de nombre de persona ("Dr./Dra."), 1 con un teléfono reemplazado por `[TELEFONO]` y 58 con un link a un tercero reemplazado por `[URL]`. Sigue sin poder detectarse un nombre escrito en texto libre (`docs/pilot/2026-10-06.md` §10; ADR-007)
- [ ] F3.6 (B) Modo incremental (re-scrape solo de lo nuevo) y detección de avisos dados de baja
- [ ] F3.7 (B) Snapshot fechado `data/raw/<fecha>/` con manifest (conteos por fuente/ciudad y hash)
  → parcial: `BaseScraper` escribe un `manifest.json` por fuente (inicio, fin, presupuesto, requests usadas, conteos por resultado y `CONTRACT_VERSION`). Falta el manifest del snapshot completo (conteos por ciudad y hash)
  → el crawler (F3.3) suma `crawl_manifest.json` en `data/interim/<fecha>/<fuente>/`: seed, páginas aleatorias, `source_id` muestreados por búsqueda y rechazos por tipo de error
- [ ] F3.8 (B) Monitor de salud: si un parser devuelve más de X% de campos nulos, falla ruidosamente

## F4 — Limpieza y normalización
- [x] F4.1 (B) Parseo de precios: "USD 150.000", "U$S 150 mil", "Gs. 1.200.000.000", "consultar" → null
  → parser inicial en parsing.py, pendiente de validar contra fixtures reales (F3.4)
  → F3.1: 641/642 strings reales parseados (el que falta es "Consultar precio."), ninguno con `currency=None`. 13 montos bajos para una venta en Clasipar quedan para F4.6 (ver `docs/sources.md` §5; cifras corregidas el 2026-10-06, §8.1)
  → piloto F3.3: 223/227 precios parseados (98,2 %), ninguno con `currency=None` (132 USD y 91 PYG). Los 4 restantes son "Gs. 0" (monto cero), para F4.6 (`docs/pilot/2026-10-06.md` §4)
  → hecho en `avm.pipeline.clean.raw_to_row` (S2): `parse_price` sobre `price_raw`; se descartan y cuentan por separado el precio sin monto, el monto cero, la moneda desconocida y el "desde"/rango. `price_provenance` y `currency_provenance` = `estructurado` (vienen del campo de precio del portal).
- [x] F4.2 (B) Conversión a USD con cotización BCP de la fecha de scrape, guardando moneda y monto originales
  → decisión pendiente: qué hacer con `currency=None` (precio sin moneda explícita). `parse_price` no la adivina por magnitud; inferirla o descartar el aviso se resuelve acá, en el pipeline
  → hecho con un **desvío por plazo** (ADR-004, sección del 2026-11-05): una única cotización de casa de cambios (Cambios Chaco, punto medio) para todos los snapshots, pasada en cada corrida (`--fx-pyg-per-usd`, `--fx-date`, `--fx-source`), en lugar de la del BCP por fecha de scrape. `currency=None` se descarta (alternativa A del ADR-005, que sigue sin decidirse): queda en limitaciones.
- [ ] F4.3 (B) m²: resolver construidos vs terreno, detectar intercambios y unidades erróneas
  → parser inicial en parsing.py, pendiente de validar contra fixtures reales (F3.4)
  → F3.1: el número sale bien en todos los strings reales, pero en Clasipar la superficie solo aparece en texto libre y `kind` suele quedar en None; hay un caso dudoso ("940M2 C/ CONSTRUCCION") y "desde N m2" no se marca (ver `docs/sources.md` §5)
  → piloto F3.3 (227 avisos): 73,6 % tiene alguna superficie en el texto y 33,9 % una de tipo `construida` (casas 42,1 %, dúplex 50,7 %, departamentos 9,2 %); el 59,2 % de los departamentos solo trae superficies `kind=None`. Con "Terreno: N m² Construcción: N m²" en la misma línea gana la etiqueta del número siguiente. El tag estructurado `Superficie construida` suma cobertura (ver F3.5). Patrones de formato en `docs/pilot/2026-10-06.md` §5
  → parcial (S2): precedencia tag > texto con `kind=construida`; si ambos existen y difieren más de 10 % (relativo al tag) se descarta el aviso; `kind=None` NO se acepta como construido en casas y dúplex (decisión por plazo, queda en limitaciones). **Excepción en departamentos (rama `f4.3-depto-area-sin-tipo`):** si no hay tag ni superficie `construida`, se acepta como construida la primera expresión `kind=None`, con `built_area_source=texto`. Justificación a priori: un departamento no tiene superficie de terreno propia. No se verificó a mano que esas superficies sean la construida; el reporte cuenta cuántas filas entran por esta regla. Sin detección de unidades erróneas más allá de los outliers de F4.6.
- [ ] F4.4 (B) Normalización de barrios: gazetteer, alias ("V. Morra", "Villa Morra") y fuzzy matching (rapidfuzz). Lo que no matchea va a revisión manual, no se asigna en silencio
  → implementado en `avm.pipeline.neighborhood` (S2): exacto → alias → fuzzy (`rapidfuzz.fuzz.ratio` ≥ 90, dentro de la ciudad; el empate entre barrios es ambiguo y no se asigna). Falta correrlo con el gazetteer real de Oscar (I2) y la revisión manual de lo que no matchea; las corridas de S2 fueron con `--gazetteer none`.
- [x] F4.5 (B) Extracción de features desde la descripción (regex primero): piscina, quincho, a estrenar, condominio/barrio cerrado, **pavimento/empedrado/tierra**, ascensor, amenities
  → hecho (S2): piscina y quincho primero por el tag del portal (SI/NO) y luego por regex; a estrenar, barrio cerrado/condominio, ascensor y calle (pavimento/empedrado/tierra) por regex sobre título + descripción, con negación explícita. `garages` queda vacío en el 100 % (el parser no lo extrae): no sirve como feature.
- [x] F4.6 (B) Reglas de outliers: USD/m² fuera de rango plausible por ciudad, errores de tipeo, alquileres colados
  → hecho con 4 reglas a priori y fijas, aprobadas el 2026-11-05 (`avm.pipeline.outliers`): m² construidos < 15 o > 600 (departamento) / 1.000 (dúplex) / 2.000 (casa), y USD/m² < 150 o > 8.000 (igual para los tres tipos). Son supuestos del equipo, no datos de mercado, y no se recalibran mirando la distribución: si una descarta mucho se informa, no se cambia. Sin rangos por ciudad ni estadísticos de la distribución (leakage).
- [ ] F4.7 (B) Reporte de calidad por snapshot: % de nulos por campo, descartes por regla y cobertura por barrio
  → hecho (S2) como `quality_report.md` por corrida (solo agregados): embudo por regla, target por tipo y ciudad, barrio por ciudad, clusters y origen tag/regex. **Parcial**: falta el % de nulos por campo, por eso la casilla sigue sin tildar.

## F5 — Deduplicación
- [x] F5.1 (B) Duplicados exactos: mismo id/url dentro de una fuente
  → hecho (S2): misma `(source, source_id)` → una fila, la de `scraped_at` más reciente, antes de los filtros.
- [ ] F5.2 (B) Near-duplicates cross-portal: blocking por (ciudad, barrio, tipo, dormitorios), luego similitud de m² ±3%, precio ±5% y texto (TF-IDF/MinHash)
- [x] F5.3 (B) Asignar `cluster_id` y elegir un representante por cluster. El `cluster_id` se usa en los splits (F8)
  → versión simple (S2): casi-duplicados dentro de Clasipar por (ciudad, tipo, barrio, m² redondeado a entero) con precio a ±1 % entre vecinos (single-linkage); se dejan todas las filas del cluster y no se elige representante. Con `--gazetteer none` el barrio es vacío para todos: agrupa de más (lado seguro para leakage).
- [ ] F5.4 (B/O) Validar el dedup contra los duplicados inyectados en el sintético (precision/recall)

## F6 — Features geoespaciales
- [ ] F6.1 (O) Gazetteer definitivo de barrios de las 4 ciudades, con fuente documentada
- [ ] F6.2 (O) Centroides: polígonos OSM cuando existan; si no, Nominatim con caché. Registrar el método por barrio
- [ ] F6.3 (O) Snapshot de POIs vía Overpass, con fecha: avenidas principales (primary/trunk), shoppings, colegios, universidades, hospitales y parques
- [ ] F6.4 (O) Features: distancia centroide → POI más cercano por categoría, conteo de POIs en radio R y distancia a centros de empleo (microcentro, eje corporativo)
- [ ] F6.5 (O) Si hay lat/lon, mismas features con precisión `aproximada` o `exacta` (hoy ninguna fuente demostró `exacta`, ADR-006). Flag en el modelo
- [ ] F6.6 (O) (Opcional) Zona fiscal catastral por barrio como feature o benchmark
- [ ] F6.7 (O) Documentar la limitación: las features son a nivel barrio y dentro de un mismo barrio no discriminan entre propiedades

## F7 — Análisis exploratorio
- [ ] F7.1 (B/O) Distribuciones de USD/m² por ciudad, tipo y barrio
- [ ] F7.2 (B/O) Cobertura: barrios con N bajo, que van a necesitar shrinkage o fallback a nivel ciudad
- [ ] F7.3 (B/O) Sesgo muestral: qué zonas sobrerrepresentan los portales. Esto entra en limitaciones
- [ ] F7.4 (B/O) Sanity check contra referencias publicadas de precio/m²
- [ ] F7.5 (B/O) Correlaciones y colinealidad (m² vs dormitorios, etc.)

## F8 — Modelado
- [ ] F8.1 (O) Target: `log(USD/m²)`. El valor total se obtiene como predicción × m²
- [ ] F8.2 (O) Esquema de splits: (a) GroupKFold por `cluster_id`, (b) holdout temporal con los últimos snapshots, (c) leave-barrio-out para medir generalización espacial
  → utilidades de split en splits.py; el esquema final se valida con datos reales (F7)
  → decisión: `temporal_holdout` con `cluster_ids` excluye del TEST los clusters ya vistos en train y deja el train completo; el test mide inmuebles no vistos según el dedup y pierde los republicados; sesgos y límites en el docstring
- [ ] F8.3 (O) **Baseline:** mediana de USD/m² por barrio, con fallback a la ciudad. Es el número a superar
- [ ] F8.4 (O) Modelo hedónico OLS, interpretable y defendible ante el tribunal
- [ ] F8.5 (O) Random Forest
- [ ] F8.6 (O) LightGBM con target encoding de barrio **dentro del fold**
- [ ] F8.7 (O) Tuning acotado (Optuna) con presupuesto fijo, evaluado solo en validación
- [ ] F8.8 (O) Interpretabilidad: SHAP global y local, más dependencia parcial de m² y de las distancias

## F9 — Incertidumbre (el "rango de error" del entregable)
- [ ] F9.1 (O) LightGBM cuantílico (α = 0.1, 0.5, 0.9)
- [ ] F9.2 (O) Conformal (CQR) sobre un set de calibración separado, para garantizar cobertura empírica
- [ ] F9.3 (O) Reportar cobertura real vs nominal y ancho medio, global y por segmento
- [ ] F9.4 (O) Verificar que los intervalos son más anchos en barrios con poca data. Si no lo son, algo está mal

## F10 — Evaluación y ablation
- [x] F10.1 (B/O) Métricas: MdAPE, MAPE, PE10/PE20 (% de predicciones dentro de ±10% y ±20%), RMSE en log
  → `metrics.py` devuelve fracciones (0,12 = 12 %); PE10 y PE20 son `pe_within` con `tol=0.10` y `tol=0.20`. Incluye también cobertura y ancho de intervalos, insumos de F9.3
- [ ] F10.2 (B/O) Tabla comparativa: baseline vs OLS vs RF vs LightGBM, en los tres esquemas de split
- [ ] F10.3 (B/O) **Ablation geo:** con y sin features espaciales. Responde directamente la pregunta de investigación
- [ ] F10.4 (B/O) Error por segmento: ciudad, tipo y rango de precio
- [ ] F10.5 (B/O) Análisis de residuos: dónde y por qué falla el modelo

## F11 — Servicio (FastAPI)
- [ ] F11.1 (B) Artefacto versionado: `models/<version>/` con modelo, metadata.json (versión de contrato, snapshot, métricas, fecha) y gazetteer
- [x] F11.2 (B) Endpoints `POST /predict`, `GET /barrios?ciudad=`, `GET /health`, `GET /model-info`
  → `src/avm/api/`: depende del `PredictorProtocol` (firma de I4), no de una implementación. Se elige con `AVM_PREDICTOR=model|fake`; sin variable o si la carga falla, `/health` y `/predict` dan 503. `fake` solo para desarrollo y la API no arranca con `AVM_ENV=production`. `just serve`.
  → Decisión: `WarningCode` es un enum cerrado y el contrato no se tocó, así que el modelo de prueba NO se avisa con un warning `modelo_de_prueba`: la metadata declara `is_test_model: true`, `/predict` agrega el header `X-AVM-Test-Model: true` y la web muestra el banner desde `/model-info`.
- [ ] F11.3 (B) Fuera de dominio: barrio desconocido → fallback a ciudad, intervalo ancho y warning explícito
  → parcial: la API devuelve los warnings del predictor sin tocarlos y el `FakePredictor` los emite con la semántica de I4 (`fallback_ciudad`, `barrio_desconocido`). El fallback y el ancho del intervalo los implementa el `Predictor` real (Oscar).
- [ ] F11.4 (B) Comparables: k avisos similares del dataset, sin datos personales, para dar contexto a la estimación
- [x] F11.5 (B) Tests de API y validación de inputs contra el contrato
  → `tests/api/`: 422 por ciudad/tipo/superficie fuera del contrato, warnings, 503 sin predictor, fake + production, rate limit, CORS, metadata sin rutas locales.

## F12 — Frontend (React)
- [x] F12.1 (B) Formulario: ciudad → barrio (dependiente), tipo, m², dormitorios, baños, cocheras y amenities
  → `web/` (React + Vite + TypeScript, sin librerías de UI). Cocheras no se pide: viaja como `null`. Amenities como Sí / No / No sé (No sé = `null`), más tipo de calle opcional. Probado a mano contra el `FakePredictor`.
- [x] F12.2 (B) Resultado: USD/m², valor total, intervalo visual, nivel de cobertura y leyenda "precio de oferta estimado"
  → La cobertura en palabras sale de `coverage_nominal` de `/model-info` (si falta, de la respuesta); banner fijo si `is_test_model`. Las métricas se muestran solo si `metadata.metrics` las trae (claves fijadas en `docs/interfaces.md`, I4).
- [ ] F12.3 (B) Comparables y warnings visibles
  → parcial: warnings visibles en lenguaje claro; comparables (F11.4) quedan fuera por plazo.
- [x] F12.4 (B) Página "Metodología y limitaciones", que también sirve para la defensa
  → `web/src/Methodology.tsx`; los números (n, fecha, métricas) vienen solo de `/model-info`, el texto no tiene cifras fijas.

## F13 — Deploy
- [ ] F13.1 (B) API en Railway y frontend en Vercel
- [ ] F13.2 (B) Variables de entorno, CORS y rate limit básico en `/predict`
  → parcial (F11): `AVM_CORS_ORIGIN` y `AVM_RATE_LIMIT_PER_MIN` ya funcionan; falta el deploy (detrás de Railway la IP real llega en `X-Forwarded-For`, hoy no se usa ese header).
- [ ] F13.3 (B) Smoke test post-deploy

## F14 — Calidad transversal
- [ ] F14.1 (B/O) Pipeline end-to-end reproducible con un solo comando, desde snapshot hasta modelo y métricas
- [ ] F14.2 (B/O) Test e2e con datos sintéticos en CI
- [ ] F14.3 (B/O) Logging estructurado en scraping y API

## F15 — Documentación académica y defensa
- [ ] F15.1 (B/O) Metodología: fuentes, ética del scraping, pipeline, dedup, features, modelos y evaluación
- [ ] F15.2 (B/O) Limitaciones explícitas: precio publicado, sesgo de portales, geo a nivel barrio, temporalidad y cobertura desigual
- [ ] F15.3 (B/O) Resultados: tablas de F10, ablation y cobertura de intervalos
- [ ] F15.4 (B/O) Bibliografía **verificada a mano**, sin referencias generadas por IA sin chequear
- [ ] F15.5 (B/O) Demo y guion de defensa, más preguntas probables del tribunal con sus respuestas

---

## Riesgos conocidos
| Riesgo | Mitigación |
|---|---|
| Portal bloquea o cambia el HTML | Caché de HTML crudo, fixtures, monitor F3.8 y múltiples fuentes |
| Pocos avisos en San Lorenzo / FdlM | Fallback jerárquico barrio → ciudad, shrinkage e intervalos más anchos |
| Muchos avisos sin m² | Imputación solo si es defendible; si no, descartar y reportar el % |
| Duplicados inflan las métricas | F5 y splits por cluster (F8.2) |
| Moneda mixta | F4.2 con cotización por fecha |
| Referencias o métricas alucinadas por IA | Todo número sale del pipeline y toda cita se verifica a mano |
