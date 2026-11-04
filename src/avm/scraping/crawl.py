"""Crawler de muestreo de listados (F3.3): del listado a un `RawListing` por aviso muestreado.

No recorre todo el portal: toma una muestra reproducible. Por cada búsqueda (`SearchTarget`: tipo x
ciudad) de la fuente:
1. Pide la página 1 y lee `last_page` y `total_results`.
2. Elige `pages_per_target - 1` páginas más al azar y SIN reposición en [2, last_page] (todas si
   hay menos, ver `pick_pages`) y las pide en orden ascendente. El piloto es `pages_per_target=2`.
3. Une las referencias de todas esas páginas (`merge_refs`) y muestrea SIN reposición hasta
   `per_target` con el mismo rng. Si hay menos, toma todas y lo registra (`short`).
Orden de los pedidos: robots.txt, TODOS los listados de todas las búsquedas y recién después los
detalles de todos los targets INTERCALADOS (round-robin), para que un corte por presupuesto o por
bloqueo no deje combinaciones enteras sin muestra. Cada detalle pasa por `parse_detail`; los
`RawListing` válidos se agregan, uno por línea y con flush, a `<out_dir>/raw_listings.jsonl`.

Reglas:
- Todo pedido pasa por `BaseScraper` (cortesía, robots.txt, presupuesto, caché sanitizada y
  bloqueos). Este módulo no abre ninguna conexión.
- Reproducibilidad: cada target usa su propio rng, `Random(f"{seed}|{url del target}")`. Así el
  muestreo de un target no depende de si otro falló. El plan (seed, páginas aleatorias y los
  `source_id` muestreados, con la página de la que salió cada uno) queda en `crawl_manifest.json`.
  Con `pages_per_target=2` el plan es idéntico al del piloto para el mismo seed.
- Un detalle que no valida se cuenta por tipo de error y se sigue. Del error solo se guarda la
  clase y el campo, NUNCA el mensaje ni el valor (traen el contenido del aviso).
- `BlockedError` corta TODO, sin reintentos; `BudgetExhaustedError` y `RobotsUnavailableError`
  también. Lo mismo `NetworkDownError`: `MAX_CONSECUTIVE_NETWORK_ERRORS` pedidos seguidos sin
  respuesta (sin conexión o timeout, ya agotados los reintentos de `BaseScraper`); cualquier
  respuesta HTTP, aunque sea un error, reinicia la cuenta. En los cuatro casos se conserva lo
  obtenido y se escribe el manifest (`stopped`).
- Antes de la primera request se imprime el pre-vuelo: requests máximas planificadas, duración y
  hora de fin estimadas (a `ESTIMATED_SECONDS_PER_REQUEST`) y un aviso si superan el presupuesto,
  que sigue siendo tope duro. Es una cota: el plan exacto sale en `[plan]` al terminar los listados.
- El archivo de salida se abre en modo exclusivo: si ya existe, falla ANTES de enviar un pedido.
"""

from __future__ import annotations

import json
import logging
import random
import re
import statistics
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any, Final

from pydantic import ValidationError

from avm.contract import CONTRACT_VERSION, RawListing
from avm.scraping.base import (
    BaseScraper,
    BlockedError,
    BudgetExhaustedError,
    FetchResult,
    RobotsUnavailableError,
)
from avm.scraping.config import JITTER_MAX_S, MIN_DELAY_S
from avm.scraping.sources.clasipar import ListingPage, ListingRef, SearchTarget

LISTINGS_NAME: Final = "raw_listings.jsonl"
MANIFEST_NAME: Final = "crawl_manifest.json"
PROGRESS_EVERY: Final = 50

# Ritmo para estimar la duración: la espera media entre requests (demora mínima más la mitad del
# jitter) más la latencia media medida en el piloto (docs/pilot/2026-10-06.md §1: 0,90 s).
PILOT_MEAN_LATENCY_S: Final = 0.9
ESTIMATED_SECONDS_PER_REQUEST: Final = MIN_DELAY_S + JITTER_MAX_S / 2 + PILOT_MEAN_LATENCY_S

# Pedidos seguidos sin respuesta (sin conexión o timeout) después de los cuales se corta la corrida.
MAX_CONSECUTIVE_NETWORK_ERRORS: Final = 20

LOG = logging.getLogger(__name__)

# Mensaje del contrato cuando un texto trae un dato personal: nombra el campo y el tipo, no el dato.
_PII_FIELD = re.compile(r"(\w+) contiene datos personales")


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Lo que el crawler necesita saber de una fuente (la lógica propia vive en `sources/`)."""

    name: str
    host: str
    sanitize: Callable[[str], str]
    targets: Callable[[], Sequence[SearchTarget]]
    page_url: Callable[[str, int], str]
    parse_listing_page: Callable[[str], ListingPage]
    merge_refs: Callable[[Iterable[ListingRef]], list[ListingRef]]
    parse_detail: Callable[..., RawListing]


class NetworkDownError(RuntimeError):
    """`MAX_CONSECUTIVE_NETWORK_ERRORS` pedidos seguidos sin respuesta: se corta la corrida."""


@dataclass(slots=True)
class TargetPlan:
    """Qué se pidió y qué se muestreó de una búsqueda."""

    target: SearchTarget
    total_results: int | None = None
    last_page: int | None = None
    random_pages: list[int] = field(default_factory=list)  # aleatorias ya pedidas, sin la 1
    pool_size: int = 0  # referencias únicas disponibles, sin las ya planificadas por otro target
    excluded_duplicates: int = 0
    short: bool = False  # menos referencias que `per_target`
    errors: list[str] = field(default_factory=list)
    sampled: list[ListingRef] = field(default_factory=list)
    origins: dict[str, list[int]] = field(default_factory=dict)  # source_id -> páginas
    attempted: int = 0
    valid: int = 0


@dataclass(frozen=True, slots=True)
class CrawlResult:
    stopped: str | None  # None, "blocked", "budget", "robots_unavailable" o "network"
    reason: str | None
    planned: int
    attempted: int
    valid: int
    rejected: int
    listings_path: Path
    manifest_path: Path


def utc_now() -> datetime:
    return datetime.now(UTC)


def _fetch_key(result: FetchResult) -> str:
    """Motivo (sin contenido) de un pedido que no devolvió una página."""
    if result.outcome == "robots":
        return "robots_prohibido"
    if result.status is None:
        return "sin_respuesta"
    if 200 <= result.status < 300:
        return "sanitizacion_fallida"
    return f"http_{result.status}"


def _validation_keys(error: ValidationError) -> set[str]:
    """Claves `tipo@campo` de un ValidationError. Nunca el input ni el mensaje completo."""
    keys: set[str] = set()
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = item["loc"]
        if location:
            keys.add(f"ValidationError:{item['type']}@{location[0]}")  # solo el campo, no la clave
        elif field_name := _PII_FIELD.search(item["msg"]):
            keys.add(f"ValidationError:datos_personales@{field_name.group(1)}")
        else:
            keys.add(f"ValidationError:{item['type']}@-")
    return keys


def pick_pages(rng: random.Random, last_page: int | None, pages_per_target: int) -> list[int]:
    """Páginas a pedir de una búsqueda: la 1 y hasta `pages_per_target - 1` más, sin reposición.

    Las extra salen al azar de [2, last_page] (todas, si son menos) y van en orden ascendente. Sin
    paginación (`last_page` None o 1) o con `pages_per_target=1` es solo la página 1 y no gasta el
    rng. Con `pages_per_target=2` hace lo mismo que el piloto: una sola extra, con un
    `randrange(n)` que consume el rng igual que el `randint(2, n + 1)` de entonces (también con
    n=1), así el `sample` de los detalles que viene después del mismo rng no cambia.
    """
    if last_page is None or last_page < 2:
        return [1]
    remaining = list(range(2, last_page + 1))
    extra = [
        remaining.pop(rng.randrange(len(remaining)))
        for _ in range(min(pages_per_target - 1, len(remaining)))
    ]
    return [1, *sorted(extra)]


def estimated_seconds_per_request(elapsed_s: float, requests_used: int) -> float:
    """Ritmo medido (segundos por request) o, sin datos todavía, el del piloto."""
    if requests_used > 0 and elapsed_s > 0:
        return elapsed_s / requests_used
    return ESTIMATED_SECONDS_PER_REQUEST


def _duration(seconds: float) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def _round_robin(plans: Sequence[TargetPlan]) -> Iterator[tuple[TargetPlan, ListingRef]]:
    """Un aviso de cada target por vuelta, en el orden de los targets."""
    queues = [(plan, deque(plan.sampled)) for plan in plans]
    while any(queue for _, queue in queues):
        for plan, queue in queues:
            if queue:
                yield plan, queue.popleft()


class _Run:
    def __init__(
        self,
        scraper: BaseScraper,
        spec: SourceSpec,
        *,
        per_target: int,
        pages_per_target: int,
        seed: int,
        out_dir: Path,
        utcnow: Callable[[], datetime],
        progress_every: int,
    ) -> None:
        self.scraper = scraper
        self.spec = spec
        self.per_target = per_target
        self.pages_per_target = pages_per_target
        self.seed = seed
        self.out_dir = out_dir
        self.utcnow = utcnow
        self.progress_every = progress_every
        self.listings_path = out_dir / LISTINGS_NAME
        self.manifest_path = out_dir / MANIFEST_NAME
        self.plans: list[TargetPlan] = []
        self.planned_ids: set[str] = set()
        self.attempted = 0
        self.valid = 0
        self.rejected = 0
        self.rejected_by: Counter[str] = Counter()
        self.fetch_errors: Counter[str] = Counter()
        self.stopped: str | None = None
        self.reason: str | None = None
        self.started_at = utcnow()
        self._finished_at: datetime | None = None
        self._file: IO[str] | None = None
        self._last_mark = 0
        self._planning = True  # True hasta terminar los listados
        self._upper_bound = 0  # requests máximas planificadas, calculadas en el pre-vuelo
        self._network_errors = 0  # pedidos seguidos sin respuesta

    # ------------------------------------------------------------------ corrida

    def run(self) -> CrawlResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.listings_path.open("x", encoding="utf-8", newline="\n") as file:
            self._file = file
            self._announce()
            try:
                self._plan_all()
                self._write_manifest()
                self._fetch_details()
            except BlockedError as error:
                self._stop("blocked", error)
                LOG.error("[bloqueo] se corta TODO, sin reintentos: %s", error)
            except BudgetExhaustedError as error:
                self._stop("budget", error)
                LOG.warning("[presupuesto] %s: se corta y se guarda lo obtenido", error)
            except RobotsUnavailableError as error:
                self._stop("robots_unavailable", error)
                LOG.error("[robots] %s", error)
            except NetworkDownError as error:
                self._stop("network", error)
                LOG.error("[red] %s: se corta y se guarda lo obtenido", error)
            except KeyboardInterrupt:
                self.stopped = "interrupted"
                raise
            except Exception as error:
                self.stopped = f"error:{type(error).__name__}"
                raise
            finally:
                self._finished_at = self.utcnow()
                self._write_manifest()
        self._summarize()
        return CrawlResult(
            stopped=self.stopped,
            reason=self.reason,
            planned=self._planned,
            attempted=self.attempted,
            valid=self.valid,
            rejected=self.rejected,
            listings_path=self.listings_path,
            manifest_path=self.manifest_path,
        )

    def _stop(self, reason: str, error: Exception) -> None:
        self.stopped, self.reason = reason, str(error)

    @property
    def _planned(self) -> int:
        return sum(len(plan.sampled) for plan in self.plans)

    # ------------------------------------------------------------------ plan

    def _announce(self) -> None:
        """Pre-vuelo: lo que la corrida puede llegar a pedir, antes de la primera request.

        Es una cota: todavía no se conoce la última página de cada búsqueda ni cuántos avisos
        tiene cada pool, así que supone `pages_per_target` listados y `per_target` detalles.
        """
        targets = len(self.spec.targets())
        listings = targets * self.pages_per_target
        details = targets * self.per_target
        self._upper_bound = 1 + listings + details
        budget = self.scraper.max_requests
        LOG.info(
            "[inicio] %s: %d búsquedas, seed %d, %d páginas y %d avisos por búsqueda",
            self.spec.name,
            targets,
            self.seed,
            self.pages_per_target,
            self.per_target,
        )
        LOG.info(
            "[pre-vuelo] requests máximas planificadas: %d (1 robots + %d listados + %d "
            "detalles), presupuesto %d",
            self._upper_bound,
            listings,
            details,
            budget,
        )
        LOG.info(
            "[pre-vuelo] %s", self._estimate("duración estimada", min(self._upper_bound, budget))
        )
        if self._upper_bound > budget:
            LOG.warning(
                "[pre-vuelo] AVISO: las %d requests máximas superan el presupuesto de %d, que es "
                "tope duro. Es una cota (todavía no se conoce la última página de cada búsqueda): "
                "el plan exacto sale en [plan] al terminar los listados y, si no alcanza, el corte "
                "por presupuesto deja sin pedir los últimos detalles, parejo entre búsquedas",
                self._upper_bound,
                budget,
            )

    def _estimate(self, label: str, requests: int) -> str:
        """`label`, duración y hora local de fin de `requests` requests al ritmo del piloto."""
        seconds = requests * ESTIMATED_SECONDS_PER_REQUEST
        end = (self.utcnow() + timedelta(seconds=seconds)).astimezone()
        pace = f"{ESTIMATED_SECONDS_PER_REQUEST:.1f}".replace(".", ",")
        return (
            f"{label} {_duration(seconds)} ({requests} requests a {pace} s por request); "
            f"fin estimado {end:%d/%m %H:%M}"
        )

    def _plan_all(self) -> None:
        for target in self.spec.targets():
            plan = TargetPlan(target)
            self.plans.append(plan)  # antes de pedir: un corte deja registrado dónde quedó
            self._plan_target(plan)
        self._planning = False
        used, remaining = self.scraper.requests_used, self.scraper.requests_remaining
        LOG.info(
            "[plan] %d detalles muestreados en %d búsquedas; requests: %d usadas + %d de "
            "detalles = %d, presupuesto %d",
            self._planned,
            len(self.plans),
            used,
            self._planned,
            used + self._planned,
            self.scraper.max_requests,
        )
        LOG.info(
            "[plan] %s", self._estimate("duración restante estimada", min(self._planned, remaining))
        )
        if self._planned > remaining:
            LOG.warning(
                "[presupuesto] faltan %d requests para pedir todos los detalles muestreados",
                self._planned - remaining,
            )

    def _plan_target(self, plan: TargetPlan) -> None:
        rng = random.Random(f"{self.seed}|{plan.target.url}")
        first = self._listing(plan, 1)
        if first is None:
            LOG.warning("[listado] %s: sin página 1 (%s)", plan.target.url, plan.errors)
            return
        plan.total_results, plan.last_page = first.total_results, first.last_page
        pages: dict[int, tuple[ListingRef, ...]] = {1: first.refs}
        for number in pick_pages(rng, first.last_page, self.pages_per_target)[1:]:
            page = self._listing(plan, number)
            if page is not None:
                pages[number] = page.refs
        for number, refs in pages.items():
            for ref in refs:
                found_in = plan.origins.setdefault(ref.source_id, [])
                if number not in found_in:
                    found_in.append(number)
        merged = self.spec.merge_refs(ref for refs in pages.values() for ref in refs)
        pool = [ref for ref in merged if ref.source_id not in self.planned_ids]
        plan.excluded_duplicates = len(merged) - len(pool)
        plan.pool_size = len(pool)
        plan.sampled = rng.sample(pool, min(self.per_target, len(pool)))
        plan.short = len(plan.sampled) < self.per_target
        self.planned_ids.update(ref.source_id for ref in plan.sampled)
        if plan.short:
            LOG.warning(
                "[muestra corta] %s: %d referencias para %d pedidas; se toman todas",
                plan.target.url,
                len(plan.sampled),
                self.per_target,
            )

    def _listing(self, plan: TargetPlan, number: int) -> ListingPage | None:
        result = self.scraper.fetch(self.spec.page_url(plan.target.url, number))
        self._progress()
        label = "pagina_1" if number == 1 else "pagina_aleatoria"
        page = self._parse_listing(plan, result, label)
        if number != 1:  # solo las que llegaron a pedirse: un corte no deja páginas sin pedir
            plan.random_pages.append(number)
        self._track_network(result)
        return page

    def _parse_listing(
        self, plan: TargetPlan, result: FetchResult, label: str
    ) -> ListingPage | None:
        if result.html is None:
            plan.errors.append(f"{label}:{_fetch_key(result)}")
            return None
        try:
            return self.spec.parse_listing_page(result.html)
        except Exception as error:  # el HTML cambió: se registra la clase, nunca el mensaje
            plan.errors.append(f"{label}:{type(error).__name__}")
            return None

    def _track_network(self, result: FetchResult) -> None:
        """Cuenta los pedidos seguidos sin respuesta; cualquier respuesta HTTP reinicia la cuenta.

        La caché y los pedidos que robots.txt prohíbe no tocan la red: no suman ni reinician.
        """
        if result.outcome == "error" and result.status is None:
            self._network_errors += 1
            if self._network_errors >= MAX_CONSECUTIVE_NETWORK_ERRORS:
                raise NetworkDownError(
                    f"{self._network_errors} pedidos seguidos sin respuesta (fallo de red)"
                )
        elif result.status is not None:
            self._network_errors = 0

    # ------------------------------------------------------------------ detalles

    def _fetch_details(self) -> None:
        for plan, ref in _round_robin(self.plans):
            self._detail(plan, ref)
            self._progress()

    def _detail(self, plan: TargetPlan, ref: ListingRef) -> None:
        result = self.scraper.fetch(ref.url)
        plan.attempted += 1
        self.attempted += 1
        self._store_detail(plan, ref, result)
        self._track_network(result)

    def _store_detail(self, plan: TargetPlan, ref: ListingRef, result: FetchResult) -> None:
        if result.html is None:
            self.fetch_errors[_fetch_key(result)] += 1
            return
        scraped_at = self.utcnow()
        try:
            listing = self.spec.parse_detail(result.html, ref.url, scraped_at, ref=ref)
        except ValidationError as error:
            self._reject(_validation_keys(error))
        except Exception as error:  # cualquier otro fallo de parseo: se cuenta y se sigue
            self._reject({type(error).__name__})
        else:
            assert self._file is not None
            self._file.write(listing.model_dump_json() + "\n")
            self._file.flush()
            plan.valid += 1
            self.valid += 1

    def _reject(self, keys: set[str]) -> None:
        self.rejected += 1
        self.rejected_by.update(keys)

    # ------------------------------------------------------------------ progreso y manifest

    def _progress(self) -> None:
        mark = self.scraper.requests_used // self.progress_every
        if mark <= self._last_mark:
            return
        self._last_mark = mark
        counts = self.scraper.counts
        latencies = self.scraper.latencies_s
        mean = f"{statistics.fmean(latencies):.2f} s" if latencies else "n/d"
        LOG.info(
            "[progreso] requests %d/%d | ok %d | error %d | cache %d | latencia media %s | "
            "detalles válidos %d rechazados %d | %s",
            self.scraper.requests_used,
            self.scraper.max_requests,
            counts["ok"],
            counts["error"],
            counts["cache"],
            mean,
            self.valid,
            self.rejected,
            self._end_estimate(),
        )

    def _end_estimate(self) -> str:
        """Hora local de fin: lo que queda por pedir (tope: el presupuesto) al ritmo medido.

        Durante los listados no se sabe cuántos detalles habrá: se usa la cota del pre-vuelo y la
        hora se rotula "fin máx.".
        """
        used = self.scraper.requests_used
        expected = self._upper_bound - used if self._planning else self._planned - self.attempted
        remaining = max(0, min(expected, self.scraper.requests_remaining))
        now = self.utcnow()
        pace = estimated_seconds_per_request((now - self.started_at).total_seconds(), used)
        end = (now + timedelta(seconds=remaining * pace)).astimezone()
        return f"{'fin máx.' if self._planning else 'fin estimado'} {end:%d/%m %H:%M}"

    def _summarize(self) -> None:
        end = self._finished_at or self.utcnow()
        minutes = (end - self.started_at).total_seconds() / 60
        LOG.info(
            "[fin] %s | requests %d/%d | detalles pedidos %d, válidos %d, rechazados %d | "
            "duración %.1f min",
            "completa" if self.stopped is None else f"cortada ({self.stopped})",
            self.scraper.requests_used,
            self.scraper.max_requests,
            self.attempted,
            self.valid,
            self.rejected,
            minutes,
        )

    def _manifest(self) -> dict[str, Any]:
        return {
            "source": self.spec.name,
            "snapshot_date": self.scraper.snapshot_date.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            "seed": self.seed,
            "budget": self.scraper.max_requests,
            "per_target": self.per_target,
            "pages_per_target": self.pages_per_target,
            "stopped": self.stopped,
            "stop_reason": self.reason,
            "requests": {
                "used": self.scraper.requests_used,
                "remaining": self.scraper.requests_remaining,
                "counts": self.scraper.counts,
            },
            "details": {
                "planned": self._planned,
                "attempted": self.attempted,
                "not_attempted": self._planned - self.attempted,
                "valid": self.valid,
                "rejected": self.rejected,
                "rejected_by_error": dict(self.rejected_by),
                "fetch_errors": dict(self.fetch_errors),
            },
            "targets": [self._target(plan) for plan in self.plans],
            "contract_version": CONTRACT_VERSION,
        }

    def _target(self, plan: TargetPlan) -> dict[str, Any]:
        return {
            "property_type": plan.target.property_type.value,
            "city": plan.target.city.value,
            "url": plan.target.url,
            "total_results": plan.total_results,
            "last_page": plan.last_page,
            "random_pages": plan.random_pages,
            "pool_size": plan.pool_size,
            "excluded_duplicates": plan.excluded_duplicates,
            "short": plan.short,
            "errors": plan.errors,
            "attempted": plan.attempted,
            "valid": plan.valid,
            "sampled": [
                {
                    "source_id": ref.source_id,
                    "pages": plan.origins[ref.source_id],
                    "patrocinado": ref.patrocinado,
                }
                for ref in plan.sampled
            ],
        }

    def _write_manifest(self) -> None:
        partial = self.manifest_path.with_suffix(".tmp")
        partial.write_text(
            json.dumps(self._manifest(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        partial.replace(self.manifest_path)


def crawl(
    scraper: BaseScraper,
    spec: SourceSpec,
    *,
    per_target: int,
    pages_per_target: int,
    seed: int,
    out_dir: Path,
    utcnow: Callable[[], datetime] = utc_now,
    progress_every: int = PROGRESS_EVERY,
) -> CrawlResult:
    """Muestrea los listados de `spec` y escribe los `RawListing` válidos en `out_dir`.

    `scraper` es el `BaseScraper` de la fuente (con su presupuesto). Por búsqueda se piden
    `pages_per_target` páginas (la 1 y el resto al azar) y se muestrean hasta `per_target` avisos.
    Devuelve el resultado también cuando la corrida se cortó (`stopped`); solo `KeyboardInterrupt`
    y los errores inesperados se propagan, después de escribir el manifest.
    """
    if per_target < 1:
        raise ValueError("per_target tiene que ser al menos 1")
    if pages_per_target < 1:
        raise ValueError("pages_per_target tiene que ser al menos 1")
    return _Run(
        scraper,
        spec,
        per_target=per_target,
        pages_per_target=pages_per_target,
        seed=seed,
        out_dir=out_dir,
        utcnow=utcnow,
        progress_every=progress_every,
    ).run()
