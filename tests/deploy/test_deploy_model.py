"""Tests de la guardia de deploy/model/ (ADR-008).

Con archivos sintéticos en `tmp_path` se prueba que la guardia detecta cada forma de aviso, y si
`deploy/model/` existe en el repo se la corre sobre el real (el CI falla si se cuela algo).
"""

import json
from pathlib import Path

import check_deploy_model as guard
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

GAZETTEER = (
    "city,neighborhood,aliases,lat,lon,centroid_method,osm_id,source\n"
    "asuncion,Villa Morra,villa morra|v. morra,-25.2860,-57.5780,osm_polygon,123456,OSM\n"
)
GEO_FEATURES = (
    "city,neighborhood,geo_precision,dist_cbd_km,n_school_1km\n"
    "asuncion,Villa Morra,barrio,4.2,7\n"
    "asuncion,,ciudad,5.0,3\n"
)
METADATA = {
    "model_version": "2026-11-06-baseline",
    "contract_version": "0.1",
    "snapshot_date": "2026-11-04",
    "trained_at": "2026-11-06T10:00:00",
    "n_train": 100,
    "features": ["city", "built_area_m2", "dist_cbd_km"],
    "coverage_nominal": 0.8,
}


def _good_dir(base: Path) -> Path:
    model_dir = base / "model"
    model_dir.mkdir()
    (model_dir / "gazetteer.csv").write_text(GAZETTEER, encoding="utf-8")
    (model_dir / "geo_features.csv").write_text(GEO_FEATURES, encoding="utf-8")
    (model_dir / "metadata.json").write_text(json.dumps(METADATA), encoding="utf-8")
    (model_dir / "calibration.json").write_text(json.dumps({"q_hat": 0.12}), encoding="utf-8")
    (model_dir / "model.txt").write_text("tree\nversion=v4\nsplit_feature=0\n", encoding="utf-8")
    (model_dir / "ATTRIBUTION.md").write_text("© OpenStreetMap contributors\n", encoding="utf-8")
    return model_dir


def test_valid_artifact_passes(tmp_path: Path) -> None:
    assert guard.check_dir(_good_dir(tmp_path)) == []


def test_extra_file_is_rejected(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "dataset.csv").write_text("listing_key,price_usd\n", encoding="utf-8")
    (model_dir / "model.csv").write_text("a,b\n", encoding="utf-8")
    problems = guard.check_dir(model_dir)
    assert any("dataset.csv" in p for p in problems)
    assert any("model.csv" in p for p in problems)


def test_subdirectory_is_rejected(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "2026-11-06-baseline").mkdir()
    assert any("subcarpetas" in p for p in guard.check_dir(model_dir))


@pytest.mark.parametrize("column", ["listing_key", "source_id", "title", "price_usd", "cluster_id"])
def test_listing_columns_in_csv_are_rejected(tmp_path: Path, column: str) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "geo_features.csv").write_text(
        f"city,neighborhood,geo_precision,{column}\nasuncion,,ciudad,x\n", encoding="utf-8"
    )
    assert any("columnas fuera de la interfaz" in p for p in guard.check_dir(model_dir))


def test_gazetteer_extra_column_is_rejected(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "gazetteer.csv").write_text(
        "city,neighborhood,description\nluque,Centro,algo\n", encoding="utf-8"
    )
    assert any("columnas fuera de la interfaz" in p for p in guard.check_dir(model_dir))


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("https://clasipar.com.py/aviso/123", "URL"),
        ("www.sitio.com.py", "URL"),
        ("contacto@ejemplo.com", "email"),
        ("0981 123 456", "teléfono"),
        ("+595 981 123456", "teléfono"),
        ("clasipar:12345", "listing_key"),
        ("x" * (guard.MAX_TEXT_CHARS + 1), "caracteres"),
    ],
)
def test_suspicious_csv_cells_are_rejected(tmp_path: Path, value: str, fragment: str) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "gazetteer.csv").write_text(
        f"city,neighborhood,aliases\nluque,Centro,{value}\n", encoding="utf-8"
    )
    assert any(fragment in p for p in guard.check_dir(model_dir))


def test_numbers_in_csv_are_not_mistaken_for_phones(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "gazetteer.csv").write_text(
        "city,neighborhood,lat,lon,osm_id\nluque,Centro,-25.26370000,-57.57590000,0981123456\n",
        encoding="utf-8",
    )
    assert guard.check_dir(model_dir) == []


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"listing_key": "x"}, "clave prohibida"),
        ({"nested": {"source_id": 1}}, "clave prohibida"),
        ({"note": "ver https://ejemplo.com"}, "URL"),
        ({"examples": ["clasipar:999"]}, "listing_key"),
        ({"note": "y" * (guard.MAX_TEXT_CHARS + 1)}, "caracteres"),
    ],
)
def test_suspicious_json_is_rejected(
    tmp_path: Path, patch: dict[str, object], fragment: str
) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "metadata.json").write_text(json.dumps({**METADATA, **patch}), encoding="utf-8")
    assert any(fragment in p for p in guard.check_dir(model_dir))


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "calibration.json").write_text("{no es json", encoding="utf-8")
    assert any("JSON" in p for p in guard.check_dir(model_dir))


def test_text_model_with_contact_data_is_rejected(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "model.txt").write_text('tree\npandas_categorical:["a@b.com"]\n', encoding="utf-8")
    assert any("model.txt línea 2" in p and "email" in p for p in guard.check_dir(model_dir))


def test_binary_model_is_allowed_by_name_only(tmp_path: Path) -> None:
    model_dir = _good_dir(tmp_path)
    (model_dir / "model.txt").unlink()
    (model_dir / "model.joblib").write_bytes(b"\x80\x04\x95binario")
    assert guard.check_dir(model_dir) == []


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main([str(tmp_path / "no-existe")]) == 0
    assert "no existe" in capsys.readouterr().out
    model_dir = _good_dir(tmp_path)
    assert guard.main([str(model_dir)]) == 0
    (model_dir / "extra.csv").write_text("a\n", encoding="utf-8")
    assert guard.main([str(model_dir)]) == 1
    assert "NO se puede publicar" in capsys.readouterr().out


def test_deploy_model_in_repo_is_publishable() -> None:
    """Si deploy/model/ existe en el repo, tiene que pasar la guardia."""
    model_dir = REPO_ROOT / "deploy" / "model"
    if not model_dir.is_dir():
        pytest.skip("deploy/model/ no existe: todavía no hay modelo publicado")
    assert guard.check_dir(model_dir) == []
