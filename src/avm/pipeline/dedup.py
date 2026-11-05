"""Deduplicación (F5.1 y F5.3 simple).

1. **Exactos** (`collapse_exact`): la misma `(source, source_id)` aparece una sola vez; si está en
   varios snapshots o repetida, se conserva la de `scraped_at` más reciente (a igual `scraped_at`,
   la del snapshot posterior). Se hace ANTES de los filtros para que el embudo cuente avisos únicos.
   Como queda una sola fila por aviso, el mismo aviso nunca cae a los dos lados de un split.
2. **Casi-duplicados** (`assign_clusters`), solo dentro de una fuente: bloque = (ciudad, tipo,
   barrio canónico, m² construidos redondeados a entero con .5 hacia arriba). Dentro del bloque, se
   ordena por precio USD y dos avisos consecutivos se unen si el más caro no supera en más de 1 % al
   más barato. Las componentes conexas son un `cluster_id` (single-linkage: por transitividad un
   cluster puede abarcar más de 1 % de extremo a extremo). El resto, cluster propio. Se dejan TODAS
   las filas del cluster (I1): el modelo decide y los splits agrupan por `cluster_id`.

Límites de la regla pedida, a propósito del lado seguro para leakage cuando fallan por exceso:
- sin gazetteer el barrio es vacío para todos: el bloque queda (ciudad, tipo, m²) y puede unir
  avisos de barrios distintos (agrupa de más, no de menos);
- el redondeo a entero puede partir un par en el borde (120,4 y 120,6 caen en bloques distintos).

`cluster_id` es determinístico: `c-` + el menor `listing_key` del cluster, con `:` → `-`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from avm.contract import RawListing
from avm.pipeline.clean import Row

PRICE_TOLERANCE: Final = Decimal("0.01")


def listing_key(source: str, source_id: str) -> str:
    return f"{source}:{source_id}"


def collapse_exact(
    items: Iterable[tuple[date, RawListing]],
) -> tuple[list[tuple[date, RawListing]], int]:
    """Una fila por `(source, source_id)`: la más reciente; devuelve cuántas se colapsaron."""
    latest: dict[tuple[str, str], tuple[date, RawListing]] = {}
    total = 0
    for snapshot, raw in items:
        total += 1
        key = (raw.source.value, raw.source_id)
        seen = latest.get(key)
        if seen is None or (raw.scraped_at, snapshot) > (seen[1].scraped_at, seen[0]):
            latest[key] = (snapshot, raw)
    return list(latest.values()), total - len(latest)


def _block(row: Row) -> tuple[str, str, str, Decimal]:
    listing = row.listing
    assert listing.built_area_m2 is not None
    return (
        listing.city.value,
        listing.property_type.value,
        listing.neighborhood_norm or "",
        listing.built_area_m2.quantize(Decimal(1), rounding=ROUND_HALF_UP),
    )


def _components[T](
    items: Sequence[T], price: Callable[[T], Decimal], key: Callable[[T], str]
) -> list[list[T]]:
    """Corridas de precios consecutivos con diferencia <= `PRICE_TOLERANCE` entre vecinos."""
    ordered = sorted(items, key=lambda item: (price(item), key(item)))
    groups: list[list[T]] = []
    for item in ordered:
        if groups and price(item) <= price(groups[-1][-1]) * (1 + PRICE_TOLERANCE):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def assign_clusters(rows: Sequence[Row]) -> dict[str, str]:
    """`listing_key` → `cluster_id` para TODAS las filas (ninguna queda sin cluster)."""
    blocks: dict[tuple[str, str, str, Decimal], list[Row]] = defaultdict(list)
    for row in rows:
        blocks[_block(row)].append(row)

    def price(row: Row) -> Decimal:
        assert row.listing.price_usd is not None
        return row.listing.price_usd

    def key(row: Row) -> str:
        return listing_key(row.listing.source.value, row.listing.source_id)

    clusters: dict[str, str] = {}
    for members in blocks.values():
        for group in _components(members, price, key):
            keys = [key(row) for row in group]
            cluster_id = "c-" + min(keys).replace(":", "-")
            for member in keys:
                clusters[member] = cluster_id
    return clusters
