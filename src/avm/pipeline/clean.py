"""RawListing → Listing (F4.1 a F4.5): precio y cotización, superficies, barrio y features.

`raw_to_row` devuelve un `Row` (el `Listing` del contrato más lo que el dataset necesita y el
contrato no tiene) o un `Discard` con la regla que lo descartó. Las reglas se aplican EN ESTE ORDEN
y un aviso se cuenta en la primera que falla (embudo secuencial, `DISCARD_ORDER`):

1. operación fuera de alcance (solo "Vendo"), tipo no mapeable, ciudad ausente o fuera de alcance;
2. precio: sin monto interpretable ("consultar"), monto cero, moneda desconocida (ADR-005: se
   descarta, nunca se adivina), "desde"/rango (`is_from_price`, ADR-006);
3. m² construidos: precedencia tag > texto con `kind=construida`; `kind=None` NO cuenta. Si el tag
   y el texto existen y difieren más de 10 % (relativo al tag) se descarta el aviso, no se elige;
4. el contrato (`Listing`) rechaza el aviso (se cuenta por campo:tipo, nunca con el valor).

Precio (ADR-004): USD tal cual; PYG ÷ cotización, con `fx_rate_pyg_per_usd` y `fx_date` en el
`Listing`. Procedencia: el precio y su moneda vienen del campo de precio del portal
(`estructurado`).

Los tags de superficie se toman de `built_area_raw`/`land_area_raw` (parser de F3.4) y, si están
vacíos, de `attributes_raw` con la misma regla (casefold): así sirven los snapshots anteriores
a F3.4.
Las coordenadas NO se usan (ADR-003: geo a nivel barrio): `geo_precision` es `barrio` o `ciudad`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import ValidationError

from avm.contract import (
    AdvertiserType,
    City,
    Currency,
    GeoPrecision,
    Listing,
    OperationType,
    PropertyType,
    Provenance,
    RawListing,
)
from avm.pipeline.areas import find_areas, tag_area
from avm.pipeline.features import (
    Origin,
    extract_amenities,
    extract_street_surface,
    parse_count,
)
from avm.pipeline.neighborhood import Gazetteer, Reason, match_neighborhood, normalize_name
from avm.pipeline.parsing import parse_price

AREA_TOLERANCE: Final = Decimal("0.10")  # |tag - texto| / tag por encima del cual se descarta
TAG_BUILT: Final = "superficie construida"
TAG_LAND: Final = "superficie de terreno m2"
SPONSORED_KEY: Final = "patrocinado"


class Rule(StrEnum):
    """Reglas de descarte de `raw_to_row`, en el orden en que se aplican."""

    OPERATION = "operacion_fuera_de_alcance"
    PROPERTY_TYPE = "tipo_de_inmueble_no_mapeable"
    CITY = "ciudad_ausente_o_fuera_de_alcance"
    PRICE_UNREADABLE = "precio_sin_monto_interpretable"
    PRICE_ZERO = "precio_cero"
    CURRENCY_UNKNOWN = "moneda_desconocida"
    FROM_PRICE = "precio_desde_o_rango"
    NO_BUILT_AREA = "sin_m2_construidos"
    AREA_MISMATCH = "m2_tag_y_texto_difieren_mas_de_10pct"
    CONTRACT = "rechazado_por_el_contrato"


DISCARD_ORDER: Final = tuple(Rule)

_SALE: Final = frozenset({"vendo", "venta", "en venta"})
_PROPERTY_TYPES: Final = {
    "casa": PropertyType.HOUSE,
    "casas": PropertyType.HOUSE,
    "departamento": PropertyType.APARTMENT,
    "departamentos": PropertyType.APARTMENT,
    "duplex": PropertyType.DUPLEX,
}
_CITIES: Final = {normalize_name(city.value.replace("_", " ")): city for city in City}
_ADVERTISERS: Final = {
    "particular": AdvertiserType.PRIVATE,
    "inmobiliaria": AdvertiserType.AGENCY,
}
_DIGIT: Final = re.compile(r"\d")
_NONZERO_DIGIT: Final = re.compile(r"[1-9]")


@dataclass(frozen=True, slots=True)
class FxContext:
    """Cotización con la que se convierten los precios en guaraníes (ADR-004)."""

    rate_pyg_per_usd: Decimal
    date: date
    source: str


@dataclass(frozen=True, slots=True)
class Discard:
    rule: Rule
    detail: str | None = None  # solo para `Rule.CONTRACT`: "campo:tipo" separados por ";"


@dataclass(frozen=True, slots=True)
class Row:
    """Un aviso listo para el dataset: el `Listing` del contrato y lo que no tiene."""

    listing: Listing
    snapshot_date: date
    is_sponsored: bool
    built_area_source: str  # "tag" | "texto"
    usd_per_m2: Decimal
    amenity_origins: Mapping[str, Origin | None]
    neighborhood_reason: Reason
    text_built_values: int  # valores distintos de m² construidos en el texto (informativo)


def property_type_of(raw: RawListing) -> PropertyType | None:
    return _PROPERTY_TYPES.get(normalize_name(raw.property_type_raw or ""))


def city_of(raw: RawListing) -> City | None:
    return _CITIES.get(normalize_name(raw.city_raw or ""))


def _attribute(attributes: Mapping[str, str], label: str) -> str | None:
    for key, value in attributes.items():
        if key.casefold().strip() == label:
            return value
    return None


def _published(raw: str | None) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").date() if raw else None
    except ValueError:
        return None


def _contract_detail(error: ValidationError) -> str:
    """Campo:tipo de cada error de validación, sin el valor (que podría ser un dato del aviso)."""
    parts = {f"{'.'.join(str(p) for p in e['loc']) or '-'}:{e['type']}" for e in error.errors()}
    return ";".join(sorted(parts))


def raw_to_row(
    raw: RawListing, snapshot_date: date, fx: FxContext, gazetteer: Gazetteer
) -> Row | Discard:
    """Convierte un aviso crudo o dice qué regla lo descarta (ver docstring del módulo)."""
    if normalize_name(raw.operation_raw or "") not in _SALE:
        return Discard(Rule.OPERATION)
    property_type = property_type_of(raw)
    if property_type is None:
        return Discard(Rule.PROPERTY_TYPE)
    city = city_of(raw)
    if city is None:
        return Discard(Rule.CITY)

    # --- precio
    price_raw = raw.price_raw or ""
    price = parse_price(price_raw)
    if price is None:
        zero = _DIGIT.search(price_raw) and not _NONZERO_DIGIT.search(price_raw)
        return Discard(Rule.PRICE_ZERO if zero else Rule.PRICE_UNREADABLE)
    if price.currency is None:
        return Discard(Rule.CURRENCY_UNKNOWN)
    if price.is_from_price:
        return Discard(Rule.FROM_PRICE)
    currency = Currency(price.currency)
    in_pyg = currency is Currency.PYG
    price_usd = price.amount / fx.rate_pyg_per_usd if in_pyg else price.amount

    # --- superficies
    tag_built = tag_area(raw.built_area_raw or _attribute(raw.attributes_raw, TAG_BUILT))
    tag_land = tag_area(raw.land_area_raw or _attribute(raw.attributes_raw, TAG_LAND))
    built_text: list[Decimal] = []
    land_text: list[Decimal] = []
    for text in (raw.title_raw, raw.description_raw):
        for area in find_areas(text or ""):
            if area.kind == "construida":
                built_text.append(area.m2)
            elif area.kind == "terreno":
                land_text.append(area.m2)
    if tag_built is None and not built_text:
        return Discard(Rule.NO_BUILT_AREA)
    if tag_built is not None and built_text:
        gap = abs(tag_built - built_text[0]) / tag_built
        if gap > AREA_TOLERANCE:
            return Discard(Rule.AREA_MISMATCH)
    built = tag_built if tag_built is not None else built_text[0]
    built_source = Provenance.STRUCTURED if tag_built is not None else Provenance.TEXT
    land = tag_land if tag_land is not None else (land_text[0] if land_text else None)
    land_source = None
    if land is not None:
        land_source = Provenance.STRUCTURED if tag_land is not None else Provenance.TEXT

    # --- barrio
    zone = match_neighborhood(raw.neighborhood_raw, city, gazetteer, city_raw=raw.city_raw)

    # --- features
    text = "\n".join(part for part in (raw.title_raw, raw.description_raw) if part)
    amenities = extract_amenities(text, raw.attributes_raw)
    sponsored = (_attribute(raw.attributes_raw, SPONSORED_KEY) or "").casefold() == "si"

    try:
        listing = Listing(
            source=raw.source,
            source_id=raw.source_id,
            url=raw.url,
            scraped_at=raw.scraped_at,
            content_hash=raw.content_hash,
            operation=OperationType.SALE,
            property_type=property_type,
            property_type_raw=raw.property_type_raw,
            city=city,
            neighborhood_raw=raw.neighborhood_raw,
            neighborhood_provenance=Provenance.STRUCTURED if raw.neighborhood_raw else None,
            neighborhood_norm=zone.name,
            neighborhood_match=zone.match,
            price_amount=price.amount,
            price_currency=currency,
            price_raw=raw.price_raw,
            price_provenance=Provenance.STRUCTURED,
            currency_provenance=Provenance.STRUCTURED,
            is_from_price=False,
            price_usd=price_usd,
            fx_rate_pyg_per_usd=fx.rate_pyg_per_usd if in_pyg else None,
            fx_date=fx.date if in_pyg else None,
            built_area_m2=built,
            built_area_provenance=built_source,
            land_area_m2=land,
            land_area_provenance=land_source,
            bedrooms=parse_count(raw.bedrooms_raw),
            bathrooms=parse_count(raw.bathrooms_raw),
            garages=parse_count(raw.garages_raw),
            has_pool=amenities.values["has_pool"],
            has_quincho=amenities.values["has_quincho"],
            is_new=amenities.values["is_new"],
            in_gated_community=amenities.values["in_gated_community"],
            has_elevator=amenities.values["has_elevator"],
            street_surface=extract_street_surface(text),
            advertiser_type=_ADVERTISERS.get(normalize_name(raw.advertiser_type_raw or "")),
            published_at=_published(raw.published_at_raw),
            geo_precision=GeoPrecision.NEIGHBORHOOD if zone.name else GeoPrecision.CITY,
        )
    except ValidationError as error:
        return Discard(Rule.CONTRACT, _contract_detail(error))

    assert listing.price_usd is not None  # el validador lo garantiza con moneda conocida
    return Row(
        listing=listing,
        snapshot_date=snapshot_date,
        is_sponsored=sponsored,
        built_area_source="tag" if tag_built is not None else "texto",
        usd_per_m2=listing.price_usd / built,
        amenity_origins=amenities.origins,
        neighborhood_reason=zone.reason,
        text_built_values=len(set(built_text)),
    )


__all__ = [
    "AREA_TOLERANCE",
    "DISCARD_ORDER",
    "Discard",
    "FxContext",
    "Row",
    "Rule",
    "city_of",
    "property_type_of",
    "raw_to_row",
]
