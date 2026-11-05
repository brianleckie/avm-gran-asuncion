"""`just build-dataset` (F4/F5): caché de `data/interim` → `data/processed/<snapshots>/dataset.csv`.

    uv run python scripts/build_dataset.py --snapshot 2026-10-06 2026-11-04 --fx-pyg-per-usd 6085
        --fx-date 2026-11-04 --fx-source "<texto>" --gazetteer none   (en una sola línea)

Todos los parámetros son OBLIGATORIOS y sin default. Sin red: lee `raw_listings.jsonl` de cada
snapshot (`<interim>/<fecha>/clasipar/`). Salida: `dataset.csv` con EXACTAMENTE las columnas de I1
(docs/interfaces.md) y `quality_report.md` (solo agregados). No pisa una salida existente.

Orden (el embudo del reporte lo sigue): se unen los snapshots → duplicados exactos (la fila más
reciente) → `raw_to_row` (precio, superficies, barrio, features; ver `clean.py`) → outliers a priori
(`outliers.py`) → `cluster_id` (`dedup.py`). Cada descarte se cuenta por regla.

`snapshot_date` de cada fila es la fecha de SU snapshot (I1). La carpeta de salida se llama como los
snapshots unidos con `_`. Código de salida: 0 ok, 2 error de argumentos o de entrada.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from avm.contract import CONTRACT_VERSION, RawListing
from avm.pipeline.clean import (
    DISCARD_ORDER,
    Discard,
    FxContext,
    Row,
    city_of,
    property_type_of,
    raw_to_row,
)
from avm.pipeline.dedup import assign_clusters, collapse_exact, listing_key
from avm.pipeline.neighborhood import Gazetteer, load_gazetteer
from avm.pipeline.outliers import OUTLIER_ORDER, outlier_rule

SOURCE: Final = "clasipar"
DEFAULT_INTERIM: Final = Path("data/interim")
DEFAULT_OUT: Final = Path("data/processed")
INVALID_RAW: Final = "registro_crudo_invalido"
EXACT_DUPLICATE: Final = "duplicado_exacto_mismo_source_id"
NO_TYPE: Final = "sin_tipo"
NO_CITY: Final = "sin_ciudad"

# Columnas de I1 (docs/interfaces.md), en orden. Un test las compara con el generador sintético.
DATASET_COLUMNS: Final = (
    "listing_key",
    "cluster_id",
    "snapshot_date",
    "city",
    "neighborhood",
    "neighborhood_match",
    "geo_precision",
    "property_type",
    "price_usd",
    "built_area_m2",
    "built_area_source",
    "land_area_m2",
    "bedrooms",
    "bathrooms",
    "garages",
    "has_pool",
    "has_quincho",
    "is_new",
    "in_gated_community",
    "has_elevator",
    "street_surface",
    "advertiser_type",
    "is_sponsored",
    "usd_per_m2",
    "log_usd_per_m2",
)


@dataclass(slots=True)
class Params:
    """Parámetros de una corrida (se vuelcan al reporte)."""

    snapshots: tuple[date, ...]
    fx: FxContext
    gazetteer: Path | None


@dataclass(slots=True)
class Pipeline:
    """Resultado de una corrida: filas finales, clusters y los conteos del embudo."""

    params: Params
    read: dict[date, int] = field(default_factory=dict)  # líneas leídas por snapshot
    invalid_raw: int = 0
    exact_collapsed: int = 0
    unique: int = 0
    discards: Counter[str] = field(default_factory=Counter)
    contract_details: Counter[str] = field(default_factory=Counter)
    scope_in: Counter[tuple[str, str]] = field(default_factory=Counter)  # (tipo, ciudad) únicos
    rows: list[Row] = field(default_factory=list)
    clusters: dict[str, str] = field(default_factory=dict)  # listing_key -> cluster_id


def load_raw(path: Path) -> tuple[list[RawListing], int]:
    """Los `RawListing` de un `raw_listings.jsonl` y cuántas líneas no validan."""
    items: list[RawListing] = []
    invalid = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                items.append(RawListing.model_validate_json(line))
            except ValidationError:
                invalid += 1
    return items, invalid


def run_pipeline(params: Params, interim_root: Path, gazetteer: Gazetteer) -> Pipeline:
    """Corre el embudo completo en memoria (ver docstring del módulo)."""
    result = Pipeline(params=params)
    incoming: list[tuple[date, RawListing]] = []
    for snapshot in params.snapshots:
        path = interim_root / snapshot.isoformat() / SOURCE / "raw_listings.jsonl"
        items, invalid = load_raw(path)
        result.read[snapshot] = len(items) + invalid
        result.invalid_raw += invalid
        incoming.extend((snapshot, raw) for raw in items)

    unique, result.exact_collapsed = collapse_exact(incoming)
    result.unique = len(unique)
    for _, raw in unique:
        kind = property_type_of(raw)
        city = city_of(raw)
        result.scope_in[(kind.value if kind else NO_TYPE, city.value if city else NO_CITY)] += 1

    rows: list[Row] = []
    for snapshot, raw in unique:
        outcome = raw_to_row(raw, snapshot, params.fx, gazetteer)
        if isinstance(outcome, Discard):
            result.discards[outcome.rule.value] += 1
            for part in (outcome.detail or "").split(";"):
                if part:  # un aviso cuenta una vez por cada campo:tipo que el contrato rechazó
                    result.contract_details[part] += 1
            continue
        built = outcome.listing.built_area_m2
        assert built is not None
        outlier = outlier_rule(outcome.listing.property_type, built, outcome.usd_per_m2)
        if outlier is not None:
            result.discards[outlier.value] += 1
            continue
        rows.append(outcome)

    rows.sort(key=lambda row: listing_key(row.listing.source.value, row.listing.source_id))
    result.rows = rows
    result.clusters = assign_clusters(rows)
    missing = [row for row in rows if _key(row) not in result.clusters]
    if missing:  # ADR-006: todas las filas tienen cluster o falla
        raise RuntimeError(f"{len(missing)} filas sin cluster_id")
    return result


def _key(row: Row) -> str:
    return listing_key(row.listing.source.value, row.listing.source_id)


def funnel_rules() -> tuple[str, ...]:
    """Reglas de descarte en el orden del embudo (sin las de carga y duplicados)."""
    return (*(rule.value for rule in DISCARD_ORDER), *(rule.value for rule in OUTLIER_ORDER))


# ------------------------------------------------------------------------------------- CSV


def _tri(value: bool | None) -> str:
    return "" if value is None else ("1" if value else "0")


def _opt(value: object) -> str:
    return "" if value is None else str(value)


def _plain(value: Decimal) -> str:
    """Decimal sin ceros de más ni notación científica (100 y no 1E+2)."""
    return format(value.normalize(), "f")


def _fixed(value: Decimal, places: int) -> str:
    return str(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def dataset_row(row: Row, cluster_id: str) -> dict[str, str]:
    """La fila de I1 de un aviso. `usd_per_m2` y su log son el target (docs/interfaces.md)."""
    listing = row.listing
    assert listing.price_usd is not None and listing.built_area_m2 is not None
    return {
        "listing_key": _key(row),
        "cluster_id": cluster_id,
        "snapshot_date": row.snapshot_date.isoformat(),
        "city": listing.city.value,
        "neighborhood": listing.neighborhood_norm or "",
        "neighborhood_match": _opt(listing.neighborhood_match.value),
        "geo_precision": listing.geo_precision.value,
        "property_type": listing.property_type.value,
        "price_usd": _fixed(listing.price_usd, 2),
        "built_area_m2": _plain(listing.built_area_m2),
        "built_area_source": row.built_area_source,
        "land_area_m2": _plain(listing.land_area_m2) if listing.land_area_m2 else "",
        "bedrooms": _opt(listing.bedrooms),
        "bathrooms": _opt(listing.bathrooms),
        "garages": _opt(listing.garages),
        "has_pool": _tri(listing.has_pool),
        "has_quincho": _tri(listing.has_quincho),
        "is_new": _tri(listing.is_new),
        "in_gated_community": _tri(listing.in_gated_community),
        "has_elevator": _tri(listing.has_elevator),
        "street_surface": listing.street_surface.value if listing.street_surface else "",
        "advertiser_type": listing.advertiser_type.value if listing.advertiser_type else "",
        "is_sponsored": "1" if row.is_sponsored else "0",
        "usd_per_m2": _fixed(row.usd_per_m2, 4),
        "log_usd_per_m2": f"{math.log(float(row.usd_per_m2)):.6f}",
    }


def write_dataset(result: Pipeline, path: Path) -> None:
    """Escribe `dataset.csv` (UTF-8, `,`, encabezado). Modo `x`: nunca pisa un archivo."""
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()
        for row in result.rows:
            writer.writerow(dataset_row(row, result.clusters[_key(row)]))


# ------------------------------------------------------------------------------------- CLI


def out_dir_name(snapshots: Sequence[date]) -> str:
    return "_".join(snapshot.isoformat() for snapshot in sorted(snapshots))


def build(
    params: Params,
    *,
    interim_root: Path = DEFAULT_INTERIM,
    out_root: Path = DEFAULT_OUT,
) -> Path:
    """Corre todo y escribe `dataset.csv` y `quality_report.md`. Devuelve la carpeta de salida."""
    from avm.pipeline.report import render_report  # evita el ciclo build <-> report

    out_dir = out_root / out_dir_name(params.snapshots)
    dataset, report = out_dir / "dataset.csv", out_dir / "quality_report.md"
    if dataset.exists() or report.exists():
        raise FileExistsError(f"{out_dir} ya tiene salida: no se pisa")
    gazetteer = load_gazetteer(params.gazetteer)
    result = run_pipeline(params, interim_root, gazetteer)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dataset(result, dataset)
    with report.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(render_report(result, contract_version=CONTRACT_VERSION))
    return out_dir


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} no es una fecha AAAA-MM-DD") from None


def _positive_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"{text!r} no es un número") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("tiene que ser un número positivo")
    return value


def _non_blank(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("no puede estar vacío")
    return text.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/build_dataset.py",
        description="Construye dataset.csv (I1) y quality_report.md desde data/interim.",
    )
    parser.add_argument(
        "--snapshot", required=True, nargs="+", type=_iso_date, help="fecha o lista de fechas"
    )
    parser.add_argument(
        "--fx-pyg-per-usd", required=True, type=_positive_decimal, help="guaraníes por dólar"
    )
    parser.add_argument("--fx-date", required=True, type=_iso_date, help="fecha de la cotización")
    parser.add_argument(
        "--fx-source", required=True, type=_non_blank, help="quién la publica, tipo y fecha"
    )
    parser.add_argument(
        "--gazetteer", required=True, help='ruta de gazetteer.csv (I2) o "none" (sin barrios)'
    )
    parser.add_argument(
        "--interim-root", type=Path, default=DEFAULT_INTERIM, help=argparse.SUPPRESS
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    snapshots = tuple(sorted(set(args.snapshot)))
    gazetteer = None if args.gazetteer.strip().lower() == "none" else Path(args.gazetteer)
    if gazetteer is not None and not gazetteer.is_file():
        parser.error("--gazetteer no es un archivo (usá una ruta existente o 'none')")
    for snapshot in snapshots:
        path = args.interim_root / snapshot.isoformat() / SOURCE / "raw_listings.jsonl"
        if not path.is_file():
            parser.error(f"no existe {path.as_posix()}")
    params = Params(
        snapshots=snapshots,
        fx=FxContext(args.fx_pyg_per_usd, args.fx_date, args.fx_source),
        gazetteer=gazetteer,
    )
    try:
        out_dir = build(params, interim_root=args.interim_root, out_root=args.out_root)
    except FileExistsError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"OK: dataset.csv y quality_report.md en {out_dir.as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
