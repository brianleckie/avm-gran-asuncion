"""Pipeline LightGBM/CQR y evaluación con particiones comunes para la ablation."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from avm.contract.version import CONTRACT_VERSION
from avm.model.conformal import apply_by_type, calibrate_by_type
from avm.model.data import IGNORED_FEATURES, load_data
from avm.model.lgbm import QuantileModel, tune
from avm.model.splits import grouped_kfold
from avm.model.training import fit_calibrated, predict_interval, score, split_calibration


def fit_lgbm(features, target, groups, train, calibration, *, seed, with_geo, min_clusters=20):
    if set(groups[train]) & set(groups[calibration]):
        raise ValueError("Clusters compartidos entre entrenamiento y calibración")
    configuration, trials = tune(features.iloc[train], target[train], groups[train], seed, with_geo)
    model = QuantileModel(with_geo=with_geo, min_clusters=min_clusters).fit(
        features.iloc[train], target[train], groups[train], configuration, seed
    )
    _, lower, upper = model.interval(features.iloc[calibration])
    parameters = calibrate_by_type(
        target[calibration],
        lower,
        upper,
        features.iloc[calibration].property_type.to_numpy(),
        groups[calibration],
    )
    missing = set(features.property_type) - set(parameters["segments"])
    if missing:
        raise ValueError(f"Falta calibración por tipo: {sorted(missing)}")
    return model, parameters, {"selected": configuration, "trials": trials}


def metric_segments(features, target, groups, predictions, *, model, cutpoints):
    point, lower, upper = predictions
    support = np.array(
        [model.neighborhood_count(row.city, row.neighborhood) for row in features.itertuples()]
    )
    segments = {
        "all": np.repeat("all", len(features)),
        "property_type": features.property_type.to_numpy(),
        "city": features.city.to_numpy(),
        "geo_precision": features.geo_precision.to_numpy(),
        "price_tercile": np.array(["bajo", "medio", "alto"])[np.digitize(target, cutpoints)],
        "neighborhood_support": np.where(
            features.geo_precision.to_numpy() == "ciudad",
            "ciudad",
            np.where(support < model.min_clusters, "pocos_datos", "suficiente"),
        ),
    }
    results = []
    for segment, values in segments.items():
        for value in sorted(set(values)):
            mask = values == value
            metrics = score(np.exp(target[mask]), point[mask], lower[mask], upper[mask])
            covered = (np.exp(target[mask]) >= lower[mask]) & (np.exp(target[mask]) <= upper[mask])
            cluster_coverage = (
                pd.DataFrame({"group": groups[mask], "covered": covered})
                .groupby("group")
                .covered.all()
            )
            results.append(
                {
                    "segment": segment,
                    "value": str(value),
                    **metrics,
                    "n_clusters": len(cluster_coverage),
                    "cluster_joint_coverage": float(cluster_coverage.mean()),
                }
            )
    return results


def predictions_cqr(model, parameters, features):
    point, raw_lower, raw_upper = model.interval(features)
    lower, upper = apply_by_type(
        raw_lower, raw_upper, features.property_type.to_numpy(), parameters
    )
    return (
        (np.exp(point), np.exp(lower), np.exp(upper)),
        (np.exp(point), np.exp(raw_lower), np.exp(raw_upper)),
    )


def train_lightgbm(
    dataset,
    geo,
    gazetteer,
    output,
    *,
    seed=7,
    min_clusters=20,
    with_geo=True,
    dataset_version="unspecified",
    stage="development",
):
    if output.exists():
        raise FileExistsError(f"Elegí otra versión: {output}")
    if stage not in {"development", "final"}:
        raise ValueError("stage debe ser development o final")
    features, target, groups = load_data(dataset, geo)
    records = pd.read_csv(dataset, keep_default_na=False)
    split = grouped_kfold(groups, 5, seed)[0]
    train, calibration = split_calibration(split.train, groups, seed + 1)
    model, parameters, tuning = fit_lgbm(
        features,
        target,
        groups,
        train,
        calibration,
        seed=seed,
        with_geo=with_geo,
        min_clusters=min_clusters,
    )
    predictions, raw_predictions = predictions_cqr(model, parameters, features.iloc[split.test])
    cutpoints = np.quantile(target[train], [1 / 3, 2 / 3])
    segments = metric_segments(
        features.iloc[split.test],
        target[split.test],
        groups[split.test],
        predictions,
        model=model,
        cutpoints=cutpoints,
    )
    raw_segments = metric_segments(
        features.iloc[split.test],
        target[split.test],
        groups[split.test],
        raw_predictions,
        model=model,
        cutpoints=cutpoints,
    )
    train_rows = features.iloc[train].copy()
    train_rows["group"] = groups[train]
    by_type = train_rows.groupby("property_type").group.nunique().to_dict()
    by_city = train_rows.groupby("city").group.nunique().to_dict()
    metadata = {
        "model_kind": "lightgbm_cqr",
        "model_version": output.name,
        "contract_version": CONTRACT_VERSION,
        "trained_at": datetime.now(UTC).isoformat(),
        "snapshot_date": str(records.snapshot_date.max()),
        "dataset_version": dataset_version,
        "release_stage": stage,
        "is_test_model": stage != "final"
        or bool(records.listing_key.str.startswith("sintetico:").all()),
        "n_dataset": len(features),
        "n_train": len(train),
        "n_calibration": len(calibration),
        "n_test": len(split.test),
        "features": model.columns,
        "with_geo": with_geo,
        "min_clusters": min_clusters,
        "coverage_nominal": parameters["coverage_nominal"],
        "ignored_features": list(IGNORED_FEATURES),
        "low_confidence_property_types": ["departamento"],
        "train_clusters_by_type": {str(k): int(v) for k, v in by_type.items()},
        "train_clusters_by_city": {str(k): int(v) for k, v in by_city.items()},
        "metrics": score(np.exp(target[split.test]), *predictions),
        "metrics_raw_interval": score(np.exp(target[split.test]), *raw_predictions),
        "metrics_by_segment": segments,
        "metrics_raw_by_segment": raw_segments,
        "tuning": tuning,
        "seed": seed,
        "split_method": "grouped_kfold5 test, grouped_kfold4 calibration, inner train validation",
        "price_tercile_log_cutpoints": cutpoints.tolist(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "geo_sha256": hashlib.sha256(geo.read_bytes()).hexdigest(),
        "gazetteer_sha256": hashlib.sha256(gazetteer.read_bytes()).hexdigest(),
        "limitations": [
            "precio de oferta estimado",
            "Departamento mantiene confianza reducida por identificación de superficie",
            "La cobertura por tipo requiere intercambiabilidad de clusters; puede fluctuar en test",
            "Resultados de desarrollo pendientes de dataset final"
            if stage != "final"
            else "Evaluación sobre dataset declarado final",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".lgbm-", dir=output.parent) as temporary:
        staging = Path(temporary)
        model.save(staging / "model.bin")
        for name, value in [("metadata.json", metadata), ("calibration.json", parameters)]:
            (staging / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
            )
        shutil.copy2(geo, staging / "geo_features.csv")
        shutil.copy2(gazetteer, staging / "gazetteer.csv")
        (staging / "ATTRIBUTION.txt").write_text(
            "© OpenStreetMap contributors (ODbL)\n", encoding="utf-8"
        )
        from avm.model.predictor import Predictor

        Predictor.load(staging)
        staging.rename(output)
    return metadata


def evaluate_lightgbm(dataset, geo, *, seed=7):
    features, target, groups = load_data(dataset, geo)
    rows, diagnostics = [], []
    for fold, split in enumerate(grouped_kfold(groups, 5, seed)):
        train, calibration = split_calibration(split.train, groups, seed + 1)
        cutpoints = np.quantile(target[train], [1 / 3, 2 / 3])
        test_features = features.iloc[split.test]
        baseline, base_cal = fit_calibrated(features, target, groups, train, calibration, 20)
        predictions = predict_interval(baseline, base_cal, test_features)
        for metrics in metric_segments(
            test_features,
            target[split.test],
            groups[split.test],
            predictions,
            model=baseline,
            cutpoints=cutpoints,
        ):
            rows.append(
                {
                    "model": "baseline",
                    "with_geo": False,
                    "fold": fold,
                    "interval": "empirical_global",
                    **metrics,
                }
            )
        for with_geo in (False, True):
            model, parameters, tuning = fit_lgbm(
                features, target, groups, train, calibration, seed=seed, with_geo=with_geo
            )
            predictions, raw_predictions = predictions_cqr(model, parameters, test_features)
            diagnostics.append(
                {"fold": fold, "with_geo": with_geo, "calibration": parameters, "tuning": tuning}
            )
            for label, values in [("cqr_by_type", predictions), ("raw_quantile", raw_predictions)]:
                for metrics in metric_segments(
                    test_features,
                    target[split.test],
                    groups[split.test],
                    values,
                    model=model,
                    cutpoints=cutpoints,
                ):
                    rows.append(
                        {
                            "model": "lightgbm",
                            "with_geo": with_geo,
                            "fold": fold,
                            "interval": label,
                            **metrics,
                        }
                    )
    return rows, diagnostics
