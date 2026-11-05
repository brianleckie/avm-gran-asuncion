"""Amenities tri-estado, calle y conteos (F4.5). Frases sintéticas, valores escritos a mano."""

import pytest

from avm.contract import StreetSurface
from avm.pipeline.features import (
    AMENITY_PATTERNS,
    extract_amenities,
    extract_street_surface,
    parse_count,
    tri_state_from_text,
)

POOL = AMENITY_PATTERNS["has_pool"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Casa con piscina y quincho", True),
        ("PISCINA climatizada", True),
        ("Tiene piscina", True),
        ("Cuenta con piscina", True),
        ("Hay piscina en el fondo", True),
        ("Amplia casa de tres dormitorios", None),
        ("", None),
        ("Sin piscina", False),
        ("sin  piscina, con quincho", False),
        ("No tiene piscina", False),
        ("No cuenta con piscina", False),
        ("No posee piscina", False),
        ("No hay piscina", False),
        ("Sin quincho ni piscina", False),
        ("Carece de piscina", False),
        ("Sin cochera, con piscina", True),  # la coma corta la cláusula
        ("sin cochera y con piscina", True),  # el "con" pegado la hace positiva
        ("Sin piscina. Hermosa piscina climatizada", None),  # contradictorio
        ("sin piscina pero con piscina de uso común", None),
        ("Piscinas", True),
    ],
)
def test_pool_phrases(text: str, expected: bool | None) -> None:
    assert tri_state_from_text(text, POOL) is expected


def test_a_negation_far_from_the_mention_does_not_negate_it() -> None:
    # "sin" queda a más de 4 palabras de "piscina"
    assert tri_state_from_text("sin muebles pero entregada limpia y ordenada piscina", POOL) is True


@pytest.mark.parametrize(
    ("text", "field", "expected"),
    [
        ("Casa a estrenar", "is_new", True),
        ("para estrenar", "is_new", True),
        ("Usada, bien cuidada", "is_new", None),
        ("En Barrio Cerrado con seguridad", "in_gated_community", True),
        ("Condominio Los Pinos", "in_gated_community", True),
        ("no es condominio", "in_gated_community", False),
        ("Edificio con ascensor", "has_elevator", True),
        ("Sin ascensor", "has_elevator", False),
        ("quincho con parrilla", "has_quincho", True),
    ],
)
def test_the_other_amenities(text: str, field: str, expected: bool | None) -> None:
    assert extract_amenities(text, {}).values[field] is expected


def test_the_text_origin_is_regex_and_a_missing_mention_has_no_origin() -> None:
    result = extract_amenities("Casa con piscina", {})
    assert result.origins["has_pool"] == "regex"
    assert result.origins["has_elevator"] is None


@pytest.mark.parametrize(
    ("tags", "text", "pool", "origin"),
    [
        ({"Piscina": "SI"}, "", True, "tag"),
        ({"Piscina": "si"}, "sin piscina", True, "tag"),  # el tag manda sobre el texto
        ({"Piscina": "NO"}, "con piscina", False, "tag"),
        ({"piscina": " Sí "}, "", True, "tag"),
        ({"Piscina": "tal vez"}, "con piscina", True, "regex"),  # valor ilegible: cae al regex
        ({"Quincho": "SI"}, "con piscina", True, "regex"),  # otro tag no cuenta
        ({}, "", None, None),
    ],
)
def test_the_portal_tag_takes_precedence_over_the_text(
    tags: dict[str, str], text: str, pool: bool | None, origin: str | None
) -> None:
    result = extract_amenities(text, tags)
    assert result.values["has_pool"] is pool
    assert result.origins["has_pool"] == origin


def test_the_quincho_tag_is_read_too() -> None:
    result = extract_amenities("", {"Quincho": "SI"})
    assert (result.values["has_quincho"], result.origins["has_quincho"]) == (True, "tag")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sobre calle asfaltada", StreetSurface.PAVED),
        ("calle pavimentada", StreetSurface.PAVED),
        ("Ubicada sobre avenida asfaltada", StreetSurface.PAVED),
        ("sobre calle empedrada", StreetSurface.COBBLESTONE),
        ("calle de tierra", StreetSurface.DIRT),
        ("Terreno de tierra colorada", None),  # sin calle cerca: no es la superficie de la calle
        ("calle sin pavimento", None),  # negada: no se sabe cuál es
        ("calle empedrada, avenida pavimentada", None),  # dos superficies distintas
        ("calle empedrada y calle empedrada", StreetSurface.COBBLESTONE),
        ("casa en zona residencial", None),
    ],
)
def test_street_surface(text: str, expected: StreetSurface | None) -> None:
    assert extract_street_surface(text) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3), (" 2 ", 2), ("0", 0), ("03", 3), ("tres", None), ("-1", None), ("2.5", None)],
)
def test_parse_count(raw: str, expected: int | None) -> None:
    assert parse_count(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "٣"])
def test_parse_count_of_nothing_or_non_ascii_digits_is_none(raw: str | None) -> None:
    assert parse_count(raw) is None
