"""RawListing → Listing (F4.1 a F4.3): precio, cotización, superficies y descartes.

Todos los avisos son sintéticos (armados en `helpers.make_raw`). Los valores esperados están
escritos a mano.
"""

from datetime import date
from decimal import Decimal

import pytest

from avm.contract import (
    AdvertiserType,
    City,
    Currency,
    GeoPrecision,
    Listing,
    NeighborhoodMatch,
    PropertyType,
    Provenance,
)
from avm.pipeline import clean
from avm.pipeline.clean import Discard, Row, Rule, raw_to_row
from avm.pipeline.neighborhood import Gazetteer, Reason
from tests.pipeline.helpers import FX, NO_GAZETTEER, SNAPSHOT, make_raw, make_row


def convert(**kwargs: object) -> Row | Discard:
    return raw_to_row(make_raw(**kwargs), SNAPSHOT, FX, NO_GAZETTEER)  # type: ignore[arg-type]


def discarded(**kwargs: object) -> Rule:
    outcome = convert(**kwargs)
    assert isinstance(outcome, Discard), outcome
    return outcome.rule


# ------------------------------------------------------------------------------------ precio


def test_a_price_in_usd_is_kept_as_it_is() -> None:
    row = make_row(price="US$. 285.000,00", built_tag="470")
    listing = row.listing
    assert listing.price_currency is Currency.USD
    assert listing.price_amount == Decimal(285000) and listing.price_usd == Decimal(285000)
    assert listing.fx_rate_pyg_per_usd is None and listing.fx_date is None
    assert round(row.usd_per_m2, 2) == Decimal("606.38")  # 285000 / 470


def test_a_price_in_guaranies_is_divided_by_the_rate_and_records_it() -> None:
    row = make_row(price="Gs. 1.217.000.000", built_tag="200")  # 6085 * 200000
    listing = row.listing
    assert listing.price_currency is Currency.PYG
    assert listing.price_amount == Decimal(1217000000)
    assert listing.price_usd == Decimal(200000)
    assert listing.fx_rate_pyg_per_usd == Decimal(6085) and listing.fx_date == date(2026, 11, 4)
    assert row.usd_per_m2 == Decimal(1000)  # 200000 / 200


def test_price_and_currency_come_from_the_portal_price_field() -> None:
    listing = make_row().listing
    assert listing.price_provenance is Provenance.STRUCTURED
    assert listing.currency_provenance is Provenance.STRUCTURED
    assert listing.price_raw == "US$. 100.000" and listing.is_from_price is False


@pytest.mark.parametrize(
    ("price", "rule"),
    [
        ("Consultar precio.", Rule.PRICE_UNREADABLE),
        ("", Rule.PRICE_UNREADABLE),
        (None, Rule.PRICE_UNREADABLE),
        ("Gs. 0", Rule.PRICE_ZERO),
        ("USD 0,00", Rule.PRICE_ZERO),
        ("150.000", Rule.CURRENCY_UNKNOWN),
        ("desde USD 90.000", Rule.FROM_PRICE),
        ("USD 100.000 - 120.000", Rule.FROM_PRICE),
    ],
)
def test_unusable_prices_are_discarded_with_their_own_rule(price: str | None, rule: Rule) -> None:
    assert discarded(price=price, built_tag="100") is rule


# ------------------------------------------------------------------------------------ alcance


@pytest.mark.parametrize("operation", ["Alquilo", "Doy en alquiler", None, ""])
def test_only_sales_are_in_scope(operation: str | None) -> None:
    assert discarded(operation=operation, built_tag="100") is Rule.OPERATION


@pytest.mark.parametrize("operation", ["Vendo", "VENDO", "Venta", "en venta"])
def test_the_sale_wordings_are_accepted(operation: str) -> None:
    assert isinstance(convert(operation=operation, built_tag="100"), Row)


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("casas", PropertyType.HOUSE),
        ("Casas", PropertyType.HOUSE),
        ("departamentos", PropertyType.APARTMENT),
        ("Departamentos", PropertyType.APARTMENT),
        ("duplex", PropertyType.DUPLEX),
        ("Dúplex", PropertyType.DUPLEX),
    ],
)
def test_property_type_mapping(raw_type: str, expected: PropertyType) -> None:
    assert make_row(property_type=raw_type).listing.property_type is expected


@pytest.mark.parametrize("raw_type", ["terrenos", "locales", None, ""])
def test_other_property_types_are_discarded(raw_type: str | None) -> None:
    assert discarded(property_type=raw_type, built_tag="100") is Rule.PROPERTY_TYPE


@pytest.mark.parametrize(
    ("raw_city", "expected"),
    [
        ("Asunción", City.ASUNCION),
        ("ASUNCION", City.ASUNCION),
        ("Luque", City.LUQUE),
        ("San Lorenzo", City.SAN_LORENZO),
        ("Fernando de la Mora", City.FERNANDO_DE_LA_MORA),
    ],
)
def test_city_mapping(raw_city: str, expected: City) -> None:
    assert make_row(city=raw_city).listing.city is expected


@pytest.mark.parametrize("raw_city", ["Encarnación", None, ""])
def test_missing_or_out_of_scope_cities_are_discarded(raw_city: str | None) -> None:
    assert discarded(city=raw_city, built_tag="100") is Rule.CITY


# ------------------------------------------------------------------------------------ m²


def test_the_tag_in_attributes_raw_of_an_old_snapshot_gives_the_built_area() -> None:
    row = make_row(built_tag="80", price="US$. 80.000")
    assert row.listing.built_area_m2 == Decimal(80)
    assert row.listing.built_area_provenance is Provenance.STRUCTURED
    assert row.built_area_source == "tag"


def test_the_built_area_raw_of_the_new_parser_is_read_too() -> None:
    row = make_row(built_tag=None, built_area_raw="90", land_area_raw="300")
    assert (row.listing.built_area_m2, row.listing.land_area_m2) == (Decimal(90), Decimal(300))
    assert row.listing.land_area_provenance is Provenance.STRUCTURED


def test_a_built_area_in_the_text_is_used_when_there_is_no_tag() -> None:
    row = make_row(built_tag=None, description="Casa de 120 m² construidos en un lote amplio")
    assert row.listing.built_area_m2 == Decimal(120)
    assert row.listing.built_area_provenance is Provenance.TEXT
    assert row.built_area_source == "texto"


def test_the_title_is_searched_too() -> None:
    row = make_row(built_tag=None, title="Casa 150 m2 construidos", description=None)
    assert row.listing.built_area_m2 == Decimal(150)


def test_an_area_without_a_type_does_not_count_as_built() -> None:
    assert discarded(built_tag=None, description="Departamento de 68 m2") is Rule.NO_BUILT_AREA


def test_a_land_area_in_the_text_does_not_count_as_built() -> None:
    assert discarded(built_tag=None, description="Terreno de 360 m2") is Rule.NO_BUILT_AREA


def test_no_area_at_all_is_discarded() -> None:
    assert discarded(built_tag=None, description="Muy linda casa") is Rule.NO_BUILT_AREA


def test_the_tag_wins_over_a_text_within_10_percent() -> None:
    row = make_row(built_tag="100", description="105 m² construidos")
    assert row.listing.built_area_m2 == Decimal(100) and row.built_area_source == "tag"


def test_a_gap_of_exactly_10_percent_is_not_discarded_but_more_is() -> None:
    assert isinstance(convert(built_tag="100", description="110 m² construidos"), Row)
    assert isinstance(convert(built_tag="100", description="90 m² construidos"), Row)
    assert discarded(built_tag="100", description="111 m² construidos") is Rule.AREA_MISMATCH
    assert discarded(built_tag="100", description="89 m² construidos") is Rule.AREA_MISMATCH


def test_the_text_is_compared_with_the_first_built_expression_and_the_rest_is_counted() -> None:
    row = make_row(built_tag="100", description="100 m² construidos y 130 m² construidos")
    assert row.listing.built_area_m2 == Decimal(100)
    assert row.text_built_values == 2


def test_the_land_area_comes_from_the_tag_then_from_the_text() -> None:
    from_tag = make_row(land_tag="360", description="terreno de 500 m2").listing
    assert (from_tag.land_area_m2, from_tag.land_area_provenance) == (
        Decimal(360),
        Provenance.STRUCTURED,
    )
    from_text = make_row(
        built_tag=None, description="120 m² construidos sobre terreno de 500 m2"
    ).listing
    assert (from_text.land_area_m2, from_text.land_area_provenance) == (
        Decimal(500),
        Provenance.TEXT,
    )
    none = make_row().listing
    assert none.land_area_m2 is None and none.land_area_provenance is None


# ------------------------------------------------------------------------------------ barrio


def test_without_a_gazetteer_the_barrio_is_unmatched_and_the_precision_is_city() -> None:
    row = make_row()
    listing = row.listing
    assert listing.neighborhood_raw == "Zona de Prueba"
    assert listing.neighborhood_provenance is Provenance.STRUCTURED
    assert (listing.neighborhood_norm, listing.neighborhood_match) == (
        None,
        NeighborhoodMatch.UNMATCHED,
    )
    assert listing.geo_precision is GeoPrecision.CITY
    assert row.neighborhood_reason is Reason.NO_GAZETTEER


def test_a_matched_barrio_gives_barrio_precision(tmp_path: object) -> None:
    gazetteer = Gazetteer(
        {City.LUQUE: clean_index({"zona de prueba": "Zona de Prueba"})}  # type: ignore[arg-type]
    )
    row = make_row(gazetteer=gazetteer)
    assert row.listing.neighborhood_norm == "Zona de Prueba"
    assert row.listing.neighborhood_match is NeighborhoodMatch.EXACT
    assert row.listing.geo_precision is GeoPrecision.NEIGHBORHOOD


def clean_index(canonical: dict[str, str]):  # noqa: ANN201
    from avm.pipeline.neighborhood import _CityIndex

    return _CityIndex(canonical=canonical)


def test_a_zone_equal_to_the_city_is_city_precision() -> None:
    row = make_row(zone="Luque")
    assert row.neighborhood_reason is Reason.SAME_AS_CITY
    assert row.listing.geo_precision is GeoPrecision.CITY


def test_a_missing_zone_has_no_neighborhood_raw_and_no_provenance() -> None:
    listing = make_row(zone=None).listing
    assert listing.neighborhood_raw is None and listing.neighborhood_provenance is None


# ------------------------------------------------------------------------------------ otros


def test_counts_advertiser_sponsored_and_dates() -> None:
    row = make_row(
        bedrooms="3",
        bathrooms="tres",
        garages=None,
        advertiser="Inmobiliaria",
        sponsored=True,
        published="29/09/2026",
    )
    listing = row.listing
    assert (listing.bedrooms, listing.bathrooms, listing.garages) == (3, None, None)
    assert listing.advertiser_type is AdvertiserType.AGENCY
    assert row.is_sponsored is True
    assert listing.published_at == date(2026, 9, 29)
    assert row.snapshot_date == SNAPSHOT


def test_unknown_advertiser_and_unreadable_dates_are_left_empty() -> None:
    row = make_row(advertiser=None, published="mañana")
    assert row.listing.advertiser_type is None and row.listing.published_at is None
    assert make_row(published=None).listing.published_at is None
    assert make_row(sponsored=False).is_sponsored is False


def test_amenities_and_street_surface_are_extracted() -> None:
    row = make_row(
        attributes={"Piscina": "SI"},
        description="Sin quincho. Sobre calle empedrada. Edificio con ascensor",
    )
    listing = row.listing
    assert (listing.has_pool, listing.has_quincho, listing.has_elevator) == (True, False, True)
    assert listing.is_new is None
    assert listing.street_surface is not None and listing.street_surface.value == "empedrado"
    assert row.amenity_origins["has_pool"] == "tag"
    assert row.amenity_origins["has_quincho"] == "regex"


def test_coordinates_are_not_used() -> None:
    listing = make_row().listing
    assert listing.latitude is None and listing.longitude is None


def test_the_content_hash_and_traceability_are_carried_over() -> None:
    raw = make_raw("42", built_tag="100")
    row = raw_to_row(raw, SNAPSHOT, FX, NO_GAZETTEER)
    assert isinstance(row, Row)
    assert (row.listing.source_id, row.listing.url) == ("42", raw.url)
    assert (row.listing.content_hash, row.listing.scraped_at) == (raw.content_hash, raw.scraped_at)


def test_a_listing_the_contract_rejects_is_discarded_with_field_and_type_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(**_: object) -> Listing:
        return Listing.model_validate({})

    monkeypatch.setattr(clean, "Listing", reject)
    outcome = convert(built_tag="100")
    assert isinstance(outcome, Discard) and outcome.rule is Rule.CONTRACT
    assert outcome.detail is not None
    assert "source:missing" in outcome.detail.split(";") and "100" not in outcome.detail
