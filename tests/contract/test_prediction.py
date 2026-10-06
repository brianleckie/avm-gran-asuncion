"""PredictionRequest / PredictionResponse (F1.5)."""

import math

import pytest
from pydantic import ValidationError

from avm.contract import (
    CONTRACT_VERSION,
    PredictionRequest,
    PredictionResponse,
    WarningCode,
)


def request(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "city": "luque",
        "neighborhood": "Laurelty",
        "property_type": "duplex",
        "built_area_m2": 90,
    }
    data.update(overrides)
    return data


def response(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "usd_per_m2": 1000.0,
        "p_low": 800.0,
        "p_high": 1250.0,
        "total_usd": 90000.0,
        "total_low": 72000.0,
        "total_high": 112500.0,
        "coverage_nominal": 0.8,
        "model_version": "sintetico-0",
    }
    data.update(overrides)
    return data


def test_valid_request() -> None:
    req = PredictionRequest.model_validate(request(has_pool=True))
    assert req.has_pool is True and req.has_quincho is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"city": "lambare"},
        {"property_type": "terreno"},
        {"built_area_m2": 0},
        {"built_area_m2": -90},
        {"built_area_m2": math.inf},
        {"land_area_m2": 100_001},
        {"bedrooms": -1},
        {"neighborhood": " "},
        {"latitude": -25.3},
    ],
)
def test_invalid_request(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(request(**overrides))


def test_built_area_is_required() -> None:
    data = request()
    del data["built_area_m2"]
    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(data)


def test_valid_response_carries_label_and_versions() -> None:
    res = PredictionResponse.model_validate(
        response(warnings=[{"code": "fallback_ciudad", "message": "Barrio sin datos."}])
    )
    assert res.label == "precio de oferta estimado"
    assert res.contract_version == CONTRACT_VERSION
    assert res.warnings[0].code is WarningCode.CITY_FALLBACK


@pytest.mark.parametrize(
    "overrides",
    [
        {"label": "valor estimado"},
        {"p_low": 1300.0},  # p_low > p_high
        {"p_low": 1100.0},  # estimado fuera del intervalo
        {"total_high": 80000.0},
        {"usd_per_m2": math.nan},
        {"coverage_nominal": 1.0},
        {"coverage_nominal": 0.0},
        {"model_version": ""},
        {"contract_version": "v1"},
        {"warnings": [{"code": "otro", "message": "x"}]},
    ],
)
def test_invalid_response(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PredictionResponse.model_validate(response(**overrides))


def test_json_round_trip() -> None:
    req = PredictionRequest.model_validate(request(street_surface="empedrado", garages=1))
    assert PredictionRequest.model_validate_json(req.model_dump_json()) == req
    res = PredictionResponse.model_validate(
        response(warnings=[{"code": "pocos_datos", "message": "Pocos avisos."}])
    )
    assert PredictionResponse.model_validate_json(res.model_dump_json()) == res
