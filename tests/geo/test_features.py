import math

import pytest

from avm.geo.features import bbox_edge_km, poi_index, spatial_features


def test_distances_and_counts_use_one_vote_per_osm_object():
    road = {
        "type": "way",
        "id": 1,
        "tags": {"highway": "primary"},
        "geometry": [{"lat": 0, "lon": 0.01}, {"lat": 0, "lon": 0.02}],
    }
    school = {"type": "node", "id": 1, "lat": 0, "lon": 0.03, "tags": {"amenity": "school"}}
    index, skipped = poi_index([road, road, school])
    result = spatial_features((0, 0), index, (0, 1))
    assert result["dist_cbd_km"] == pytest.approx(111.195, abs=0.001)
    assert result["dist_road_km"] == pytest.approx(1.112, abs=0.001)
    assert result["n_road_1km"] == 0
    assert result["n_road_3km"] == 1
    assert result["n_school_3km"] == 0
    assert result["n_school_5km"] == 1
    assert result["dist_park_km"] is None
    assert not any(skipped.values())


def test_bbox_edge_respects_latitude():
    assert bbox_edge_km((60, 0), (59, -0.01, 61, 1)) == pytest.approx(
        1.11195 * math.cos(math.pi / 3), abs=0.001
    )
    with pytest.raises(ValueError, match="fuera del bbox"):
        bbox_edge_km((62, 0), (59, -0.01, 61, 1))
