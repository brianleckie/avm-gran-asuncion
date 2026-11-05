from shapely.geometry import Polygon

from avm.geo.gazetteer import build_rows


def test_reviewed_san_felipe_and_generic_exclusion():
    shape = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    elements = [
        {
            "type": "node",
            "id": 1969335519,
            "lat": 1,
            "lon": 1,
            "tags": {"name": "San Felipe", "is_in:town": "San Lorenzo"},
        },
        {"type": "node", "id": 2979211659, "lat": 2, "lon": 2, "tags": {"name": "San Felipe"}},
    ]
    rows, issues = build_rows("san_lorenzo", elements, shape)
    assert rows[0]["osm_id"] == 1969335519
    assert issues[0]["reason"] == "reviewed_provisional_selection"
    # Una decisión revisada no debe propagarse a otra ciudad por homonimia.
    rows, issues = build_rows("asuncion", elements, shape)
    assert rows == [] and issues[0]["reason"] == "ambiguous_name"
    rows, issues = build_rows(
        "asuncion",
        [{"type": "node", "id": 1, "lat": 1, "lon": 1, "tags": {"name": "Bañado"}}],
        shape,
    )
    assert rows == [] and issues[0]["reason"] == "generic_name_excluded"


def test_reviewed_node_requires_current_city_tag():
    shape = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    elements = [
        {"type": "node", "id": identifier, "lat": 1, "lon": 1, "tags": {"name": "San Felipe"}}
        for identifier in [1969335519, 2979211659]
    ]
    rows, issues = build_rows("san_lorenzo", elements, shape)
    assert rows == [] and issues[0]["reason"] == "ambiguous_name"
