"""Entrenamiento y evaluación agrupada reproducible del baseline (F8.3)."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from avm.contract.version import CONTRACT_VERSION
from avm.model import metrics
from avm.model.baseline import Baseline
from avm.model.data import IGNORED_FEATURES, load_data
from avm.model.splits import grouped_kfold


def split_calibration(indices, groups, seed):
    split = grouped_kfold(groups[indices], n_splits=4, seed=seed)[0]
    return indices[split.train], indices[split.test]


def fit_calibrated(features, target, groups, train, calibration, min_clusters):
    if set(groups[train]) & set(groups[calibration]):
        raise ValueError("Clusters compartidos entre entrenamiento y calibración")
    model = Baseline(min_clusters).fit(features.iloc[train], target[train], groups[train])
    residuals = target[calibration] - model.predict(features.iloc[calibration])
    lower, upper = np.quantile(residuals, [0.1, 0.9])
    parameters = {
        "coverage_nominal": 0.8,
        "residual_low": min(0.0, float(lower)),
        "residual_high": max(0.0, float(upper)),
        "method": "empirical_signed_log_residuals",
        "n_calibration": len(calibration),
    }
    return model, parameters


def predict_interval(model, calibration, features):
    log_prediction = model.predict(features)
    return (
        np.exp(log_prediction),
        np.exp(log_prediction + calibration["residual_low"]),
        np.exp(log_prediction + calibration["residual_high"]),
    )


def score(target, prediction, low, high):
    return {
        "mdape": metrics.mdape(target, prediction),
        "mape": metrics.mape(target, prediction),
        "pe10": metrics.pe_within(target, prediction, 0.1),
        "pe20": metrics.pe_within(target, prediction, 0.2),
        "rmse_log": metrics.rmse_log(target, prediction),
        "interval_coverage": metrics.interval_coverage(target, low, high),
        "mean_interval_width": metrics.mean_interval_width(low, high, prediction, relative=True),
        "n_test": len(target),
    }


def train_baseline(
    dataset: Path, geo: Path, gazetteer: Path, output: Path, *, seed=7, min_clusters=20
):
    if output.exists():
        raise FileExistsError(f"Elegí una versión nueva, la carpeta ya existe: {output}")
    features, target, groups = load_data(dataset, geo)
    if len(set(groups)) < 10:
        raise ValueError("Se requieren al menos 10 clusters para train/calibración/test")
    records = pd.read_csv(dataset, keep_default_na=False)
    real_target = np.exp(target)
    if not np.isfinite(real_target).all() or (real_target <= 0).any():
        raise ValueError("Target fuera del rango representable")
    outer_splits = grouped_kfold(groups, n_splits=5, seed=seed)
    holdout = outer_splits[0]
    train, calibration = split_calibration(holdout.train, groups, seed + 1)
    model, parameters = fit_calibrated(features, target, groups, train, calibration, min_clusters)
    prediction, low, high = predict_interval(model, parameters, features.iloc[holdout.test])
    test_metrics = score(real_target[holdout.test], prediction, low, high)
    segments = {}
    for column in ("city", "property_type"):
        segments[column] = {}
        for value in sorted(features[column].unique()):
            mask = features.iloc[holdout.test][column].to_numpy() == value
            if mask.any():
                segments[column][value] = score(
                    real_target[holdout.test][mask], prediction[mask], low[mask], high[mask]
                )
    cv_results = []
    for fold, split in enumerate(outer_splits):
        fold_train, fold_cal = split_calibration(split.train, groups, seed + 1)
        fold_model, fold_parameters = fit_calibrated(
            features, target, groups, fold_train, fold_cal, min_clusters
        )
        values = predict_interval(fold_model, fold_parameters, features.iloc[split.test])
        cv_results.append({"fold": fold, **score(real_target[split.test], *values)})
    train_types = {
        value: len(set(groups[train][features.iloc[train].property_type.to_numpy() == value]))
        for value in sorted(features.property_type.unique())
    }
    metadata = {
        "model_version": output.name,
        "model_kind": "baseline",
        "contract_version": CONTRACT_VERSION,
        "snapshot_date": str(records.snapshot_date.max()),
        "trained_at": datetime.now(UTC).isoformat(),
        "n_train": len(train),
        "n_calibration": len(calibration),
        "n_test": len(holdout.test),
        "n_dataset": len(target),
        "features": list(features.columns),
        "baseline_inputs": ["city", "neighborhood", "property_type"],
        "coverage_nominal": 0.8,
        "ignored_features": list(IGNORED_FEATURES),
        "min_clusters": min_clusters,
        "low_confidence_property_types": ["departamento"],
        "train_clusters_by_type": train_types,
        "dataset_rows_by_type": {
            str(k): int(v) for k, v in records.property_type.value_counts().items()
        },
        "metrics": test_metrics,
        "metrics_by_segment": segments,
        "grouped_kfold": cv_results,
        "seed": seed,
        "split_method": "grouped_kfold(5), fold 0 test; inner grouped_kfold(4) calibration",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "geo_sha256": hashlib.sha256(geo.read_bytes()).hexdigest(),
        "gazetteer_sha256": hashlib.sha256(gazetteer.read_bytes()).hexdigest(),
        "is_test_model": bool(records.listing_key.str.startswith("sintetico:").all()),
        "limitations": [
            "precio de oferta estimado",
            "Intervalos empíricos sin garantía conformal",
            "Garages y street_surface excluidos por cobertura",
            "Métricas por fila; cada cluster tiene un voto en las medianas",
            "Departamento requiere revisar el supuesto de superficie construida",
            "Modelo final conserva train/calibración/test separados",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".baseline-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, value in [
            ("model.json", model.to_dict()),
            ("calibration.json", parameters),
            ("metadata.json", metadata),
        ]:
            (staging / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
            )
        shutil.copy2(geo, staging / "geo_features.csv")
        shutil.copy2(gazetteer, staging / "gazetteer.csv")
        (staging / "ATTRIBUTION.txt").write_text(
            "© OpenStreetMap contributors (ODbL)\n", encoding="utf-8"
        )
        # Validar la misma ruta de carga que usa la API antes de publicar la carpeta.
        from avm.model.predictor import Predictor

        Predictor.load(staging)
        staging.rename(output)
    return metadata
