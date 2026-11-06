import numpy as np
import pytest

from avm.model.conformal import apply_by_type, calibrate_by_type


def test_segmented_quantile_rank_and_cluster_maximum():
    target = np.r_[np.arange(10), np.arange(10) / 10]
    types = ["casa"] * 10 + ["departamento"] * 10
    groups = [str(i) for i in range(10)] * 2
    result = calibrate_by_type(target, np.zeros(20), np.zeros(20), types, groups)
    assert result["segments"]["casa"]["qhat"] == 8
    assert result["segments"]["departamento"]["qhat"] == pytest.approx(0.8)
    assert result["segments"]["casa"]["rank"] == 9
    duplicated = calibrate_by_type(
        np.r_[target, [100] * 30],
        np.zeros(50),
        np.zeros(50),
        types + ["casa"] * 30,
        groups + ["0"] * 30,
    )
    assert duplicated["segments"]["casa"]["n_clusters"] == 10
    assert duplicated["segments"]["casa"]["qhat"] == 9
    lower, upper = apply_by_type([0, 0], [1, 1], ["casa", "departamento"], result)
    assert lower.tolist() == pytest.approx([-8, -0.8])
    assert upper.tolist() == pytest.approx([9, 1.8])


def test_small_segment_and_missing_type_fail_explicitly():
    with pytest.raises(ValueError, match="insuficiente"):
        calibrate_by_type([1], [0], [0], ["casa"], ["a"])
    with pytest.raises(ValueError, match="No hay calibración"):
        apply_by_type([0], [1], ["duplex"], {"segments": {}})
    with pytest.raises(ValueError, match="inválidos"):
        calibrate_by_type([np.nan], [0], [1], ["casa"], ["a"])
