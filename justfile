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
# Excepción: avm.contract se mide como paquete (son varios archivos chicos de schemas). Las comillas
# del glob evitan que sh lo expanda en Ubuntu; PowerShell las quita antes de pasarlo.
test:
    uv run pytest --cov=avm.pipeline.parsing --cov=avm.model.metrics --cov=avm.model.splits --cov=avm.contract --cov-branch --cov-report=
    uv run coverage report --show-missing --include=src/avm/pipeline/parsing.py --fail-under=95
    uv run coverage report --show-missing --include=src/avm/model/metrics.py --fail-under=95
    uv run coverage report --show-missing --include=src/avm/model/splits.py --fail-under=95
    uv run coverage report --show-missing --include="src/avm/contract/*" --fail-under=95

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

# --- Pipeline: todavía sin implementación (cada receta apunta a su tarea del ROADMAP) ---

scrape:
    @echo "No implementado, ver ROADMAP F3"
    @exit 1

build-dataset:
    @echo "No implementado, ver ROADMAP F4/F5"
    @exit 1

train:
    @echo "No implementado, ver ROADMAP F8"
    @exit 1

evaluate:
    @echo "No implementado, ver ROADMAP F10"
    @exit 1

serve:
    @echo "No implementado, ver ROADMAP F11"
    @exit 1
