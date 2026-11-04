"""Punto de entrada del crawler (F3.3): argumentos obligatorios, códigos de salida y archivos.

Sin red: el transporte, el reloj y las carpetas se inyectan. Con el sitio falso de
`tests/scraping/fake_site.py`, pasando por el sanitizador real de Clasipar.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from avm.scraping.crawl import MAX_CONSECUTIVE_NETWORK_ERRORS
from avm.scraping.run import DEFAULT_INTERIM, EXIT_BLOCKED, EXIT_OK, EXIT_STOPPED, SOURCES, main
from tests.scraping.fake_site import NOW, SNAPSHOT, FakeSite
from tests.scraping.test_base import MaxJitter

ARGS = [
    "--source",
    "clasipar",
    "--budget",
    "100",
    "--pages-per-target",
    "2",
    "--per-target",
    "2",
    "--seed",
    "42",
]
JUSTFILE = Path(__file__).parents[2] / "justfile"


def invoke(tmp_path: Path, site: FakeSite, argv: list[str] = ARGS) -> int:
    return main(
        argv,
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
        today=lambda: SNAPSHOT,
        utcnow=lambda: NOW,
        scraper_options={
            "transport": httpx.MockTransport(site),
            "clock": site.clock,
            "sleep": site.clock.sleep,
            "rng": MaxJitter(),
        },
    )


# ------------------------------------------------------------------------- argumentos


@pytest.mark.parametrize(
    "flag", ["--source", "--budget", "--pages-per-target", "--per-target", "--seed"]
)
def test_the_five_parameters_are_required_and_have_no_default(
    tmp_path: Path, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeSite()
    argv = list(ARGS)
    index = argv.index(flag)
    del argv[index : index + 2]
    with pytest.raises(SystemExit) as exit_info:
        invoke(tmp_path, site, argv)
    assert exit_info.value.code == 2
    assert flag in capsys.readouterr().err
    assert site.paths == []  # sin parámetros no se envía nada


def _argv(**overrides: str) -> list[str]:
    values = {
        "source": "clasipar",
        "budget": "100",
        "pages-per-target": "2",
        "per-target": "2",
        "seed": "1",
    } | overrides
    return [item for name, value in values.items() for item in (f"--{name}", value)]


@pytest.mark.parametrize(
    "argv",
    [
        _argv(source="infocasas"),
        _argv(budget="0"),
        _argv(budget="mucho"),
        _argv(**{"pages-per-target": "0"}),
        _argv(**{"pages-per-target": "-1"}),
        _argv(**{"pages-per-target": "muchas"}),
        _argv(**{"per-target": "-3"}),
        _argv(seed="azar"),
    ],
)
def test_invalid_values_are_rejected_with_the_argparse_exit_code(
    tmp_path: Path, argv: list[str]
) -> None:
    site = FakeSite()
    with pytest.raises(SystemExit) as exit_info:
        invoke(tmp_path, site, argv)
    assert exit_info.value.code == 2 and site.paths == []


def test_clasipar_is_the_only_registered_source() -> None:
    assert set(SOURCES) == {"clasipar"}  # InfoCasas está descartada por sus ToS (docs/sources.md)


# ------------------------------------------------------------------------- corrida


def test_a_complete_run_exits_zero_and_writes_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeSite()
    assert invoke(tmp_path, site) == EXIT_OK
    interim = tmp_path / "interim" / "2026-10-06" / "clasipar"
    raw = tmp_path / "raw" / "2026-10-06" / "clasipar"
    assert len((interim / "raw_listings.jsonl").read_text("utf-8").splitlines()) == 24
    crawl = json.loads((interim / "crawl_manifest.json").read_text("utf-8"))
    assert crawl["seed"] == 42 and crawl["stopped"] is None
    base = json.loads((raw / "manifest.json").read_text("utf-8"))
    assert base["max_requests"] == 100 and base["requests_used"] == 1 + 24 + 24
    assert (raw / "requests.jsonl").is_file()
    output = capsys.readouterr().out
    assert "[inicio]" in output and "[fin]" in output
    assert "ó" in output  # la salida conserva los acentos


def test_a_block_exits_with_code_3_and_keeps_what_was_obtained(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeSite()
    site.detail_status[6] = 403
    assert invoke(tmp_path, site) == EXIT_BLOCKED == 3
    interim = tmp_path / "interim" / "2026-10-06" / "clasipar"
    assert len((interim / "raw_listings.jsonl").read_text("utf-8").splitlines()) == 5
    assert json.loads((interim / "crawl_manifest.json").read_text("utf-8"))["stopped"] == "blocked"
    assert len(site.requested("detail")) == 6  # ninguno después del bloqueo
    assert "[bloqueo]" in capsys.readouterr().out


def test_unreadable_robots_exits_with_code_4(tmp_path: Path) -> None:
    site = FakeSite()
    site.robots_status = 503
    assert invoke(tmp_path, site) == EXIT_STOPPED == 4


def test_consecutive_network_failures_exit_with_code_4_and_keep_what_was_obtained(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    limit = MAX_CONSECUTIVE_NETWORK_ERRORS
    site = FakeSite()
    # Las primeras 5 respuestas de detalle andan; las siguientes `limit` fallan sin respuesta.
    site.detail_errors = {n: httpx.ConnectError("sin red") for n in range(6, 6 + limit)}
    assert invoke(tmp_path, site, _argv(**{"per-target": "3", "seed": "42"})) == EXIT_STOPPED
    interim = tmp_path / "interim" / "2026-10-06" / "clasipar"
    assert len((interim / "raw_listings.jsonl").read_text("utf-8").splitlines()) == 5
    assert json.loads((interim / "crawl_manifest.json").read_text("utf-8"))["stopped"] == "network"
    assert len(site.requested("detail")) == 5 + limit  # ninguno después del corte
    assert "[red]" in capsys.readouterr().out


def test_the_scrape_recipe_takes_the_five_parameters_in_a_single_line() -> None:
    text = JUSTFILE.read_text("utf-8")
    recipe = re.search(r"^scrape (?P<params>[^:\n]*):\n(?P<body>(?:[ \t]+.*\n?)+)", text, re.M)
    assert recipe is not None
    params = recipe["params"].split()
    assert params == ["source", "budget", "pages_per_target", "per_target", "seed"]
    assert not any("=" in param for param in params)  # obligatorios, sin defaults
    body = [line for line in recipe["body"].splitlines() if line.strip()]
    assert len(body) == 1 and "&&" not in body[0] and ";" not in body[0]  # PowerShell y sh
    for flag, param in zip(
        ["source", "budget", "pages-per-target", "per-target", "seed"], params, strict=True
    ):
        assert f"--{flag} {{{{{param}}}}}" in body[0]


def test_an_exhausted_budget_is_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeSite()
    argv = _argv(budget="30", seed="42")
    assert invoke(tmp_path, site, argv) == EXIT_OK
    assert len(site.paths) == 30 and "[presupuesto]" in capsys.readouterr().out


def test_the_default_folders_are_relative_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    site = FakeSite()
    code = main(
        ARGS,
        today=lambda: SNAPSHOT,
        scraper_options={
            "transport": httpx.MockTransport(site),
            "clock": site.clock,
            "sleep": site.clock.sleep,
            "rng": MaxJitter(),
        },
    )
    assert code == EXIT_OK and Path("data/interim") == DEFAULT_INTERIM
    assert (Path("data/interim") / "2026-10-06" / "clasipar" / "raw_listings.jsonl").is_file()
    assert (Path("data/raw") / "2026-10-06" / "clasipar" / "manifest.json").is_file()


def test_the_logging_setup_is_removed_after_the_run(tmp_path: Path) -> None:
    logger = logging.getLogger("avm.scraping")
    before: dict[str, Any] = {"handlers": list(logger.handlers), "level": logger.level}
    invoke(tmp_path, FakeSite())
    assert list(logger.handlers) == before["handlers"] and logger.level == before["level"]


def test_an_existing_output_file_aborts_the_run_before_any_request(tmp_path: Path) -> None:
    out_dir = tmp_path / "interim" / "2026-10-06" / "clasipar"
    out_dir.mkdir(parents=True)
    (out_dir / "raw_listings.jsonl").write_text("previo\n", encoding="utf-8")
    # El registro de la corrida anterior (el manifest de BaseScraper) tampoco se toca.
    raw = tmp_path / "raw" / "2026-10-06" / "clasipar"
    raw.mkdir(parents=True)
    (raw / "manifest.json").write_text('{"requests_used": 253}\n', encoding="utf-8")
    site = FakeSite()
    with pytest.raises(FileExistsError, match="raw_listings.jsonl"):
        invoke(tmp_path, site)
    assert site.paths == []
    assert (raw / "manifest.json").read_text("utf-8") == '{"requests_used": 253}\n'
    assert sorted(path.name for path in raw.iterdir()) == ["manifest.json"]
    assert logging.getLogger("avm.scraping").handlers == []  # tampoco deja el handler puesto
