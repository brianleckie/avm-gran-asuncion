"""Predictor I4 que carga parámetros agregados y devuelve el contrato de la API."""

import copy
import csv
import json
from pathlib import Path
from typing import Any, Self

import numpy as np
import pandas as pd

from avm.contract import City, PredictionRequest, PredictionResponse, PredictionWarning, WarningCode
from avm.contract.version import CONTRACT_VERSION
from avm.geo.gazetteer import normalize
from avm.model.baseline import Baseline
from avm.model.conformal import apply_by_type
from avm.model.data import prepare_features, read_geo


class Predictor:
    @classmethod
    def load(cls, model_dir: Path) -> Self:
        predictor = cls()
        predictor._metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        if predictor._metadata["contract_version"] != CONTRACT_VERSION:
            raise ValueError("Versión del contrato incompatible")
        kind = predictor._metadata.get("model_kind", "baseline")
        if kind == "baseline":
            predictor.model = Baseline.from_dict(
                json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
            )
        elif kind == "lightgbm_cqr":
            from avm.model.lgbm import QuantileModel

            predictor.model = QuantileModel.load(model_dir / "model.bin")
        else:
            raise ValueError(f"Tipo de modelo no soportado: {kind}")
        predictor.calibration = json.loads(
            (model_dir / "calibration.json").read_text(encoding="utf-8")
        )
        predictor.geo = read_geo(model_dir / "geo_features.csv")
        predictor._neighborhoods = {city.value: [] for city in City}
        predictor._aliases = {}
        with (model_dir / "gazetteer.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                city, name = row["city"], row["neighborhood"]
                City(city)
                predictor._neighborhoods[city].append(name)
                for alias in [name, *row.get("aliases", "").split("|")]:
                    if not alias:
                        continue
                    key = city, normalize(alias)
                    if key in predictor._aliases and predictor._aliases[key] != name:
                        raise ValueError("Alias ambiguo en el artefacto")
                    predictor._aliases[key] = name
        return predictor

    @property
    def metadata(self) -> dict[str, Any]:
        return copy.deepcopy(self._metadata)

    def neighborhoods(self, city: City) -> list[str]:
        return sorted(self._neighborhoods[city.value])

    def predict(self, request: PredictionRequest) -> PredictionResponse:
        warnings = []
        name = self._aliases.get((request.city.value, normalize(request.neighborhood or "")), "")
        if request.neighborhood and not name:
            warnings.append(
                PredictionWarning(
                    code=WarningCode.UNKNOWN_NEIGHBORHOOD,
                    message="El barrio no figura en el catálogo de la ciudad.",
                )
            )
        record = request.model_dump(mode="json")
        record["neighborhood"] = name
        features = prepare_features(pd.DataFrame([record]), self.geo)
        if self._metadata.get("model_kind", "baseline") == "baseline":
            median, count, level = self.model.select(features.iloc[0].to_dict())
            low = median + self.calibration["residual_low"]
            high = median + self.calibration["residual_high"]
        else:
            medians, lower, upper = self.model.interval(features)
            lower, upper = apply_by_type(
                lower, upper, [request.property_type.value], self.calibration
            )
            median, low, high = float(medians[0]), float(lower[0]), float(upper[0])
            count = self._metadata["train_clusters_by_city"].get(request.city.value, 0)
            level = "barrio" if features.iloc[0].neighborhood else "ciudad"
        if level != "barrio":
            warnings.append(
                PredictionWarning(
                    code=WarningCode.CITY_FALLBACK,
                    message="Se usó el respaldo de ciudad o tipo y ciudad.",
                )
            )
        n_local = self.model.neighborhood_count(request.city.value, name) if name else count
        type_count = self._metadata["train_clusters_by_type"].get(request.property_type.value, 0)
        calibration_count = (
            self.calibration.get("segments", {})
            .get(request.property_type.value, {})
            .get("n_clusters", self.model.min_clusters)
        )
        low_confidence_type = request.property_type.value in self._metadata.get(
            "low_confidence_property_types", []
        )
        if (
            n_local < self.model.min_clusters
            or type_count < self.model.min_clusters
            or calibration_count < self.model.min_clusters
            or low_confidence_type
        ):
            warnings.append(
                PredictionWarning(
                    code=WarningCode.LOW_DATA,
                    message=(
                        "Departamento con confianza reducida por la identificación de superficie."
                        if low_confidence_type
                        else "Hay pocos grupos de entrenamiento para este segmento."
                    ),
                )
            )
        point, lower, upper = (float(value) for value in np.exp([median, low, high]))
        return PredictionResponse(
            usd_per_m2=point,
            p_low=lower,
            p_high=upper,
            total_usd=point * request.built_area_m2,
            total_low=lower * request.built_area_m2,
            total_high=upper * request.built_area_m2,
            coverage_nominal=self.calibration["coverage_nominal"],
            warnings=tuple(warnings),
            model_version=self._metadata["model_version"],
        )
