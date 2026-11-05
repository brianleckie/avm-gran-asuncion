"""Carga I1 y join I3 con una lista explícita de features permitidas."""

from pathlib import Path

import numpy as np
import pandas as pd

from avm.contract import City, PredictionRequest

# Se excluyen por indicación de Brian y por su escasa cobertura en el dataset v1.
IGNORED_FEATURES = ("garages", "street_surface")
INPUT_FEATURES = tuple(
    name for name in PredictionRequest.model_fields if name not in IGNORED_FEATURES
)


def read_geo(path: Path) -> pd.DataFrame:
    geo = pd.read_csv(path, keep_default_na=False)
    required = {"city", "neighborhood", "geo_precision"}
    if not required.issubset(geo.columns):
        raise ValueError("I3 requiere city, neighborhood y geo_precision")
    if geo.duplicated(["city", "neighborhood"]).any():
        raise ValueError("I3 contiene claves duplicadas")
    for city in City:
        if not ((geo.city == city.value) & (geo.neighborhood == "")).any():
            raise ValueError(f"I3 no tiene fallback de ciudad: {city}")
    columns = [c for c in geo if c.startswith(("dist_", "n_"))]
    if not columns:
        raise ValueError("I3 no contiene features espaciales")
    for column in columns:
        geo[column] = pd.to_numeric(geo[column].replace("", np.nan), errors="raise")
        if np.isinf(geo[column]).any() or (geo[column].dropna() < 0).any():
            raise ValueError(f"I3 contiene valores inválidos: {column}")
    return geo[["city", "neighborhood", "geo_precision", *columns]]


def prepare_features(records: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    """Misma transformación para entrenamiento e inferencia, sin acceder al target."""
    records = records.reset_index(drop=True)
    features = records.reindex(columns=INPUT_FEATURES).copy()
    features["neighborhood"] = features.neighborhood.fillna("").astype(str)
    geo_index = geo.set_index(["city", "neighborhood"])
    numeric_geo = [c for c in geo if c.startswith(("dist_", "n_"))]
    joined = []
    for index, row in features.iterrows():
        key = row.city, row.neighborhood
        if not row.neighborhood or key not in geo_index.index:
            key = row.city, ""
            features.at[index, "neighborhood"] = ""
        if key not in geo_index.index:
            raise ValueError(f"I3 no tiene la ciudad solicitada: {row.city}")
        joined.append(geo_index.loc[key, ["geo_precision", *numeric_geo]].to_dict())
    return pd.concat([features, pd.DataFrame(joined)], axis=1)


def load_data(dataset: Path, geo_path: Path):
    records = pd.read_csv(dataset, keep_default_na=False)
    required = {"cluster_id", "log_usd_per_m2", "city", "property_type", "built_area_m2"}
    if not required.issubset(records):
        raise ValueError(f"I1 incompleto: {sorted(required - set(records))}")
    if records.empty or records.cluster_id.eq("").any():
        raise ValueError("I1 vacío o sin cluster_id")
    y = pd.to_numeric(records.log_usd_per_m2, errors="raise").to_numpy(dtype=float)
    area = pd.to_numeric(records.built_area_m2, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(y).all() or not np.isfinite(area).all() or (area <= 0).any():
        raise ValueError("I1 contiene target o superficie inválidos")
    if not records.city.isin([city.value for city in City]).all():
        raise ValueError("I1 contiene ciudad fuera del alcance")
    return prepare_features(records, read_geo(geo_path)), y, records.cluster_id.to_numpy()
