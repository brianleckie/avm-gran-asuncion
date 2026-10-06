"""Crawler de muestreo (F3.3), sin red: sitio falso con `httpx.MockTransport` y reloj falso.

Las propiedades que se verifican (orden round-robin, determinismo con el seed, presupuesto, cortes
limpios, rechazos contados sin contenido) salen de la especificación de la tarea, no de correr el
código. El contenido de las páginas es inventado (`tests/scraping/fake_site.py`).
"""

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError, model_validator

from avm.contract import RawListing
from avm.scraping.base import BaseScraper
from avm.scraping.crawl import LISTINGS_NAME, MANIFEST_NAME, CrawlResult, _validation_keys, crawl
from avm.scraping.sanitize import SanitizationError
from avm.scraping.sources.clasipar import ClasiparParseError, parse_detail
from tests.scraping.fake_site import (
    NOW,
    SPEC,
    FakeSite,
    listing_path,
    make_scraper,
    target_of,
)

PHONE = "0981 123 456"  # inventado; lo detecta `avm.contract.pii`
LOGGER = "avm.scraping.crawl"


def run(
    tmp_path: Path,
    *,
    site: FakeSite | None = None,
    per_target: int = 3,
    seed: int = 42,
    budget: int = 400,
    spec: Any = SPEC,
    progress_every: int = 50,
    **scraper_options: Any,
) -> tuple[CrawlResult, FakeSite, BaseScraper]:
    site = site if site is not None else FakeSite()
    with make_scraper(tmp_path, site, max_requests=budget, **scraper_options) as scraper:
        result = crawl(
            scraper,
            spec,
            per_target=per_target,
            seed=seed,
            out_dir=tmp_path / "interim",
            utcnow=lambda: NOW,
            progress_every=progress_every,
        )
    return result, site, scraper


def manifest(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "interim" / MANIFEST_NAME).read_text("utf-8"))


def listings(tmp_path: Path) -> list[RawListing]:
    lines = (tmp_path / "interim" / LISTINGS_NAME).read_text("utf-8").splitlines()
    return [RawListing.model_validate_json(line) for line in lines]


def plan(data: dict[str, Any]) -> list[tuple[int | None, list[str]]]:
    return [
        (target["random_page"], [item["source_id"] for item in target["sampled"]])
        for target in data["targets"]
    ]


# ------------------------------------------------------------------------- recorrido básico


def test_a_full_run_samples_per_target_and_writes_valid_listings(tmp_path: Path) -> None:
    result, site, scraper = run(tmp_path, per_target=3)
    assert result.stopped is None and result.reason is None
    assert (result.planned, result.attempted, result.valid, result.rejected) == (36, 36, 36, 0)
    # 1 robots + 12 búsquedas x 2 páginas + 36 detalles; el tope no se toca.
    assert scraper.requests_used == 1 + 24 + 36
    assert len(site.requested("robots")) == 1
    assert len(site.requested("listing")) == 24
    assert len(listings(tmp_path)) == 36


def test_listing_pages_come_first_one_and_one_random_per_target(tmp_path: Path) -> None:
    _, site, _ = run(tmp_path)
    paths = site.paths
    assert paths[0] == "/robots.txt"
    listing_paths = paths[1:25]
    assert all("/inmuebles/" in path and "anuncio-" not in path for path in listing_paths)
    assert all(
        path.rsplit("/", 1)[-1].startswith("anuncio-") for path in paths[25:]
    )  # después de los 24 listados, solo detalles
    for search in range(12):
        first, second = listing_paths[2 * search], listing_paths[2 * search + 1]
        assert first == listing_path(search)  # la página 1 no lleva sufijo
        page = int(second.rsplit("/page-", 1)[1])
        assert second == listing_path(search, page) and 2 <= page <= site.default_last_page


def test_details_are_requested_round_robin_across_targets(tmp_path: Path) -> None:
    _, site, _ = run(tmp_path, per_target=3)
    assert [target_of(source_id) for source_id in site.detail_ids()] == list(range(12)) * 3


def test_the_sample_comes_from_page_one_and_the_random_page_without_repeats(
    tmp_path: Path,
) -> None:
    run(tmp_path, per_target=10)
    data = manifest(tmp_path)
    site = FakeSite()
    for search, target in enumerate(data["targets"]):
        random_page = target["random_page"]
        assert 2 <= random_page <= 5
        ids = [item["source_id"] for item in target["sampled"]]
        assert len(ids) == len(set(ids)) == 10  # sin reposición
        from_first = {str(source_id) for source_id in site.ids(search, 1)}
        from_random = {str(source_id) for source_id in site.ids(search, random_page)}
        assert set(ids) <= from_first | from_random
        for item in target["sampled"]:
            expected = [1] if item["source_id"] in from_first else [random_page]
            assert item["pages"] == expected


def test_a_sponsored_card_repeated_in_both_pages_is_one_ad_from_both_pages(
    tmp_path: Path,
) -> None:
    site = FakeSite()
    site.per_page = 4
    site.default_last_page = 2  # la página aleatoria es siempre la 2
    shared = site.ids(0, 1)[0]
    site.extra_ids[(0, 2)] = [shared]  # el mismo aviso, también en la página 2
    site.sponsored = {shared}
    run(tmp_path, site=site, per_target=20)
    target = manifest(tmp_path)["targets"][0]
    item = next(item for item in target["sampled"] if item["source_id"] == str(shared))
    assert item["pages"] == [1, 2] and item["patrocinado"] is True
    assert [entry["source_id"] for entry in target["sampled"]].count(str(shared)) == 1
    assert target["pool_size"] == 4 + 4  # 4 + 4 + 1 repetido, deduplicado por source_id


def test_an_ad_repeated_inside_one_page_is_one_ad_from_that_page(tmp_path: Path) -> None:
    site = FakeSite()
    site.per_page = 3
    site.default_last_page = 1
    site.extra_ids[(0, 1)] = [site.ids(0, 1)[0]]  # la misma tarjeta, dos veces en la página 1
    run(tmp_path, site=site, per_target=10)
    target = manifest(tmp_path)["targets"][0]
    assert target["pool_size"] == 3 and len(target["sampled"]) == 3
    assert all(item["pages"] == [1] for item in target["sampled"])


def test_a_search_with_one_page_does_not_request_a_second_one(tmp_path: Path) -> None:
    site = FakeSite()
    site.last_page[3] = 1
    _, site, _ = run(tmp_path, site=site)
    assert len(site.requested("listing")) == 23
    target = manifest(tmp_path)["targets"][3]
    assert target["random_page"] is None and target["last_page"] == 1


def test_without_pagination_info_only_the_first_page_is_used(tmp_path: Path) -> None:
    site = FakeSite()
    site.paginated = False
    run(tmp_path, site=site, per_target=5)
    data = manifest(tmp_path)
    assert len(site.requested("listing")) == 12
    assert all(t["last_page"] is None and t["random_page"] is None for t in data["targets"])
    assert all(len(t["sampled"]) == 5 for t in data["targets"])


def test_a_target_with_fewer_refs_than_per_target_takes_all_and_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    site = FakeSite()
    site.per_page = 4
    site.last_page[0] = 1  # un solo listado de 4 avisos
    result, _, _ = run(tmp_path, site=site, per_target=6)
    first, second = manifest(tmp_path)["targets"][:2]
    assert (first["pool_size"], len(first["sampled"]), first["short"]) == (4, 4, True)
    assert (second["pool_size"], len(second["sampled"]), second["short"]) == (8, 6, False)
    assert result.planned == 4 + 11 * 6 and result.valid == result.planned
    assert any("muestra corta" in record.message for record in caplog.records)


# ------------------------------------------------------------------------- determinismo


def test_the_same_seed_gives_the_same_plan_and_another_seed_a_different_one(
    tmp_path: Path,
) -> None:
    run(tmp_path / "a", per_target=5, seed=7)
    run(tmp_path / "b", per_target=5, seed=7)
    run(tmp_path / "c", per_target=5, seed=8)
    assert plan(manifest(tmp_path / "a")) == plan(manifest(tmp_path / "b"))
    assert plan(manifest(tmp_path / "a")) != plan(manifest(tmp_path / "c"))
    assert manifest(tmp_path / "a")["seed"] == 7


def test_a_failing_target_does_not_change_the_sample_of_the_others(tmp_path: Path) -> None:
    run(tmp_path / "ok", per_target=5)
    broken = FakeSite()
    broken.status[listing_path(0)] = 404  # la búsqueda 0 no responde
    run(tmp_path / "broken", site=broken, per_target=5)
    healthy, degraded = plan(manifest(tmp_path / "ok")), plan(manifest(tmp_path / "broken"))
    assert degraded[0] == (None, [])
    assert healthy[1:] == degraded[1:]


def test_ads_already_planned_by_another_target_are_not_planned_twice(tmp_path: Path) -> None:
    site = FakeSite()
    site.per_page = 4
    site.default_last_page = 1
    shared = site.ids(0, 1)[0]
    site.extra_ids[(1, 1)] = [shared]  # un patrocinado de la búsqueda 0 aparece también en la 1
    result, site, _ = run(tmp_path, site=site, per_target=10)
    first, second = manifest(tmp_path)["targets"][:2]
    assert first["excluded_duplicates"] == 0 and len(first["sampled"]) == 4
    assert second["excluded_duplicates"] == 1 and len(second["sampled"]) == 4
    assert len(site.detail_ids()) == len(set(site.detail_ids()))
    assert result.planned == 12 * 4


# ------------------------------------------------------------------------- presupuesto


def test_the_budget_is_respected_and_the_cut_is_balanced_across_targets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    result, site, scraper = run(tmp_path, per_target=5, budget=40)
    assert result.stopped == "budget" and "40" in str(result.reason)
    assert scraper.requests_used == 40 and len(site.paths) == 40  # nunca se envía de más
    # 1 robots + 24 listados dejan 15 pedidos para detalles: 3 vueltas completas de 12 + ... = 15.
    assert result.attempted == 15 and result.valid == 15
    counts = [target["attempted"] for target in manifest(tmp_path)["targets"]]
    assert max(counts) - min(counts) <= 1 and sum(counts) == 15
    data = manifest(tmp_path)
    assert data["stopped"] == "budget"
    assert data["details"]["planned"] == 60 and data["details"]["not_attempted"] == 45
    assert any("presupuesto" in r.message and r.levelno == logging.WARNING for r in caplog.records)


def test_budget_exhausted_while_listing_stops_before_any_detail(tmp_path: Path) -> None:
    result, site, scraper = run(tmp_path, budget=10)
    assert result.stopped == "budget" and result.attempted == 0
    assert scraper.requests_used == 10 and site.requested("detail") == []
    assert listings(tmp_path) == []
    data = manifest(tmp_path)
    assert 1 <= len(data["targets"]) < 12 and data["stopped"] == "budget"


# ------------------------------------------------------------------------- cortes y bloqueos


def test_a_block_in_the_details_stops_everything_and_keeps_what_was_obtained(
    tmp_path: Path,
) -> None:
    site = FakeSite()
    site.detail_status[5] = 429
    result, site, scraper = run(tmp_path, site=site, per_target=3)
    assert result.stopped == "blocked" and "429" in str(result.reason)
    assert len(site.requested("detail")) == 5  # el quinto fue el bloqueo: no hubo un sexto
    assert (result.attempted, result.valid) == (4, 4)
    assert len(listings(tmp_path)) == 4
    assert manifest(tmp_path)["stopped"] == "blocked"
    base_manifest = json.loads((scraper.directory / "manifest.json").read_text("utf-8"))
    assert (
        base_manifest["blocked"] is True and base_manifest["requests_used"] == scraper.requests_used
    )


def test_a_block_while_listing_stops_before_any_detail(tmp_path: Path) -> None:
    site = FakeSite()
    site.status[listing_path(2)] = 403
    result, site, _ = run(tmp_path, site=site)
    assert result.stopped == "blocked" and result.attempted == 0
    assert site.requested("detail") == [] and listings(tmp_path) == []
    data = manifest(tmp_path)
    assert [t["property_type"] for t in data["targets"]] == ["casa"] * 3
    assert data["stopped"] == "blocked"


def test_unreadable_robots_txt_stops_the_run_cleanly(tmp_path: Path) -> None:
    site = FakeSite()
    site.robots_status = 500
    result, site, _ = run(tmp_path, site=site)
    assert result.stopped == "robots_unavailable" and result.attempted == 0
    assert site.requested("listing") == [] and listings(tmp_path) == []
    data = manifest(tmp_path)
    assert data["stopped"] == "robots_unavailable"
    assert len(data["targets"]) == 1 and data["targets"][0]["sampled"] == []


def test_a_search_forbidden_by_robots_is_skipped_without_requesting_it(tmp_path: Path) -> None:
    site = FakeSite()
    site.robots = "User-agent: *\nDisallow: /inmuebles/duplex/\n"
    result, site, _ = run(tmp_path, site=site, per_target=3)
    assert not [path for path in site.paths if "/duplex/" in path]
    targets = manifest(tmp_path)["targets"]
    assert [t["errors"] for t in targets[8:]] == [["pagina_1:robots_prohibido"]] * 4
    assert all(t["sampled"] == [] and t["pool_size"] == 0 for t in targets[8:])
    assert result.stopped is None and result.valid == 8 * 3


def test_a_keyboard_interrupt_writes_the_manifest_and_re_raises(tmp_path: Path) -> None:
    site = FakeSite()
    site.detail_errors[4] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, site=site, per_target=3)
    assert manifest(tmp_path)["stopped"] == "interrupted"
    assert len(listings(tmp_path)) == 3  # lo que ya estaba escrito se conserva
    assert (tmp_path / "raw" / "2026-10-06" / "clasipar" / "manifest.json").is_file()


def test_an_unexpected_error_writes_the_manifest_and_re_raises(tmp_path: Path) -> None:
    site = FakeSite()
    site.detail_errors[2] = RuntimeError("falla del transporte")
    with pytest.raises(RuntimeError):
        run(tmp_path, site=site, per_target=3)
    data = manifest(tmp_path)
    assert data["stopped"] == "error:RuntimeError" and len(data["targets"]) == 12
    assert len(listings(tmp_path)) == 1


# ------------------------------------------------------------------------- errores por tipo


def test_listing_failures_are_recorded_per_target_and_the_run_goes_on(tmp_path: Path) -> None:
    site = FakeSite()
    site.broken_listings = {listing_path(2)}  # cambió el HTML de una búsqueda
    site.status[listing_path(5, 3)] = 404
    site.status[listing_path(5, 2)] = 404
    site.status[listing_path(5, 4)] = 404
    site.status[listing_path(5, 5)] = 404
    result, site, _ = run(tmp_path, site=site, per_target=4)
    targets = manifest(tmp_path)["targets"]
    assert targets[2]["errors"] == ["pagina_1:ClasiparParseError"]
    assert targets[2]["sampled"] == [] and targets[2]["random_page"] is None
    # sin la página aleatoria, el pool sale solo de la página 1
    assert targets[5]["errors"] == ["pagina_aleatoria:http_404"]
    assert targets[5]["random_page"] in (2, 3, 4, 5)
    assert {page for item in targets[5]["sampled"] for page in item["pages"]} == {1}
    assert result.stopped is None and result.valid == 11 * 4


def test_rejected_details_are_counted_by_error_type_and_never_keep_the_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    calls: list[str] = []

    def flaky_parse(html: str, url: str, scraped_at: Any, *, ref: Any = None) -> RawListing:
        calls.append(url)
        number = len(calls)
        base = {"source": "clasipar", "source_id": "1", "url": url, "scraped_at": scraped_at}
        if number == 1:  # el contrato rechaza un teléfono: el error no debe repetirlo
            return RawListing(**base, content_hash="0" * 64, title_raw=f"Llamar al {PHONE}")
        if number == 2:
            return RawListing(**base, content_hash="no-es-un-hash")
        if number == 3:
            raise RuntimeError(f"se rompió con {PHONE}")
        if number == 4:
            raise ClasiparParseError(f"estructura inesperada {PHONE}")
        return parse_detail(html, url, scraped_at, ref=ref)

    result, _, _ = run(tmp_path, spec=replace(SPEC, parse_detail=flaky_parse), per_target=3)
    assert (result.attempted, result.rejected, result.valid) == (36, 4, 32)
    data = manifest(tmp_path)
    assert data["details"]["rejected"] == 4
    assert data["details"]["rejected_by_error"] == {
        "ValidationError:datos_personales@title_raw": 1,
        "ValidationError:string_pattern_mismatch@content_hash": 1,
        "RuntimeError": 1,
        "ClasiparParseError": 1,
    }
    everything = json.dumps(data) + (tmp_path / "interim" / LISTINGS_NAME).read_text("utf-8")
    everything += "\n".join(record.getMessage() for record in caplog.records)
    assert PHONE not in everything and "Llamar" not in everything


def test_validation_keys_only_keep_the_error_type_and_the_field() -> None:
    class Strict(BaseModel):
        name: str

        @model_validator(mode="after")
        def _check(self) -> "Strict":
            raise ValueError(f"mensaje con el valor {self.name}")

    with pytest.raises(ValidationError) as caught:
        Strict(name="SECRETO")
    keys = _validation_keys(caught.value)  # error de modelo, sin campo ni mensaje del contrato
    assert keys == {"ValidationError:value_error@-"}
    assert "SECRETO" not in str(keys)
    with pytest.raises(ValidationError) as missing:
        Strict()  # type: ignore[call-arg]
    assert _validation_keys(missing.value) == {"ValidationError:missing@name"}


def test_fetch_failures_are_counted_by_status(tmp_path: Path) -> None:
    site = FakeSite()
    site.detail_status[3] = 404

    seen: list[str] = []

    def sanitize(html: str) -> str:
        if 'class="tit-anuncio"' in html:  # solo las páginas de detalle
            seen.append(html)
            if len(seen) == 2:
                raise SanitizationError("quedó un rastro")
        return html

    result, _, _ = run(tmp_path, site=site, per_target=3, sanitize=sanitize)
    data = manifest(tmp_path)["details"]
    assert data["fetch_errors"] == {"http_404": 1, "sanitizacion_fallida": 1}
    assert (result.attempted, result.valid, result.rejected) == (36, 34, 0)
    assert result.attempted == result.valid + result.rejected + sum(data["fetch_errors"].values())


def test_a_network_error_is_counted_as_no_response(tmp_path: Path) -> None:
    site = FakeSite()
    site.detail_errors[1] = httpx.ConnectError("sin conexión")  # no se reintenta
    result, _, _ = run(tmp_path, site=site, per_target=1)
    assert manifest(tmp_path)["details"]["fetch_errors"] == {"sin_respuesta": 1}
    assert result.valid == 11


# ------------------------------------------------------------------------- salida


def test_valid_listings_are_raw_listings_with_the_sponsored_mark(tmp_path: Path) -> None:
    site = FakeSite()
    site.sponsored = set(site.ids(0, 1)[:10])
    run(tmp_path, site=site, per_target=10)
    rows = listings(tmp_path)
    assert len(rows) == 120
    for row in rows:
        assert row.source.value == "clasipar" and row.scraped_at == NOW
        assert (row.attributes_raw.get("patrocinado") == "si") == (
            int(row.source_id) in site.sponsored
        )
        assert row.operation_raw == "Vendo" and row.advertiser_type_raw == "Particular"
    sampled = {
        item["source_id"]: item for t in manifest(tmp_path)["targets"] for item in t["sampled"]
    }
    assert all(
        sampled[row.source_id]["patrocinado"] == (int(row.source_id) in site.sponsored)
        for row in rows
    )


def test_the_manifest_records_the_whole_plan(tmp_path: Path) -> None:
    run(tmp_path, per_target=3, seed=42, budget=300)
    data = manifest(tmp_path)
    assert data["source"] == "clasipar" and data["snapshot_date"] == "2026-10-06"
    assert (data["seed"], data["budget"], data["per_target"]) == (42, 300, 3)
    assert data["stopped"] is None and data["contract_version"]
    assert data["started_at"] == NOW.isoformat() and data["finished_at"] == NOW.isoformat()
    assert data["requests"]["used"] == 61 and data["requests"]["remaining"] == 239
    assert data["requests"]["counts"]["ok"] == 61
    assert data["details"] == {
        "planned": 36,
        "attempted": 36,
        "not_attempted": 0,
        "valid": 36,
        "rejected": 0,
        "rejected_by_error": {},
        "fetch_errors": {},
    }
    first = data["targets"][0]
    assert (first["property_type"], first["city"]) == ("casa", "asuncion")
    assert first["url"].endswith("/inmuebles/casas/intencion:vendo-t_s/localidad:asuncion-3")
    assert (first["total_results"], first["last_page"]) == (125, 5)
    assert first["pool_size"] == 60 and first["short"] is False and first["errors"] == []
    assert (first["attempted"], first["valid"]) == (3, 3)
    assert {t["city"] for t in data["targets"]} == {
        "asuncion",
        "luque",
        "san_lorenzo",
        "fernando_de_la_mora",
    }


def test_the_plan_is_saved_before_the_details_are_requested(tmp_path: Path) -> None:
    site = FakeSite()
    seen: list[dict[str, Any]] = []

    def spy(request: httpx.Request) -> httpx.Response:
        if "anuncio-" in request.url.path and not seen:
            seen.append(manifest(tmp_path))  # justo antes del primer detalle
        return site(request)

    with make_scraper(tmp_path, site, transport=httpx.MockTransport(spy)) as scraper:
        crawl(scraper, SPEC, per_target=2, seed=1, out_dir=tmp_path / "interim", utcnow=lambda: NOW)
    assert len(seen[0]["targets"]) == 12 and seen[0]["targets"][0]["sampled"]
    assert seen[0]["details"]["attempted"] == 0


def test_progress_is_logged_every_n_requests_with_the_mean_latency(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    site = FakeSite()
    site.latency = 0.2
    run(tmp_path, site=site, per_target=3, progress_every=10)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[progreso]")]
    assert len(lines) == 6  # 61 requests: marcas en 10, 20, 30, 40, 50 y 60
    assert "requests 10/400" in lines[0] and "latencia media 0.20 s" in lines[0]
    assert "ok 10" in lines[0] and "error 0" in lines[0] and "cache 0" in lines[0]
    assert "requests 60/400" in lines[-1]
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("[inicio]") for m in messages)
    assert any(m.startswith("[fin]") for m in messages)


def test_an_existing_output_file_is_never_overwritten(tmp_path: Path) -> None:
    out_dir = tmp_path / "interim"
    out_dir.mkdir()
    (out_dir / LISTINGS_NAME).write_text("previo\n", encoding="utf-8")
    site = FakeSite()
    with pytest.raises(FileExistsError):
        run(tmp_path, site=site)
    assert site.paths == [] and (out_dir / LISTINGS_NAME).read_text("utf-8") == "previo\n"


def test_per_target_must_be_positive(tmp_path: Path) -> None:
    site = FakeSite()
    with pytest.raises(ValueError, match="per_target"):
        run(tmp_path, site=site, per_target=0)
    assert site.paths == []
