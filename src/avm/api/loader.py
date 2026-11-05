"""Carga del predictor al arrancar, según AVM_PREDICTOR."""

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path

from avm.api.config import Settings
from avm.api.fake import FakePredictor
from avm.api.protocol import PredictorProtocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadResult:
    predictor: PredictorProtocol | None
    error: str | None = None


def _fail(message: str) -> LoadResult:
    return LoadResult(predictor=None, error=message)


def load_predictor(settings: Settings) -> LoadResult:
    """Devuelve el predictor o un mensaje claro (sin rutas ni trazas) de por qué no hay.

    `fake` con AVM_ENV=production no es un fallo recuperable: la API se niega a arrancar.
    """
    mode = settings.predictor
    if mode == "fake":
        if settings.is_production:
            raise RuntimeError(
                "AVM_PREDICTOR=fake está prohibido con AVM_ENV=production: "
                "el predictor de prueba no puede servir en producción."
            )
        return LoadResult(FakePredictor.load(Path(".")))
    if mode is None:
        return _fail(
            "No hay predictor configurado: definí AVM_PREDICTOR=model (con AVM_MODEL_DIR) "
            "o AVM_PREDICTOR=fake (solo desarrollo)."
        )
    if mode != "model":
        return _fail(f"AVM_PREDICTOR={mode!r} no es válido: usá 'model' o 'fake'.")
    if settings.model_dir is None:
        return _fail("AVM_PREDICTOR=model requiere AVM_MODEL_DIR con la carpeta models/<version>/.")
    try:
        module = importlib.import_module("avm.model.predictor")
    except ImportError:
        log.exception("No se pudo importar avm.model.predictor")
        return _fail(
            "El módulo avm.model.predictor todavía no está disponible en esta instalación."
        )
    try:
        predictor: PredictorProtocol = module.Predictor.load(Path(settings.model_dir))
    except Exception:
        log.exception("Falló Predictor.load")
        return _fail("No se pudo cargar el modelo de AVM_MODEL_DIR (el detalle está en los logs).")
    return LoadResult(predictor)
