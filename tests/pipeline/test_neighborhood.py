"""Normalización de barrios contra el gazetteer (F4.4). Gazetteer y zonas inventados."""

from pathlib import Path

import pytest

from avm.contract import City, NeighborhoodMatch
from avm.pipeline.neighborhood import (
    FUZZY_THRESHOLD,
    Gazetteer,
    Reason,
    load_gazetteer,
    match_neighborhood,
    normalize_name,
)

GAZETTEER_CSV = """city,neighborhood,aliases,lat,lon,centroid_method,osm_id,source
asuncion,Villa Morra,villa morra|v. morra|vmorra,,,sintetico,,sintetico
asuncion,Ñandú Norte,nandu norte,,,sintetico,,sintetico
luque,Centro,,,,sintetico,,sintetico
luque,Villa Aaaa,,,,sintetico,,sintetico
luque,Villa Aaab,,,,sintetico,,sintetico
luque,Barrio Jardín,jardin,,,sintetico,,sintetico
"""


@pytest.fixture
def gazetteer(tmp_path: Path) -> Gazetteer:
    path = tmp_path / "gazetteer.csv"
    path.write_text(GAZETTEER_CSV, encoding="utf-8")
    return load_gazetteer(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Villa Morra", "villa morra"),
        ("  VILLA   MORRA ", "villa morra"),
        ("Barrio San Roque", "san roque"),
        ("B° San Roque", "san roque"),
        ("Bº San Roque", "san roque"),  # ordinal masculino
        ("Ñandú", "nandu"),
        ("Cañada", "canada"),
        ("V. Morra", "v morra"),
        ("barriocito", "barriocito"),  # "barrio" solo como palabra entera
        ("", ""),
        ("Barrio", ""),
    ],
)
def test_normalize_name(text: str, expected: str) -> None:
    assert normalize_name(text) == expected


def test_fuzzy_threshold_is_the_explicit_value_of_the_brief() -> None:
    assert FUZZY_THRESHOLD == 90


def test_exact_match_ignores_case_accents_and_the_word_barrio(gazetteer: Gazetteer) -> None:
    for zone in ("Villa Morra", "villa  MORRA", "Barrio Villa Morra", "B° Villa Morra"):
        result = match_neighborhood(zone, City.ASUNCION, gazetteer)
        assert (result.name, result.match) == ("Villa Morra", NeighborhoodMatch.EXACT)
    result = match_neighborhood("nandu norte", City.ASUNCION, gazetteer)
    assert (result.name, result.match) == ("Ñandú Norte", NeighborhoodMatch.EXACT)


def test_the_canonical_name_may_include_the_word_barrio(gazetteer: Gazetteer) -> None:
    result = match_neighborhood("Jardín", City.LUQUE, gazetteer)
    assert (result.name, result.match) == ("Barrio Jardín", NeighborhoodMatch.EXACT)


def test_alias_match(gazetteer: Gazetteer) -> None:
    for zone in ("V. Morra", "vmorra"):
        result = match_neighborhood(zone, City.ASUNCION, gazetteer)
        assert (result.name, result.match) == ("Villa Morra", NeighborhoodMatch.ALIAS)
    assert result.reason is Reason.MATCHED


def test_fuzzy_match_at_and_above_the_threshold(gazetteer: Gazetteer) -> None:
    # "villa mor" vs "villa morra": 9 de 11 letras en común -> ratio 2*9/(9+11) = 90,0 (el borde)
    exact_border = match_neighborhood("Villa Mor", City.ASUNCION, gazetteer)
    assert (exact_border.name, exact_border.match) == ("Villa Morra", NeighborhoodMatch.FUZZY)
    # "villa mora" vs "villa morra": ratio 2*10/(10+11) = 95,2
    typo = match_neighborhood("Villa Mora", City.ASUNCION, gazetteer)
    assert (typo.name, typo.match) == ("Villa Morra", NeighborhoodMatch.FUZZY)


def test_fuzzy_below_the_threshold_is_not_assigned(gazetteer: Gazetteer) -> None:
    # "villa mo" vs "villa morra": ratio 2*8/(8+11) = 84,2
    result = match_neighborhood("Villa Mo", City.ASUNCION, gazetteer)
    assert (result.name, result.match, result.reason) == (
        None,
        NeighborhoodMatch.UNMATCHED,
        Reason.NO_MATCH,
    )


def test_two_different_barrios_with_the_same_score_are_ambiguous_and_not_assigned(
    gazetteer: Gazetteer,
) -> None:
    # "villa aaac" está a 9 de 10 letras de "villa aaaa" y de "villa aaab": empate exacto
    result = match_neighborhood("Villa Aaac", City.LUQUE, gazetteer)
    assert (result.name, result.match, result.reason) == (
        None,
        NeighborhoodMatch.UNMATCHED,
        Reason.AMBIGUOUS,
    )


def test_matching_only_looks_inside_the_city_of_the_listing(gazetteer: Gazetteer) -> None:
    result = match_neighborhood("Villa Morra", City.LUQUE, gazetteer)  # es de Asunción
    assert (result.name, result.reason) == (None, Reason.NO_MATCH)
    other = match_neighborhood("Villa Morra", City.SAN_LORENZO, gazetteer)  # ciudad sin barrios
    assert (other.name, other.reason) == (None, Reason.NO_MATCH)


def test_a_zone_equal_to_the_city_stays_unmatched(gazetteer: Gazetteer) -> None:
    result = match_neighborhood("Luque", City.LUQUE, gazetteer)
    assert (result.name, result.match, result.reason) == (
        None,
        NeighborhoodMatch.UNMATCHED,
        Reason.SAME_AS_CITY,
    )
    assert match_neighborhood("ASUNCIÓN", City.ASUNCION, gazetteer).reason is Reason.SAME_AS_CITY
    from_raw = match_neighborhood("Ciudad Prueba", City.LUQUE, gazetteer, city_raw="Ciudad Prueba")
    assert from_raw.reason is Reason.SAME_AS_CITY  # igual a la ciudad de la ficha


@pytest.mark.parametrize("zone", [None, "", "   ", "Barrio"])
def test_a_missing_zone_has_no_barrio(zone: str | None, gazetteer: Gazetteer) -> None:
    assert match_neighborhood(zone, City.LUQUE, gazetteer).reason is Reason.NO_ZONE


def test_without_a_gazetteer_everything_is_unmatched() -> None:
    empty = load_gazetteer(None)
    assert empty.is_empty
    result = match_neighborhood("Villa Morra", City.ASUNCION, empty)
    assert (result.name, result.match, result.reason) == (
        None,
        NeighborhoodMatch.UNMATCHED,
        Reason.NO_GAZETTEER,
    )
    assert match_neighborhood("Asunción", City.ASUNCION, empty).reason is Reason.SAME_AS_CITY
    assert match_neighborhood(None, City.ASUNCION, empty).reason is Reason.NO_ZONE


def test_an_alias_that_points_to_two_barrios_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "gazetteer.csv"
    path.write_text(
        "city,neighborhood,aliases\nluque,Uno,comun\nluque,Dos,comun\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="alias ambiguo"):
        load_gazetteer(path)


def test_rows_without_a_barrio_or_alias_are_skipped_when_loading(tmp_path: Path) -> None:
    path = tmp_path / "gazetteer.csv"
    path.write_text("city,neighborhood,aliases\nluque,,\nluque,Uno,| |uno\n", encoding="utf-8")
    result = match_neighborhood("Uno", City.LUQUE, load_gazetteer(path))
    assert (result.name, result.match) == ("Uno", NeighborhoodMatch.EXACT)
