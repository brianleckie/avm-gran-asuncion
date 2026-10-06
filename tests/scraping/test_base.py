"""BaseScraper: cortesía, presupuesto, robots, bloqueos, reintentos, caché sanitizada y registro.

Sin red: el transporte es `httpx.MockTransport`, y el reloj y el sleep son falsos (no se espera).
"""

import json
import random
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from avm.contract import CONTRACT_VERSION
from avm.contract.pii import find_pii
from avm.scraping.base import (
    BaseScraper,
    BlockedError,
    BudgetExhaustedError,
    RobotsUnavailableError,
    ScraperError,
    looks_blocked,
)
from avm.scraping.config import MAX_RETRIES, MIN_DELAY_S, USER_AGENT
from avm.scraping.sanitize import SanitizationError, sanitize_html

HOST = "portal.test"
BASE = f"https://{HOST}"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
PAGE = "<html><body><h1>Casa en venta</h1></body></html>"

Reply = Callable[[httpx.Request], httpx.Response] | Exception


def ok(text: str = PAGE, **kwargs: Any) -> Reply:
    return lambda request: httpx.Response(200, text=text, **kwargs)


def status(code: int, text: str = "", headers: dict[str, str] | None = None) -> Reply:
    return lambda request: httpx.Response(code, text=text, headers=headers)


class FakeClock:
    """Reloj monotónico que solo avanza cuando alguien duerme."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class MaxJitter(random.Random):
    """Jitter determinista: siempre el máximo del rango."""

    def uniform(self, a: float, b: float) -> float:
        return b


class Server:
    """Transporte falso: registra (path, hora del reloj falso) y responde según la ruta."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[tuple[str, float]] = []
        self.headers: list[httpx.Headers] = []
        self.routes: dict[str, list[Reply]] = {
            "/robots.txt": [ok("User-agent: *\nDisallow: /app/\n")]
        }

    def route(self, path: str, *replies: Reply) -> None:
        self.routes[path] = list(replies)

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((path, self.clock.now))
        self.headers.append(request.headers)
        queue = self.routes.get(path)
        reply: Reply = ok()
        if queue:
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return reply(request)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def server(clock: FakeClock) -> Server:
    return Server(clock)


def make_scraper(tmp_path: Path, server: Server, clock: FakeClock, **overrides: Any) -> BaseScraper:
    kwargs: dict[str, Any] = {
        "source": "portal",
        "host": HOST,
        "snapshot_date": date(2026, 10, 6),
        "max_requests": 50,
        "sanitize": lambda html: html,
        "root": tmp_path,
        "transport": httpx.MockTransport(server),
        "clock": clock,
        "sleep": clock.sleep,
        "utcnow": lambda: NOW,
        "rng": MaxJitter(),
    }
    kwargs.update(overrides)
    return BaseScraper(**kwargs)


def timeout(request: httpx.Request | None = None) -> Exception:
    return httpx.ReadTimeout("sin respuesta")


# ---------------------------------------------------------------------------- configuración


def test_max_requests_is_required(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="max_requests"):
        BaseScraper(  # type: ignore[call-arg]
            source="portal", host=HOST, snapshot_date=date(2026, 10, 6), sanitize=str, root=tmp_path
        )


@pytest.mark.parametrize(
    "overrides",
    [{"max_requests": 0}, {"min_delay_s": MIN_DELAY_S - 0.1}, {"jitter_max_s": 0.5}],
)
def test_values_below_the_minimums_are_rejected(
    tmp_path: Path, server: Server, clock: FakeClock, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        make_scraper(tmp_path, server, clock, **overrides)


def test_stricter_values_are_accepted(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock, min_delay_s=10, jitter_max_s=3) as scraper:
        assert scraper.requests_remaining == 50


def test_user_agent_is_identifiable(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
    assert {headers["user-agent"] for headers in server.headers} == {USER_AGENT}
    assert "AVM-GranAsuncion-Academic" in USER_AGENT


def test_other_host_is_rejected(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock) as scraper, pytest.raises(ValueError, match="host"):
        scraper.fetch("https://otro.test/a")
    assert server.calls == []


def test_only_https_urls_are_requested(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock) as scraper, pytest.raises(ValueError, match="https"):
        scraper.fetch(f"http://{HOST}/a")
    assert server.calls == []


# ---------------------------------------------------------------------------- presupuesto


def test_budget_is_never_exceeded(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock, max_requests=3) as scraper:
        scraper.fetch(f"{BASE}/a")  # robots.txt (1) + página (2)
        scraper.fetch(f"{BASE}/b")  # (3)
        with pytest.raises(BudgetExhaustedError):
            scraper.fetch(f"{BASE}/c")
        assert scraper.requests_used == 3 and scraper.requests_remaining == 0
    assert len(server.calls) == 3


def test_retries_consume_the_budget(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    server.route("/a", status(503))
    scraper = make_scraper(tmp_path, server, clock, max_requests=3)
    with scraper, pytest.raises(BudgetExhaustedError):
        scraper.fetch(f"{BASE}/a")  # robots.txt (1), intento (2), reintento (3), no hay más
    assert len(server.calls) == 3


# ---------------------------------------------------------------------------- demora


def test_waits_between_requests_with_the_fake_clock(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        for name in ("a", "b", "c"):
            scraper.fetch(f"{BASE}/{name}")
    times = [at for _, at in server.calls]
    assert server.paths() == ["/robots.txt", "/a", "/b", "/c"]
    gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
    assert all(gap >= MIN_DELAY_S for gap in gaps)
    assert gaps == [MIN_DELAY_S + 1.0] * 3  # demora más el jitter máximo
    assert len(clock.sleeps) == 3  # la primera request no espera


def test_no_extra_wait_when_the_delay_already_passed(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
        slept = len(clock.sleeps)
        clock.now += 60  # el llamador tardó (por ejemplo, parseando) más que la demora mínima
        scraper.fetch(f"{BASE}/b")
    assert len(clock.sleeps) == slept  # ya pasó la demora: no se duerme de más


def test_jitter_is_between_zero_and_its_maximum(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock, rng=random.Random(7)) as scraper:
        for name in ("a", "b", "c", "d"):
            scraper.fetch(f"{BASE}/{name}")
    assert all(MIN_DELAY_S <= sleep <= MIN_DELAY_S + 1.0 for sleep in clock.sleeps)


def test_crawl_delay_above_the_minimum_wins(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/robots.txt", ok("User-agent: *\nCrawl-delay: 20\n"))
    with make_scraper(tmp_path, server, clock, rng=random.Random(1)) as scraper:
        scraper.fetch(f"{BASE}/a")
        scraper.fetch(f"{BASE}/b")
    times = [at for _, at in server.calls]
    assert times[2] - times[1] >= 20


# ---------------------------------------------------------------------------- bloqueos

CHALLENGE = "<html><title>Just a moment...</title></html>"
SMALL_CAPTCHA = "<div>please solve the captcha</div>"


@pytest.mark.parametrize(
    "reply",
    [
        status(403, "prohibido"),
        status(429),
        ok(CHALLENGE),
        ok(SMALL_CAPTCHA),
        status(503, CHALLENGE),
    ],
)
def test_a_block_stops_the_whole_run(
    tmp_path: Path, server: Server, clock: FakeClock, reply: Reply
) -> None:
    server.route("/a", reply)
    with make_scraper(tmp_path, server, clock) as scraper:
        with pytest.raises(BlockedError):
            scraper.fetch(f"{BASE}/a")
        calls = len(server.calls)
        with pytest.raises(BlockedError):
            scraper.fetch(f"{BASE}/b")
        with pytest.raises(BlockedError):  # tampoco una URL que podría estar en la caché
            scraper.fetch(f"{BASE}/a")
        assert len(server.calls) == calls  # ni una request más, ni un reintento
    manifest = json.loads((tmp_path / "2026-10-06" / "portal" / "manifest.json").read_text("utf-8"))
    assert manifest["blocked"] is True and "/a" in manifest["blocked_reason"]
    assert manifest["counts"]["bloqueado"] == 1


def test_a_block_on_robots_txt_stops_the_run(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/robots.txt", status(403))
    with make_scraper(tmp_path, server, clock) as scraper, pytest.raises(BlockedError):
        scraper.fetch(f"{BASE}/a")
    assert server.paths() == ["/robots.txt"]


def test_recaptcha_in_a_large_page_is_not_a_block(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    big = "<html>" + "x" * 40_000 + "<div class='g-recaptcha'>captcha</div></html>"
    server.route("/a", ok(big))
    with make_scraper(tmp_path, server, clock) as scraper:
        assert scraper.fetch(f"{BASE}/a").outcome == "ok"


def test_looks_blocked_rules() -> None:
    assert looks_blocked(403, b"") == "HTTP 403"
    assert looks_blocked(200, b"<p>ok</p>") is None
    assert looks_blocked(200, b"<title>Just a moment...</title>") is not None
    assert looks_blocked(200, b"access denied") is not None
    # robots.txt: las palabras genéricas no cuentan, los marcadores de challenge sí.
    assert looks_blocked(200, b"access denied", generic_markers=False) is None
    assert looks_blocked(200, b"cf-chl", generic_markers=False) is not None


# ---------------------------------------------------------------------------- robots


def test_a_url_forbidden_by_robots_is_not_requested(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        result = scraper.fetch(f"{BASE}/app/panel")
        assert (result.outcome, result.status, result.html) == ("robots", None, None)
        assert scraper.fetch(f"{BASE}/a").outcome == "ok"
    assert server.paths() == ["/robots.txt", "/a"]  # robots.txt una sola vez por corrida


def test_missing_robots_txt_allows_everything(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/robots.txt", status(404))
    with make_scraper(tmp_path, server, clock) as scraper:
        assert scraper.fetch(f"{BASE}/app/panel").outcome == "ok"


@pytest.mark.parametrize(
    "replies",
    [
        [status(503)],
        [status(301, headers={"location": f"{BASE}/otro"})],
        [timeout()],
        [status(401)],
    ],
    ids=["5xx", "redirect", "timeout", "401"],
)
def test_unreadable_robots_txt_stops_before_any_page(
    tmp_path: Path, server: Server, clock: FakeClock, replies: list[Reply]
) -> None:
    server.route("/robots.txt", *replies)
    scraper = make_scraper(tmp_path, server, clock)
    with scraper, pytest.raises(RobotsUnavailableError):
        scraper.fetch(f"{BASE}/a")
    assert "/a" not in server.paths()


def test_unreadable_robots_txt_is_requested_only_once_per_run(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/robots.txt", status(503))
    scraper = make_scraper(tmp_path, server, clock)
    with pytest.raises(RobotsUnavailableError):
        scraper.fetch(f"{BASE}/a")
    used, robots_requests = scraper.requests_used, server.paths().count("/robots.txt")
    assert robots_requests == 1 + MAX_RETRIES  # un intento y sus reintentos
    with pytest.raises(RobotsUnavailableError):  # la segunda falla sin pedir nada más
        scraper.fetch(f"{BASE}/b")
    assert scraper.requests_used == used
    assert server.paths().count("/robots.txt") == robots_requests
    assert "/a" not in server.paths() and "/b" not in server.paths()
    scraper.close()


# ---------------------------------------------------------------------------- caché


def test_a_cache_hit_generates_no_request(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        first = scraper.fetch(f"{BASE}/a")
        again = scraper.fetch(f"{BASE}/a")
    assert (first.outcome, again.outcome) == ("ok", "cache")
    assert again.html == first.html and again.status is None
    assert server.paths() == ["/robots.txt", "/a"]


def test_the_cache_is_shared_by_the_snapshot_across_runs(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
    before = len(server.calls)
    with make_scraper(tmp_path, server, clock) as scraper:
        assert scraper.fetch(f"{BASE}/a").outcome == "cache"
        assert scraper.requests_used == 0
    assert len(server.calls) == before  # ni siquiera robots.txt


def test_cache_path_is_the_sha256_of_the_url(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
        path = scraper.cache_path(f"{BASE}/a")
    assert path.parent == tmp_path / "2026-10-06" / "portal"
    assert len(path.stem) == 64 and path.suffix == ".html" and path.is_file()
    assert not list(path.parent.glob("*.tmp"))


def test_the_declared_charset_is_respected(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    body = "Asunción".encode("latin-1")
    server.route(
        "/a",
        lambda request: httpx.Response(
            200, content=body, headers={"content-type": "text/html; charset=latin-1"}
        ),
    )
    with make_scraper(tmp_path, server, clock) as scraper:
        assert scraper.fetch(f"{BASE}/a").html == "Asunción"


# ---------------------------------------------------------------------------- reintentos


@pytest.mark.parametrize(
    ("replies", "attempts", "outcome"),
    [
        ([timeout(), ok()], 2, "ok"),
        ([status(500), status(502), ok()], 3, "ok"),
        ([status(503)], 1 + MAX_RETRIES, "error"),
        ([timeout()], 1 + MAX_RETRIES, "error"),
        ([status(404)], 1, "error"),
        ([status(410)], 1, "error"),
        ([status(301, headers={"location": f"{BASE}/otro"})], 1, "error"),
        ([httpx.ConnectError("sin red")], 1, "error"),
    ],
    ids=["timeout", "5xx-5xx", "5xx-siempre", "timeout-siempre", "404", "410", "3xx", "red"],
)
def test_only_timeouts_and_5xx_are_retried_at_most_twice(
    tmp_path: Path,
    server: Server,
    clock: FakeClock,
    replies: list[Reply],
    attempts: int,
    outcome: str,
) -> None:
    server.route("/a", *replies)
    with make_scraper(tmp_path, server, clock) as scraper:
        result = scraper.fetch(f"{BASE}/a")
    assert result.outcome == outcome
    assert server.paths().count("/a") == attempts
    assert attempts <= 1 + MAX_RETRIES


def test_failures_are_not_cached_and_do_not_stop_the_run(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/a", status(404))
    with make_scraper(tmp_path, server, clock) as scraper:
        failed = scraper.fetch(f"{BASE}/a")
        assert (failed.outcome, failed.status, failed.html) == ("error", 404, None)
        assert scraper.fetch(f"{BASE}/b").outcome == "ok"
        assert not scraper.cache_path(f"{BASE}/a").exists()


def test_retry_backoff_never_goes_below_the_minimum_delay(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/a", status(503))
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
    times = [at for path, at in server.calls if path == "/a"]
    assert times[1] - times[0] >= MIN_DELAY_S
    assert times[2] - times[1] >= 2 * MIN_DELAY_S  # el backoff crece


# ---------------------------------------------------------------------------- disco

ADVERTISER_PAGE = (
    "<html><head>"
    '<script type="application/ld+json">{"name": "Casa"}</script></head><body>'
    "<h1>Casa en venta</h1>"
    '<div class="anunciante"><h5>Juana Perez</h5>'
    '<a href="https://portal.test/empresa/inmo-ejemplo-9">Inmo Ejemplo</a>'
    '<img src="//cdn.test/corporate/2021/logo.jpg" alt="Juana Perez"></div>'
    '<img src="//cdn.test/users/2026/avatar.jpg" alt="Pedro Gomez">'
    "<p>Llamar al 0981 123 456 o a vendedor@ejemplo.com.py, https://wa.me/595981123456</p>"
    "</body></html>"
)


def advertiser_sanitizer(html: str) -> str:
    return sanitize_html(
        html,
        drop_selectors=("div.anunciante", 'a[href*="/empresa/"]'),
        drop_img_src=("/corporate/", "/users/"),
    )


def test_nothing_with_personal_data_or_advertiser_names_reaches_the_disk(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/a", ok(ADVERTISER_PAGE))
    with make_scraper(tmp_path, server, clock, sanitize=advertiser_sanitizer) as scraper:
        result = scraper.fetch(f"{BASE}/a")
    assert result.outcome == "ok" and result.html is not None
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) == 3  # página sanitizada, requests.jsonl y manifest.json
    for path in files:
        content = path.read_text(encoding="utf-8")
        for leftover in ("Juana", "Perez", "Pedro", "Gomez", "Inmo Ejemplo", "inmo-ejemplo"):
            assert leftover not in content, f"{leftover!r} en {path.name}"
        for leftover in ("/empresa/", "/corporate/", "/users/", "0981", "vendedor@", "wa.me"):
            assert leftover not in content, f"{leftover!r} en {path.name}"
        assert not find_pii(content)
    assert "Casa en venta" in result.html and "[TELEFONO]" in result.html


def test_robots_txt_is_not_written_to_disk(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
    names = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert "robots.txt" not in names and len(names) == 3


def test_a_page_that_cannot_be_sanitized_is_not_written(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    def refuses(html: str) -> str:
        raise SanitizationError("quedó un rastro")

    with make_scraper(tmp_path, server, clock, sanitize=refuses) as scraper:
        result = scraper.fetch(f"{BASE}/a")
        assert (result.outcome, result.status, result.html) == ("error", 200, None)
        assert not scraper.cache_path(f"{BASE}/a").exists()
    assert not list(tmp_path.rglob("*.html"))


# ---------------------------------------------------------------------------- log y manifest


def test_log_and_manifest_are_well_formed(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    server.route("/b", status(404))
    with make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
        scraper.fetch(f"{BASE}/a")
        scraper.fetch(f"{BASE}/b")
        scraper.fetch(f"{BASE}/app/x")
    directory = tmp_path / "2026-10-06" / "portal"
    lines = [
        json.loads(line) for line in (directory / "requests.jsonl").read_text("utf-8").splitlines()
    ]
    assert [(entry["url"].removeprefix(BASE), entry["result"]) for entry in lines] == [
        ("/robots.txt", "ok"),
        ("/a", "ok"),
        ("/a", "cache"),
        ("/b", "error"),
        ("/app/x", "robots"),
    ]
    for entry in lines:
        assert set(entry) == {"url", "status", "ts", "bytes", "result"}
        assert entry["ts"].endswith("+00:00")
    assert lines[1]["status"] == 200 and lines[1]["bytes"] == len(PAGE.encode())
    assert lines[2]["status"] is None and lines[4]["bytes"] == 0

    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    assert manifest["source"] == "portal" and manifest["host"] == HOST
    assert manifest["snapshot_date"] == "2026-10-06"
    assert manifest["started_at"] == NOW.isoformat() and manifest["finished_at"] == NOW.isoformat()
    assert manifest["max_requests"] == 50 and manifest["requests_used"] == 3
    assert manifest["counts"] == {"ok": 2, "cache": 1, "robots": 1, "bloqueado": 0, "error": 1}
    assert manifest["blocked"] is False and manifest["blocked_reason"] is None
    assert manifest["contract_version"] == CONTRACT_VERSION
    assert manifest["user_agent"] == USER_AGENT and manifest["min_delay_s"] == MIN_DELAY_S


def test_the_default_clock_is_utc_aware(tmp_path: Path, server: Server, clock: FakeClock) -> None:
    scraper = BaseScraper(
        source="portal",
        host=HOST,
        snapshot_date=date(2026, 10, 6),
        max_requests=5,
        sanitize=str,
        root=tmp_path,
        transport=httpx.MockTransport(server),
        clock=clock,
        sleep=clock.sleep,
    )
    with scraper:
        scraper.fetch(f"{BASE}/a")
    manifest = json.loads((tmp_path / "2026-10-06" / "portal" / "manifest.json").read_text("utf-8"))
    for key in ("started_at", "finished_at"):
        assert datetime.fromisoformat(manifest[key]).utcoffset() == NOW.utcoffset()


def test_the_manifest_is_written_even_if_the_block_raises(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    server.route("/a", status(429))
    with pytest.raises(BlockedError), make_scraper(tmp_path, server, clock) as scraper:
        scraper.fetch(f"{BASE}/a")
    assert (tmp_path / "2026-10-06" / "portal" / "manifest.json").is_file()


def test_a_closed_scraper_rejects_requests_and_close_is_idempotent(
    tmp_path: Path, server: Server, clock: FakeClock
) -> None:
    scraper = make_scraper(tmp_path, server, clock)
    scraper.close()
    scraper.close()
    with pytest.raises(ScraperError, match="cerró"):
        scraper.fetch(f"{BASE}/a")
    assert server.calls == []
