"""Superficies de un texto y de un tag (F4.3). Valores esperados escritos a mano."""

from decimal import Decimal

import pytest

from avm.pipeline.areas import find_areas, tag_area


def test_find_areas_returns_every_expression_not_only_the_first() -> None:
    areas = find_areas("120 m² construidos sobre terreno de 360 m²")
    assert [(a.m2, a.kind) for a in areas] == [
        (Decimal(120), "construida"),
        (Decimal(360), "terreno"),
    ]


def test_find_areas_reads_dimensions_as_land_by_default() -> None:
    assert [(a.m2, a.kind) for a in find_areas("Lote de 12x30")] == [(Decimal(360), "terreno")]


def test_find_areas_keeps_an_expression_without_a_type_as_none() -> None:
    assert [(a.m2, a.kind) for a in find_areas("departamento de 68 m2")] == [(Decimal(68), None)]


@pytest.mark.parametrize(
    "text",
    ["", "sin superficie", "3 dormitorios", "120 mts de frente", "0 m2", "lote de 10x12x3"],
)
def test_find_areas_returns_nothing_without_an_area(text: str) -> None:
    assert find_areas(text) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("470", Decimal(470)),
        (" 90 ", Decimal(90)),
        ("1.200", Decimal(1200)),
        ("120,5", Decimal("120.5")),
        ("120.4", Decimal("120.4")),
    ],
)
def test_tag_area_reads_a_bare_number(raw: str, expected: Decimal) -> None:
    assert tag_area(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "0", "abc", "120 m2", "-5", "100001", "[TELEFONO]"])
def test_tag_area_rejects_anything_that_is_not_a_plausible_number(raw: str | None) -> None:
    assert tag_area(raw) is None
