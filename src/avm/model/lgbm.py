"""LightGBM cuantílico con vocabularios ajustados exclusivamente en train."""

import gzip
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from avm.model.baseline import group_key
from avm.model.splits import grouped_kfold

CATEGORICAL_COLUMNS = ("city", "neighborhood", "property_type", "geo_precision")
CONFIGURATIONS = (
    {"n_estimators": 200, "num_leaves": 15, "min_child_samples": 20},
    {"n_estimators": 250, "num_leaves": 31, "min_child_samples": 30},
)
ALPHAS = (0.1, 0.5, 0.9)


def make_estimator(alpha, configuration, seed):
    return lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        learning_rate=0.05,
        reg_lambda=2.0,
        random_state=seed,
        n_jobs=1,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
        **configuration,
    )


class QuantileModel:
    def __init__(self, *, with_geo=True, min_clusters=20):
        if min_clusters < 1:
            raise ValueError("min_clusters debe ser positivo")
        self.with_geo = with_geo
        self.min_clusters = min_clusters
        self.columns = []
        self.categories = {}
        self.boosters = {}
        self.support = {}

    def fit_schema(self, features):
        self.columns = [c for c in features if self.with_geo or not c.startswith(("dist_", "n_"))]
        self.categories = {
            c: sorted(features[c].fillna("").astype(str).unique().tolist())
            for c in CATEGORICAL_COLUMNS
            if c in self.columns
        }

    def transform(self, features):
        if not set(self.columns).issubset(features):
            raise ValueError("Faltan columnas de entrenamiento en la entrada")
        result = features[self.columns].copy()
        for column in self.columns:
            if column in self.categories:
                values = result[column].fillna("").astype(str)
                values = values.where(values.isin(self.categories[column]))
                result[column] = pd.Categorical(values, categories=self.categories[column])
            else:
                result[column] = pd.to_numeric(result[column].replace("", np.nan), errors="raise")
                if np.isinf(result[column]).any():
                    raise ValueError(f"Feature infinita: {column}")
                result[column] = result[column].astype(float)
        return result

    def fit(self, features, target, groups, configuration, seed):
        self.fit_schema(features)
        encoded = self.transform(features)
        sizes = pd.Series(groups).value_counts()
        weights = np.array([1.0 / sizes[group] for group in groups])
        self.boosters = {}
        for alpha in ALPHAS:
            estimator = make_estimator(alpha, configuration, seed)
            estimator.fit(encoded, target, sample_weight=weights)
            self.boosters[alpha] = estimator.booster_
        support = features[["city", "neighborhood"]].reset_index(drop=True).copy()
        support["group"] = np.asarray(groups)
        self.support = {
            group_key(city, neighborhood=name): int(count)
            for (city, name), count in support.groupby(["city", "neighborhood"])
            .group.nunique()
            .items()
        }
        return self

    def raw_quantiles(self, features):
        encoded = self.transform(features)
        return np.column_stack([self.boosters[a].predict(encoded, num_threads=1) for a in ALPHAS])

    def interval(self, features):
        raw = self.raw_quantiles(features)
        # Envolvente previa a calibración que contiene siempre la mediana estimada.
        return raw[:, 1], raw.min(axis=1), raw.max(axis=1)

    def predict(self, features):
        return self.interval(features)[0]

    def neighborhood_count(self, city, neighborhood):
        return self.support.get(group_key(city, neighborhood=neighborhood), 0)

    def save(self, path: Path):
        value = {
            "kind": "lightgbm_cqr",
            "with_geo": self.with_geo,
            "min_clusters": self.min_clusters,
            "columns": self.columns,
            "categories": self.categories,
            "support": self.support,
            "boosters": {str(a): self.boosters[a].model_to_string() for a in ALPHAS},
        }
        path.write_bytes(
            gzip.compress(json.dumps(value, ensure_ascii=False).encode("utf-8"), mtime=0)
        )

    @classmethod
    def load(cls, path: Path):
        value = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        if value["kind"] != "lightgbm_cqr":
            raise ValueError("Tipo de modelo no compatible")
        model = cls(with_geo=value["with_geo"], min_clusters=value["min_clusters"])
        model.columns, model.categories, model.support = (
            value["columns"],
            value["categories"],
            value["support"],
        )
        model.boosters = {a: lgb.Booster(model_str=value["boosters"][str(a)]) for a in ALPHAS}
        return model


def tune(features, target, groups, seed, with_geo):
    split = grouped_kfold(groups, n_splits=4, seed=seed)[0]
    schema = QuantileModel(with_geo=with_geo)
    schema.fit_schema(features.iloc[split.train])
    train = schema.transform(features.iloc[split.train])
    validation = schema.transform(features.iloc[split.test])
    sizes = pd.Series(groups[split.train]).value_counts()
    weights = np.array([1.0 / sizes[g] for g in groups[split.train]])
    trials = []
    for configuration in CONFIGURATIONS:
        estimator = make_estimator(0.5, configuration, seed)
        estimator.fit(train, target[split.train], sample_weight=weights)
        prediction = estimator.predict(validation, num_threads=1)
        error = float(np.mean(np.abs(target[split.test] - prediction)))
        trials.append({"configuration": dict(configuration), "validation_mae_log": error})
    selected = min(trials, key=lambda trial: trial["validation_mae_log"])["configuration"]
    return selected, trials
