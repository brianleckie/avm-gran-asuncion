# AVM Gran Asunción — contexto para Claude Code

Proyecto final de Ingeniería Informática (Brian Leckie y Oscar Arce). Automated Valuation Model que estima el **precio de oferta** por m² y el valor total de casas, departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la Mora, con intervalo de predicción.

El roadmap completo está en `ROADMAP.md`. Cada tarea tiene un ID (`F3.2`). Trabajá **una tarea por sesión** y referenciá el ID en commits y PRs.

## Reglas duras (no las negocies, no las "mejores")
- **Precio publicado ≠ precio de transacción.** Nunca escribas "valor de mercado" o "precio real" en código, UI, docstrings ni docs. Usá "precio de oferta estimado".
- **No asumas coordenadas.** La geo base es a nivel barrio. `lat`/`lon` son opcionales en todos los schemas.
- **El contrato manda.** `src/avm/contract/` es la fuente de verdad. No modifiques schemas sin que te lo pida explícitamente y sin un ADR en `docs/adr/`.
- **Cero leakage.** Splits por `cluster_id`. Target encoding y cualquier estadística del target se calculan solo dentro del fold de entrenamiento.
- **Scraping ético.** Rate limit ≥ 2 s entre requests, respetar robots.txt y user-agent identificable. **Nunca persistas teléfonos, nombres de agentes ni emails.**
- **No inventes números.** Ninguna métrica, cifra de mercado ni referencia bibliográfica que no salga del código o de una fuente que te pasemos. Si falta un dato, decilo.

## Stack
- Python 3.12, uv, pydantic v2, httpx, selectolax/BeautifulSoup, pandas, scikit-learn, lightgbm, rapidfuzz, osmnx/overpy, FastAPI
- Frontend: React + Vite + TypeScript en `web/`
- Deploy: Railway (API) y Vercel (web)

## Estructura
```
src/avm/contract/   schemas pydantic (RawListing, Listing, FeatureRow, Prediction*)
src/avm/synth/      generador de datos sintéticos
src/avm/scraping/   base.py + sources/<fuente>.py
src/avm/pipeline/   clean, currency, dedup
src/avm/geo/        gazetteer, pois, features
src/avm/model/      baseline, ols, rf, lgbm, conformal, evaluate
src/avm/api/        FastAPI
tests/              espejo de src/; fixtures HTML en tests/fixtures/
data/               raw/<fecha>/, interim/, processed/  (gitignored)
docs/adr/           decisiones de arquitectura
```

## Comandos
- `uv run pytest` · `uv run ruff check --fix . && uv run ruff format .`
- `just <tarea>` para el pipeline (ver justfile)
- mypy corre strict solo sobre src/avm/contract (configurado vía `files` en pyproject.toml). No correr `mypy src/` ni `mypy .`: aplica strict a todo el proyecto. No intentar resolverlo con overrides por módulo, ver comentario en pyproject.toml.

## Cómo trabajamos
1. Arrancá cada tarea en **plan mode**: leé el código relevante, proponé un plan corto y esperá aprobación.
2. Parsers y limpieza: **tests primero**, con fixtures reales.
3. Commits chicos con el formato `F4.1: parsear precios en guaraníes`.
4. Al terminar, marcá la tarea en `ROADMAP.md` y anotá cualquier decisión nueva.
5. Idioma: código e identificadores en inglés; docs, comentarios de dominio y UI en español.
