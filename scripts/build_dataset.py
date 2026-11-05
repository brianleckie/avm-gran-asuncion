"""Construye dataset.csv (I1) y quality_report.md desde la caché de data/interim (F4/F5).

Uso (desde la raíz del repo; en la terminal va en una sola línea):
    uv run python scripts/build_dataset.py --snapshot 2026-10-06 2026-11-04
        --fx-pyg-per-usd 6085 --fx-date 2026-11-04 --fx-source "<quién, tipo y fecha>"
        --gazetteer none

La lógica está en `avm.pipeline.build`; ver su docstring para las reglas.
"""

from avm.pipeline.build import main

if __name__ == "__main__":
    raise SystemExit(main())
