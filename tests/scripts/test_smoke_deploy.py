"""Tests de scripts/smoke.py (F13.3) contra la API en proceso, sin red."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import smoke
from fastapi.testclient import TestClient

from avm.api.app import create_app
from avm.api.config import Settings
from avm.api.fake import FakePredictor
from avm.contract import City

ORIGIN = "https://avm.vercel.app"


def _client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def no_model(tmp_path: Path) -> Iterator[TestClient]:
    yield from _client(
        Settings(predictor="model", model_dir=str(tmp_path / "missing-model"), env="production")
    )


@pytest.fixture
def fake() -> Iterator[TestClient]:
    yield from _client(Settings(predictor="fake", cors_origins=(ORIGIN,)))


def _run(client: httpx.Client, **kwargs: Any) -> bool:
    return smoke.run_smoke(client, sleep=lambda _s: None, **kwargs)


def test_without_model_is_degraded_but_not_a_failure(
    no_model: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(no_model) is True
    out = capsys.readouterr().out
    assert "sin modelo todavía" in out
    assert "omitido" in out  # /predict no se intenta


def test_test_model_fails_unless_allowed(
    fake: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(fake) is False
    assert "MODELO DE PRUEBA" in capsys.readouterr().out
    assert _run(fake, allow_test_model=True) is True


def test_real_model_passes_full_flow() -> None:
    class Real(FakePredictor):
        @property
        def metadata(self) -> dict[str, Any]:
            return {"model_version": "x"}

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = Real()
        assert _run(c) is True


def test_predict_failure_is_reported() -> None:
    class Broken(FakePredictor):
        def predict(self, request: Any) -> Any:
            raise ValueError("boom")

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = Broken()
        assert _run(c, allow_test_model=True) is False


def test_empty_barrios_fail() -> None:
    class Empty(FakePredictor):
        def neighborhoods(self, city: City) -> list[str]:
            return []

    app = create_app(Settings(predictor="fake"))
    with TestClient(app) as c:
        app.state.predictor = Empty()
        assert _run(c, allow_test_model=True) is False


def test_live_down_fails_after_retries(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    waits: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x") as c:
        ok = smoke.run_smoke(c, live_retries=3, retry_wait=1.0, sleep=waits.append)
    assert ok is False
    assert waits == [1.0, 1.0]
    assert "/live no respondió 200" in capsys.readouterr().out


def test_connection_error_on_live_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x") as c:
        assert smoke.run_smoke(c, live_retries=2, sleep=lambda _s: None) is False


def test_unexpected_health_status_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.path == "/live" else 500)

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x") as c:
        assert _run(c) is False


def test_cors_check(fake: TestClient) -> None:
    assert _run(fake, origin=ORIGIN, allow_test_model=True) is True
    assert _run(fake, origin="https://otro.example", allow_test_model=True) is False


def test_invalid_contract_response_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/predict":
            return httpx.Response(200, json={"usd_per_m2": 1})
        if request.url.path == "/barrios":
            return httpx.Response(200, json=["Centro"])
        return httpx.Response(200, json={"status": "ok", "model_version": "x"})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x") as c:
        assert _run(c) is False


def test_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def fake_run(client: httpx.Client, **kwargs: Any) -> bool:
        assert str(client.base_url) == "https://api.example"
        assert kwargs == {"origin": ORIGIN, "allow_test_model": True}
        return True

    monkeypatch.setattr(smoke, "run_smoke", fake_run)
    argv = ["https://api.example/", "--origin", ORIGIN, "--allow-test-model"]
    assert smoke.main(argv) == 0
    monkeypatch.setattr(smoke, "run_smoke", lambda client, **kw: False)
    assert smoke.main(["https://api.example"]) == 1
    assert "FALLÓ" in capsys.readouterr().out
