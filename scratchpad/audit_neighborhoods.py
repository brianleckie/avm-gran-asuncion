"""Auditoría F4.4 sin precios: solo claves de I1, ciudad y zona del crudo local."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

from avm.contract import City
from avm.pipeline.neighborhood import load_gazetteer, match_neighborhood, normalize_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.dataset.open(encoding="utf-8", newline="") as stream:
        kept = {row["listing_key"] for row in csv.DictReader(stream)}
    latest = {}
    for snapshot in ("2026-10-06", "2026-11-04"):
        path = Path("data/interim") / snapshot / "clasipar/raw_listings.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = f"{row['source']}:{row['source_id']}"
            if key in kept:
                latest[key] = (row.get("city_raw", ""), row.get("neighborhood_raw") or "")
    gazetteer = load_gazetteer(args.gazetteer)
    cities = {normalize_name(city.value.replace("_", " ")): city for city in City}
    counts = defaultdict(Counter)
    for city_raw, zone in latest.values():
        city = cities.get(normalize_name(city_raw or ""))
        if city is not None and zone and match_neighborhood(zone, city, gazetteer).name is None:
            counts[city][zone] += 1
    results = []
    for city, zones in sorted(counts.items()):
        choices = gazetteer.cities[city].canonical
        for zone, count in zones.most_common(40):
            best = process.extractOne(normalize_name(zone), list(choices), scorer=fuzz.ratio)
            results.append(
                {
                    "city": city.value,
                    "zone": zone,
                    "count": count,
                    "candidate": choices[best[0]],
                    "score": round(best[1], 2),
                    "classification": "review",
                    "note": "",
                }
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(f"{len(results)} zonas para revisión en {args.out}")


if __name__ == "__main__":
    main()
