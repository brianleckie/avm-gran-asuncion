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

# Corre los tests; exige ≥ 95 % de cobertura (líneas y ramas) sobre avm.pipeline.parsing (adelanto de F4.1/F4.3)
test:
    uv run pytest --cov=avm.pipeline.parsing --cov-branch --cov-report=term-missing --cov-fail-under=95

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
