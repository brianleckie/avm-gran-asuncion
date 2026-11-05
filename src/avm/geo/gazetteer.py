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
    "osm_id",
    "source",
)

# Decisiones revisadas con Oscar; no son reglas generales de desempate.
# 1969335519 explicita is_in:town=San Lorenzo; el otro nodo no lo hace.
# Es un punto de referencia provisional, no una coordenada de precisión parcelaria.
REVIEWED_NODES = {("san_lorenzo", "san felipe"): 1969335519}
EXCLUDED_GENERIC_NAMES = {("asuncion", "banado")}


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
        shape = polygon(element)
        if shape is not None and not city_shape.covers(shape):
            issues.append(
                {
                    "city": city,
                    "name": tags["name"],
                    "osm_type": element["type"],
                    "osm_id": element["id"],
                    "reason": "polygon_crosses_city_boundary",
                    "boundary_source": "osm",
                }
            )
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
        key = re.sub(r"[^a-z0-9]+", " ", normalize(tags["name"])).strip()
        groups[key].append((element, lat, lon, method))
    rows = []
    order = {"polygon_representative_point": 0, "osm_node": 1, "missing": 2}
    for name, candidates in sorted(groups.items()):
        if (city, name) in EXCLUDED_GENERIC_NAMES:
            issues.append(
                {
                    "city": city,
                    "name": name,
                    "reason": "generic_name_excluded",
                    "osm_ids": [c[0]["id"] for c in candidates],
                }
            )
            continue
        candidates.sort(key=lambda x: (order[x[3]], x[0]["type"], x[0]["id"]))
        # Dos polígonos o dos nodos homónimos requieren revisión, no selección silenciosa.
        best = candidates[0]
        same_rank = [c for c in candidates if c[3] == best[3]]
        if len(same_rank) > 1:
            selected_id = REVIEWED_NODES.get((city, name))
            reviewed = [
                c
                for c in same_rank
                if c[0]["type"] == "node"
                and c[0]["id"] == selected_id
                and normalize(c[0].get("tags", {}).get("is_in:town", "")) == city.replace("_", " ")
            ]
            if len(reviewed) == 1:
                best = reviewed[0]
                issues.append(
                    {
                        "city": city,
                        "name": name,
                        "reason": "reviewed_provisional_selection",
                        "selected_osm_id": selected_id,
                        "alternative_osm_ids": [
                            c[0]["id"] for c in candidates if c[0]["id"] != selected_id
                        ],
                        "basis": "municipal containment and explicit is_in:town",
                    }
                )
            else:
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
                        element["tags"]["name"].strip(),
                        "|".join(
                            sorted(
                                {a for c in candidates for a in aliases(c[0]["tags"]).split("|")}
                            )
                        ),
                        lat,
                        lon,
                        {
                            "polygon_representative_point": "osm_polygon",
                            "osm_node": "osm_point",
                            "missing": "missing",
                        }[method],
                        element["id"],
                        f"OSM {element['type']}/{element['id']}",
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
