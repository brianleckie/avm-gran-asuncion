"""Gazetteer de observaciones OSM; no presume una lista oficial completa."""

import csv
import re
import unicodedata
from collections import defaultdict

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize_full, unary_union

COLUMNS = (
    "city",
    "neighborhood",
    "aliases",
    "lat",
    "lon",
    "centroid_method",
    "osm_type",
    "osm_id",
    "source_url",
)


def normalize(value):
    return " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        ).split()
    )


def aliases(tags):
    names = {tags["name"]}
    for key in ("alt_name", "short_name", "official_name", "name:es"):
        names.update(filter(None, tags.get(key, "").split(";")))
    normalized = {normalize(name) for name in names}
    for name in list(normalized):
        if re.search(r"\bvilla\b", name):
            normalized.add(re.sub(r"\bvilla\b", "v.", name))
        if name.startswith("barrio "):
            normalized.update({name[7:], "b° " + name[7:]})
    return "|".join(sorted(normalized))


def polygon(element):
    """Reconstruye anillos; geometría incompleta/inválida queda sin polígono."""
    if element["type"] == "way":
        coords = [(p["lon"], p["lat"]) for p in element.get("geometry", [])]
        if len(coords) < 4 or coords[0] != coords[-1]:
            return None
        shape = Polygon(coords)
    elif element["type"] == "relation":
        rings = {"outer": [], "inner": []}
        for member in element.get("members", []):
            role = member.get("role") or "outer"
            points = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
            if role in rings and member["type"] in {"way", "relation"} and len(points) < 2:
                return None
            if member["type"] == "way" and role in rings and len(points) >= 2:
                rings[role].append(LineString(points))
        outer, cuts, dangles, invalid = polygonize_full(unary_union(rings["outer"]))
        if outer.is_empty or any(not g.is_empty for g in (cuts, dangles, invalid)):
            return None
        inner, cuts, dangles, invalid = polygonize_full(unary_union(rings["inner"]))
        if any(not g.is_empty for g in (cuts, dangles, invalid)):
            return None
        shape = unary_union(outer).difference(unary_union(inner))
    else:
        return None
    return shape if isinstance(shape, Polygon | MultiPolygon) and shape.is_valid else None


def location(element):
    shape = polygon(element)
    if shape is not None and not shape.is_empty:
        point = shape.representative_point()
        return point.y, point.x, "polygon_representative_point"
    if element["type"] == "node":
        return element["lat"], element["lon"], "osm_node"
    return None, None, "missing"


def build_rows(city, elements, city_shape):
    """Agrupa nombres equivalentes; conflictos espaciales se envían a revisión."""
    groups = defaultdict(list)
    issues = []
    for element in elements:
        tags = element.get("tags", {})
        if not tags.get("name"):
            continue
        lat, lon, method = location(element)
        if lat is not None and not city_shape.covers(Point(lon, lat)):
            issues.append(
                {
                    "city": city,
                    "name": tags["name"],
                    "osm_id": element["id"],
                    "reason": "outside_city",
                }
            )
            continue
        groups[normalize(tags["name"])].append((element, lat, lon, method))
    rows = []
    order = {"polygon_representative_point": 0, "osm_node": 1, "missing": 2}
    for name, candidates in sorted(groups.items()):
        candidates.sort(key=lambda x: (order[x[3]], x[0]["type"], x[0]["id"]))
        # Dos polígonos o dos nodos homónimos requieren revisión, no selección silenciosa.
        best = candidates[0]
        same_rank = [c for c in candidates if c[3] == best[3]]
        if len(same_rank) > 1:
            issues.append(
                {
                    "city": city,
                    "name": name,
                    "reason": "ambiguous_name",
                    "osm_ids": [c[0]["id"] for c in candidates],
                }
            )
            continue
        element, lat, lon, method = best
        rows.append(
            dict(
                zip(
                    COLUMNS,
                    (
                        city,
                        name,
                        "|".join(
                            sorted(
                                {a for c in candidates for a in aliases(c[0]["tags"]).split("|")}
                            )
                        ),
                        lat,
                        lon,
                        method,
                        element["type"],
                        element["id"],
                        f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
                    ),
                    strict=True,
                )
            )
        )
    return rows, issues


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
