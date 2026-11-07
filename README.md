# AVM Gran Asunción

Automated Valuation Model (AVM) que estima el **precio de oferta** por m² y el valor total de casas, departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la Mora, con un intervalo de predicción. Proyecto final de Ingeniería Informática (Brian Leckie y Oscar Arce).

> **Precio de oferta, no de transacción.** Los datos evaluados son avisos de Clasipar; el dataset no observa montos de cierre. Las métricas miden predicción del precio publicado. Ver [ADR-001](docs/adr/001-precio-publicado.md) y [calidad v3](docs/results/v3-quality-report.md).

[Web](https://avm-gran-asuncion.vercel.app) · [Modelo activo](https://avm-gran-asuncion-production.up.railway.app/model-info) · [Metodología](docs/metodologia.md) · [Limitaciones](docs/limitaciones.md) · [Defensa](docs/defensa.md).

## Estado y resultados

Baseline y Predictor están implementados. El candidato v3 usa LightGBM con CQR por tipo; su publicación requiere revisión, merge humano y redeploy. Consultar `model_version` en la API para conocer el artefacto realmente activo. Procedimiento en [deploy/README](deploy/README.md).

El dataset v3 tiene 1.769 filas y 27,8 % de barrio reconocido. En el test del candidato: MdAPE 20,92 %, cobertura global 78,53 % y casas 74,05 %, por debajo del nominal 80 %. La ablation da un efecto mixto de geo; el menor error en departamentos requiere cautela por la superficie sin tipo. Fuentes: [calidad](docs/results/v3-quality-report.md), [metadata](docs/results/v3-model-summary.json) y [evaluación/selección](docs/results/2026-11-06-v3.md).

## Instalación

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.12 si hace falta) y, opcionalmente, [just](https://just.systems/) (`uv tool install rust-just`).

```bash
uv sync                 # crea .venv e instala el paquete y las dependencias de desarrollo
uv run pytest           # corre los tests
uv run pre-commit install   # hooks de git (una vez por clon)
```

Con `just`: `just install`, `just test`, `just check` (lint + mypy + tests). `just --list` muestra las tareas implementadas: scraping, build-dataset, train, evaluate, serve y smoke. Los parámetros reproducibles de la corrida v3 están en [metodología](docs/metodologia.md); los snapshots y datasets se comparten fuera de git.

## API y web (local)

```powershell
# Terminal 1: API con el predictor de PRUEBA (solo desarrollo; sus valores no significan nada)
$env:AVM_PREDICTOR = "fake"; $env:AVM_CORS_ORIGIN = "http://localhost:5173"; just serve

# Terminal 2: web
cd web; npm install; Copy-Item .env.example .env.local; npm run dev
```

Para probar el artefacto incluido en esta rama, en otra terminal PowerShell:

```powershell
$env:AVM_PREDICTOR = "model"
$env:AVM_MODEL_DIR = "deploy/model"
$env:AVM_CORS_ORIGIN = "http://localhost:5173"
just serve
```

También puede cargarse `models/<version>/`. Variables y comportamiento en [configuración de API](src/avm/api/config.py). El predictor fake es exclusivamente de desarrollo.

## Deploy

API en Railway (`Dockerfile`, `railway.toml`) y web en Vercel (`web/`). Sin modelo, la API queda viva (`/live` 200) y no lista (`/health` 503). Paso a paso, variables y smoke test (`just smoke <url>`) en [docs/deploy.md](docs/deploy.md); cómo llega el modelo a producción, en [ADR-008](docs/adr/008-modelo-en-produccion.md).

## Más información

- [ROADMAP.md](ROADMAP.md): tareas por fase, con responsable.
- [CLAUDE.md](CLAUDE.md): reglas del proyecto y estructura del código.
- [docs/adr/](docs/adr/): decisiones de arquitectura.
- [docs/results/2026-11-06-v3.md](docs/results/2026-11-06-v3.md): selección, test, ablation y archivos de respaldo.
- [docs/defensa.md](docs/defensa.md): guion de demo y preguntas con respaldo en el repositorio.

## Referencias

[REFERENCIAS — completar a mano]

© OpenStreetMap contributors, ODbL. Detalles y límites de la referencia geográfica en [docs/geo.md](docs/geo.md).
