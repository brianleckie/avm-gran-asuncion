"""Clasipar falso para testear el crawler sin red: robots.txt, listados y detalles sintéticos.

Todo el contenido es inventado (ids, títulos, precios). Los ids se arman a partir del target y de la
página (`(target + 1) * 100_000 + página * 100 + n`), así que de un id se deduce de qué búsqueda
salió: los tests lo usan para verificar el orden de los pedidos.
"""

import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from avm.scraping.base import BaseScraper
from avm.scraping.run import SOURCES
from avm.scraping.sources.clasipar import HOST, search_urls
from tests.scraping.test_base import FakeClock, MaxJitter

BASE = f"https://{HOST}"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
SNAPSHOT = date(2026, 10, 6)
ROBOTS = "User-agent: *\nDisallow: /app/\n"
SPEC = replace(SOURCES["clasipar"], sanitize=lambda html: html)

_LISTING = re.compile(
    r"^/inmuebles/(?P<category>[^/]+)/intencion:vendo-t_s/localidad:(?P<locality>[^/]+?)"
    r"(?:/page-(?P<page>\d+))?$"
)
_DETAIL = re.compile(r"^/inmuebles/(?P<category>[^/]+)/anuncio-(?P<id>\d+)$")
_SEARCHES = [
    (match["category"], match["locality"])
    for target in search_urls()
    if (match := _LISTING.match(target.url.removeprefix(BASE)))
]


def target_of(source_id: int | str) -> int:
    """Índice (0 a 11, el orden de `search_urls()`) de la búsqueda de la que sale un id."""
    return int(source_id) // 100_000 - 1


def _detail_html(source_id: int, *, number: str | None = None) -> str:
    return (
        f'<html><body><h1 class="tit-anuncio">Casa de prueba {source_id}</h1>'
        '<h3 class="user-price">US$. 100.000,00</h3>'
        '<div class="anuncio-detalles">'
        f'<div class="grid__item"><span>Nro. de Anuncio:</span><h6>{number or source_id}</h6></div>'
        '<div class="grid__item"><span>Ciudad:</span><h6>Asunción</h6></div>'
        '<div class="grid__item"><span>Zona:</span><h6>Villa Aurelia</h6></div></div>'
        '<p class="desc-user">Casa de 120 m2 construidos<br>terreno de 360 m2</p>'
        "</body></html>"
    )


class FakeSite:
    """Transporte falso (callable para `httpx.MockTransport`) que registra cada pedido."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock if clock is not None else FakeClock()
        self.latency = 0.0
        self.paths: list[str] = []
        self.robots = ROBOTS
        self.robots_status = 200
        self.per_page = 30
        self.default_last_page = 5
        self.last_page: dict[int, int] = {}  # índice de búsqueda -> última página
        self.paginated = True
        self.sponsored: set[int] = set()
        self.extra_ids: dict[tuple[int, int], list[int]] = {}  # (búsqueda, página) -> más ids
        self.status: dict[str, int] = {}  # path -> status forzado
        self.errors: dict[str, BaseException] = {}  # path -> excepción al pedirlo
        self.detail_status: dict[int, int] = {}  # n-ésimo pedido de detalle -> status forzado
        self.detail_errors: dict[int, BaseException] = {}  # n-ésimo pedido de detalle -> excepción
        self.broken_listings: set[str] = set()  # paths con una tarjeta sin link
        self.details: dict[int, str] = {}  # id -> HTML propio

    # ------------------------------------------------------------------ consultas

    def requested(self, kind: str) -> list[str]:
        """Paths pedidos de un tipo: "listing", "detail" o "robots"."""
        patterns = {"listing": _LISTING, "detail": _DETAIL}
        if kind == "robots":
            return [path for path in self.paths if path == "/robots.txt"]
        return [path for path in self.paths if patterns[kind].match(path)]

    def detail_ids(self) -> list[int]:
        return [int(_DETAIL.match(path)["id"]) for path in self.requested("detail")]  # type: ignore[index]

    def pages_of(self, search: int) -> int:
        return self.last_page.get(search, self.default_last_page)

    def ids(self, search: int, page: int) -> list[int]:
        base = (search + 1) * 100_000 + page * 100
        return [base + n for n in range(self.per_page)] + self.extra_ids.get((search, page), [])

    def detail_path(self, search: int, source_id: int) -> str:
        return f"/inmuebles/{_SEARCHES[search][0]}/anuncio-{source_id}"

    # ------------------------------------------------------------------ transporte

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        self.clock.now += self.latency
        if path in self.errors:
            raise self.errors[path]
        if _DETAIL.match(path):
            number = len(self.requested("detail"))
            if number in self.detail_errors:
                raise self.detail_errors[number]
            if number in self.detail_status:
                return httpx.Response(self.detail_status[number], text="")
        if path == "/robots.txt":
            return httpx.Response(self.robots_status, text=self.robots)
        if path in self.status:
            return httpx.Response(self.status[path], text="")
        if match := _LISTING.match(path):
            return self._listing(match)
        if match := _DETAIL.match(path):
            source_id = int(match["id"])
            return httpx.Response(200, text=self.details.get(source_id, _detail_html(source_id)))
        return httpx.Response(404, text="")

    def _listing(self, match: re.Match[str]) -> httpx.Response:
        search = _SEARCHES.index((match["category"], match["locality"]))
        page = int(match["page"] or 1)
        if match.string in self.broken_listings:  # una tarjeta sin link: cambió el HTML
            return httpx.Response(
                200,
                text='<html><body><article class="box-anuncio">sin link</article></body></html>',
            )
        last = self.pages_of(search)
        cards = "".join(self._card(search, source_id) for source_id in self.ids(search, page))
        pagination = (
            '<ul id="pagination">'
            f'<li class="active"><a data-page="{page}">{page}</a></li>'
            f'<li><a data-page="{last}">{last}</a></li></ul>'
            if self.paginated
            else ""
        )
        total = f"{last * 25:,}".replace(",", ".")
        body = f"<p><small><strong>{total} Resultados</strong></small></p>{cards}{pagination}"
        return httpx.Response(200, text=f"<html><body>{body}</body></html>")

    def _card(self, search: int, source_id: int) -> str:
        premium = " box-anuncio--premium" if source_id in self.sponsored else ""
        return (
            f'<article class="box-anuncio{premium}">'
            f'<a class="titAnuncio" href="{self.detail_path(search, source_id)}">'
            f"Casa {source_id}</a>"
            '<p class="price">US$. 100.000,00</p>'
            "<h6><strong>Vendo</strong> | Ofrecido por: <strong>Particular</strong></h6>"
            "</article>"
        )


def listing_path(search: int, page: int = 1) -> str:
    """Path de la página `page` de la búsqueda número `search`."""
    path = urlsplit(search_urls()[search].url).path
    return path if page == 1 else f"{path}/page-{page}"


def make_scraper(
    tmp_path: Path, site: FakeSite, *, max_requests: int = 400, **overrides: Any
) -> BaseScraper:
    """BaseScraper contra el sitio falso, con reloj falso (no espera) y sin sanitizar."""
    options: dict[str, Any] = {
        "source": "clasipar",
        "host": HOST,
        "snapshot_date": SNAPSHOT,
        "max_requests": max_requests,
        "sanitize": SPEC.sanitize,
        "root": tmp_path / "raw",
        "transport": httpx.MockTransport(site),
        "clock": site.clock,
        "sleep": site.clock.sleep,
        "utcnow": lambda: NOW,
        "rng": MaxJitter(),
    }
    options.update(overrides)
    return BaseScraper(**options)
