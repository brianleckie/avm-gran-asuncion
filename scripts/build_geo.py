"""F6.1–F6.3: snapshot reproducible de barrios y POIs (datos fuera de git)."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from avm.geo.gazetteer import build_rows, polygon, write_csv
from avm.geo.osm import (
    CITY_NAMES,
    CITY_QUERY,
    OSMClient,
    neighborhood_query,
    poi_categories,
    poi_query,
)


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build(snapshot, out, *, overpass=None):
    client = OSMClient(snapshot, **({"overpass": overpass} if overpass else {}))
    try:
        cities = client.overpass(CITY_QUERY)["elements"]
        by_name = {e["tags"]["name"]: e for e in cities}
        if set(by_name) != set(CITY_NAMES.values()) or len(cities) != 4:
            raise ValueError("La consulta debe devolver exactamente las cuatro ciudades")
        bounds = [e["bounds"] for e in cities]
        # Margen explícito en grados, derivado de límites OSM; no es un radio métrico.
        bbox = [
            min(b["minlat"] for b in bounds) - 0.02,
            min(b["minlon"] for b in bounds) - 0.02,
            max(b["maxlat"] for b in bounds) + 0.02,
            max(b["maxlon"] for b in bounds) + 0.02,
        ]
        rows, issues, coverage = [], [], {}
        for city, name in CITY_NAMES.items():
            boundary = by_name[name]
            shape = polygon(boundary)
            if shape is None:
                raise ValueError(f"Límite de ciudad inválido: {city}")
            elements = client.overpass(neighborhood_query(boundary["id"]))["elements"]
            city_rows, city_issues = build_rows(city, elements, shape)
            rows.extend(city_rows)
            issues.extend(city_issues)
            coverage[city] = {
                "city_osm_id": boundary["id"],
                "rows": len(city_rows),
                "methods": dict(Counter(r["centroid_method"] for r in city_rows)),
                "observed_tags": dict(
                    Counter(
                        f"place={e.get('tags', {}).get('place', '')};"
                        f"admin_level={e.get('tags', {}).get('admin_level', '')}"
                        for e in elements
                        if e.get("tags", {}).get("name")
                    )
                ),
                "issues": len(city_issues),
            }
        pois = client.overpass(poi_query(bbox))
        counts = Counter(cat for e in pois["elements"] for cat in poi_categories(e))
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / "gazetteer.csv", rows)
        save_json(snapshot / "pois.json", pois)
        save_json(out / "geo_issues.json", issues)
        summary = {
            "generated_at": datetime.now(UTC).isoformat(),
            "bbox": bbox,
            "bbox_margin_degrees": 0.02,
            "cities": coverage,
            "poi_counts_osm_objects": dict(counts),
            "snapshot": str(snapshot),
            "attribution": "© OpenStreetMap contributors (ODbL)",
        }
        save_json(out / "geo_summary.json", summary)
        client.manifest.update(summary)
        save_json(client.manifest_path, client.manifest)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/reference"))
    parser.add_argument("--overpass", help="Endpoint alternativo explícito, registrado en manifest")
    args = parser.parse_args()
    build(args.snapshot, args.out, overpass=args.overpass)
