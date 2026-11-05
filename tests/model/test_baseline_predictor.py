import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from make_synthetic_dataset import main as make_synthetic

from avm.api.app import create_app
from avm.api.config import Settings
from avm.contract import City, PredictionRequest, PredictionResponse, WarningCode
from avm.model.baseline import Baseline
from avm.model.data import IGNORED_FEATURES, load_data
from avm.model.predictor import Predictor
from avm.model.splits import grouped_kfold
from avm.model.training import train_baseline


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline-data")
    data = root / "inputs"
    make_synthetic(["--out", str(data), "--n", "500", "--seed", "7"])
    model = root / "model"
    train_baseline(data / "dataset.csv", data / "geo_features.csv", data / "gazetteer.csv", model)
    return data, model


def test_features_exclude_target_and_provenance_and_fallback(synthetic, tmp_path):
    data, _ = synthetic
    features, _, _ = load_data(data / "dataset.csv", data / "geo_features.csv")
    forbidden = {
        "listing_key",
        "cluster_id",
        "snapshot_date",
        "neighborhood_match",
        "price_usd",
        "built_area_source",
        "advertiser_type",
        "is_sponsored",
        "usd_per_m2",
        "log_usd_per_m2",
        *IGNORED_FEATURES,
    }
    assert not (set(features) & forbidden)
    rows = pd.read_csv(data / "dataset.csv", keep_default_na=False)
    rows.loc[0, "neighborhood"] = "Desconocido"
    dataset = tmp_path / "dataset.csv"
    rows.to_csv(dataset, index=False)
    features, _, _ = load_data(dataset, data / "geo_features.csv")
    assert features.loc[0, "geo_precision"] == "ciudad"
    assert features.loc[0, "neighborhood"] == ""


def test_cluster_duplicates_do_not_dominate_median():
    features = pd.DataFrame(
        {"city": ["luque"] * 12, "property_type": ["casa"] * 12, "neighborhood": [""] * 12}
    )
    model = Baseline(min_clusters=1).fit(features, [1] * 10 + [3, 4], ["a"] * 10 + ["b", "c"])
    assert model.predict(features.iloc[:1])[0] == 3


def test_contract_warnings_aliases_and_defensive_metadata(synthetic):
    _, model_dir = synthetic
    predictor = Predictor.load(model_dir)
    request = PredictionRequest(
        city="luque", property_type="departamento", built_area_m2=120, neighborhood="Desconocido"
    )
    result = predictor.predict(request)
    assert result.total_usd == pytest.approx(result.usd_per_m2 * 120)
    assert result.p_low <= result.usd_per_m2 <= result.p_high
    assert {w.code for w in result.warnings} >= {
        WarningCode.UNKNOWN_NEIGHBORHOOD,
        WarningCode.CITY_FALLBACK,
        WarningCode.LOW_DATA,
    }
    assert predictor.neighborhoods(City.LUQUE)
    predictor.metadata["features"].clear()
    assert predictor.metadata["features"]
    name = predictor.neighborhoods(City.LUQUE)[0]
    request = request.model_copy(update={"neighborhood": name.lower()})
    assert WarningCode.UNKNOWN_NEIGHBORHOOD not in {
        w.code for w in predictor.predict(request).warnings
    }


def test_existing_api_loads_real_predictor_interface(synthetic):
    _, model_dir = synthetic
    with TestClient(create_app(Settings(predictor="model", model_dir=str(model_dir)))) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/predict", json={"city": "luque", "property_type": "casa", "built_area_m2": 120}
        )
        assert response.status_code == 200
        PredictionResponse.model_validate(response.json())


def test_test_targets_do_not_change_fit_or_calibration(synthetic, tmp_path):
    data, model_dir = synthetic
    records = pd.read_csv(data / "dataset.csv", keep_default_na=False)
    split = grouped_kfold(records.cluster_id.to_numpy(), 5, seed=7)[0]
    assert not set(records.iloc[split.train].cluster_id) & set(records.iloc[split.test].cluster_id)
    records.loc[split.test, "log_usd_per_m2"] += 0.2
    changed = tmp_path / "dataset.csv"
    records.to_csv(changed, index=False)
    new_dir = tmp_path / "changed"
    train_baseline(changed, data / "geo_features.csv", data / "gazetteer.csv", new_dir)
    for name in ["model.json", "calibration.json"]:
        assert json.loads((model_dir / name).read_text(encoding="utf-8")) == json.loads(
            (new_dir / name).read_text(encoding="utf-8")
        )
    with pytest.raises(FileExistsError):
        train_baseline(changed, data / "geo_features.csv", data / "gazetteer.csv", new_dir)


def test_calibration_never_leaks_clusters(synthetic):
    data, _ = synthetic
    _, _, groups = load_data(data / "dataset.csv", data / "geo_features.csv")
    outer = grouped_kfold(groups, 5, seed=7)[0]
    inner = grouped_kfold(groups[outer.train], 4, seed=8)[0]
    assert not set(groups[outer.train[inner.train]]) & set(groups[outer.train[inner.test]])
    assert np.intersect1d(outer.train[inner.test], outer.test).size == 0
