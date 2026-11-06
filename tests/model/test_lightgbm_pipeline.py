import gzip
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from make_synthetic_dataset import main as make_synthetic

from avm.api.app import create_app
from avm.api.config import Settings
from avm.contract import PredictionRequest, PredictionResponse, WarningCode
from avm.model.data import load_data
from avm.model.experiment import train_lightgbm
from avm.model.lgbm import QuantileModel
from avm.model.predictor import Predictor
from avm.model.splits import grouped_kfold


@pytest.fixture(scope="module")
def synthetic_lgbm(tmp_path_factory):
    root = tmp_path_factory.mktemp("lgbm-data")
    data = root / "inputs"
    make_synthetic(["--out", str(data), "--n", "700", "--seed", "7"])
    model = root / "model"
    train_lightgbm(
        data / "dataset.csv",
        data / "geo_features.csv",
        data / "gazetteer.csv",
        model,
        dataset_version="synthetic",
    )
    return data, model


def test_schema_is_train_only_and_ablation_excludes_numeric_geo():
    frame = pd.DataFrame(
        {
            "city": ["luque"],
            "neighborhood": ["A"],
            "property_type": ["casa"],
            "geo_precision": ["barrio"],
            "built_area_m2": [120],
            "dist_cbd_km": [1],
            "n_school_1km": [2],
        }
    )
    model = QuantileModel(with_geo=False)
    model.fit_schema(frame)
    test = frame.copy()
    test.loc[0, "neighborhood"] = "Unseen"
    encoded = model.transform(test)
    assert encoded.neighborhood.isna().all()
    assert model.categories["neighborhood"] == ["A"]
    assert not any(c.startswith(("dist_", "n_")) for c in encoded)
    assert {"city", "neighborhood", "geo_precision"}.issubset(encoded)


def test_roundtrip_segmented_intervals_and_api(synthetic_lgbm):
    _, model_dir = synthetic_lgbm
    predictor = Predictor.load(model_dir)
    assert set(predictor.calibration["segments"]) == {"casa", "departamento", "duplex"}
    assert predictor.metadata["is_test_model"] is True
    for kind in ["casa", "departamento", "duplex"]:
        response = predictor.predict(
            PredictionRequest(
                city="luque", property_type=kind, neighborhood="Unknown", built_area_m2=120
            )
        )
        assert response.total_usd == pytest.approx(response.usd_per_m2 * 120)
        assert response.p_low <= response.usd_per_m2 <= response.p_high
        assert WarningCode.UNKNOWN_NEIGHBORHOOD in {w.code for w in response.warnings}
    with TestClient(create_app(Settings(predictor="model", model_dir=str(model_dir)))) as client:
        result = client.post(
            "/predict", json={"city": "luque", "property_type": "casa", "built_area_m2": 100}
        )
        assert result.status_code == 200
        PredictionResponse.model_validate(result.json())
    with (
        pytest.raises(RuntimeError, match="modelo de prueba"),
        TestClient(
            create_app(Settings(predictor="model", model_dir=str(model_dir), env="production"))
        ),
    ):
        pass


def test_quantile_roundtrip_and_no_test_target_leakage(synthetic_lgbm, tmp_path):
    data, model_dir = synthetic_lgbm
    frame, _, groups = load_data(data / "dataset.csv", data / "geo_features.csv")
    model = QuantileModel.load(model_dir / "model.bin")
    point, low, high = model.interval(frame.iloc[:8])
    assert np.all(low <= point) and np.all(point <= high)
    records = pd.read_csv(data / "dataset.csv", keep_default_na=False)
    test = grouped_kfold(groups, 5, seed=7)[0].test
    records.loc[test, "log_usd_per_m2"] += 0.2
    changed = tmp_path / "dataset.csv"
    records.to_csv(changed, index=False)
    new_model = tmp_path / "changed-model"
    train_lightgbm(changed, data / "geo_features.csv", data / "gazetteer.csv", new_model)
    assert json.loads(gzip.decompress((new_model / "model.bin").read_bytes())) == json.loads(
        gzip.decompress((model_dir / "model.bin").read_bytes())
    )
    assert (new_model / "calibration.json").read_text() == (
        model_dir / "calibration.json"
    ).read_text()
    loaded = QuantileModel.load(new_model / "model.bin")
    assert loaded.predict(frame.iloc[:8]) == pytest.approx(point)
