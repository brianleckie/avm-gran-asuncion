"""Tests de las piezas chicas de la API: config, rate limiter, FakePredictor, wording."""

from pathlib import Path

import pytest

from avm.api import fake as fake_module
from avm.api.config import DEFAULT_RATE_LIMIT_PER_MIN, Settings
from avm.api.fake import FakePredictor
from avm.api.protocol import PredictorProtocol
from avm.api.ratelimit import UNKNOWN_CLIENT, RateLimiter, client_ip
from avm.contract import City, PredictionRequest

API_DIR = Path(__file__).resolve().parents[2] / "src" / "avm" / "api"


def test_settings_defaults_and_parsing() -> None:
    s = Settings.from_env({})
    assert s.predictor is None
    assert s.env == "development"
    assert s.rate_limit_per_min == DEFAULT_RATE_LIMIT_PER_MIN
    s = Settings.from_env(
        {
            "AVM_PREDICTOR": " FAKE ",
            "AVM_MODEL_DIR": "models/v1",
            "AVM_ENV": "production",
            "AVM_CORS_ORIGIN": "https://x.vercel.app",
            "AVM_RATE_LIMIT_PER_MIN": "5",
        }
    )
    assert (s.predictor, s.model_dir, s.is_production, s.rate_limit_per_min) == (
        "fake",
        "models/v1",
        True,
        5,
    )
    assert s.cors_origin == "https://x.vercel.app"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1", True), ("true", True), (" TRUE ", True), ("0", False), ("yes", False), ("", False)],
)
def test_settings_trust_proxy(raw: str, expected: bool) -> None:
    assert Settings.from_env({"AVM_TRUST_PROXY": raw}).trust_proxy is expected
    assert Settings.from_env({}).trust_proxy is False


@pytest.mark.parametrize(
    ("forwarded_for", "peer", "trust", "expected"),
    [
        # Sin confianza en el proxy, el header se ignora.
        ("203.0.113.5", "10.0.0.1", False, "10.0.0.1"),
        # Con confianza: el ÚLTIMO valor (el que agrega el proxy), con o sin espacios.
        ("203.0.113.5", "10.0.0.1", True, "203.0.113.5"),
        ("198.51.100.1, 203.0.113.5", "10.0.0.1", True, "203.0.113.5"),
        ("198.51.100.1,203.0.113.5 ", "10.0.0.1", True, "203.0.113.5"),
        ("2001:db8::1", "10.0.0.1", True, "2001:db8::1"),
        # Valor inválido o header ausente/vacío: IP de la conexión.
        ("no-es-una-ip", "10.0.0.1", True, "10.0.0.1"),
        ("203.0.113.5, basura", "10.0.0.1", True, "10.0.0.1"),
        (None, "10.0.0.1", True, "10.0.0.1"),
        ("", "10.0.0.1", True, "10.0.0.1"),
        # Sin conexión conocida.
        (None, None, True, UNKNOWN_CLIENT),
        (None, None, False, UNKNOWN_CLIENT),
    ],
)
def test_client_ip(forwarded_for: str | None, peer: str | None, trust: bool, expected: str) -> None:
    assert client_ip(forwarded_for, peer, trust) == expected


@pytest.mark.parametrize("bad", ["abc", "0", "-3"])
def test_settings_rejects_bad_rate_limit(bad: str) -> None:
    with pytest.raises(RuntimeError):
        Settings.from_env({"AVM_RATE_LIMIT_PER_MIN": bad})


def test_rate_limiter_window_and_keys() -> None:
    now = [0.0]
    rl = RateLimiter(2, window=10, clock=lambda: now[0])
    assert rl.check("a") is None
    assert rl.check("a") is None
    wait = rl.check("a")
    assert wait is not None and wait == pytest.approx(10)
    assert rl.check("b") is None  # otra IP tiene su propio cupo
    now[0] = 10.0
    assert rl.check("a") is None  # la ventana ya venció


def test_rate_limiter_prunes_stale_keys() -> None:
    now = [0.0]
    rl = RateLimiter(1, window=1, clock=lambda: now[0])
    for i in range(1100):
        rl.check(f"ip{i}")
    now[0] = 5.0
    rl.check("nueva")
    assert len(rl._hits) < 1100


def test_fake_conforms_to_protocol_and_is_a_test_model() -> None:
    predictor: PredictorProtocol = FakePredictor.load(Path("."))
    md = predictor.metadata
    assert md["is_test_model"] is True and md["n_train"] == 0
    assert "metrics" not in md
    assert all(predictor.neighborhoods(c) for c in City)


def test_fake_reads_synthetic_gazetteer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gaz = tmp_path / "gazetteer.csv"
    gaz.write_text(
        "city,neighborhood,aliases\n"
        "luque,Barrio Uno,\n"
        "luque,Barrio Uno,\n"
        "luque,,\n"
        "otra_ciudad,Fuera,\n"
        "asuncion,Centro,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fake_module, "SYNTHETIC_GAZETTEER", gaz)
    p = FakePredictor.load(Path("."))
    assert p.neighborhoods(City.LUQUE) == ["Barrio Uno"]
    assert p.neighborhoods(City.ASUNCION) == ["Centro"]


def test_fake_ignores_empty_or_bad_gazetteer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gaz = tmp_path / "gazetteer.csv"
    gaz.write_text("x,y\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(fake_module, "SYNTHETIC_GAZETTEER", gaz)
    p = FakePredictor.load(Path("."))
    assert p.neighborhoods(City.LUQUE)[0].startswith("Barrio de prueba")


def test_fake_response_scales_with_area() -> None:
    p = FakePredictor()
    req = PredictionRequest(city=City.LUQUE, property_type="casa", built_area_m2=50)  # type: ignore[arg-type]
    r = p.predict(req)
    assert r.total_low <= r.total_usd <= r.total_high
    assert r.total_usd == pytest.approx(r.usd_per_m2 * 50)


def test_api_sources_avoid_forbidden_wording() -> None:
    for path in API_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "valor de mercado" not in text, path
        assert "precio real" not in text, path


def test_public_metadata_handles_paths_and_odd_types() -> None:
    from datetime import date
    from pathlib import PurePath

    from avm.api.sanitize import public_metadata

    out = public_metadata(
        {
            "p": PurePath("a/b"),
            "d": date(2026, 11, 5),
            "obj": object.__name__,
            "lst": ["ok", r"C:\x\y", "/etc/z", 3],
            "weird": complex(1, 2),
        }
    )
    assert out["p"] is None
    assert out["d"] == "2026-11-05"
    assert out["lst"] == ["ok", 3]
    assert out["weird"] == "(1+2j)"
