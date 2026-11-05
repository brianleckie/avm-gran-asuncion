"""Rate limit simple en memoria, por IP (ventana deslizante). Un solo proceso."""

import ipaddress
import time
from collections import deque
from collections.abc import Callable

from avm.api.config import RATE_LIMIT_WINDOW_SECONDS

UNKNOWN_CLIENT = "desconocida"


def client_ip(forwarded_for: str | None, peer: str | None, trust_proxy: bool) -> str:
    """IP contra la que se aplica el rate limit.

    Con `trust_proxy` se toma el ÚLTIMO valor de X-Forwarded-For: es el que agrega el proxy de
    confianza. Si el proxy reemplaza el header, primero y último coinciden; si lo agrega, el
    primero lo controla el cliente. Si el valor no es una IP válida o falta el header, se usa la IP
    de la conexión. Sin `trust_proxy` el header se ignora.
    """
    if trust_proxy and forwarded_for:
        candidate = forwarded_for.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return peer or UNKNOWN_CLIENT


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window: float = RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """None si el pedido pasa; si no, segundos hasta que se libere un cupo."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return max(self._window - (now - hits[0]), 0.0)
        hits.append(now)
        self._prune(now)
        return None

    def _prune(self, now: float) -> None:
        """Evita que el diccionario crezca sin límite con IPs que ya no vuelven."""
        if len(self._hits) < 1024:
            return
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] >= self._window]
        for key in stale:
            del self._hits[key]
