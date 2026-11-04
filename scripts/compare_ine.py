"""Contrasta nombres exactos INE/OSM; no inventa equivalencias ni coordenadas."""

import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from avm.geo.gazetteer import normalize
from avm.geo.osm import CITY_NAMES


def compare(source, gazetteer, out):
    with gazetteer.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    lookup = {(r["city"], alias) for r in rows for alias in r["aliases"].split("|")}
    cities = {normalize(name): city for city, name in CITY_NAMES.items()}
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    results = []
    with zipfile.ZipFile(source) as archive:
        strings = [
            "".join(si.itertext())
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", ns)
        ]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in sheet.findall(".//m:row", ns):
            cells = {}
            for cell in row.findall("m:c", ns):
                value = cell.find("m:v", ns)
                text = value.text if value is not None else ""
                cells["".join(c for c in cell.get("r") if c.isalpha())] = (
                    strings[int(text)] if cell.get("t") == "s" else text
                )
            city = cities.get(normalize(cells.get("E", "")))
            if city is None or not cells.get("G"):
                continue
            name = normalize(cells["G"])
            results.append(
                {
                    "city": city,
                    "ine_name": cells["G"],
                    "ine_department": cells.get("B", ""),
                    "ine_district": cells.get("D", ""),
                    "ine_locality": cells.get("F", ""),
                    "source_row": row.get("r"),
                    "status": "exact_name_or_alias"
                    if (city, name) in lookup
                    else "needs_name_review",
                }
            )
    if not results:
        raise ValueError("No se encontraron las ciudades: revisar formato del catálogo INE")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "ine_comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "interpretation": "Nombres no coincidentes requieren revisión; no prueban ausencia",
        "cities": {
            city: {
                "ine_rows": sum(r["city"] == city for r in results),
                "matched": sum(
                    r["city"] == city and r["status"] == "exact_name_or_alias" for r in results
                ),
                "needs_review": sum(
                    r["city"] == city and r["status"] == "needs_name_review" for r in results
                ),
            }
            for city in CITY_NAMES
        },
    }
    (out / "ine_comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ine", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, default=Path("data/reference/gazetteer.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/reference"))
    args = parser.parse_args()
    compare(args.ine, args.gazetteer, args.out)
