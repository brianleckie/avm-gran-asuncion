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

from avm.model.metrics import (
    interval_coverage,
    mape,
    mdape,
    mean_interval_width,
    pe_within,
    rmse_log,
)

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


# --------------------------------------------------------------------------------------------
# Intervalos de predicción: cobertura y ancho
#
# Ejemplo calculado a mano:
#   y    = [10, 20, 30, 40]
#   low  = [ 8, 22, 25, 35]
#   high = [12, 30, 35, 38]
#
#   10 ∈ [8, 12] sí;  20 ∈ [22, 30] no (queda debajo de low);  30 ∈ [25, 35] sí;
#   40 ∈ [35, 38] no (queda arriba de high)  →  cobertura = 2/4 = 0,5
#
#   Anchos high − low = [4, 8, 10, 3]  →  ancho medio absoluto = 25 / 4 = 6,25
#   Relativos a ŷ = y: [4/10, 8/20, 10/30, 3/40] = [0,4; 0,4; 0,3333…; 0,075]
#                  →  ancho medio relativo = 1,2083333… / 4 = 0,30208333…
# --------------------------------------------------------------------------------------------
Y = [10, 20, 30, 40]
LOW = [8, 22, 25, 35]
HIGH = [12, 30, 35, 38]


def test_interval_coverage_hand_computed():
    assert interval_coverage(Y, LOW, HIGH) == pytest.approx(0.5, abs=1e-12)


def test_mean_interval_width_absolute_hand_computed():
    assert mean_interval_width(LOW, HIGH) == pytest.approx(6.25, abs=1e-12)


def test_mean_interval_width_relative_hand_computed():
    result = mean_interval_width(LOW, HIGH, Y, relative=True)
    assert result == pytest.approx(0.30208333333, abs=1e-10)


def test_interval_bounds_are_inclusive_and_zero_width_is_allowed():
    # y igual a low o a high cuenta como cubierto; un intervalo de ancho 0 sobre y también.
    assert interval_coverage([10, 20], [10, 15], [12, 20]) == 1.0
    assert interval_coverage([10], [10], [10]) == 1.0
    assert mean_interval_width([10], [10]) == 0.0


def test_interval_bounds_do_not_need_to_be_positive():
    # Solo y (un precio) debe ser > 0: un límite inferior <= 0 es un problema del modelo que no
    # se esconde rechazando la entrada. y = [5, 5]: 5 ∈ [−3, 6] sí; 5 ∈ [−10, 4] no → 0,5.
    assert interval_coverage([5, 5], [-3, -10], [6, 4]) == pytest.approx(0.5, abs=1e-12)
    # Anchos: 6 − (−3) = 9 y 4 − (−10) = 14 → (9 + 14) / 2 = 11,5.
    assert mean_interval_width([-3, -10], [6, 4]) == pytest.approx(11.5, abs=1e-12)


# (y, low, high, patrón del mensaje)
INVALID_COVERAGE = [
    pytest.param([1, 2, 3], [1, 2], [2, 3], "mismo largo", id="y y low de distinto largo"),
    pytest.param([1, 2], [1, 2], [2, 3, 4], "mismo largo", id="low y high de distinto largo"),
    pytest.param([], [], [], "vacío", id="vacío"),
    pytest.param([[1], [2]], [[1], [2]], [[2], [3]], "1-D", id="2-D"),
    pytest.param([1, np.nan], [1, 2], [2, 3], "y.*NaN", id="NaN en y"),
    pytest.param([1, 2], [1, np.nan], [2, 3], "low.*NaN", id="NaN en low"),
    pytest.param([1, 2], [1, 2], [2, np.inf], "high.*infinitos", id="inf en high"),
    pytest.param([0, 2], [1, 2], [2, 3], "y.*> 0", id="y cero"),
    pytest.param([-1, 2], [1, 2], [2, 3], "y.*> 0", id="y negativo"),
    pytest.param([1, 2], [3, 2], [2, 3], "low.*<= high", id="low mayor que high"),
]


@pytest.mark.parametrize(("y", "low", "high", "message"), INVALID_COVERAGE)
def test_interval_coverage_rejects_invalid_inputs(y, low, high, message):
    with pytest.raises(ValueError, match=message):
        interval_coverage(y, low, high)


@pytest.mark.parametrize(
    ("low", "high", "message"),
    [
        pytest.param([1, 2], [2, 3, 4], "mismo largo", id="largos distintos"),
        pytest.param([], [], "vacío", id="vacío"),
        pytest.param([np.nan, 2], [2, 3], "low.*NaN", id="NaN"),
        pytest.param([3, 2], [2, 3], "low.*<= high", id="low mayor que high"),
    ],
)
def test_mean_interval_width_rejects_invalid_intervals(low, high, message):
    with pytest.raises(ValueError, match=message):
        mean_interval_width(low, high)


def test_relative_width_requires_a_valid_prediction():
    with pytest.raises(ValueError, match="relative=True requiere y_pred"):
        mean_interval_width(LOW, HIGH, relative=True)
    with pytest.raises(ValueError, match="y_pred.*mismo largo"):
        mean_interval_width(LOW, HIGH, [10, 20, 30], relative=True)
    with pytest.raises(ValueError, match="y_pred.*> 0"):
        mean_interval_width(LOW, HIGH, [10, 20, 0, 40], relative=True)
    with pytest.raises(ValueError, match="y_pred.*NaN"):
        mean_interval_width(LOW, HIGH, [10, 20, np.nan, 40], relative=True)


def test_y_pred_without_relative_is_an_error_not_silently_ignored():
    with pytest.raises(ValueError, match="y_pred solo se usa con relative=True"):
        mean_interval_width(LOW, HIGH, Y)


@pytest.mark.parametrize("relative", [False, True])
def test_overflowing_width_is_an_error_not_an_inf(relative):
    # high − low = 2e308 desborda a inf.
    kwargs = {"y_pred": [1.0], "relative": True} if relative else {}
    with pytest.raises(ValueError, match="no finito"):
        mean_interval_width([-1e308], [1e308], **kwargs)


# --------------------------------------------------------------------------------------------
# Property tests (hypothesis): intervalos
# --------------------------------------------------------------------------------------------


@st.composite
def interval_cases(draw):
    """y positivos con intervalos válidos (low <= high), del mismo largo."""
    n = draw(st.integers(min_value=1, max_value=30))
    y = draw(st.lists(PRICES, min_size=n, max_size=n))
    ends = draw(st.lists(st.tuples(PRICES, PRICES), min_size=n, max_size=n))
    low = [min(a, b) for a, b in ends]
    high = [max(a, b) for a, b in ends]
    return y, low, high


@given(case=interval_cases())
def test_coverage_is_a_fraction_and_widths_are_never_negative(case):
    y, low, high = case
    assert 0.0 <= interval_coverage(y, low, high) <= 1.0
    assert mean_interval_width(low, high) >= 0.0
    assert mean_interval_width(low, high, y, relative=True) >= 0.0


@given(case=interval_cases(), margin=st.floats(min_value=0.0, max_value=1e6))
def test_widening_every_interval_never_lowers_coverage(case, margin):
    y, low, high = case
    wider_low = [value - margin for value in low]
    wider_high = [value + margin for value in high]
    assert interval_coverage(y, wider_low, wider_high) >= interval_coverage(y, low, high)


@given(values=st.lists(PRICES, min_size=1, max_size=30))
def test_zero_width_intervals_on_y_cover_everything_with_zero_width(values):
    assert interval_coverage(values, values, values) == 1.0
    assert mean_interval_width(values, values) == 0.0
    assert mean_interval_width(values, values, values, relative=True) == 0.0
