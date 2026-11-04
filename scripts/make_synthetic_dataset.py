"""Genera un dataset SINTÉTICO con la forma exacta de docs/interfaces.md (I1, I2 e I3).

Sirve para que el modelado (F6.4, F8 a F10) avance antes de que exista el dataset real, y para el
test e2e (F14.2). Nada de esto sale de un portal: los barrios son nombres inventados
("Sintético Asunción 01"), las distancias y los precios son números generados con un seed fijo.

Uso (desde la raíz del repo):
    uv run python scripts/make_synthetic_dataset.py --out data/processed/sintetico --n 3000 --seed 7

Escribe dataset.csv (I1), gazetteer.csv (I2) y geo_features.csv (I3). Si la carpeta ya tiene
alguno de esos archivos, falla sin pisar nada.

El "ground truth" del generador (efectos hedónicos y geo) queda en ground_truth.json: un modelo
correcto tiene que recuperar el efecto de la distancia al centro, y la ablation geo (F10.3) tiene
que mostrar que sin features geo el error sube. Si no pasa con este dataset, el bug es del código.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

CITIES = {
    # ciudad: (barrios inventados, nivel de log(USD/m²) de la ciudad, peso en la muestra)
    "asuncion": (24, 7.10, 0.55),
    "luque": (10, 6.65, 0.20),
    "san_lorenzo": (8, 6.55, 0.12),
    "fernando_de_la_mora": (8, 6.60, 0.13),
}
TYPES = {"casa": (0.0, 0.40), "departamento": (0.25, 0.35), "duplex": (-0.05, 0.25)}
POI_CATEGORIES = ["primary_road", "mall", "school", "university", "hospital", "park"]
RADII_KM = {"school": 1, "mall": 2, "hospital": 2, "park": 1}

DATASET_COLUMNS = [
    "listing_key",
    "cluster_id",
    "snapshot_date",
    "city",
    "neighborhood",
    "neighborhood_match",
    "geo_precision",
    "property_type",
    "price_usd",
    "built_area_m2",
    "built_area_source",
    "land_area_m2",
    "bedrooms",
    "bathrooms",
    "garages",
    "has_pool",
    "has_quincho",
    "is_new",
    "in_gated_community",
    "has_elevator",
    "street_surface",
    "advertiser_type",
    "is_sponsored",
    "usd_per_m2",
    "log_usd_per_m2",
]


def _tri(rng: np.random.Generator, p_true: float, p_missing: float) -> str:
    """Tri-estado del contrato: '1', '0' o '' (el aviso no lo menciona)."""
    if rng.random() < p_missing:
        return ""
    return "1" if rng.random() < p_true else "0"


def build_geo(rng: np.random.Generator) -> tuple[list[dict], list[dict]]:
    gazetteer: list[dict] = []
    features: list[dict] = []
    for city, (n_barrios, _, _) in CITIES.items():
        city_dist = rng.uniform(0.5, 3.0) if city == "asuncion" else rng.uniform(8.0, 16.0)
        city_row = {
            "city": city,
            "neighborhood": "",
            "geo_precision": "ciudad",
            "dist_cbd_km": round(city_dist + 2.0, 3),
        }
        for cat in POI_CATEGORIES:
            city_row[f"dist_{cat}_km"] = round(rng.uniform(0.5, 2.0), 3)
        for cat, r in RADII_KM.items():
            city_row[f"n_{cat}_{r}km"] = int(rng.poisson(3))
        features.append(city_row)
        for i in range(1, n_barrios + 1):
            name = f"Sintético {city.replace('_', ' ').title()} {i:02d}"
            gazetteer.append(
                {
                    "city": city,
                    "neighborhood": name,
                    "aliases": f"{name.lower()}|sint {city[:3]} {i}",
                    "lat": "",
                    "lon": "",
                    "centroid_method": "sintetico",
                    "osm_id": "",
                    "source": "sintetico",
                }
            )
            row = {
                "city": city,
                "neighborhood": name,
                "geo_precision": "barrio",
                "dist_cbd_km": round(max(0.2, city_dist + rng.normal(0, 2.0)), 3),
            }
            for cat in POI_CATEGORIES:
                row[f"dist_{cat}_km"] = round(float(rng.gamma(2.0, 0.6)), 3)
            for cat, r in RADII_KM.items():
                row[f"n_{cat}_{r}km"] = int(rng.poisson(4))
            features.append(row)
    return gazetteer, features


def build_dataset(
    rng: np.random.Generator, n: int, gazetteer: list[dict], features: list[dict]
) -> tuple[list[dict], dict]:
    effects = {
        "log_built_area": -0.18,
        "dist_cbd_km": -0.035,
        "dist_mall_km": -0.04,
        "has_pool": 0.06,
        "is_new": 0.08,
        "in_gated_community": 0.07,
        "has_elevator": 0.05,
    }
    by_key = {(f["city"], f["neighborhood"]): f for f in features}
    barrios = {c: [g["neighborhood"] for g in gazetteer if g["city"] == c] for c in CITIES}
    barrio_shift = {g["neighborhood"]: float(rng.normal(0, 0.15)) for g in gazetteer}
    cities = list(CITIES)
    weights = np.array([CITIES[c][2] for c in cities])
    rows: list[dict] = []
    cluster = 0
    while len(rows) < n:
        cluster += 1
        city = str(rng.choice(cities, p=weights / weights.sum()))
        ptype = str(rng.choice(list(TYPES), p=[w for _, w in TYPES.values()]))
        unmatched = rng.random() < 0.15  # barrio que no matchea: cae a la ciudad (ADR-003)
        barrio = "" if unmatched else str(rng.choice(barrios[city]))
        geo = by_key[(city, barrio)]
        mu = 4.3 if ptype == "departamento" else 4.9
        area = round(float(np.exp(rng.normal(mu, 0.35))), 1)  # redondeo ANTES del precio
        flags = {
            "has_pool": _tri(rng, 0.3 if ptype != "departamento" else 0.5, 0.4),
            "has_quincho": _tri(rng, 0.4, 0.5),
            "is_new": _tri(rng, 0.25, 0.5),
            "in_gated_community": _tri(rng, 0.2, 0.6),
            "has_elevator": _tri(rng, 0.7 if ptype == "departamento" else 0.02, 0.5),
        }
        log_m2 = (
            CITIES[city][1]
            + TYPES[ptype][0]
            + barrio_shift.get(barrio, 0.0)
            + effects["log_built_area"] * (math.log(area) - 4.6)
            + effects["dist_cbd_km"] * geo["dist_cbd_km"]
            + effects["dist_mall_km"] * geo["dist_mall_km"]
            + sum(effects.get(k, 0.0) for k, v in flags.items() if v == "1")
        )
        # Ruido heteroscedástico: más ancho donde hay menos datos (ciudad sin barrio).
        log_m2 += rng.normal(0, 0.30 if unmatched else 0.20)
        copies = 1 + int(rng.random() < 0.12) + int(rng.random() < 0.04)  # duplicados del cluster
        for copy in range(copies):
            if len(rows) >= n:
                break
            jitter = rng.normal(0, 0.02) if copy else 0.0
            usd_m2 = math.exp(log_m2 + jitter)
            rows.append(
                {
                    "listing_key": f"sintetico:{cluster:06d}{copy}",
                    "cluster_id": f"c{cluster:06d}",
                    "snapshot_date": "2026-11-01",
                    "city": city,
                    "neighborhood": barrio,
                    "neighborhood_match": "sin_match" if unmatched else "exacto",
                    "geo_precision": "ciudad" if unmatched else "barrio",
                    "property_type": ptype,
                    "price_usd": round(usd_m2 * area, 2),
                    "built_area_m2": area,
                    "built_area_source": str(rng.choice(["tag", "texto"])),
                    "land_area_m2": (
                        "" if ptype == "departamento" else round(area * rng.uniform(1.2, 3), 1)
                    ),
                    "bedrooms": int(np.clip(round(area / 40), 1, 6)),
                    "bathrooms": int(np.clip(round(area / 60), 1, 5)),
                    "garages": "" if rng.random() < 0.4 else int(rng.integers(0, 3)),
                    **flags,
                    "street_surface": ""
                    if rng.random() < 0.6
                    else str(rng.choice(["pavimento", "empedrado", "tierra"])),
                    "advertiser_type": str(rng.choice(["particular", "inmobiliaria"])),
                    "is_sponsored": int(rng.random() < 0.07),
                    "usd_per_m2": round(usd_m2, 4),
                    "log_usd_per_m2": round(math.log(usd_m2), 6),
                }
            )
    return rows, {
        "effects_on_log_usd_per_m2": effects,
        "noise_sd": {"barrio": 0.20, "ciudad": 0.30},
        "duplicates": "12 % de los clusters con 2 avisos y 4 % con 3",
    }


def _write(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("x", newline="", encoding="utf-8") as fh:  # "x": nunca pisa
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    rng = np.random.default_rng(args.seed)
    gazetteer, features = build_geo(rng)
    rows, truth = build_dataset(rng, args.n, gazetteer, features)
    args.out.mkdir(parents=True, exist_ok=True)
    _write(args.out / "gazetteer.csv", gazetteer, list(gazetteer[0]))
    _write(args.out / "geo_features.csv", features, list(features[0]))
    _write(args.out / "dataset.csv", rows, DATASET_COLUMNS)
    with (args.out / "ground_truth.json").open("x", encoding="utf-8") as fh:
        json.dump({"seed": args.seed, "n": args.n, **truth}, fh, ensure_ascii=False, indent=2)
    print(f"OK: {len(rows)} filas, {len(gazetteer)} barrios -> {args.out}")


if __name__ == "__main__":
    main()
