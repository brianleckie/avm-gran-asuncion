"""Tests de las métricas de evaluación (F10.1).

Los valores de referencia están calculados a mano en los comentarios, no con las propias funciones.
Convenciones bajo prueba: los resultados son fracciones (0,12 = 12 %), las magnitudes son precios
positivos en unidades naturales y toda entrada inválida levanta ValueError (nunca un resultado
silencioso).
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from avm.model.metrics import mape, mdape, pe_within, rmse_log

# --------------------------------------------------------------------------------------------
# Ejemplo principal, calculado a mano
#
#   y_true = [100, 200, 400, 800]        y_pred = [125, 150, 400, 600]
#
#   Errores relativos |ŷ − y| / y = [25/100, 50/200, 0/400, 200/800] = [0,25; 0,25; 0; 0,25]
#   (0,25 es exacto en binario: el borde "≤ tol" no depende del redondeo de punto flotante.)
#
#   MAPE  = (0,25 + 0,25 + 0 + 0,25) / 4 = 0,75 / 4 = 0,1875
#   MdAPE = mediana de [0; 0,25; 0,25; 0,25] = (0,25 + 0,25) / 2 = 0,25
#   PE(tol=0,25) = 4/4 = 1       (borde inclusivo: los tres errores de 0,25 cuentan)
#   PE(tol=0,20) = 1/4 = 0,25    (solo el error 0)
#   PE(tol=0)    = 1/4 = 0,25    (solo la predicción exacta)
#
#   Errores en log: ln(125/100) = ln 1,25 = 0,22314355131;  ln(150/200) = ln 0,75 = −0,28768207245;
#   ln(400/400) = 0;  ln(600/800) = ln 0,75.
#   Cuadrados: 0,04979304449; 0,08276097481; 0; 0,08276097481.
#   Media de cuadrados = (0,04979304449 + 0,08276097481 + 0 + 0,08276097481) / 4 = 0,05382874853
#   rmse_log = √0,05382874853 = 0,23201023367
# --------------------------------------------------------------------------------------------
Y_TRUE = [100, 200, 400, 800]
Y_PRED = [125, 150, 400, 600]


def test_mape_hand_computed():
    assert mape(Y_TRUE, Y_PRED) == pytest.approx(0.1875, abs=1e-12)


def test_mdape_hand_computed():
    assert mdape(Y_TRUE, Y_PRED) == pytest.approx(0.25, abs=1e-12)


@pytest.mark.parametrize(("tol", "expected"), [(0.25, 1.0), (0.20, 0.25), (0.0, 0.25), (1, 1.0)])
def test_pe_within_hand_computed(tol, expected):
    assert pe_within(Y_TRUE, Y_PRED, tol) == pytest.approx(expected, abs=1e-12)


def test_rmse_log_hand_computed():
    assert rmse_log(Y_TRUE, Y_PRED) == pytest.approx(0.23201023367, abs=1e-10)


# Un solo punto, cuenta directa: y = 100, ŷ = 50 → error relativo |50 − 100| / 100 = 0,5 y
# error en log |ln(50) − ln(100)| = ln 2 = 0,69314718056.
def test_single_observation_hand_computed():
    assert mape([100], [50]) == pytest.approx(0.5, abs=1e-12)
    assert mdape([100], [50]) == pytest.approx(0.5, abs=1e-12)
    assert pe_within([100], [50], 0.5) == 1.0
    assert pe_within([100], [50], 0.49) == 0.0
    assert rmse_log([100], [50]) == pytest.approx(0.69314718056, abs=1e-10)


# El MAPE es asimétrico: una subestimación pesa a lo sumo 100 %, una sobreestimación no tiene
# tope. y = 100: ŷ = 1 → |1 − 100| / 100 = 0,99;  ŷ = 1000 → |1000 − 100| / 100 = 9.
def test_mape_is_asymmetric_between_under_and_overestimation():
    assert mape([100], [1]) == pytest.approx(0.99, abs=1e-12)
    assert mape([100], [1000]) == pytest.approx(9.0, abs=1e-12)


# La mediana no se mueve con un error enorme; la media sí. Errores [0,1; 0,1; 0,1; 50]:
# MdAPE = 0,1;  MAPE = (0,3 + 50) / 4 = 12,575.
def test_mdape_is_robust_to_one_huge_error_and_mape_is_not():
    y_true = [100, 100, 100, 100]
    y_pred = [110, 110, 110, 5100]
    assert mdape(y_true, y_pred) == pytest.approx(0.1, abs=1e-12)
    assert mape(y_true, y_pred) == pytest.approx(12.575, abs=1e-12)


def test_perfect_prediction_gives_zero_error_and_full_pe():
    values = [95_000.0, 120_500.5, 310_000.0]
    assert mape(values, values) == 0.0
    assert mdape(values, values) == 0.0
    assert rmse_log(values, values) == 0.0
    assert pe_within(values, values, 0.0) == 1.0


@pytest.mark.parametrize("container", [list, tuple, np.array])
def test_accepts_any_array_like_and_returns_python_float(container):
    result = mape(container(Y_TRUE), container(Y_PRED))
    assert type(result) is float
    assert result == pytest.approx(0.1875, abs=1e-12)


# --------------------------------------------------------------------------------------------
# Validación de entradas: error explícito, nunca un resultado silencioso
# --------------------------------------------------------------------------------------------

# (y_true, y_pred, patrón del mensaje)
INVALID_PAIRS = [
    pytest.param([1, 2, 3], [1, 2], "mismo largo", id="largos distintos"),
    pytest.param([], [], "vacío", id="vacío"),
    pytest.param([[1, 2], [3, 4]], [[1, 2], [3, 4]], "1-D", id="2-D"),
    pytest.param([1, np.nan], [1, 2], "y_true.*NaN", id="NaN en y_true"),
    pytest.param([1, 2], [1, np.nan], "y_pred.*NaN", id="NaN en y_pred"),
    pytest.param([1, np.inf], [1, 2], "y_true.*infinitos", id="inf en y_true"),
    pytest.param([1, 2], [1, -np.inf], "y_pred.*infinitos", id="-inf en y_pred"),
    pytest.param([1, None], [1, 2], "y_true.*NaN", id="None en y_true"),
    pytest.param([0, 2], [1, 2], "y_true.*> 0", id="y_true cero"),
    pytest.param([-1, 2], [1, 2], "y_true.*> 0", id="y_true negativo"),
    pytest.param([1, 2], [0, 2], "y_pred.*> 0", id="y_pred cero"),
    pytest.param([1, 2], [1, -2], "y_pred.*> 0", id="y_pred negativo"),
    pytest.param(["a", "b"], [1, 2], "números", id="texto"),
]


@pytest.mark.parametrize(("y_true", "y_pred", "message"), INVALID_PAIRS)
@pytest.mark.parametrize("metric", [mape, mdape, rmse_log])
def test_invalid_inputs_raise_value_error(metric, y_true, y_pred, message):
    with pytest.raises(ValueError, match=message):
        metric(y_true, y_pred)


@pytest.mark.parametrize(("y_true", "y_pred", "message"), INVALID_PAIRS)
def test_pe_within_validates_the_pair_too(y_true, y_pred, message):
    with pytest.raises(ValueError, match=message):
        pe_within(y_true, y_pred, 0.1)


@pytest.mark.parametrize("tol", [-0.1, np.nan, np.inf, -np.inf, "diez", None])
def test_pe_within_rejects_invalid_tolerance(tol):
    with pytest.raises(ValueError, match="tol"):
        pe_within(Y_TRUE, Y_PRED, tol)


@pytest.mark.parametrize("metric", [mape, mdape])
def test_overflowing_result_is_an_error_not_an_inf(metric):
    # |1e300 − 1e-300| / 1e-300 desborda a inf: se rechaza en vez de devolver inf.
    with pytest.raises(ValueError, match="no finito"):
        metric([1e-300], [1e300])


# --------------------------------------------------------------------------------------------
# Property tests (hypothesis)
# --------------------------------------------------------------------------------------------

PRICES = st.floats(min_value=1e-3, max_value=1e9, allow_nan=False, allow_infinity=False)


@st.composite
def price_pairs(draw):
    """Dos listas de precios positivos del mismo largo."""
    n = draw(st.integers(min_value=1, max_value=30))
    y_true = draw(st.lists(PRICES, min_size=n, max_size=n))
    y_pred = draw(st.lists(PRICES, min_size=n, max_size=n))
    return y_true, y_pred


@given(pair=price_pairs())
def test_error_metrics_are_never_negative_and_always_finite(pair):
    y_true, y_pred = pair
    for metric in (mape, mdape, rmse_log):
        value = metric(y_true, y_pred)
        assert np.isfinite(value)
        assert value >= 0.0


@given(pair=price_pairs(), tolerances=st.tuples(st.floats(0, 50), st.floats(0, 50)))
def test_pe_within_is_monotone_in_the_tolerance_and_bounded(pair, tolerances):
    y_true, y_pred = pair
    low_tol, high_tol = sorted(tolerances)
    low = pe_within(y_true, y_pred, low_tol)
    high = pe_within(y_true, y_pred, high_tol)
    assert 0.0 <= low <= high <= 1.0


@given(values=st.lists(PRICES, min_size=1, max_size=30))
def test_a_perfect_prediction_is_error_free(values):
    assert mape(values, values) == 0.0
    assert mdape(values, values) == 0.0
    assert rmse_log(values, values) == 0.0
    assert pe_within(values, values, 0.0) == 1.0
