"""Tests de la API (F11.2, F11.3, F11.5) con TestClient y el FakePredictor."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from avm.api.app import TEST_MODEL_HEADER, create_app
from avm.api.config import Settings
from avm.api.fake import FakePredictor
from avm.contract import City, PredictionResponse

VALID = {"city": "luque", "property_type": "casa", "built_area_m2": 120}


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        return c


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


# --- /predict: validación y contrato ---


def test_predict_returns_valid_contract_response(client: TestClient) -> None:
    r = client.post("/predict", json={**VALID, "neighborhood": "Barrio de prueba 1"})
    assert r.status_code == 200
    body = PredictionResponse.model_validate(r.json())
    assert body.label == "precio de oferta estimado"
    assert body.total_usd == pytest.approx(body.usd_per_m2 * 120)
    assert body.warnings == ()


@pytest.mark.parametrize(
    "patch",
    [
        {"city": "encarnacion"},
        {"property_type": "terreno"},
        {"built_area_m2": 0},
        {"built_area_m2": -5},
        {"lat": -25.3},
    ],
)
def test_predict_out_of_scope_is_422(client: TestClient, patch: dict[str, Any]) -> None:
    assert client.post("/predict", json={**VALID, **patch}).status_code == 422


def test_predict_missing_area_is_422(client: TestClient) -> None:
    body = {k: v for k, v in VALID.items() if k != "built_area_m2"}
    assert client.post("/predict", json=body).status_code == 422


def test_predict_without_neighborhood_warns_city_fallback(client: TestClient) -> None:
    r = client.post("/predict", json=VALID)
    codes = [w["code"] for w in r.json()["warnings"]]
    assert codes == ["fallback_ciudad"]


def test_predict_unknown_neighborhood_warns(client: TestClient) -> None:
    r = client.post("/predict", json={**VALID, "neighborhood": "Barrio inexistente"})
    codes = [w["code"] for w in r.json()["warnings"]]
    assert codes == ["barrio_desconocido", "fallback_ciudad"]


def test_predict_neighborhood_match_ignores_case_and_accents(client: TestClient) -> None:
    r = client.post("/predict", json={**VALID, "neighborhood": "  BARRIO DE PRUEBÁ 2 "})
    assert r.json()["warnings"] == []


def test_predict_marks_test_model_header(client: TestClient) -> None:
    r = client.post("/predict", json=VALID)
    assert r.headers[TEST_MODEL_HEADER] == "true"


def test_predict_internal_error_hides_details() -> None:
    class Boom(FakePredictor):
        def predict(self, request: Any) -> Any:
            raise ValueError("C:\\secreto\\modelo.bin")

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = Boom()
        r = c.post("/predict", json=VALID)
    assert r.status_code == 500
    assert "secreto" not in r.text


def test_real_model_has_no_test_header() -> None:
    class Real(FakePredictor):
        @property
        def metadata(self) -> dict[str, Any]:
            return {"model_version": "x"}

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = Real()
        r = c.post("/predict", json=VALID)
    assert TEST_MODEL_HEADER not in r.headers


# --- /barrios ---


def test_barrios_lists_neighborhoods(client: TestClient) -> None:
    r = client.get("/barrios", params={"ciudad": "asuncion"})
    assert r.status_code == 200
    assert r.json() == client.app.state.predictor.neighborhoods(City.ASUNCION)  # type: ignore[attr-defined]
    assert len(r.json()) > 0


def test_barrios_invalid_city_is_422(client: TestClient) -> None:
    assert client.get("/barrios", params={"ciudad": "encarnacion"}).status_code == 422
    assert client.get("/barrios").status_code == 422


# --- /model-info ---


def test_model_info_declares_test_model(client: TestClient) -> None:
    info = client.get("/model-info").json()
    assert info["is_test_model"] is True
    assert info["n_train"] == 0
    assert "metrics" not in info


def test_model_info_has_no_local_paths() -> None:
    class WithPaths(FakePredictor):
        @property
        def metadata(self) -> dict[str, Any]:
            return {
                "model_version": "v1",
                "model_dir": "C:\\Users\\x\\models\\v1",
                "source": "/home/x/data.csv",
                "nested": {"artifact_path": "models/v1", "n_train": 10, "note": "relativo\\raro"},
                "features": ["a", "b"],
                "trained_at": __import__("datetime").datetime(2026, 11, 5, 12, 0),
            }

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = WithPaths()
        info = c.get("/model-info").json()
    assert info == {
        "model_version": "v1",
        "nested": {"n_train": 10},
        "features": ["a", "b"],
        "trained_at": "2026-11-05T12:00:00",
    }


# --- /health y carga del predictor ---


def test_health_ok_with_fake(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_and_predict_503_without_predictor() -> None:
    with _client(Settings()) as c:
        health = c.get("/health")
        assert health.status_code == 503
        assert "AVM_PREDICTOR" in health.json()["detail"]
        assert c.post("/predict", json=VALID).status_code == 503
        assert c.get("/barrios", params={"ciudad": "luque"}).status_code == 503
        assert c.get("/model-info").status_code == 503


def test_unknown_predictor_mode_is_503() -> None:
    with _client(Settings(predictor="otro")) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert "'model' o 'fake'" in r.json()["detail"]


def test_model_mode_without_model_dir_is_503() -> None:
    with _client(Settings(predictor="model")) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert "AVM_MODEL_DIR" in r.json()["detail"]


def test_model_mode_without_predictor_module_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real = importlib.import_module

    def fake_import(name: str, *a: Any, **k: Any) -> Any:
        if name == "avm.model.predictor":
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)

    monkeypatch.setattr("avm.api.loader.importlib.import_module", fake_import)
    with _client(Settings(predictor="model", model_dir="models/x")) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert "avm.model.predictor" in r.json()["detail"]


def test_model_mode_loads_predictor_from_model_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Path] = []

    class Loaded(FakePredictor):
        @classmethod
        def load(cls, model_dir: Path) -> "Loaded":
            seen.append(model_dir)
            return cls()

        @property
        def metadata(self) -> dict[str, Any]:
            return {"model_version": "v-real"}

    class Module:
        Predictor = Loaded

    monkeypatch.setattr("avm.api.loader.importlib.import_module", lambda name: Module)
    with _client(Settings(predictor="model", model_dir=str(tmp_path))) as c:
        r = c.get("/health")
    assert r.json() == {"status": "ok", "model_version": "v-real"}
    assert seen == [tmp_path]


def test_model_load_failure_is_503_without_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        @classmethod
        def load(cls, model_dir: Path) -> None:
            raise OSError("no existe C:\\Users\\x\\models\\v1")

    class Module:
        Predictor = Broken

    monkeypatch.setattr("avm.api.loader.importlib.import_module", lambda name: Module)
    with _client(Settings(predictor="model", model_dir="models/v1")) as c:
        r = c.get("/health")
        p = c.post("/predict", json=VALID)
    assert r.status_code == p.status_code == 503
    assert "Users" not in r.text
    assert "logs" in r.json()["detail"]


def test_fake_in_production_refuses_to_start() -> None:
    app = create_app(Settings(predictor="fake", env="production"))
    with pytest.raises(RuntimeError, match="producción|production"), TestClient(app):
        pass


def test_fake_env_check_is_case_insensitive() -> None:
    app = create_app(Settings(predictor="fake", env=" Production "))
    with pytest.raises(RuntimeError), TestClient(app):
        pass


# --- rate limit y CORS ---


def test_rate_limit_returns_429_with_retry_after() -> None:
    with _client(Settings(predictor="fake", rate_limit_per_min=2)) as c:
        assert c.post("/predict", json=VALID).status_code == 200
        assert c.post("/predict", json=VALID).status_code == 200
        r = c.post("/predict", json=VALID)
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1
        # Solo limita /predict.
        assert c.get("/health").status_code == 200


def test_cors_allows_only_configured_origin() -> None:
    with _client(Settings(predictor="fake", cors_origin="http://localhost:5173")) as c:
        ok = c.get("/health", headers={"Origin": "http://localhost:5173"})
        other = c.get("/health", headers={"Origin": "http://evil.example"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in other.headers


def test_no_cors_without_origin(client: TestClient) -> None:
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in r.headers


def test_test_model_from_model_mode_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    class Flagged(FakePredictor):
        @classmethod
        def load(cls, model_dir: Path) -> "Flagged":
            return cls()

    class Module:
        Predictor = Flagged

    monkeypatch.setattr("avm.api.loader.importlib.import_module", lambda name: Module)
    app = create_app(Settings(predictor="model", model_dir="models/x", env="production"))
    with pytest.raises(RuntimeError, match="is_test_model"), TestClient(app):
        pass
    # En desarrollo sí se sirve.
    with _client(Settings(predictor="model", model_dir="models/x")) as c:
        assert c.get("/health").status_code == 200


@pytest.mark.parametrize("value", ["prod", "PRODUCTION", " Prod "])
def test_fake_refuses_production_aliases(value: str) -> None:
    app = create_app(Settings(predictor="fake", env=value))
    with pytest.raises(RuntimeError), TestClient(app):
        pass
