"""El generador sintético respeta docs/interfaces.md (I1-I3) y es reproducible."""

import csv
import math

import pytest
from make_synthetic_dataset import DATASET_COLUMNS, main


def _read(path):
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_shapes_and_invariants(tmp_path):
    main(["--out", str(tmp_path), "--n", "500", "--seed", "1"])
    rows = _read(tmp_path / "dataset.csv")
    assert len(rows) == 500
    assert list(rows[0]) == DATASET_COLUMNS
    geo = {(g["city"], g["neighborhood"]) for g in _read(tmp_path / "geo_features.csv")}
    for r in rows:  # todo aviso tiene features geo (de barrio o de ciudad)
        assert (r["city"], r["neighborhood"]) in geo
        usd_m2 = float(r["price_usd"]) / float(r["built_area_m2"])
        assert math.isclose(usd_m2, float(r["usd_per_m2"]), rel_tol=1e-3)
        assert (r["geo_precision"] == "ciudad") == (r["neighborhood"] == "")
    assert any(r["has_pool"] == "" for r in rows)  # el tri-estado aparece


def test_same_seed_same_output(tmp_path):
    main(["--out", str(tmp_path / "a"), "--n", "200", "--seed", "3"])
    main(["--out", str(tmp_path / "b"), "--n", "200", "--seed", "3"])
    assert (tmp_path / "a/dataset.csv").read_bytes() == (tmp_path / "b/dataset.csv").read_bytes()


def test_never_overwrites(tmp_path):
    main(["--out", str(tmp_path), "--n", "50", "--seed", "1"])
    with pytest.raises(FileExistsError):
        main(["--out", str(tmp_path), "--n", "50", "--seed", "1"])
