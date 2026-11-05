"""Interfaz I4 del Predictor (docs/interfaces.md), tal como la consume la API.

La API depende de este Protocol y no de una implementación: el `Predictor` real vive en
`avm.model.predictor` (Oscar) y el `FakePredictor` de desarrollo en `avm.api.fake`.
"""

from pathlib import Path
from typing import Any, Protocol, Self

from avm.contract import City, PredictionRequest, PredictionResponse


class PredictorProtocol(Protocol):
    """Firma exacta de I4: load, predict, neighborhoods y metadata."""

    @classmethod
    def load(cls, model_dir: Path) -> Self: ...

    def predict(self, request: PredictionRequest) -> PredictionResponse: ...

    def neighborhoods(self, city: City) -> list[str]: ...

    @property
    def metadata(self) -> dict[str, Any]: ...
