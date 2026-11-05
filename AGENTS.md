# AGENTS.md — AVM Gran Asunción (instrucciones para Codex y cualquier agente)

Proyecto final de Ingeniería Informática (Brian Leckie y Oscar Arce). Automated Valuation Model que
estima el **precio de oferta** por m² y el valor total de casas, departamentos y dúplex en venta en
Asunción, Luque, San Lorenzo y Fernando de la Mora, con intervalo de predicción.

Leé SIEMPRE, antes de tocar código: este archivo, `CLAUDE.md` (mismas reglas, escrito para Claude
Code), `docs/interfaces.md` (cómo se conectan las partes) y la tarea del `ROADMAP.md` que te pidan.
Si sos el agente de Oscar, leé también `docs/handoff/OSCAR.md`.

## Reglas duras (no se negocian, no se "mejoran")
- **Precio publicado ≠ precio de transacción.** Nunca escribas "valor de mercado" ni "precio real"
  en código, UI, docstrings ni docs. Usá "precio de oferta estimado".
- **No inventes números.** Ninguna métrica, cifra de mercado, coordenada ni referencia bibliográfica
  que no salga del código, de los datos o de una fuente citada. Si falta un dato, decilo.
- **Cero leakage.** Splits agrupados por `cluster_id` (usá `avm.model.splits`). Target encoding,
  medianas por barrio y cualquier estadística del target se calculan SOLO dentro del fold de train.
  La calibración conformal usa un set separado del de entrenamiento.
- **Features permitidas = campos de `PredictionRequest` + features geo (`docs/interfaces.md` I3).**
  Nada que el usuario no pueda cargar en el formulario entra al modelo (ni `advertiser_type`, ni
  `is_sponsored`, ni `built_area_source`, ni nada derivado del precio).
- **El contrato manda.** `src/avm/contract/` no se toca sin pedido explícito y un ADR en `docs/adr/`.
- **No scrapear portales inmobiliarios.** Solo `avm.scraping` (Brian) hace requests a Clasipar.
  OpenStreetMap (Overpass/Nominatim) sí, con caché local, user-agent identificable y respetando sus
  políticas de uso (Nominatim: máximo 1 request por segundo). Atribución "© OpenStreetMap
  contributors" en todo lo que use esos datos.
- **Datos.** Nada de `data/` ni `models/` se commitea, salvo `deploy/model/` (ADR-008: solo la
  versión final del modelo, validada por `scripts/check_deploy_model.py`). Los docs y reportes
  publican solo agregados.
- **Git.** Nunca push a `main`, nunca force-push, nunca mergear PRs. Una rama por tarea
  (`f8.6-lightgbm`), PR hacia `main`, el merge lo hace un humano.

## Stack y comandos
- Python 3.12 con **uv**. `uv sync`, `uv run pytest`, `uv run ruff check --fix .`, `uv run ruff format .`
- Task runner: `just` (`just check` = lint + tests, lo mismo que el CI).
- mypy corre strict SOLO sobre `src/avm/contract` (config en `pyproject.toml`). No correr `mypy src/`.
- Desarrollo en Windows (PowerShell) y CI en Ubuntu: todo comando nuevo tiene que andar en ambos.
- Dependencias: agregalas con `uv add <paquete>` y commiteá `pyproject.toml` + `uv.lock` en el mismo
  commit. Si `uv.lock` da conflicto al rebasear, NO lo edites a mano: tomá el de `main` y corré `uv lock`.

## Quién es dueño de qué (para no pisarse)
| Carpeta | Dueño | Notas |
|---|---|---|
| `src/avm/scraping/`, `src/avm/pipeline/` | Brian | scraping, limpieza, dedup, `dataset.csv` |
| `src/avm/api/`, `web/` | Brian | FastAPI y React |
| `src/avm/geo/` | Oscar | gazetteer, POIs, features geo |
| `src/avm/model/` (salvo `metrics.py` y `splits.py`, compartidos) | Oscar | modelos, intervalos, `Predictor` |
| `src/avm/contract/`, `docs/interfaces.md` | los dos | solo con acuerdo y ADR |

Si necesitás algo de la carpeta del otro, no lo edites: dejalo anotado en el PR.

## Cómo trabajar
1. Antes de escribir código, proponé un plan corto (archivos, tests, criterio de terminado).
2. Tests para la lógica que importa: features geo, splits sin leakage, métricas, cobertura de
   intervalos, el `Predictor`. Usá el dataset sintético (`scripts/make_synthetic_dataset.py`) para
   tests y desarrollo; nunca datos reales en `tests/`.
3. Commits chicos con el ID del ROADMAP: `F8.6: LightGBM con target encoding dentro del fold`.
4. Al terminar: `just check` en verde, marcá la tarea en `ROADMAP.md` y anotá decisiones nuevas.
5. Idioma: código e identificadores en inglés; docs, comentarios de dominio y UI en español.
