"""Listing (F1.3): alcance, procedencia, reglas de precio, geo y round-trip."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from avm.contract import (
    CoordinateFlag,
    Currency,
    GeoPrecision,
    Listing,
    OperationType,
    Provenance,
)


def base(**overrides: object) -> dict[str, object]:
    """Aviso válido en USD, sin coordenadas y con barrio normalizado."""
    data: dict[str, object] = {
        "source": "clasipar",
        "source_id": "2919242",
        "url": "https://clasipar.paraguay.com/inmuebles/casas/x-2919242",
        "scraped_at": datetime(2026, 10, 5, 23, 59, tzinfo=UTC),
        "content_hash": "b" * 64,
        "property_type": "casa",
        "city": "asuncion",
        "neighborhood_raw": "Villa Aurelia",
        "neighborhood_provenance": "estructurado",
        "neighborhood_norm": "Villa Aurelia",
        "neighborhood_match": "exacto",
        "price_amount": "235000",
        "price_currency": "USD",
        "currency_provenance": "texto",
        "price_raw": "US$. 235.000,00",
        "price_provenance": "estructurado",
        "is_from_price": False,
        "price_usd": "235000",
        "geo_precision": "barrio",
    }
    data.update(overrides)
    return data


PYG = {
    "price_amount": "1200000000",
    "price_currency": "PYG",
    "price_usd": "200000",
    "fx_rate_pyg_per_usd": "6000",
    "fx_date": date(2026, 10, 5),
}
COORDS = {
    "latitude": -25.3148,
    "longitude": -57.5614,
    "coordinates_provenance": "estructurado",
    "geo_precision": "aproximada",
}


def test_valid_listing_defaults() -> None:
    listing = Listing.model_validate(base())
    assert listing.operation is OperationType.SALE
    assert listing.has_pool is None and listing.coordinate_flags == ()


def test_amenities_are_tri_state() -> None:
    listing = Listing.model_validate(base(has_pool=True, has_quincho=False))
    assert (listing.has_pool, listing.has_quincho, listing.has_elevator) == (True, False, None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"city": "lambare"},
        {"property_type": "terreno"},
        {"operation": "alquiler"},
        {"built_area_m2": "-120", "built_area_provenance": "texto"},
        {"built_area_m2": "0", "built_area_provenance": "texto"},
        {"land_area_m2": "100001", "land_area_provenance": "texto"},
        {"bedrooms": -1},
        {"price_amount": "0", "price_usd": "0"},
        {"street_surface": "asfalto"},
        {"telefono": "0981123456"},
    ],
)
def test_out_of_scope_or_invalid_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(base(**overrides))


def test_price_currency_must_be_explicit() -> None:
    data = base()
    del data["price_currency"]
    with pytest.raises(ValidationError):
        Listing.model_validate(data)


def test_pyg_with_fx_rate_is_valid() -> None:
    listing = Listing.model_validate(base(**PYG))
    assert listing.price_currency is Currency.PYG
    assert listing.price_amount == Decimal("1200000000")


def test_unknown_currency_is_valid_without_usd() -> None:
    listing = Listing.model_validate(
        base(price_currency=None, currency_provenance=None, price_usd=None)
    )
    assert listing.price_currency is None and listing.price_usd is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_usd": "234000"},  # USD distinto del monto
        {"fx_rate_pyg_per_usd": "6000", "fx_date": date(2026, 10, 5)},  # USD con cotización
        {**PYG, "fx_rate_pyg_per_usd": None},  # PYG sin cotización
        {**PYG, "price_usd": "210000"},  # PYG con conversión incorrecta
        {"price_currency": None, "currency_provenance": None},  # moneda desconocida con USD
        {"price_currency": None, "price_usd": None},  # procedencia sin moneda
        {"currency_provenance": None},  # moneda sin procedencia
    ],
)
def test_price_rules(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(base(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"built_area_m2": "120"},
        {"land_area_provenance": "texto"},
        {"neighborhood_provenance": None},
        {"neighborhood_match": "sin_match"},
        {"neighborhood_norm": None, "geo_precision": "ciudad"},
    ],
)
def test_values_and_provenance_or_match_go_together(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(base(**overrides))


def test_unknown_currency_requires_raw_price_text() -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(
            base(price_currency=None, currency_provenance=None, price_usd=None, price_raw=None)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_raw": "Llamar 0981 123 456"},
        {"neighborhood_raw": "Zona 0981 123 456"},
        {"property_type_raw": "casa, info vendedor@ejemplo.com.py"},
    ],
)
def test_personal_data_is_rejected_in_listing_without_echoing_it(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as error:
        Listing.model_validate(base(**overrides))
    assert "datos personales" in str(error.value)
    assert "0981" not in str(error.value) and "vendedor" not in str(error.value)


def test_invalid_input_is_not_echoed_in_listing_errors() -> None:
    with pytest.raises(ValidationError) as error:
        Listing.model_validate(base(price_amount="abc 0981123456"))
    assert "0981123456" not in str(error.value)


def test_unmatched_neighborhood_uses_city_precision() -> None:
    listing = Listing.model_validate(
        base(neighborhood_norm=None, neighborhood_match="sin_match", geo_precision="ciudad")
    )
    assert listing.geo_precision is GeoPrecision.CITY


def test_listing_with_coordinates_and_shared_flag() -> None:
    listing = Listing.model_validate(base(**COORDS, coordinate_flags=["compartidas"]))
    assert listing.coordinate_flags == (CoordinateFlag.SHARED,)


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": -25.3},  # una sola coordenada
        {**COORDS, "coordinates_provenance": None},
        {"coordinate_flags": ["compartidas"]},  # flags sin coordenadas
        {**COORDS, "coordinate_flags": ["compartidas", "compartidas"]},
        {**COORDS, "geo_precision": "barrio"},  # con coordenadas, precisión sin coordenadas
        {"geo_precision": "exacta"},  # sin coordenadas, precisión con coordenadas
        {"neighborhood_norm": None, "neighborhood_match": None},  # barrio sin barrio
        {"geo_precision": "ciudad"},  # ciudad con barrio normalizado
        {**COORDS, "geo_precision": "exacta", "coordinate_flags": ["compartidas"]},
        {**COORDS, "latitude": -91},
        {**COORDS, "longitude": 181},
    ],
)
def test_geo_rules(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(base(**overrides))


def test_text_provenance_is_recorded() -> None:
    listing = Listing.model_validate(
        base(built_area_m2="90", built_area_provenance="texto", is_from_price=True)
    )
    assert listing.built_area_provenance is Provenance.TEXT
    assert listing.is_from_price


@pytest.mark.parametrize("extra", [{}, PYG, COORDS])
def test_json_round_trip(extra: dict[str, object]) -> None:
    url = "https://clasipar.paraguay.com/inmuebles/casas/X_y?a=1#f"
    listing = Listing.model_validate(base(**extra, url=url, garages=2, has_pool=False))
    again = Listing.model_validate_json(listing.model_dump_json())
    assert again == listing
    assert again.url == url
