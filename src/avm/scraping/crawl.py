"""Crawler de muestreo de listados (F3.3): del listado a un `RawListing` por aviso muestreado.

No recorre todo el portal: toma una muestra reproducible, pensada para el piloto. Por cada búsqueda
(`SearchTarget`: tipo x ciudad) de la fuente:
1. Pide la página 1 y lee `last_page` y `total_results`.
2. Si `last_page > 1`, pide UNA página al azar en [2, last_page].
3. Une las referencias de ambas páginas (`merge_refs`) y muestrea SIN reposición hasta
   `per_target` con el mismo rng. Si hay menos, toma todas y lo registra (`short`).
Después pide los detalles de todos los targets INTERCALADOS (round-robin), para que un corte por
presupuesto o por bloqueo no deje combinaciones enteras sin muestra. Cada detalle pasa por
`parse_detail`; los `RawListing` válidos se agregan, uno por línea y con flush, a
`<out_dir>/raw_listings.jsonl`.

Reglas:
- Todo pedido pasa por `BaseScraper` (cortesía, robots.txt, presupuesto, caché sanitizada y
  bloqueos). Este módulo no abre ninguna conexión.
- Reproducibilidad: cada target usa su propio rng, `Random(f"{seed}|{url del target}")`. Así el
  muestreo de un target no depende de si otro falló. El plan (seed, páginas aleatorias y los
  `source_id` muestreados, con la página de la que salió cada uno) queda en `crawl_manifest.json`.
- Un detalle que no valida se cuenta por tipo de error y se sigue. Del error solo se guarda la
  clase y el campo, NUNCA el mensaje ni el valor (traen el contenido del aviso).
- `BlockedError` corta TODO, sin reintentos; `BudgetExhaustedError` y `RobotsUnavailableError`
  también. En los tres casos se conserva lo obtenido y se escribe el manifest (`stopped`).
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
from datetime import UTC, datetime
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


@dataclass(slots=True)
class TargetPlan:
    """Qué se pidió y qué se muestreó de una búsqueda."""

    target: SearchTarget
    total_results: int | None = None
    last_page: int | None = None
    random_page: int | None = None
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
    stopped: str | None  # None, "blocked", "budget" o "robots_unavailable"
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
        seed: int,
        out_dir: Path,
        utcnow: Callable[[], datetime],
        progress_every: int,
    ) -> None:
        self.scraper = scraper
        self.spec = spec
        self.per_target = per_target
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
        targets = len(self.spec.targets())
        total = 1 + 2 * targets + self.per_target * targets
        seconds = total * (MIN_DELAY_S + JITTER_MAX_S / 2)
        LOG.info(
            "[inicio] %s: %d búsquedas, seed %d, %d por búsqueda; plan de hasta %d requests "
            "(1 robots + %d listados + %d detalles), presupuesto %d; unos %.0f min de espera sin "
            "contar la latencia",
            self.spec.name,
            targets,
            self.seed,
            self.per_target,
            total,
            2 * targets,
            self.per_target * targets,
            self.scraper.max_requests,
            seconds / 60,
        )
        if total > self.scraper.max_requests:
            LOG.warning(
                "[presupuesto] el plan (%d requests) supera el presupuesto (%d): el corte por "
                "presupuesto va a dejar muestra sin pedir",
                total,
                self.scraper.max_requests,
            )

    def _plan_all(self) -> None:
        for target in self.spec.targets():
            plan = TargetPlan(target)
            self.plans.append(plan)  # antes de pedir: un corte deja registrado dónde quedó
            self._plan_target(plan)
        LOG.info(
            "[plan] %d detalles muestreados en %d búsquedas; quedan %d requests de presupuesto",
            self._planned,
            len(self.plans),
            self.scraper.requests_remaining,
        )
        if self._planned > self.scraper.requests_remaining:
            LOG.warning(
                "[presupuesto] faltan %d requests para pedir todos los detalles muestreados",
                self._planned - self.scraper.requests_remaining,
            )

    def _plan_target(self, plan: TargetPlan) -> None:
        rng = random.Random(f"{self.seed}|{plan.target.url}")
        first = self._listing(plan, 1)
        if first is None:
            LOG.warning("[listado] %s: sin página 1 (%s)", plan.target.url, plan.errors)
            return
        plan.total_results, plan.last_page = first.total_results, first.last_page
        pages: dict[int, tuple[ListingRef, ...]] = {1: first.refs}
        if first.last_page is not None and first.last_page > 1:
            plan.random_page = rng.randint(2, first.last_page)
            second = self._listing(plan, plan.random_page)
            if second is not None:
                pages[plan.random_page] = second.refs
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
        if result.html is None:
            plan.errors.append(f"{label}:{_fetch_key(result)}")
            return None
        try:
            return self.spec.parse_listing_page(result.html)
        except Exception as error:  # el HTML cambió: se registra la clase, nunca el mensaje
            plan.errors.append(f"{label}:{type(error).__name__}")
            return None

    # ------------------------------------------------------------------ detalles

    def _fetch_details(self) -> None:
        for plan, ref in _round_robin(self.plans):
            self._detail(plan, ref)
            self._progress()

    def _detail(self, plan: TargetPlan, ref: ListingRef) -> None:
        result = self.scraper.fetch(ref.url)
        plan.attempted += 1
        self.attempted += 1
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
            "detalles válidos %d rechazados %d",
            self.scraper.requests_used,
            self.scraper.max_requests,
            counts["ok"],
            counts["error"],
            counts["cache"],
            mean,
            self.valid,
            self.rejected,
        )

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
            "random_page": plan.random_page,
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
    seed: int,
    out_dir: Path,
    utcnow: Callable[[], datetime] = utc_now,
    progress_every: int = PROGRESS_EVERY,
) -> CrawlResult:
    """Muestrea los listados de `spec` y escribe los `RawListing` válidos en `out_dir`.

    `scraper` es el `BaseScraper` de la fuente (con su presupuesto). Devuelve el resultado también
    cuando la corrida se cortó (`stopped`); solo `KeyboardInterrupt` y los errores inesperados se
    propagan, después de escribir el manifest.
    """
    if per_target < 1:
        raise ValueError("per_target tiene que ser al menos 1")
    return _Run(
        scraper,
        spec,
        per_target=per_target,
        seed=seed,
        out_dir=out_dir,
        utcnow=utcnow,
        progress_every=progress_every,
    ).run()
