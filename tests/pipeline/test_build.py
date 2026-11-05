"""`build-dataset` de punta a punta (F4/F5) con avisos sintéticos y valores escritos a mano."""

import csv
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from make_synthetic_dataset import DATASET_COLUMNS as SYNTHETIC_COLUMNS

from avm.contract import RawListing
from avm.pipeline import build
from avm.pipeline.build import (
    DATASET_COLUMNS,
    Params,
    build_parser,
    funnel_rules,
    main,
    out_dir_name,
)
from avm.pipeline.clean import FxContext
from tests.pipeline.helpers import make_raw

FX_SOURCE = "Casa de cambios de prueba, punto medio, 04/11/2026"
EARLY = make_raw("3").scraped_at.replace(month=10, day=6)


def write_snapshot(root: Path, snapshot: str, lines: list[str]) -> None:
    folder = root / snapshot / "clasipar"
    folder.mkdir(parents=True)
    (folder / "raw_listings.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def line(raw: RawListing) -> str:
    return raw.model_dump_json()


@pytest.fixture
def interim(tmp_path: Path) -> Path:
    """Dos snapshots. Los comentarios dicen qué le pasa a cada aviso."""
    root = tmp_path / "interim"
    write_snapshot(
        root,
        "2026-11-04",
        [
            # 1 y 2: mismo bloque y mismo precio en USD (el 2 está en PYG: 608.500.000 / 6085)
            line(
                make_raw(
                    "1",
                    price="US$. 100.000",
                    built_tag="100",
                    attributes={"Piscina": "SI"},
                    description="Sin quincho",
                    bedrooms="3",
                )
            ),
            line(make_raw("2", price="Gs. 608.500.000", built_tag="100")),
            # 3: departamento de Asunción, m² en el texto, patrocinado (el viejo vale otro precio)
            line(
                make_raw(
                    "3",
                    price="US$. 50.000",
                    property_type="departamentos",
                    city="Asunción",
                    advertiser="Inmobiliaria",
                    description="Departamento de 50 m² construidos",
                    sponsored=True,
                )
            ),
            line(make_raw("4", price="Consultar precio.", built_tag="100")),  # sin monto
            line(make_raw("5", price="US$. 100.000")),  # sin m² construidos
            line(make_raw("6", price="US$. 1.000", built_tag="100")),  # 10 USD/m²: outlier
            line(make_raw("7", price="US$. 100.000", built_tag="100", city="Encarnación")),
            '{"no": "es un aviso"}',  # línea inválida
            "",  # línea en blanco: se ignora
        ],
    )
    write_snapshot(
        root,
        "2026-10-06",
        [
            line(make_raw("3", price="US$. 40.000", scraped_at=EARLY)),  # el 3 viejo: se colapsa
            line(
                make_raw(
                    "9",
                    price="US$. 150.000",
                    property_type="duplex",
                    city="San Lorenzo",
                    built_tag="200",
                    scraped_at=EARLY,
                )
            ),
        ],
    )
    return root


def run(
    interim: Path, out: Path, *extra: str, snapshots: tuple[str, ...] = ("2026-10-06", "2026-11-04")
) -> int:
    return main(
        [
            "--snapshot",
            *snapshots,
            "--fx-pyg-per-usd",
            "6085",
            "--fx-date",
            "2026-11-04",
            "--fx-source",
            FX_SOURCE,
            "--gazetteer",
            "none",
            "--interim-root",
            str(interim),
            "--out-root",
            str(out),
            *extra,
        ]
    )


def read_rows(out: Path, name: str = "2026-10-06_2026-11-04") -> list[dict[str, str]]:
    with (out / name / "dataset.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ------------------------------------------------------------------------------------ dataset


def test_the_columns_are_exactly_those_of_i1_and_match_the_synthetic_generator() -> None:
    assert list(DATASET_COLUMNS) == SYNTHETIC_COLUMNS
    assert len(DATASET_COLUMNS) == 25


def test_the_dataset_has_the_expected_rows_with_hand_written_values(
    interim: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert run(interim, out) == 0
    rows = read_rows(out)
    assert list(rows[0]) == list(DATASET_COLUMNS)
    assert [r["listing_key"] for r in rows] == [
        "clasipar:1",
        "clasipar:2",
        "clasipar:3",
        "clasipar:9",
    ]
    first, second, third, ninth = rows
    assert first == {
        "listing_key": "clasipar:1",
        "cluster_id": "c-clasipar-1",
        "snapshot_date": "2026-11-04",
        "city": "luque",
        "neighborhood": "",
        "neighborhood_match": "sin_match",
        "geo_precision": "ciudad",
        "property_type": "casa",
        "price_usd": "100000.00",
        "built_area_m2": "100",
        "built_area_source": "tag",
        "land_area_m2": "",
        "bedrooms": "3",
        "bathrooms": "",
        "garages": "",
        "has_pool": "1",
        "has_quincho": "0",
        "is_new": "",
        "in_gated_community": "",
        "has_elevator": "",
        "street_surface": "",
        "advertiser_type": "particular",
        "is_sponsored": "0",
        "usd_per_m2": "1000.0000",
        "log_usd_per_m2": "6.907755",  # ln(1000)
    }
    assert second["price_usd"] == "100000.00"  # 608.500.000 / 6085
    assert second["cluster_id"] == "c-clasipar-1"  # casi-duplicado del 1
    assert (third["city"], third["property_type"]) == ("asuncion", "departamento")
    assert (third["built_area_m2"], third["built_area_source"]) == ("50", "texto")
    assert (third["is_sponsored"], third["advertiser_type"]) == ("1", "inmobiliaria")
    assert third["price_usd"] == "50000.00"  # la fila del snapshot más reciente, no los 40.000
    assert third["snapshot_date"] == "2026-11-04"
    assert (ninth["snapshot_date"], ninth["usd_per_m2"], ninth["log_usd_per_m2"]) == (
        "2026-10-06",  # cada fila lleva la fecha de SU snapshot
        "750.0000",
        "6.620073",  # ln(750)
    )
    assert ninth["property_type"] == "duplex" and ninth["city"] == "san_lorenzo"


def test_every_row_satisfies_the_i1_invariants(interim: Path, tmp_path: Path) -> None:
    run(interim, tmp_path / "out")
    rows = read_rows(tmp_path / "out")
    assert len({r["listing_key"] for r in rows}) == len(rows)
    for r in rows:
        assert r["cluster_id"] and float(r["price_usd"]) > 0 and float(r["built_area_m2"]) > 0
        assert math.isclose(
            math.log(float(r["usd_per_m2"])), float(r["log_usd_per_m2"]), abs_tol=1e-6
        )
        assert math.isclose(
            float(r["price_usd"]) / float(r["built_area_m2"]), float(r["usd_per_m2"]), rel_tol=1e-4
        )
        assert (r["geo_precision"] == "ciudad") == (r["neighborhood"] == "")
        assert r["is_sponsored"] in {"0", "1"} and r["built_area_source"] in {"tag", "texto"}


def test_a_single_snapshot_uses_its_own_folder_name(interim: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run(interim, out, snapshots=("2026-10-06",)) == 0
    # el 3 de este snapshot no tiene m² construidos: solo llega el 9
    assert [r["listing_key"] for r in read_rows(out, "2026-10-06")] == ["clasipar:9"]


def test_the_folder_name_joins_the_sorted_snapshots() -> None:
    assert out_dir_name([date(2026, 11, 4), date(2026, 10, 6)]) == "2026-10-06_2026-11-04"


def test_a_gazetteer_assigns_barrios_and_barrio_precision(interim: Path, tmp_path: Path) -> None:
    gazetteer = tmp_path / "gazetteer.csv"
    gazetteer.write_text(
        "city,neighborhood,aliases\nluque,Zona Canónica,zona de prueba\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    argv = [
        "--snapshot", "2026-11-04", "--fx-pyg-per-usd", "6085", "--fx-date", "2026-11-04",
        "--fx-source", FX_SOURCE, "--gazetteer", str(gazetteer),
        "--interim-root", str(interim), "--out-root", str(out),
    ]  # fmt: skip
    assert main(argv) == 0
    by_key = {r["listing_key"]: r for r in read_rows(out, "2026-11-04")}
    luque = by_key["clasipar:1"]
    assert (luque["neighborhood"], luque["neighborhood_match"], luque["geo_precision"]) == (
        "Zona Canónica",
        "alias",
        "barrio",
    )
    assert by_key["clasipar:3"]["geo_precision"] == "ciudad"  # Asunción no está en el gazetteer
    report = (out / "2026-11-04" / "quality_report.md").read_text(encoding="utf-8")
    assert "gazetteer.csv" in report


# ------------------------------------------------------------------------------------ reporte


def test_the_funnel_counts_every_discard_by_rule(interim: Path, tmp_path: Path) -> None:
    run(interim, tmp_path / "out")
    report = (tmp_path / "out" / "2026-10-06_2026-11-04" / "quality_report.md").read_text("utf-8")
    for expected in (
        "| líneas leídas | 10 |  | 10 |",
        "| registro_crudo_invalido | 10 | 1 | 9 |",
        "| duplicado_exacto_mismo_source_id | 9 | 1 | 8 |",
        "| ciudad_ausente_o_fuera_de_alcance | 8 | 1 | 7 |",
        "| precio_sin_monto_interpretable | 7 | 1 | 6 |",
        "| sin_m2_construidos | 6 | 1 | 5 |",
        "| outlier_usd_por_m2_minimo | 5 | 1 | 4 |",
        "| **filas en dataset.csv** |  |  | 4 |",
    ):
        assert expected in report, expected
    assert (
        "| operacion_fuera_de_alcance | 8 | 0 | 8 |" in report
    )  # las reglas sin descartes salen en 0


def test_the_funnel_lists_every_rule_in_order(interim: Path, tmp_path: Path) -> None:
    run(interim, tmp_path / "out")
    report = (tmp_path / "out" / "2026-10-06_2026-11-04" / "quality_report.md").read_text("utf-8")
    positions = [report.index(f"| {rule} |") for rule in funnel_rules()]
    assert positions == sorted(positions) and len(positions) == len(set(funnel_rules()))


def test_the_report_has_target_by_type_and_city_neighborhood_clusters_and_origins(
    interim: Path, tmp_path: Path
) -> None:
    run(interim, tmp_path / "out")
    report = (tmp_path / "out" / "2026-10-06_2026-11-04" / "quality_report.md").read_text("utf-8")
    assert "| casa | 6 | 2 | 33,3 % |" in report  # ids 1, 2, 4, 5, 6 y 7 entran; llegan el 1 y el 2
    assert "| departamento | 1 | 1 | 100,0 % |" in report
    assert "| sin_ciudad | 1 | 0 | 0,0 % |" in report
    assert "| casa | sin_ciudad | 1 | 0 | 0,0 % |" in report
    assert "Clusters: 3. Tamaño máximo: 2." in report  # {1, 2}, {3} y {9}
    assert "| 1 | 2 |" in report and "| 2 | 1 |" in report
    assert "| has_pool | 1 | 0 | 3 | 1 | 0 |" in report  # 1 por tag; 0 por regex
    assert "| has_quincho | 0 | 1 | 3 | 0 | 1 |" in report  # "Sin quincho" por regex
    assert "| tag | 3 | 75,0 % |" in report and "| texto | 1 | 25,0 % |" in report
    assert "| con_match" not in report  # sin gazetteer no hay barrios matcheados
    assert "| sin_match: sin_gazetteer" in report or "sin_gazetteer" in report


def test_the_report_states_the_parameters_and_that_garages_is_empty(
    interim: Path, tmp_path: Path
) -> None:
    run(interim, tmp_path / "out")
    report = (tmp_path / "out" / "2026-10-06_2026-11-04" / "quality_report.md").read_text("utf-8")
    assert "6085 PYG por USD, fecha 2026-11-04, fuente: " + FX_SOURCE in report
    assert "2026-10-06 (2 líneas), 2026-11-04 (8 líneas)" in report
    assert "Gazetteer: none. Umbral fuzzy: 90." in report
    assert "`garages` queda vacío en el 100 % de las filas (4 de 4)" in report
    assert "no sirve como feature" in report


def test_the_report_has_no_ad_text_and_no_forbidden_wording(interim: Path, tmp_path: Path) -> None:
    run(interim, tmp_path / "out")
    report = (tmp_path / "out" / "2026-10-06_2026-11-04" / "quality_report.md").read_text("utf-8")
    for text in ("Casa de prueba", "Zona de Prueba", "Departamento de 50", "Sin quincho"):
        assert text not in report
    lowered = report.lower()
    assert "valor de mercado" not in lowered and "precio real" not in lowered
    assert "precio de oferta" in lowered


def test_the_pipeline_sources_never_use_the_forbidden_wording() -> None:
    root = Path(__file__).resolve().parents[2]
    files = [
        *(root / "src" / "avm" / "pipeline").glob("*.py"),
        root / "scripts" / "build_dataset.py",
    ]
    for path in files:
        lowered = path.read_text(encoding="utf-8").lower()
        assert "valor de mercado" not in lowered and "precio real" not in lowered, path.name


def test_an_empty_result_still_renders_the_report(tmp_path: Path) -> None:
    root = tmp_path / "interim"
    write_snapshot(root, "2026-11-04", [line(make_raw("1", price="Consultar"))])
    assert run(root, tmp_path / "out", snapshots=("2026-11-04",)) == 0
    report = (tmp_path / "out" / "2026-11-04" / "quality_report.md").read_text("utf-8")
    assert "| **filas en dataset.csv** |  |  | 0 |" in report
    assert "Clusters: 0. Tamaño máximo: 0." in report
    assert "queda vacío en el 100 %" not in report  # sin filas no hay nada que afirmar
    assert len(read_rows(tmp_path / "out", "2026-11-04")) == 0


def test_contract_rejections_are_reported_by_field_and_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from avm.contract import Listing
    from avm.pipeline import clean

    monkeypatch.setattr(clean, "Listing", lambda **_: Listing.model_validate({}))
    root = tmp_path / "interim"
    write_snapshot(root, "2026-11-04", [line(make_raw("1", built_tag="100"))])
    assert run(root, tmp_path / "out", snapshots=("2026-11-04",)) == 0
    report = (tmp_path / "out" / "2026-11-04" / "quality_report.md").read_text("utf-8")
    assert "| rechazado_por_el_contrato | 1 | 1 | 0 |" in report
    assert "| source:missing | 1 |" in report


# ------------------------------------------------------------------------------------ CLI


def test_a_second_run_does_not_overwrite_the_output(interim: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run(interim, out) == 0
    before = (out / "2026-10-06_2026-11-04" / "dataset.csv").read_bytes()
    assert run(interim, out) == 2
    assert (out / "2026-10-06_2026-11-04" / "dataset.csv").read_bytes() == before


@pytest.mark.parametrize(
    "missing", ["--snapshot", "--fx-pyg-per-usd", "--fx-date", "--fx-source", "--gazetteer"]
)
def test_every_parameter_is_required(missing: str, interim: Path, tmp_path: Path) -> None:
    values = {
        "--snapshot": ["2026-11-04"],
        "--fx-pyg-per-usd": ["6085"],
        "--fx-date": ["2026-11-04"],
        "--fx-source": [FX_SOURCE],
        "--gazetteer": ["none"],
    }
    argv = [token for key, value in values.items() if key != missing for token in (key, *value)]
    with pytest.raises(SystemExit) as error:
        main([*argv, "--interim-root", str(interim), "--out-root", str(tmp_path / "out")])
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--fx-pyg-per-usd", "0"),
        ("--fx-pyg-per-usd", "-5"),
        ("--fx-pyg-per-usd", "abc"),
        ("--fx-pyg-per-usd", "NaN"),
        ("--fx-date", "04/11/2026"),
        ("--fx-source", "   "),
        ("--snapshot", "noviembre"),
    ],
)
def test_invalid_values_are_rejected(flag: str, value: str, interim: Path, tmp_path: Path) -> None:
    args = {
        "--snapshot": "2026-11-04",
        "--fx-pyg-per-usd": "6085",
        "--fx-date": "2026-11-04",
        "--fx-source": FX_SOURCE,
        "--gazetteer": "none",
    }
    args[flag] = value
    argv = [token for pair in args.items() for token in pair]
    with pytest.raises(SystemExit) as error:
        main([*argv, "--interim-root", str(interim), "--out-root", str(tmp_path / "out")])
    assert error.value.code == 2


def test_a_missing_snapshot_or_gazetteer_is_an_argument_error(
    interim: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as error:
        run(interim, tmp_path / "out", snapshots=("2026-12-31",))
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        run(interim, tmp_path / "out2", "--gazetteer", str(tmp_path / "no-existe.csv"))
    assert error.value.code == 2


def test_the_parser_has_no_defaults_for_the_required_parameters() -> None:
    parser = build_parser()
    required = {a.dest for a in parser._actions if a.required}  # noqa: SLF001
    assert required == {"snapshot", "fx_pyg_per_usd", "fx_date", "fx_source", "gazetteer"}


def test_a_row_without_a_cluster_makes_the_build_fail(
    interim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build, "assign_clusters", lambda rows: {})
    params = Params(
        snapshots=(date(2026, 11, 4),),
        fx=FxContext(Decimal(6085), date(2026, 11, 4), FX_SOURCE),
        gazetteer=None,
    )
    with pytest.raises(RuntimeError, match="sin cluster_id"):
        build.run_pipeline(params, interim, build.load_gazetteer(None))
