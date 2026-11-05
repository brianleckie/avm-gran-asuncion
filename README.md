# AVM Gran Asunción

Automated Valuation Model (AVM) que estima el **precio de oferta** por m² y el valor total de casas, departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la Mora, con un intervalo de predicción. Proyecto final de Ingeniería Informática (Brian Leckie y Oscar Arce).

> **Precio de oferta, no de transacción.** Los datos salen de avisos publicados en portales y en Paraguay no existe un registro público de precios de cierre. Todo resultado del proyecto (métricas, API, UI, informe) mide qué tan bien se predice el precio publicado, no el de una venta concretada. Ver [ADR-001](docs/adr/001-precio-publicado.md).

## Instalación

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.12 si hace falta) y, opcionalmente, [just](https://just.systems/) (`uv tool install rust-just`).

```bash
uv sync                 # crea .venv e instala el paquete y las dependencias de desarrollo
uv run pytest           # corre los tests
uv run pre-commit install   # hooks de git (una vez por clon)
```

Con `just`: `just install`, `just test`, `just check` (lint + mypy + tests). `just --list` muestra todas las tareas; `just scrape <fuente> <presupuesto> <páginas_por_búsqueda> <por_búsqueda> <seed>` (F3.3, los 5 parámetros son obligatorios) es la única tarea del pipeline implementada; el resto todavía no.

## API y web (local)

```powershell
# Terminal 1: API con el predictor de PRUEBA (solo desarrollo; sus valores no significan nada)
$env:AVM_PREDICTOR = "fake"; $env:AVM_CORS_ORIGIN = "http://localhost:5173"; just serve

# Terminal 2: web
cd web; npm install; Copy-Item .env.example .env.local; npm run dev
```

Con el modelo de Oscar (`models/<version>/`): `AVM_PREDICTOR=model` y `AVM_MODEL_DIR=models\<version>`. Variables y comportamiento en `src/avm/api/config.py`.

## Más información

- [ROADMAP.md](ROADMAP.md): tareas por fase, con responsable.
- [CLAUDE.md](CLAUDE.md): reglas del proyecto y estructura del código.
- [docs/adr/](docs/adr/): decisiones de arquitectura.
