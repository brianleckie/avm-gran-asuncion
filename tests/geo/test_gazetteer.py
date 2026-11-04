"""Pruebas geométricas sintéticas; ninguna coordenada se usa como dato real."""

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from avm.geo.gazetteer import COLUMNS, aliases, build_rows, location, polygon, write_csv


def node(identifier=1, name="Villa Prueba", lat=1, lon=1):
    return {
        "type": "node",
        "id": identifier,
        "lat": lat,
        "lon": lon,
        "tags": {"name": name, "place": "neighbourhood"},
    }


def test_rows_and_csv(tmp_path):
    shape = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    rows, issues = build_rows("asuncion", [node(), node(2, "Fuera", 8, 8)], shape)
    assert len(rows) == 1
    assert issues[0]["reason"] == "outside_city"
    assert tuple(rows[0]) == COLUMNS
    assert rows[0]["aliases"] == "v. prueba|villa prueba"
    target = tmp_path / "gazetteer.csv"
    write_csv(target, rows)
    with target.open(encoding="utf-8", newline="") as stream:
        saved = list(csv.DictReader(stream))
    assert len({(r["city"], r["neighborhood"]) for r in saved}) == len(saved)
    assert shape.covers(Point(float(saved[0]["lon"]), float(saved[0]["lat"])))


def test_aliases_have_only_supported_variations():
    assert aliases({"name": "Barrio Ñandú", "alt_name": "Ñandú;Nandu"}) == (
        "barrio nandu|b° nandu|nandu"
    )


def test_homonyms_are_not_silently_selected():
    rows, issues = build_rows(
        "luque", [node(), node(2, lat=2)], Polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    )
    assert rows == []
    assert issues[0]["reason"] == "ambiguous_name"


def test_full_polygon_containment_resolves_crossing_homonym():
    def area(identifier, coords):
        return {
            "type": "way",
            "id": identifier,
            "tags": {"name": "Prueba"},
            "geometry": [{"lon": x, "lat": y} for x, y in coords],
        }

    inside = area(1, [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)])
    crossing = area(2, [(1, 1), (4, 1), (4, 2), (1, 2), (1, 1)])
    city_shape = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    # El punto representativo del polígono que cruza también está dentro: no basta.
    assert city_shape.covers(polygon(crossing).representative_point())
    rows, issues = build_rows("luque", [inside, crossing], city_shape)
    assert len(rows) == 1 and rows[0]["osm_id"] == 1
    assert issues[0]["reason"] == "polygon_crosses_city_boundary"
    assert issues[0]["boundary_source"] == "osm"


def test_polygon_with_hole_and_split_outer():
    element = {
        "type": "relation",
        "members": [
            {
                "type": "way",
                "role": "outer",
                "geometry": [{"lon": x, "lat": y} for x, y in [(0, 0), (4, 0), (4, 4)]],
            },
            {
                "type": "way",
                "role": "outer",
                "geometry": [{"lon": x, "lat": y} for x, y in [(4, 4), (0, 4), (0, 0)]],
            },
            {
                "type": "way",
                "role": "inner",
                "geometry": [
                    {"lon": x, "lat": y} for x, y in [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]
                ],
            },
        ],
    }
    shape = polygon(element)
    assert shape.area == 12
    lat, lon, method = location(element)
    assert method == "polygon_representative_point"
    assert shape.contains(Point(lon, lat))


@pytest.mark.parametrize(
    "element",
    [
        {"type": "way", "geometry": []},
        {"type": "relation", "members": []},
        {
            "type": "way",
            "geometry": [{"lon": x, "lat": y} for x, y in [(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]],
        },
    ],
)
def test_invalid_geometry_is_missing(element):
    assert location(element) == (None, None, "missing")


def test_saved_real_osm_fixture():
    path = Path(__file__).parent / "fixtures" / "osm_sample.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["elements"]
    for element in data["elements"]:
        lat, lon, method = location(element)
        assert method != "missing"
        assert -90 <= lat <= 90 and -180 <= lon <= 180
