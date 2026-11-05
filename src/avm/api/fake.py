"""FakePredictor: SOLO para desarrollo local de la API y la web. No es un modelo.

Devuelve siempre los mismos valores de relleno (obviamente no reales) para poder probar el flujo
completo antes de que exista el Predictor de I4. La API se niega a arrancar con este predictor si
AVM_ENV=production, y su metadata se declara modelo de prueba (`is_test_model`).
"""

import csv
import unicodedata
from pathlib import Path
from typing import Any, Self

from avm.contract import (
    City,
    PredictionRequest,
    PredictionResponse,
    PredictionWarning,
    WarningCode,
)

SYNTHETIC_GAZETTEER = Path("data/processed/sintetico/gazetteer.csv")
FAKE_MODEL_VERSION = "modelo-de-prueba"
FAKE_NEIGHBORHOODS_PER_CITY = 3

# Valores de relleno sin significado: ni un precio ni una estimación.
_PLACEHOLDER_USD_PER_M2 = 1000.0
_PLACEHOLDER_LOW = 800.0
_PLACEHOLDER_HIGH = 1200.0
_PLACEHOLDER_COVERAGE = 0.8


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.strip().casefold())
    return "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")


def _read_gazetteer(path: Path) -> dict[City, list[str]]:
    result: dict[City, list[str]] = {city: [] for city in City}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                city = City(row["city"])
            except (KeyError, ValueError):
                continue
            name = (row.get("neighborhood") or "").strip()
            if name and name not in result[city]:
                result[city].append(name)
    return result


def _placeholder_gazetteer() -> dict[City, list[str]]:
    return {
        city: [f"Barrio de prueba {i}" for i in range(1, FAKE_NEIGHBORHOODS_PER_CITY + 1)]
        for city in City
    }


class FakePredictor:
    """Cumple `PredictorProtocol` sin modelo detrás."""

    def __init__(self, gazetteer: dict[City, list[str]] | None = None) -> None:
        self._gazetteer = gazetteer if gazetteer is not None else _placeholder_gazetteer()

    @classmethod
    def load(cls, model_dir: Path | None = None) -> Self:
        """`model_dir` se ignora; lee el gazetteer sintético si existe en data/processed/."""
        if SYNTHETIC_GAZETTEER.is_file():
            gazetteer = _read_gazetteer(SYNTHETIC_GAZETTEER)
            if any(gazetteer.values()):
                return cls(gazetteer)
        return cls()

    def neighborhoods(self, city: City) -> list[str]:
        return list(self._gazetteer.get(city, []))

    def predict(self, request: PredictionRequest) -> PredictionResponse:
        warnings: list[PredictionWarning] = []
        if request.neighborhood is None:
            warnings.append(
                PredictionWarning(
                    code=WarningCode.CITY_FALLBACK,
                    message="Sin barrio: se estimó con datos de la ciudad.",
                )
            )
        else:
            known = {_fold(name) for name in self.neighborhoods(request.city)}
            if _fold(request.neighborhood) not in known:
                warnings.append(
                    PredictionWarning(
                        code=WarningCode.UNKNOWN_NEIGHBORHOOD,
                        message="El barrio no figura en el listado de la ciudad.",
                    )
                )
                warnings.append(
                    PredictionWarning(
                        code=WarningCode.CITY_FALLBACK,
                        message="Se estimó con datos de la ciudad.",
                    )
                )
        area = request.built_area_m2
        return PredictionResponse(
            usd_per_m2=_PLACEHOLDER_USD_PER_M2,
            p_low=_PLACEHOLDER_LOW,
            p_high=_PLACEHOLDER_HIGH,
            total_usd=_PLACEHOLDER_USD_PER_M2 * area,
            total_low=_PLACEHOLDER_LOW * area,
            total_high=_PLACEHOLDER_HIGH * area,
            coverage_nominal=_PLACEHOLDER_COVERAGE,
            warnings=tuple(warnings),
            model_version=FAKE_MODEL_VERSION,
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_version": FAKE_MODEL_VERSION,
            "is_test_model": True,
            "description": "Modelo de prueba para desarrollo: sus valores no significan nada.",
            "n_train": 0,
            "coverage_nominal": _PLACEHOLDER_COVERAGE,
        }
