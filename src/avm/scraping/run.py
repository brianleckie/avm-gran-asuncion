"""Punto de entrada del crawler de muestreo (F3.3).

    uv run python -m avm.scraping.run --source clasipar --budget 260 --per-target 19 --seed 42
    just scrape clasipar 260 19 42

Los cuatro parámetros son OBLIGATORIOS y no tienen default: el presupuesto de requests y el seed
tienen que ser una decisión explícita en cada corrida. Correr desde la raíz del repo: escribe en
`data/raw/<fecha>/<fuente>/` (caché sanitizada, `requests.jsonl`, `manifest.json`) y en
`data/interim/<fecha>/<fuente>/` (`raw_listings.jsonl`, `crawl_manifest.json`). `<fecha>` es la del
día en que arranca la corrida (la fecha del snapshot, ADR-006 punto 12).

Código de salida: 0 corrida completa (también si se agotó el presupuesto: queda dicho en el log y
en el manifest); 2 error de argumentos (argparse); 3 BLOQUEO de la fuente (se cortó todo, sin
reintentos: no volver a correr sin revisar); 4 otro corte (robots.txt no disponible).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from avm.scraping.base import DEFAULT_ROOT, BaseScraper
from avm.scraping.crawl import SourceSpec, crawl, utc_now
from avm.scraping.sources import clasipar

DEFAULT_INTERIM: Final = Path("data/interim")

EXIT_OK: Final = 0
EXIT_BLOCKED: Final = 3
EXIT_STOPPED: Final = 4

SOURCES: Final[dict[str, SourceSpec]] = {
    "clasipar": SourceSpec(
        name="clasipar",
        host=clasipar.HOST,
        sanitize=clasipar.sanitize_clasipar_html,
        targets=clasipar.search_urls,
        page_url=clasipar.page_url,
        parse_listing_page=clasipar.parse_listing_page,
        merge_refs=clasipar.merge_refs,
        parse_detail=clasipar.parse_detail,
    )
}


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} no es un entero") from None
    if value < 1:
        raise argparse.ArgumentTypeError("tiene que ser al menos 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m avm.scraping.run",
        description="Muestrea los listados de una fuente y guarda los avisos como RawListing.",
    )
    parser.add_argument(
        "--source", required=True, choices=sorted(SOURCES), help="fuente a recorrer"
    )
    parser.add_argument(
        "--budget",
        required=True,
        type=_positive_int,
        help="tope DURO de requests de la corrida (robots.txt, listados y reintentos incluidos)",
    )
    parser.add_argument(
        "--per-target",
        required=True,
        type=_positive_int,
        help="avisos a muestrear por búsqueda (tipo x ciudad)",
    )
    parser.add_argument(
        "--seed", required=True, type=int, help="semilla del muestreo (reproducible)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    raw_root: Path = DEFAULT_ROOT,
    interim_root: Path = DEFAULT_INTERIM,
    today: Callable[[], date] = date.today,
    utcnow: Callable[[], datetime] = utc_now,
    scraper_options: Mapping[str, Any] | None = None,
) -> int:
    """Corre el crawler. Los parámetros por nombre son para los tests (carpetas, hora y red)."""
    args = build_parser().parse_args(argv)
    spec = SOURCES[args.source]
    snapshot_date = today()
    out_dir = interim_root / snapshot_date.isoformat() / spec.name

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logger = logging.getLogger("avm.scraping")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with BaseScraper(
            source=spec.name,
            host=spec.host,
            snapshot_date=snapshot_date,
            max_requests=args.budget,
            sanitize=spec.sanitize,
            root=raw_root,
            utcnow=utcnow,
            **(scraper_options or {}),
        ) as scraper:
            result = crawl(
                scraper,
                spec,
                per_target=args.per_target,
                seed=args.seed,
                out_dir=out_dir,
                utcnow=utcnow,
            )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    if result.stopped == "blocked":
        return EXIT_BLOCKED
    if result.stopped in (None, "budget"):
        return EXIT_OK
    return EXIT_STOPPED


if __name__ == "__main__":  # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
