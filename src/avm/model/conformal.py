"""CQR por tipo con un score máximo por cluster de calibración."""

import math

import numpy as np
import pandas as pd


def calibrate_by_type(target, lower, upper, property_types, groups, coverage=0.8):
    if not 0 < coverage < 1:
        raise ValueError("La cobertura debe estar entre cero y uno")
    arrays = [np.asarray(values) for values in (target, lower, upper, property_types, groups)]
    if any(a.ndim != 1 or len(a) != len(arrays[0]) for a in arrays) or not len(arrays[0]):
        raise ValueError("La calibración requiere arrays 1D del mismo largo, no vacíos")
    y, low, high, types, cluster_ids = arrays
    if any(pd.isna(a).any() or np.any(a == "") for a in (types, cluster_ids)):
        raise ValueError("La calibración requiere tipo y cluster identificados")
    if not all(np.isfinite(a).all() for a in (y, low, high)) or np.any(low > high):
        raise ValueError("Límites o targets inválidos para calibración")
    frame = pd.DataFrame(
        {
            "type": types,
            "group": cluster_ids,
            "score": np.maximum.reduce([low - y, y - high, np.zeros(len(y))]),
        }
    )
    segments = {}
    for kind, rows in frame.groupby("type", sort=True):
        scores = rows.groupby("group").score.max().to_numpy()
        rank = math.ceil((len(scores) + 1) * coverage)
        if rank > len(scores):
            raise ValueError(f"Calibración insuficiente para {kind}: {len(scores)} clusters")
        segments[str(kind)] = {
            "qhat": float(np.sort(scores)[rank - 1]),
            "n_clusters": len(scores),
            "n_rows": len(rows),
            "rank": rank,
        }
    return {
        "method": "cqr_by_property_type_cluster_max",
        "coverage_nominal": coverage,
        "score_scale": "log_usd_per_m2",
        "segments": segments,
    }


def apply_by_type(lower, upper, property_types, calibration):
    lower, upper = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    if lower.ndim != 1 or lower.shape != upper.shape or len(property_types) != len(lower):
        raise ValueError("Límites y tipos deben tener el mismo largo y ser 1D")
    corrections = []
    for kind in property_types:
        if kind not in calibration["segments"]:
            raise ValueError(f"No hay calibración para el tipo {kind}")
        corrections.append(calibration["segments"][kind]["qhat"])
    corrections = np.asarray(corrections)
    if not np.isfinite(corrections).all() or (corrections < 0).any():
        raise ValueError("Corrección conformal inválida")
    return lower - corrections, upper + corrections
