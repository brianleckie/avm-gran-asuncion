"""Clasifica la auditoría revisada usando ubicación y decisiones textuales, sin precios."""

import csv
from collections import Counter
from pathlib import Path

from avm.contract import City, NeighborhoodMatch
from avm.pipeline.neighborhood import load_gazetteer, match_neighborhood, normalize_name

missing = {
    "asuncion": {"carmelitas", "santa librada"},
    "luque": {"villa adela", "barrio america", "jardin de oro", "amistad", "curva romero"},
    "san_lorenzo": {"laguna grande", "laurelty"},
    "fernando_de_la_mora": {"san miguel fernando de la mora"},
}
gazetteer = load_gazetteer(Path("data/reference/gazetteer.csv"))
source = Path("data/processed/f4.4-audit/before.csv")
with source.open(encoding="utf-8", newline="") as stream:
    rows = list(csv.DictReader(stream))
for row in rows:
    zone = row["zone"]
    city = City(row["city"])
    result = match_neighborhood(zone, city, gazetteer)
    key = normalize_name(zone)
    if result.name and result.match in {
        NeighborhoodMatch.MANUAL,
        NeighborhoodMatch.EXACT,
        NeighborhoodMatch.ALIAS,
    }:
        row["classification"] = "a"
        row["note"] = "Mismo barrio con variante textual o contexto de ciudad"
        row["candidate"] = result.name
    elif key in {normalize_name(n) for n in missing.get(city.value, set())}:
        row["classification"] = "c"
        row["note"] = (
            "Nombre ausente del gazetteer municipal. Requiere confirmación espacial en OSM"
        )
    elif any(word in key for word in ["vendo", "en venta", "dormitorios", "tu nuevo hogar"]):
        row["classification"] = "d"
        row["note"] = "Texto comercial sin barrio identificable de forma única"
    else:
        row["classification"] = "b"
        row["note"] = (
            "Zona amplia, referencia vial o múltiples ubicaciones. Mantener sin asignación manual"
        )
output = source.with_name("classified.csv")
with output.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

print(dict(Counter(r["classification"] for r in rows)))
