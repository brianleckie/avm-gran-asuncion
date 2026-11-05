"""Genera la propuesta I3 y un reporte de cobertura, sin consultar la red."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from avm.geo.features import (
    CATEGORIES,
    FEATURE_COLUMNS,
    RADII_KM,
    bbox_edge_km,
    poi_index,
    spatial_features,
)
from avm.geo.gazetteer import location
from avm.geo.osm import CITY_NAMES, CITY_QUERY

CBD_OSM_NODE = 249854726


def build(snapshot, gazetteer, output):
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    city_request = next(
        r
        for r in manifest["requests"]
        if r["status"] == 200 and r["payload"] == {"data": CITY_QUERY}
    )
    boundaries = {
        e["tags"]["name"]: e
        for e in json.loads((snapshot / city_request["response"]).read_text(encoding="utf-8"))[
            "elements"
        ]
    }
    cbd_node = next(
        m
        for m in boundaries[CITY_NAMES["asuncion"]]["members"]
        if m["type"] == "node" and m["ref"] == CBD_OSM_NODE and m["role"] == "admin_centre"
    )
    cbd = cbd_node["lat"], cbd_node["lon"]
    with gazetteer.open(encoding="utf-8", newline="") as stream:
        origins = [
            (r["city"], r["neighborhood"], float(r["lat"]), float(r["lon"]))
            for r in csv.DictReader(stream)
        ]
    for city, name in CITY_NAMES.items():
        lat, lon, method = location(boundaries[name])
        if method != "polygon_representative_point":
            raise ValueError(f"Límite municipal sin punto representativo: {city}")
        origins.append((city, "", lat, lon))
    keys = {(city, neighborhood) for city, neighborhood, *_ in origins}
    if len(keys) != len(origins) or any(city not in CITY_NAMES for city, _ in keys):
        raise ValueError("Claves duplicadas o ciudad desconocida en el gazetteer")
    pois_path = snapshot / "pois.json"
    index, skipped = poi_index(json.loads(pois_path.read_text(encoding="utf-8"))["elements"])
    rows, edges = [], []
    for city, neighborhood, lat, lon in origins:
        features = spatial_features((lat, lon), index, cbd)
        key = {"city": city, "neighborhood": neighborhood}
        rows.append({**key, "geo_precision": "barrio" if neighborhood else "ciudad", **features})
        edge = bbox_edge_km((lat, lon), manifest["bbox"])
        radii = [radius for radius in RADII_KM if radius >= edge]
        nearest = [
            category
            for category in CATEGORIES
            if features[f"dist_{category}_km"] is None or features[f"dist_{category}_km"] >= edge
        ]
        if radii or nearest:
            edges.append(
                {
                    **key,
                    "bbox_edge_km": edge,
                    "radii_at_risk_km": radii,
                    "nearest_categories_at_risk": nearest,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "rows": len(rows),
        "cbd_osm_node": CBD_OSM_NODE,
        "bbox": manifest["bbox"],
        "gazetteer_sha256": hashlib.sha256(gazetteer.read_bytes()).hexdigest(),
        "pois_sha256": hashlib.sha256(pois_path.read_bytes()).hexdigest(),
        "poi_skipped_by_category": skipped,
        "edge_risk": edges,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{len(rows)} filas; {len(edges)} con algún indicador de borde")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, default=Path("data/reference/gazetteer.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/reference/geo_features.csv"))
    args = parser.parse_args()
    build(args.snapshot, args.gazetteer, args.out)
