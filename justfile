# Task runner del proyecto. `just --list` muestra las tareas.
#
# Portabilidad: en Windows just usa `sh` por defecto, que no existe sin WSL/Git Bash; por eso se
# fuerza PowerShell. Cada línea de receta es un único comando (sin `&&`) para que valga en ambas shells.
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

default:
    @just --list

# Sincroniza el entorno con uv.lock
install:
    uv sync

# Corre los tests y exige ≥ 95 % de cobertura (líneas y ramas) en CADA módulo con umbral. Se mide por
# módulo y no sobre el total, porque un total combinado puede esconder un módulo flojo detrás de otro
# al 100 %. `coverage report` sale con error si el módulo no tiene datos o queda bajo el umbral.
# Excepción: avm.contract y avm.scraping se miden como paquete (son varios archivos chicos). Las
# comillas del glob evitan que sh lo expanda en Ubuntu; PowerShell las quita antes de pasarlo. Un
# solo `*` no cruza directorios: avm.scraping lista aparte su subpaquete `sources`.
test:
    uv run pytest --cov=avm.pipeline --cov=avm.model.metrics --cov=avm.model.splits --cov=avm.contract --cov=avm.scraping --cov-branch --cov-report=
    uv run coverage report --show-missing --include="src/avm/pipeline/*" --fail-under=95
    uv run coverage report --show-missing --include=src/avm/model/metrics.py --fail-under=95
    uv run coverage report --show-missing --include=src/avm/model/splits.py --fail-under=95
    uv run coverage report --show-missing --include="src/avm/contract/*" --fail-under=95
    uv run coverage report --show-missing --include="src/avm/scraping/*,src/avm/scraping/sources/*" --fail-under=95

# Análisis estático: ruff (lint + formato) y mypy estricto sobre src/avm/contract
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

# Aplica los fixes automáticos de ruff y formatea
format:
    uv run ruff check --fix .
    uv run ruff format .

# lint + test (lo mismo que corre el CI)
check: lint test

# --- Pipeline ---

# Crawler de muestreo (F3.3). Los 5 parámetros son OBLIGATORIOS y no tienen default (presupuesto de
# requests, páginas y avisos por búsqueda, y seed explícitos en cada corrida). Ej.: el piloto fue
# `just scrape clasipar 260 2 19 42`; el crawl grande, `just scrape clasipar 3900 30 400 11`. Es la
# única receta que sale a la red: solo al host de la fuente, vía BaseScraper (6 s entre requests, robots.txt).
scrape source budget pages_per_target per_target seed:
    uv run python -m avm.scraping.run --source {{source}} --budget {{budget}} --pages-per-target {{pages_per_target}} --per-target {{per_target}} --seed {{seed}}

# dataset.csv (I1) y quality_report.md desde la caché de data/interim (F4/F5). Todos los parámetros
# son OBLIGATORIOS y sin default: cotización (PYG por USD), su fecha (AAAA-MM-DD), su fuente (texto
# entre comillas dobles, sin comillas dentro), el gazetteer (ruta de I2 o `none`) y una o más fechas
# de snapshot al final. Sin red. Ej.: `just build-dataset 6085 2026-11-04 "Cambios Chaco S.A.,
# punto medio compra 5.980 / venta 6.190, 04/11/2026" none 2026-10-06 2026-11-04`
build-dataset fx_rate fx_date fx_source gazetteer +snapshots:
    uv run python scripts/build_dataset.py --snapshot {{snapshots}} --fx-pyg-per-usd {{fx_rate}} --fx-date {{fx_date}} --fx-source "{{fx_source}}" --gazetteer {{gazetteer}}

# --- Todavía sin implementación (cada receta apunta a su tarea del ROADMAP) ---

train dataset geo gazetteer model out:
    uv run python scripts/train.py --dataset "{{dataset}}" --geo "{{geo}}" --gazetteer "{{gazetteer}}" --model {{model}} --out "{{out}}"

evaluate:
    @echo "No implementado, ver ROADMAP F10"
    @exit 1

# Variables: AVM_PREDICTOR=fake|model, AVM_MODEL_DIR, AVM_ENV, AVM_CORS_ORIGIN, AVM_RATE_LIMIT_PER_MIN,
# AVM_TRUST_PROXY (ver src/avm/api/config.py). Sin AVM_PREDICTOR, /health y /predict responden 503.
# API local (F11)
serve:
    uv run uvicorn avm.api.app:app --host 127.0.0.1 --port 8000

# Ej.: `just smoke https://xxx.up.railway.app --origin https://<web>`. `--origin` verifica CORS;
# `--allow-test-model` es para `just serve` con el fake.
# Smoke test post-deploy de la API (F13.3)
smoke url *options:
    uv run python scripts/smoke.py {{url}} {{options}}
