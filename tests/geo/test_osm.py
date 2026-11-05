import json

import httpx
import pytest

from avm.geo.osm import OSMClient, neighborhood_query, poi_categories, poi_query


def test_cache_and_manifest(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"elements": []})

    client = OSMClient(tmp_path, transport=httpx.MockTransport(handler))
    assert client.overpass("query") == {"elements": []}
    assert client.overpass("query") == {"elements": []}
    client.close()
    assert len(calls) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requests"][0]["payload"] == {"data": "query"}
    assert len(manifest["requests"][0]["sha256"]) == 64


@pytest.mark.parametrize(
    "status,payload,error",
    [
        (429, {}, httpx.HTTPStatusError),
        (200, {"remark": "runtime error", "elements": []}, ValueError),
    ],
)
def test_errors_are_saved_and_not_accepted(tmp_path, status, payload, error):
    client = OSMClient(
        tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload))
    )
    with pytest.raises(error):
        client.overpass("bad")
    client.close()
    assert len(list(tmp_path.glob("*.response"))) == 1
    assert not list(tmp_path.glob("overpass-*.json"))


def test_budget_before_network(tmp_path):
    client = OSMClient(
        tmp_path, transport=httpx.MockTransport(lambda r: pytest.fail("No debe consultar red"))
    )
    client.manifest["requests"] = [{"service": "nominatim"}] * 199
    with pytest.raises(RuntimeError, match="Presupuesto"):
        client.geocode("Prueba", "luque")
    client.close()


def test_queries_and_categories():
    assert "map_to_area" in neighborhood_query(123)
    assert "-1,-2,3,4" in poi_query((-1, -2, 3, 4))
    assert poi_categories({"tags": {"highway": "trunk", "amenity": "school"}}) == ["road", "school"]
    assert poi_categories({"tags": {"amenity": "cafe"}}) == []
