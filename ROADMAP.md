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
- [ ] F3.3 (B) Crawler de listados → URLs de avisos, filtrados por venta, tipo y ciudad
  → hecha la parte pura (`search_urls`, `page_url` y `merge_refs` en `sources/clasipar.py`); falta el loop que recorre las páginas con `BaseScraper`. **D5**: las tarjetas patrocinadas se incluyen, se deduplican por `source_id` dentro de la corrida y se marcan en `attributes_raw` con `patrocinado` = `si`
- [x] F3.4 (B) Parser por fuente → `RawListing`. **Tests con fixtures HTML guardados**, porque los selectores se rompen
  → solo Clasipar (InfoCasas descartada): `src/avm/scraping/sources/clasipar.py`, con selectores en `docs/sources.md` §2.8 y 3 fixtures de detalle y 1 de listado. El detalle no trae la operación ni el tipo de anunciante del aviso (son de los relacionados): se toman de la tarjeta (`ListingRef`). **D2**: `content_hash` = sha256 de un JSON canónico del contenido, sin `scraped_at` ni atributos volátiles. Los tests usan valores escritos a mano desde el HTML. Crudo local borrado (`docs/sources.md` §8.3)
- [ ] F3.5 (B) Excluir datos personales: teléfonos, nombres de agentes y emails no se persisten
  → cubierto en lo esencial por D1 y D3 (caché y `RawListing` sanitizados). Pendiente: nombres de personas en texto libre (título o descripción), dominios sin esquema ("sitio.com.py") y los falsos negativos del regex (por ejemplo "981 123 456", sin el `0`)
- [ ] F3.6 (B) Modo incremental (re-scrape solo de lo nuevo) y detección de avisos dados de baja
- [ ] F3.7 (B) Snapshot fechado `data/raw/<fecha>/` con manifest (conteos por fuente/ciudad y hash)
  → parcial: `BaseScraper` escribe un `manifest.json` por fuente (inicio, fin, presupuesto, requests usadas, conteos por resultado y `CONTRACT_VERSION`). Falta el manifest del snapshot completo (conteos por ciudad y hash)
- [ ] F3.8 (B) Monitor de salud: si un parser devuelve más de X% de campos nulos, falla ruidosamente

## F4 — Limpieza y normalización
- [ ] F4.1 (B) Parseo de precios: "USD 150.000", "U$S 150 mil", "Gs. 1.200.000.000", "consultar" → null
  → parser inicial en parsing.py, pendiente de validar contra fixtures reales (F3.4)
  → F3.1: 641/642 strings reales parseados (el que falta es "Consultar precio."), ninguno con `currency=None`. 13 montos bajos para una venta en Clasipar quedan para F4.6 (ver `docs/sources.md` §5; cifras corregidas el 2026-10-06, §8.1)
- [ ] F4.2 (B) Conversión a USD con cotización BCP de la fecha de scrape, guardando moneda y monto originales
  → decisión pendiente: qué hacer con `currency=None` (precio sin moneda explícita). `parse_price` no la adivina por magnitud; inferirla o descartar el aviso se resuelve acá, en el pipeline
- [ ] F4.3 (B) m²: resolver construidos vs terreno, detectar intercambios y unidades erróneas
  → parser inicial en parsing.py, pendiente de validar contra fixtures reales (F3.4)
  → F3.1: el número sale bien en todos los strings reales, pero en Clasipar la superficie solo aparece en texto libre y `kind` suele quedar en None; hay un caso dudoso ("940M2 C/ CONSTRUCCION") y "desde N m2" no se marca (ver `docs/sources.md` §5)
- [ ] F4.4 (B) Normalización de barrios: gazetteer, alias ("V. Morra", "Villa Morra") y fuzzy matching (rapidfuzz). Lo que no matchea va a revisión manual, no se asigna en silencio
- [ ] F4.5 (B) Extracción de features desde la descripción (regex primero): piscina, quincho, a estrenar, condominio/barrio cerrado, **pavimento/empedrado/tierra**, ascensor, amenities
- [ ] F4.6 (B) Reglas de outliers: USD/m² fuera de rango plausible por ciudad, errores de tipeo, alquileres colados
- [ ] F4.7 (B) Reporte de calidad por snapshot: % de nulos por campo, descartes por regla y cobertura por barrio

## F5 — Deduplicación
- [ ] F5.1 (B) Duplicados exactos: mismo id/url dentro de una fuente
- [ ] F5.2 (B) Near-duplicates cross-portal: blocking por (ciudad, barrio, tipo, dormitorios), luego similitud de m² ±3%, precio ±5% y texto (TF-IDF/MinHash)
- [ ] F5.3 (B) Asignar `cluster_id` y elegir un representante por cluster. El `cluster_id` se usa en los splits (F8)
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
- [ ] F11.2 (B) Endpoints `POST /predict`, `GET /barrios?ciudad=`, `GET /health`, `GET /model-info`
- [ ] F11.3 (B) Fuera de dominio: barrio desconocido → fallback a ciudad, intervalo ancho y warning explícito
- [ ] F11.4 (B) Comparables: k avisos similares del dataset, sin datos personales, para dar contexto a la estimación
- [ ] F11.5 (B) Tests de API y validación de inputs contra el contrato

## F12 — Frontend (React)
- [ ] F12.1 (B) Formulario: ciudad → barrio (dependiente), tipo, m², dormitorios, baños, cocheras y amenities
- [ ] F12.2 (B) Resultado: USD/m², valor total, intervalo visual, nivel de cobertura y leyenda "precio de oferta estimado"
- [ ] F12.3 (B) Comparables y warnings visibles
- [ ] F12.4 (B) Página "Metodología y limitaciones", que también sirve para la defensa

## F13 — Deploy
- [ ] F13.1 (B) API en Railway y frontend en Vercel
- [ ] F13.2 (B) Variables de entorno, CORS y rate limit básico en `/predict`
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
