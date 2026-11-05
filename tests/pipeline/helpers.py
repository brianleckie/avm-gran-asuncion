"""RawListing sintéticos para los tests del builder. Todo inventado: nada sale de un portal."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from avm.contract import RawListing, Source
from avm.pipeline.clean import FxContext, Row, raw_to_row
from avm.pipeline.neighborhood import Gazetteer

SCRAPED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
SNAPSHOT = date(2026, 11, 4)
FX = FxContext(Decimal(6085), date(2026, 11, 4), "fuente de prueba")
NO_GAZETTEER = Gazetteer()
HASH = "a" * 64


def make_raw(
    source_id: str = "1001",
    *,
    title: str | None = "Casa de prueba",
    description: str | None = None,
    price: str | None = "US$. 100.000",
    built_tag: str | None = None,
    land_tag: str | None = None,
    attributes: dict[str, str] | None = None,
    property_type: str | None = "casas",
    city: str | None = "Luque",
    zone: str | None = "Zona de Prueba",
    operation: str | None = "Vendo",
    advertiser: str | None = "Particular",
    bedrooms: str | None = None,
    bathrooms: str | None = None,
    garages: str | None = None,
    published: str | None = "29/09/2026",
    scraped_at: datetime = SCRAPED,
    built_area_raw: str | None = None,
    land_area_raw: str | None = None,
    sponsored: bool = False,
) -> RawListing:
    """Un RawListing válido. `built_tag`/`land_tag` van a `attributes_raw` (snapshots viejos)."""
    attrs = dict(attributes or {})
    if built_tag is not None:
        attrs["Superficie construida"] = built_tag
    if land_tag is not None:
        attrs["Superficie de terreno m2"] = land_tag
    if sponsored:
        attrs["patrocinado"] = "si"
    return RawListing(
        source=Source.CLASIPAR,
        source_id=source_id,
        url=f"https://clasipar.paraguay.com/inmuebles/casas/prueba-{source_id}",
        scraped_at=scraped_at,
        content_hash=HASH,
        title_raw=title,
        description_raw=description,
        price_raw=price,
        built_area_raw=built_area_raw,
        land_area_raw=land_area_raw,
        bedrooms_raw=bedrooms,
        bathrooms_raw=bathrooms,
        garages_raw=garages,
        property_type_raw=property_type,
        operation_raw=operation,
        city_raw=city,
        neighborhood_raw=zone,
        published_at_raw=published,
        advertiser_type_raw=advertiser,
        attributes_raw=attrs,
    )


def make_row(source_id: str = "1001", gazetteer: Gazetteer = NO_GAZETTEER, **kwargs: object) -> Row:
    """El Row de un aviso que tiene que pasar todas las reglas (falla el test si no)."""
    kwargs.setdefault("built_tag", "100")
    outcome = raw_to_row(make_raw(source_id, **kwargs), SNAPSHOT, FX, gazetteer)  # type: ignore[arg-type]
    assert isinstance(outcome, Row), outcome
    return outcome
