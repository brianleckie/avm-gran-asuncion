"""Configuración de la API, leída de variables de entorno.

Variables:
- AVM_PREDICTOR: "model" (Predictor real de I4) o "fake" (solo desarrollo local). Sin valor, la
  API arranca pero /health y /predict devuelven 503.
- AVM_MODEL_DIR: carpeta models/<version>/ (solo con AVM_PREDICTOR=model).
- AVM_ENV: "production" (o "prod") prohíbe el predictor "fake" y cualquier predictor que se
  declare modelo de prueba (`is_test_model`). Sin valor se asume desarrollo: definirla en el deploy.
- AVM_CORS_ORIGIN: único origen permitido por CORS. Sin valor, no se permite ninguno.
- AVM_RATE_LIMIT_PER_MIN: pedidos por minuto y por IP en POST /predict.
- AVM_TRUST_PROXY: "1" (o "true") si la API corre detrás de un proxy de confianza (Railway): el rate
  limit toma la IP del ÚLTIMO valor de X-Forwarded-For (el que agrega el proxy). Sin valor se usa la
  IP de la conexión y el header se ignora. No activar si la API es accesible sin pasar por el proxy.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Límite por defecto de POST /predict: parámetro de configuración, no una medida del modelo.
DEFAULT_RATE_LIMIT_PER_MIN = 30
RATE_LIMIT_WINDOW_SECONDS = 60.0

# Valores de AVM_ENV que cuentan como producción. Sin AVM_ENV se asume desarrollo: hay que definirla
# en el deploy (F13).
PRODUCTION_ENV_VALUES = frozenset({"production", "prod"})

# Valores de AVM_TRUST_PROXY que lo activan; cualquier otro (o vacío) lo deja apagado.
TRUTHY_VALUES = frozenset({"1", "true"})


@dataclass(frozen=True)
class Settings:
    predictor: str | None = None
    model_dir: str | None = None
    env: str = "development"
    cors_origin: str | None = None
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN
    trust_proxy: bool = False

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENV_VALUES

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ

        def get(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        raw_limit = get("AVM_RATE_LIMIT_PER_MIN")
        limit = DEFAULT_RATE_LIMIT_PER_MIN
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError as exc:
                raise RuntimeError("AVM_RATE_LIMIT_PER_MIN debe ser un entero positivo") from exc
            if limit < 1:
                raise RuntimeError("AVM_RATE_LIMIT_PER_MIN debe ser un entero positivo")
        return cls(
            predictor=(get("AVM_PREDICTOR") or "").lower() or None,
            model_dir=get("AVM_MODEL_DIR"),
            env=get("AVM_ENV") or "development",
            cors_origin=get("AVM_CORS_ORIGIN"),
            rate_limit_per_min=limit,
            trust_proxy=(get("AVM_TRUST_PROXY") or "").lower() in TRUTHY_VALUES,
        )
