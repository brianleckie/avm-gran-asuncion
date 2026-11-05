"""Variables espaciales de I3 a partir de un snapshot OSM."""

import numpy as np

from avm.geo.gazetteer import location
from avm.geo.osm import poi_categories

EARTH_RADIUS_KM = 6371.0088
CATEGORIES = ("road", "mall", "school", "university", "hospital", "park")
RADII_KM = (1, 3, 5)
FEATURE_COLUMNS = (
    "city",
    "neighborhood",
    "geo_precision",
    "dist_cbd_km",
    *(f"dist_{category}_km" for category in CATEGORIES),
    *(f"n_{category}_{radius}km" for category in CATEGORIES for radius in RADII_KM),
)


def haversine_km(origin, coordinates):
    """Distancias de círculo máximo para pares (latitud, longitud)."""
    lat, lon = np.radians(origin)
    target_lat, target_lon = np.radians(coordinates).T
    a = (
        np.sin((target_lat - lat) / 2) ** 2
        + np.cos(lat) * np.cos(target_lat) * np.sin((target_lon - lon) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def poi_index(elements):
    """Agrupa vértices por vía y un punto representativo por cada otro objeto."""
    points = {category: [] for category in CATEGORIES}
    starts = {category: [] for category in CATEGORIES}
    skipped = dict.fromkeys(CATEGORIES, 0)
    seen = set()
    for element in elements:
        key = element["type"], element["id"]
        if key in seen:
            continue
        seen.add(key)
        for category in poi_categories(element):
            if category == "road":
                coordinates = [(p["lat"], p["lon"]) for p in element.get("geometry", []) if p]
            else:
                lat, lon, _ = location(element)
                coordinates = [] if lat is None else [(lat, lon)]
            if not coordinates:
                skipped[category] += 1
                continue
            starts[category].append(len(points[category]))
            points[category].extend(coordinates)
    index = {
        category: (np.asarray(points[category]).reshape(-1, 2), starts[category])
        for category in CATEGORIES
    }
    return index, skipped


def spatial_features(origin, index, cbd):
    features = {"dist_cbd_km": float(haversine_km(origin, [cbd])[0])}
    for category, (coordinates, starts) in index.items():
        distances = np.minimum.reduceat(haversine_km(origin, coordinates), starts) if starts else []
        features[f"dist_{category}_km"] = float(min(distances)) if len(distances) else None
        for radius in RADII_KM:
            features[f"n_{category}_{radius}km"] = (
                int(np.count_nonzero(distances <= radius)) if len(distances) else 0
            )
    return features


def bbox_edge_km(origin, bbox):
    """Cota inferior a la distancia a un borde del rectángulo consultado."""
    lat, lon = origin
    south, west, north, east = bbox
    if not (south <= lat <= north and west <= lon <= east):
        raise ValueError(f"Origen fuera del bbox: {origin}")
    meridian_distance = np.arcsin(
        np.cos(np.radians(lat)) * np.sin(np.radians(min(lon - west, east - lon)))
    )
    parallel_distance = np.radians(min(lat - south, north - lat))
    return float(EARTH_RADIUS_KM * min(meridian_distance, parallel_distance))
