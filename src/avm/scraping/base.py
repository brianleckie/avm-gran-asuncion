"""BaseScraper (F3.2): cliente HTTP cortés, con caché sanitizada, registro y manifest.

Reglas (CLAUDE.md, docs/sources.md y las decisiones D1 y D3 de F3.2):
- Una request a la vez, con una demora de al menos `MIN_DELAY_S` (6 s) más un jitter de 0 a
  `JITTER_MAX_S` (1 s) desde que terminó la anterior. Los parámetros solo se pueden configurar hacia
  más conservador: valores más bajos que esos mínimos dan `ValueError`. Si robots.txt declara un
  `Crawl-delay` mayor, rige el mayor.
- Presupuesto duro de requests por corrida (`max_requests`, obligatorio y sin default). Cada
  intento cuenta, también el de robots.txt y los reintentos. Nunca se excede: al agotarse,
  `BudgetExhaustedError` antes de enviar.
- robots.txt (`urllib.robotparser`) se pide una vez por corrida, con este mismo cliente, y se
  consulta antes de cada URL: una URL prohibida no se pide. Si no se puede leer (sin respuesta,
  401, redirección o 5xx), `RobotsUnavailableError` y no se vuelve a pedir en esa corrida.
  LIMITACIÓN: `urllib.robotparser` no entiende los comodines `*` ni `$`; Clasipar no los usa
  (docs/sources.md §2.1), pero una fuente que sí los use los evaluaría mal y habría que reemplazar
  el matcher.
- 403, 429 o un challenge (marcadores de `config.py`) detienen la corrida entera: `BlockedError`,
  sin reintentos, y toda llamada posterior lanza sin enviar nada.
- Solo se reintentan timeouts y respuestas 5xx, como máximo `MAX_RETRIES` (2) veces, con una
  espera que nunca baja de la demora mínima. Los demás errores (404, otros 4xx, 3xx, errores de
  red) son un `FetchResult` con `outcome="error"` y no se reintentan. No se siguen redirecciones.
- Solo se escribe a disco HTML YA SANITIZADO (D1): `data/raw/<YYYY-MM-DD>/<fuente>/<sha256 de la
  URL>.html`. Si la sanitización falla (`SanitizationError`) no se escribe nada. Con la URL en
  caché no hay request. El log `requests.jsonl` (url, status, timestamp UTC, bytes, resultado y
  `duration_s`) y el `manifest.json` no llevan cuerpos ni headers. `duration_s` es lo que tardó el
  intercambio HTTP (sin la demora entre requests) y es `null` si no se envió nada (caché o robots).

La demora se lleva por instancia: una corrida usa UN scraper por fuente y snapshot (dos instancias
seguidas enviarían su primera request, la de robots.txt, sin esperar). La caché se lee tal como se
escribió, sin volver a sanitizar: si cambia el sanitizador, las páginas ya cacheadas del mismo
snapshot conservan la versión vieja. Solo se piden URLs https del host de la fuente.

El transporte HTTP, el reloj, el sleep, la hora UTC y el generador de jitter son inyectables para
testear sin red y sin esperar.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, NoReturn, Self
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from avm.contract import CONTRACT_VERSION
from avm.scraping.config import (
    BLOCK_STATUSES,
    BODY_SCAN_CHARS,
    CHALLENGE_MARKERS,
    JITTER_MAX_S,
    MAX_RETRIES,
    MIN_DELAY_S,
    PRODUCT_TOKEN,
    SMALL_PAGE_BYTES,
    SMALL_PAGE_MARKERS,
    TIMEOUT_S,
    USER_AGENT,
)
from avm.scraping.sanitize import SanitizationError

Outcome = Literal["ok", "cache", "robots", "bloqueado", "error"]
OUTCOMES: Final[tuple[Outcome, ...]] = ("ok", "cache", "robots", "bloqueado", "error")

DEFAULT_ROOT: Final = Path("data/raw")
LOG_NAME: Final = "requests.jsonl"
MANIFEST_NAME: Final = "manifest.json"


class ScraperError(RuntimeError):
    """Base de los errores del scraper."""


class BlockedError(ScraperError):
    """La fuente bloqueó (403, 429 o challenge): la corrida se detiene entera."""


class BudgetExhaustedError(ScraperError):
    """Se agotó el presupuesto de requests de la corrida: no se envía ninguna más."""


class RobotsUnavailableError(ScraperError):
    """No se pudo leer robots.txt: sin sus reglas no se pide nada."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Resultado de `fetch`. `html` es el HTML sanitizado (el mismo que está en la caché)."""

    url: str
    outcome: Outcome
    status: int | None = None
    html: str | None = None


@dataclass(frozen=True, slots=True)
class _Reply:
    status: int | None  # None: timeout o error de red, sin respuesta
    body: bytes
    encoding: str = "utf-8"
    duration_s: float | None = None  # lo que tardó el intercambio HTTP, sin la demora previa

    @property
    def text(self) -> str:
        return self.body.decode(self.encoding, errors="replace")


def looks_blocked(status: int, body: bytes, *, generic_markers: bool = True) -> str | None:
    """Motivo del bloqueo si la respuesta parece un bloqueo o un challenge; None si no.

    Los marcadores genéricos ("captcha", "access denied"...) solo cuentan en páginas chicas: un
    aviso normal trae un reCAPTCHA en el formulario de contacto (docs/sources.md §2.7). Con
    `generic_markers=False` solo valen los de challenge (robots.txt no es HTML y puede nombrar
    cualquier palabra en su lista de bots).
    """
    if status in BLOCK_STATUSES:
        return f"HTTP {status}"
    head = body[:BODY_SCAN_CHARS].decode("utf-8", errors="replace").lower()
    markers: tuple[str, ...] = CHALLENGE_MARKERS
    if generic_markers and len(body) < SMALL_PAGE_BYTES:
        markers += SMALL_PAGE_MARKERS
    for marker in markers:
        if marker in head:
            return f"marcador '{marker}' en el cuerpo"
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BaseScraper:
    """Cliente cortés de UNA fuente. Usar como context manager para cerrar con manifest."""

    def __init__(
        self,
        *,
        source: str,
        host: str,
        snapshot_date: date,
        max_requests: int,
        sanitize: Callable[[str], str],
        root: Path = DEFAULT_ROOT,
        transport: httpx.BaseTransport | None = None,
        min_delay_s: float = MIN_DELAY_S,
        jitter_max_s: float = JITTER_MAX_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        utcnow: Callable[[], datetime] = _utc_now,
        rng: random.Random | None = None,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests tiene que ser al menos 1")
        if min_delay_s < MIN_DELAY_S:
            raise ValueError(f"la demora mínima no puede bajar de {MIN_DELAY_S} s")
        if jitter_max_s < JITTER_MAX_S:
            raise ValueError(f"el jitter máximo no puede bajar de {JITTER_MAX_S} s")
        self.source = source
        self.host = host
        self.snapshot_date = snapshot_date
        self.max_requests = max_requests
        self.directory = root / snapshot_date.isoformat() / source
        self._sanitize = sanitize
        self._min_delay = min_delay_s
        self._jitter_max = jitter_max_s
        self._clock = clock
        self._sleep = sleep
        self._utcnow = utcnow
        self._rng = rng if rng is not None else random.Random()
        self._client = httpx.Client(
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
            follow_redirects=False,
        )
        self._started_at = utcnow()
        self._used = 0
        self._counts: Counter[str] = Counter()
        self._latencies: list[float] = []
        self._last_done: float | None = None
        self._robots: RobotFileParser | None = None
        self._robots_error: RobotsUnavailableError | None = None
        self._blocked_reason: str | None = None
        self._closed = False

    # ------------------------------------------------------------------ API pública

    @property
    def requests_used(self) -> int:
        return self._used

    @property
    def requests_remaining(self) -> int:
        return self.max_requests - self._used

    @property
    def counts(self) -> dict[str, int]:
        """Resultados registrados hasta ahora (una copia, con todas las claves de `OUTCOMES`)."""
        return {outcome: self._counts[outcome] for outcome in OUTCOMES}

    @property
    def latencies_s(self) -> tuple[float, ...]:
        """Duración en segundos de cada request enviada (robots.txt y reintentos incluidos)."""
        return tuple(self._latencies)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def cache_path(self, url: str) -> Path:
        return self.directory / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.html"

    def fetch(self, url: str) -> FetchResult:
        """Pide `url` (o la devuelve de la caché). Orden: caché, robots, presupuesto y demora."""
        if self._closed:
            raise ScraperError("el scraper ya se cerró")
        if self._blocked_reason is not None:
            raise BlockedError(f"{self.host} bloqueado: {self._blocked_reason}")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != self.host:
            raise ValueError(f"{url} no es una URL https del host {self.host}")
        cached = self._read_cache(url)
        if cached is not None:
            self._log(url, None, len(cached.encode("utf-8")), "cache")
            return FetchResult(url, "cache", None, cached)
        if not self._allowed_by_robots(url):
            self._log(url, None, 0, "robots")
            return FetchResult(url, "robots")
        return self._settle(url, self._send(url))

    def close(self) -> None:
        """Escribe el manifest y cierra el cliente. Se puede llamar más de una vez."""
        if self._closed:
            return
        self._closed = True
        self._client.close()
        manifest = {
            "source": self.source,
            "host": self.host,
            "snapshot_date": self.snapshot_date.isoformat(),
            "started_at": self._started_at.isoformat(),
            "finished_at": self._utcnow().isoformat(),
            "max_requests": self.max_requests,
            "requests_used": self._used,
            "counts": self.counts,
            "blocked": self._blocked_reason is not None,
            "blocked_reason": self._blocked_reason,
            "min_delay_s": self._min_delay,
            "jitter_max_s": self._jitter_max,
            "user_agent": USER_AGENT,
            "contract_version": CONTRACT_VERSION,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    # ------------------------------------------------------------------ envío

    def _spend(self) -> None:
        if self._used >= self.max_requests:
            raise BudgetExhaustedError(f"presupuesto de {self.max_requests} requests agotado")
        self._used += 1

    def _wait(self, floor: float = 0.0) -> None:
        """Espera hasta `demora + jitter` (o `floor`, si es mayor) desde que terminó la última."""
        if self._last_done is None:
            return
        delay = max(self._min_delay + self._rng.uniform(0, self._jitter_max), floor)
        remaining = self._last_done + delay - self._clock()
        if remaining > 0:
            self._sleep(remaining)

    def _send(self, url: str, *, generic_markers: bool = True) -> _Reply:
        """Envía con demora, presupuesto, detección de bloqueo y reintentos de timeout y 5xx."""
        retries = 0
        while True:
            self._spend()
            self._wait(floor=self._min_delay * 2 ** (retries - 1) if retries else 0.0)
            started = self._clock()
            try:
                response = self._client.get(url)
            except httpx.TimeoutException:
                reply, retryable = _Reply(None, b""), True
            except httpx.HTTPError:
                reply, retryable = _Reply(None, b""), False
            else:
                reply = _Reply(response.status_code, response.content, response.encoding or "utf-8")
                retryable = response.status_code >= 500
            self._last_done = self._clock()
            reply = replace(reply, duration_s=self._last_done - started)
            self._latencies.append(self._last_done - started)
            if reply.status is not None and (
                reason := looks_blocked(reply.status, reply.body, generic_markers=generic_markers)
            ):
                self._block(url, reply, reason)
            if retryable and retries < MAX_RETRIES:
                self._log(url, reply.status, len(reply.body), "error", reply.duration_s)
                retries += 1
                continue
            return reply

    def _block(self, url: str, reply: _Reply, reason: str) -> NoReturn:
        self._blocked_reason = f"{reason} en {url}"
        self._log(url, reply.status, len(reply.body), "bloqueado", reply.duration_s)
        raise BlockedError(f"{self.host} bloqueado: {self._blocked_reason}")

    def _settle(self, url: str, reply: _Reply) -> FetchResult:
        status = reply.status
        if status is None or not 200 <= status < 300:
            self._log(url, status, len(reply.body), "error", reply.duration_s)
            return FetchResult(url, "error", status)
        try:
            html = self._sanitize(reply.text)
        except SanitizationError:  # falla cerrado: lo que no se puede sanitizar no se escribe
            self._log(url, status, len(reply.body), "error", reply.duration_s)
            return FetchResult(url, "error", status)
        self._write_cache(url, html)
        self._log(url, status, len(reply.body), "ok", reply.duration_s)
        return FetchResult(url, "ok", status, html)

    # ------------------------------------------------------------------ robots

    def _allowed_by_robots(self, url: str) -> bool:
        if self._robots_error is not None:  # se pide una vez por corrida, también si falló
            raise self._robots_error
        if self._robots is None:
            try:
                self._robots = self._load_robots()
            except RobotsUnavailableError as error:
                self._robots_error = error
                raise
        return self._robots.can_fetch(PRODUCT_TOKEN, url)

    def _load_robots(self) -> RobotFileParser:
        url = f"https://{self.host}/robots.txt"
        reply = self._send(url, generic_markers=False)
        status = reply.status
        # Sin respuesta, 401 (como urllib.robotparser: todo prohibido), redirección o 5xx.
        if status is None or status in (401, *range(300, 400)) or status >= 500:
            self._log(url, status, len(reply.body), "error", reply.duration_s)
            raise RobotsUnavailableError(f"no se pudo leer {url} (status {status})")
        parser = RobotFileParser()
        # 2xx: se parsea. 4xx (sin robots.txt): sin reglas, todo permitido.
        parser.parse(reply.text.splitlines() if status < 300 else [])
        self._log(url, status, len(reply.body), "ok", reply.duration_s)
        crawl_delay = parser.crawl_delay(PRODUCT_TOKEN)
        if crawl_delay is not None:
            self._min_delay = max(self._min_delay, float(crawl_delay))
        return parser

    # ------------------------------------------------------------------ caché y log

    def _read_cache(self, url: str) -> str | None:
        path = self.cache_path(url)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def _write_cache(self, url: str, html: str) -> None:
        path = self.cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".tmp")
        partial.write_text(html, encoding="utf-8", newline="\n")
        partial.replace(path)

    def _log(
        self,
        url: str,
        status: int | None,
        size: int,
        result: Outcome,
        duration_s: float | None = None,
    ) -> None:
        self._counts[result] += 1
        entry = {
            "url": url,
            "status": status,
            "ts": self._utcnow().isoformat(),
            "bytes": size,
            "result": result,
            "duration_s": None if duration_s is None else round(duration_s, 3),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / LOG_NAME).open("a", encoding="utf-8", newline="\n") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
