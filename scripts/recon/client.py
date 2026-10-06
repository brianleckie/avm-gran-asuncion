"""Cliente de reconocimiento (F3.1): una request a la vez, identificada, con tope y registro.

Reglas (más estrictas que las de CLAUDE.md porque corre desde una IP residencial):
- User-agent identificable y fijo. Nada de headers de navegador ni rotación de UA.
- `MIN_DELAY_S` entre requests (a cualquier fuente), sin concurrencia y SIN reintentos.
- Tope de `MAX_REQUESTS_PER_SOURCE` por fuente, contando también las requests fallidas. El tope se
  lleva en un ledger JSON en disco, así que vale entre corridas.
- Antes de pedir, la URL se valida contra el robots.txt de la fuente (ver `robots.py`).
- Ante 403, 429, 503 o una página de challenge/captcha la fuente queda bloqueada en el ledger y no
  se le hacen más requests.
- No sigue redirects: se registran y quien llama decide (y gasta otra request).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from recon.robots import is_allowed, rules_for

USER_AGENT = "AVM-GranAsuncion-Academic/0.1 (proyecto universitario; contacto: https://github.com/brianleckie)"
PRODUCT_TOKEN = USER_AGENT.split("/", 1)[0]
MIN_DELAY_S = 6.0
MAX_REQUESTS_PER_SOURCE = 25
TIMEOUT_S = 20.0

SOURCES = {
    "infocasas": "www.infocasas.com.py",
    "clasipar": "clasipar.paraguay.com",
}

BLOCK_STATUSES = frozenset({403, 429, 503})
# Marcadores de páginas de challenge; se buscan en minúsculas en el cuerpo.
CHALLENGE_MARKERS = ("cf-chl", "challenge-platform", "just a moment...")
# Marcadores genéricos: solo cuentan en páginas chicas, porque un aviso normal puede traer un
# reCAPTCHA en el formulario de contacto. Una página de challenge suele pesar pocos KB.
SMALL_PAGE_MARKERS = ("captcha", "attention required", "access denied")
SMALL_PAGE_BYTES = 30_000


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


Sender = Callable[[str], Response]


class ReconError(RuntimeError):
    """La request no se hizo (o no debe repetirse) por una regla del reconocimiento."""


class SourceBlockedError(ReconError):
    pass


def looks_blocked(response: Response) -> str | None:
    """Motivo del bloqueo si la respuesta parece un bloqueo o un challenge; None si no."""
    if response.status in BLOCK_STATUSES:
        return f"HTTP {response.status}"
    head = response.body[:20_000].decode("utf-8", errors="replace").lower()
    markers = CHALLENGE_MARKERS
    if len(response.body) < SMALL_PAGE_BYTES:
        markers += SMALL_PAGE_MARKERS
    for marker in markers:
        if marker in head:
            return f"marcador '{marker}' en el cuerpo"
    return None


def httpx_sender() -> Sender:
    """Sender real. httpx se importa acá para que los tests no dependan del grupo `scraping`."""
    import httpx

    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=TIMEOUT_S,
    )

    def send(url: str) -> Response:
        r = client.get(url)
        return Response(status=r.status_code, headers=dict(r.headers), body=r.content)

    return send


class Ledger:
    """Registro persistente de requests por fuente (incluye las fallidas) y fuentes bloqueadas."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"requests": [], "blocked": {}}

    def count(self, source: str) -> int:
        return sum(1 for entry in self.data["requests"] if entry["source"] == source)

    def last_time(self) -> float | None:
        times = [entry["ts"] for entry in self.data["requests"]]
        return max(times) if times else None

    def blocked_reason(self, source: str) -> str | None:
        return self.data["blocked"].get(source)

    def record(self, source: str, url: str, status: int | None, ts: float, note: str = "") -> None:
        self.data["requests"].append(
            {"source": source, "url": url, "status": status, "ts": ts, "note": note}
        )
        self.save()

    def block(self, source: str, reason: str) -> None:
        self.data["blocked"][source] = reason
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")


class ReconClient:
    def __init__(
        self,
        source: str,
        ledger: Ledger,
        robots_txt: str,
        send: Sender | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if source not in SOURCES:
            raise ValueError(f"fuente desconocida: {source}")
        self.source = source
        self.ledger = ledger
        self.group, self.rules = rules_for(robots_txt, PRODUCT_TOKEN)
        self._send = send
        self._sleep = sleep
        self._clock = clock

    def check(self, url: str) -> None:
        """Valida una URL sin pedirla. Lanza ReconError si no se debe pedir."""
        if urlsplit(url).hostname != SOURCES[self.source]:
            raise ReconError(f"{url} no es del host de {self.source}")
        if reason := self.ledger.blocked_reason(self.source):
            raise SourceBlockedError(f"{self.source} bloqueada: {reason}")
        if not is_allowed(self.rules, url):
            raise ReconError(f"robots.txt (grupo '{self.group}') prohíbe {url}")
        if self.ledger.count(self.source) >= MAX_REQUESTS_PER_SOURCE:
            raise ReconError(f"tope de {MAX_REQUESTS_PER_SOURCE} requests en {self.source}")

    def get(self, url: str) -> Response:
        self.check(url)
        last = self.ledger.last_time()
        if last is not None:
            wait = last + MIN_DELAY_S - self._clock()
            if wait > 0:
                self._sleep(wait)
        if self._send is None:
            self._send = httpx_sender()
        try:
            response = self._send(url)
        except Exception as exc:  # cuenta igual: la request salió o pudo salir
            self.ledger.record(self.source, url, None, self._clock(), note=f"error: {exc!r}")
            raise
        reason = looks_blocked(response)
        self.ledger.record(self.source, url, response.status, self._clock(), note=reason or "")
        if reason:
            self.ledger.block(self.source, f"{reason} en {url}")
            raise SourceBlockedError(f"{self.source} bloqueada: {reason} en {url}")
        return response
