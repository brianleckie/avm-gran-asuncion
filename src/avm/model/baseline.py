"""Medianas de log USD/m² por barrio con fallback jerárquico."""

import json

import numpy as np


def group_key(city="", property_type="", neighborhood=""):
    return json.dumps([city, property_type, neighborhood], ensure_ascii=False)


class Baseline:
    def __init__(self, min_clusters=20):
        if min_clusters < 1:
            raise ValueError("min_clusters debe ser positivo")
        self.min_clusters = min_clusters
        self.statistics = {}

    def fit(self, features, target, groups):
        frame = features[["city", "property_type", "neighborhood"]].reset_index(drop=True).copy()
        frame["target"] = np.asarray(target)
        frame["group"] = np.asarray(groups)
        self.statistics = {}
        for columns in [[], ["city"], ["city", "property_type"], ["city", "neighborhood"]]:
            if not columns:
                buckets = [((), frame)]
            else:
                buckets = frame.groupby(columns, sort=True, dropna=False)
            for values, bucket in buckets:
                values = values if isinstance(values, tuple) else (values,)
                key_parts = dict(zip(columns, values, strict=True))
                if "neighborhood" in key_parts and not key_parts["neighborhood"]:
                    continue
                # Un cluster tiene un voto aunque contenga varias republicaciones.
                cluster_targets = bucket.groupby("group").target.median()
                self.statistics[group_key(**key_parts)] = {
                    "median": float(cluster_targets.median()),
                    "n_clusters": len(cluster_targets),
                }
        return self

    def select(self, row):
        keys = []
        if row["neighborhood"]:
            keys.append((group_key(row["city"], neighborhood=row["neighborhood"]), "barrio"))
        keys.extend(
            [
                (group_key(row["city"], row["property_type"]), "tipo_ciudad"),
                (group_key(row["city"]), "ciudad"),
                (group_key(), "global"),
            ]
        )
        for key, level in keys:
            stats = self.statistics.get(key)
            if stats and (stats["n_clusters"] >= self.min_clusters or level == "global"):
                return stats["median"], stats["n_clusters"], level
        raise ValueError("Baseline sin entrenamiento")

    def predict(self, features):
        return np.array([self.select(row)[0] for row in features.to_dict("records")])

    def neighborhood_count(self, city, neighborhood):
        return self.statistics.get(group_key(city, neighborhood=neighborhood), {}).get(
            "n_clusters", 0
        )

    def to_dict(self):
        return {
            "kind": "baseline",
            "min_clusters": self.min_clusters,
            "statistics": self.statistics,
        }

    @classmethod
    def from_dict(cls, value):
        if value.get("kind") != "baseline":
            raise ValueError("Tipo de modelo no soportado")
        model = cls(value["min_clusters"])
        model.statistics = value["statistics"]
        return model
