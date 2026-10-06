"""RawListing (F1.2): construcción, rechazos, round-trip y fixtures reales de Clasipar."""

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from avm.contract import RawListing, Source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "clasipar"
SCRAPED_AT = datetime(2026, 10, 5, 23, 59, tzinfo=UTC)


def base(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "source": "sintetico",
        "source_id": "123",
        "url": "https://ejemplo.invalid/aviso-123",
        "scraped_at": SCRAPED_AT,
        "content_hash": "a" * 64,
    }
    data.update(overrides)
    return data


def test_minimal_raw_listing_is_valid() -> None:
    raw = RawListing.model_validate(base())
    assert raw.source is Source.SYNTHETIC
    assert raw.price_raw is None and raw.attributes_raw == {}


def test_blank_raw_text_becomes_none_but_content_is_not_stripped() -> None:
    raw = RawListing.model_validate(base(latitude_raw="", price_raw="  Gs. 1.000  "))
    assert raw.latitude_raw is None
    assert raw.price_raw == "  Gs. 1.000  "


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "otro_portal"),
        ("source_id", "  "),
        ("url", "ftp://ejemplo.invalid/x"),
        ("url", "/inmuebles/casas/x"),
        ("url", "https://ejemplo.invalid/a b"),
        ("scraped_at", datetime(2026, 10, 5, 12, 0)),
        ("scraped_at", datetime(2026, 10, 5, 12, 0, tzinfo=timezone(timedelta(hours=-3)))),
        ("content_hash", "A" * 64),
        ("content_hash", "a" * 63),
        ("telefono", "0981 123 456"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RawListing.model_validate(base(**{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"description_raw": "Llamar al 0981 123 456"},
        {"description_raw": "Oficina (595 21) 414 1690"},
        {"title_raw": "Escribir a vendedor@ejemplo.com.py"},
        {"description_raw": "https://wa.me/595981123456"},
        {"attributes_raw": {"Contacto": "0981-123-456"}},
    ],
)
def test_personal_data_is_rejected_without_echoing_it(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        RawListing.model_validate(base(**overrides))
    assert "datos personales" in str(error.value)
    assert "123" not in str(error.value).replace("source_id", "")


def test_prices_and_ids_are_not_mistaken_for_phones() -> None:
    raw = RawListing.model_validate(
        base(price_raw="Gs. 1.050.000.000", description_raw="ID: 38434 vf. 1.213 m2")
    )
    assert raw.price_raw == "Gs. 1.050.000.000"


def test_json_round_trip_keeps_url_identical() -> None:
    url = "https://clasipar.paraguay.com/inmuebles/casas/X-Y_z?ref=1&b=%C3%B3#frag"
    raw = RawListing.model_validate(base(url=url, attributes_raw={"Quincho": "SI"}))
    again = RawListing.model_validate_json(raw.model_dump_json())
    assert again == raw
    assert again.url == url


# --- Fixtures reales (F3.1) -------------------------------------------------------------------
# Los objetos se arman a mano con valores copiados de los HTML; cada valor se verifica contra el
# fixture para garantizar que es un valor observado y no uno inventado.


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_hash(name: str) -> str:
    return hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()


DETAIL_HOUSE = {
    "source": "clasipar",
    "source_id": "2919242",
    "url": "https://clasipar.paraguay.com/inmuebles/casas/casa-a-la-venta-en-villa-aurelia-asuncion-2919242",
    "price_raw": "Gs. 1.200.000.000",
    "property_type_raw": "House",
    "city_raw": "Asunción",
    "neighborhood_raw": "Villa Aurelia",
    "latitude_raw": "-25.314827172122374",
    "longitude_raw": "-57.56149041173563",
    "bedrooms_raw": "2",
    "published_at_raw": "03/09/2026",
    "description_raw": "Dimenciones 379 m2",
    "attributes_raw": {"Habitación en suite": "1", "Quincho": "SI"},
}
DETAIL_DUPLEX = {
    "source": "clasipar",
    "source_id": "2926791",
    "url": "https://clasipar.paraguay.com/inmuebles/duplex/vendo-hermosa-casa-a-estrenar-en-luque-2926791",
    "price_raw": "Gs. 530.000.000",
    "property_type_raw": "House",
    "city_raw": "Luque",
    "neighborhood_raw": "Luque",
    "published_at_raw": "18/09/2026",
    "description_raw": "Terreno: 180 m²",
}
LISTING_CARD = {
    "source": "clasipar",
    "source_id": "2919242",
    "url": "https://clasipar.paraguay.com/inmuebles/casas/casa-a-la-venta-en-villa-aurelia-asuncion-2919242",
    "title_raw": "Casa a la venta en Villa Aurelia - Asunción",
    "price_raw": "Gs. 1.200.000.000",
    "operation_raw": "Vendo",
    "advertiser_type_raw": "Inmobiliaria",
}


@pytest.mark.parametrize(
    ("fixture", "values"),
    [
        ("detalle_1.html", DETAIL_HOUSE),
        ("detalle_2.html", DETAIL_DUPLEX),
        ("listado.html", LISTING_CARD),
    ],
)
def test_real_fixture_values_fit_in_raw_listing(fixture: str, values: dict[str, object]) -> None:
    text = fixture_text(fixture)
    for key, value in values.items():
        observed = value.items() if isinstance(value, dict) else [(None, value)]
        for attr_key, attr_value in observed:
            if key != "source":
                assert str(attr_value) in text, f"{key}={attr_value!r} no está en {fixture}"
            if attr_key is not None:
                assert attr_key in text
    raw = RawListing.model_validate(
        {**values, "scraped_at": SCRAPED_AT, "content_hash": fixture_hash(fixture)}
    )
    assert RawListing.model_validate_json(raw.model_dump_json()) == raw


def test_empty_json_ld_coordinates_of_real_fixture_become_none() -> None:
    text = fixture_text("detalle_2.html")
    assert '"latitude": ""' in text
    raw = RawListing.model_validate(
        {
            **DETAIL_DUPLEX,
            "latitude_raw": "",
            "longitude_raw": "",
            "scraped_at": SCRAPED_AT,
            "content_hash": fixture_hash("detalle_2.html"),
        }
    )
    assert raw.latitude_raw is None and raw.longitude_raw is None
