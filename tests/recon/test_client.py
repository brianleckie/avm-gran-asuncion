"""Cliente de reconocimiento sin red: tope, robots, bloqueo, espera entre requests."""

from pathlib import Path

import pytest
from recon.client import (
    MAX_REQUESTS_PER_SOURCE,
    MIN_DELAY_S,
    Ledger,
    ReconClient,
    ReconError,
    Response,
    SourceBlockedError,
    looks_blocked,
)

ROBOTS = "User-agent: *\nDisallow: /venta/*-y-*\n"
BASE = "https://www.infocasas.com.py"


class FakeServer:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[str] = []

    def __call__(self, url: str) -> Response:
        self.calls.append(url)
        return self.response


def make_client(
    tmp_path: Path, response: Response | None = None
) -> tuple[ReconClient, FakeServer, list[float]]:
    server = FakeServer(response or Response(200, {}, b"<html>ok</html>"))
    sleeps: list[float] = []
    client = ReconClient(
        "infocasas",
        Ledger(tmp_path / "ledger.json"),
        ROBOTS,
        send=server,
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )
    return client, server, sleeps


def test_budget_is_enforced_and_persisted(tmp_path: Path) -> None:
    client, server, _ = make_client(tmp_path)
    for _ in range(MAX_REQUESTS_PER_SOURCE):
        client.get(f"{BASE}/")
    with pytest.raises(ReconError, match="tope"):
        client.get(f"{BASE}/")
    assert len(server.calls) == MAX_REQUESTS_PER_SOURCE
    # Un cliente nuevo sobre el mismo ledger tampoco puede seguir.
    again, _, _ = make_client(tmp_path)
    with pytest.raises(ReconError, match="tope"):
        again.check(f"{BASE}/")


def test_robots_disallowed_url_is_not_requested(tmp_path: Path) -> None:
    client, server, _ = make_client(tmp_path)
    with pytest.raises(ReconError, match="robots"):
        client.get(f"{BASE}/venta/casas-y-departamentos/asuncion")
    assert server.calls == []


def test_other_host_is_rejected(tmp_path: Path) -> None:
    client, server, _ = make_client(tmp_path)
    with pytest.raises(ReconError, match="host"):
        client.get("https://clasipar.paraguay.com/")
    assert server.calls == []


@pytest.mark.parametrize(
    "response",
    [
        Response(429, {}, b""),
        Response(403, {}, b"forbidden"),
        Response(200, {}, b"<title>Just a moment...</title>"),
        Response(200, {}, b"<div>please solve the captcha</div>"),
    ],
)
def test_block_stops_the_source(tmp_path: Path, response: Response) -> None:
    client, server, _ = make_client(tmp_path, response)
    with pytest.raises(SourceBlockedError):
        client.get(f"{BASE}/")
    with pytest.raises(SourceBlockedError):
        client.get(f"{BASE}/otra")
    assert len(server.calls) == 1


def test_recaptcha_in_a_large_page_is_not_a_block() -> None:
    body = b"<html>" + b"x" * 40_000 + b"<div class='g-recaptcha'></div></html>"
    assert looks_blocked(Response(200, {}, body)) is None


def test_waits_between_requests(tmp_path: Path) -> None:
    client, _, sleeps = make_client(tmp_path)
    client.get(f"{BASE}/")
    client.get(f"{BASE}/")
    assert sleeps and sleeps[-1] >= MIN_DELAY_S - 1


def test_transport_error_still_counts(tmp_path: Path) -> None:
    def boom(url: str) -> Response:
        raise OSError("red caída")

    ledger = Ledger(tmp_path / "ledger.json")
    client = ReconClient("infocasas", ledger, ROBOTS, send=boom, sleep=lambda s: None)
    with pytest.raises(OSError):
        client.get(f"{BASE}/")
    assert ledger.count("infocasas") == 1
