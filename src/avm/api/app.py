"""API FastAPI del AVM (F11): POST /predict, GET /barrios, GET /model-info, GET /health (readiness)
y GET /live (liveness).

Depende de `PredictorProtocol` (I4), no de una implementación. Arranque:
`just serve` (ver el docstring de `avm.api.config` para las variables de entorno).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from avm.api.config import Settings
from avm.api.loader import load_predictor
from avm.api.protocol import PredictorProtocol
from avm.api.ratelimit import RateLimiter, client_ip
from avm.api.sanitize import public_metadata
from avm.contract import City, PredictionRequest, PredictionResponse

log = logging.getLogger(__name__)

TEST_MODEL_HEADER = "X-AVM-Test-Model"
_NO_PREDICTOR = "No hay un predictor cargado."


def _is_test_model(predictor: PredictorProtocol) -> bool:
    return predictor.metadata.get("is_test_model") is True


def _get_predictor(request: Request) -> PredictorProtocol:
    predictor: PredictorProtocol | None = getattr(request.app.state, "predictor", None)
    if predictor is None:
        detail = getattr(request.app.state, "load_error", None) or _NO_PREDICTOR
        raise HTTPException(status_code=503, detail=detail)
    return predictor


PredictorDep = Annotated[PredictorProtocol, Depends(_get_predictor)]


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings if settings is not None else Settings.from_env()
    limiter = RateLimiter(cfg.rate_limit_per_min)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Con AVM_PREDICTOR=fake y AVM_ENV=production esto levanta RuntimeError: no arranca.
        result = load_predictor(cfg)
        app.state.predictor = result.predictor
        app.state.load_error = result.error
        if result.error:
            log.error("Sin predictor: %s", result.error)
        yield

    app = FastAPI(
        title="AVM Gran Asunción",
        description="Precio de oferta estimado (no precio de transacción) por m² y total.",
        lifespan=lifespan,
    )

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            expose_headers=[TEST_MODEL_HEADER],
        )

    def rate_limit(request: Request) -> None:
        peer = request.client.host if request.client else None
        ip = client_ip(request.headers.get("x-forwarded-for"), peer, cfg.trust_proxy)
        retry_after = limiter.check(ip)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="Demasiados pedidos: esperá un momento y volvé a intentar.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    @app.post("/predict", response_model=PredictionResponse, dependencies=[Depends(rate_limit)])
    def predict(
        body: PredictionRequest, response: Response, predictor: PredictorDep
    ) -> PredictionResponse:
        try:
            result = predictor.predict(body)
        except Exception:
            log.exception("Falló Predictor.predict")
            raise HTTPException(
                status_code=500, detail="No se pudo calcular la estimación."
            ) from None
        if _is_test_model(predictor):
            response.headers[TEST_MODEL_HEADER] = "true"
        return result

    @app.get("/barrios", response_model=list[str])
    def barrios(ciudad: City, predictor: PredictorDep) -> list[str]:
        return predictor.neighborhoods(ciudad)

    @app.get("/model-info")
    def model_info(predictor: PredictorDep) -> dict[str, Any]:
        info: dict[str, Any] = public_metadata(predictor.metadata)
        return info

    @app.get("/live")
    def live() -> dict[str, str]:
        """Liveness: 200 si el proceso está arriba, haya o no predictor (healthcheck de Railway)."""
        return {"status": "ok"}

    @app.get("/health")
    def health(predictor: PredictorDep) -> dict[str, Any]:
        version = predictor.metadata.get("model_version")
        return {"status": "ok", "model_version": version}

    return app


app = create_app()
