"""Métricas de evaluación del AVM (F10.1).

Convenciones (valen para todas las funciones):
- Las magnitudes (`y_true`, `y_pred`) son precios de oferta en unidades naturales (USD o USD/m²),
  nunca logaritmos: `rmse_log` aplica el logaritmo adentro. Deben ser finitas y estrictamente
  positivas.
- Los resultados son fracciones, no porcentajes: 0,12 significa 12 %. La tolerancia de `pe_within`
  también: PE10 es `tol=0.10`.
- Toda entrada inválida (largos distintos, vacío, no 1-D, NaN o infinitos, valores no positivos)
  levanta ValueError con un mensaje explícito. Un resultado que desborda a infinito también se
  rechaza: nunca se devuelve un número engañoso.
- Solo numpy. Los resultados son `float` de Python.

Estas métricas miden qué tan bien se predice el precio de oferta publicado (ADR-001), no un precio
de cierre.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]

# Margen relativo para que un error que en teoría vale exactamente `tol` no quede afuera por el
# redondeo de punto flotante: |0,77 − 0,7| / 0,7 da 0,10000000000000009 y no 0,1. Es mucho menor
# que cualquier diferencia real entre precios, así que no admite errores realmente mayores.
_PE_ROUNDING_SLACK = 1e-12


# --------------------------------------------------------------------------------------------
# Validación de entradas
# --------------------------------------------------------------------------------------------


def _as_1d_float(values: ArrayLike, name: str) -> FloatArray:
    """Convierte a un array 1-D de floats, no vacío y sin NaN ni infinitos."""
    try:
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: no se puede convertir a números ({exc})") from exc
    if array.ndim != 1:
        raise ValueError(f"{name}: debe ser 1-D, tiene {array.ndim} dimensiones")
    if array.size == 0:
        raise ValueError(f"{name}: no puede estar vacío")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name}: contiene NaN o infinitos")
    return array


def _require_positive(array: FloatArray, name: str) -> None:
    if not np.all(array > 0):
        raise ValueError(f"{name}: todos los valores deben ser > 0")


def _validate_prices(y_true: ArrayLike, y_pred: ArrayLike) -> tuple[FloatArray, FloatArray]:
    true = _as_1d_float(y_true, "y_true")
    pred = _as_1d_float(y_pred, "y_pred")
    if true.shape != pred.shape:
        raise ValueError(
            f"y_true e y_pred deben tener el mismo largo (recibidos {true.size} y {pred.size})"
        )
    _require_positive(true, "y_true")
    _require_positive(pred, "y_pred")
    return true, pred


def _validate_tolerance(tol: float) -> float:
    try:
        value = float(tol)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tol: no se puede convertir a número ({tol!r})") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"tol: debe ser un número finito >= 0 (recibido {tol!r})")
    return value


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name}: resultado no finito (desborde numérico con estas magnitudes)")
    return value


def _relative_errors(true: FloatArray, pred: FloatArray) -> FloatArray:
    """|ŷ − y| / y por observación. Un desborde queda como inf y lo rechaza `_finite`."""
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        return np.abs(pred - true) / true


# --------------------------------------------------------------------------------------------
# Métricas de error de punto
# --------------------------------------------------------------------------------------------


def mape(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Error porcentual absoluto medio (fracción, no porcentaje).

    Definición: MAPE = (1/n) · Σ |ŷᵢ − yᵢ| / yᵢ.

    Por qué se usa en AVMs: es el error relativo promedio, así que permite comparar propiedades
    baratas y caras, cosa que el error absoluto en USD no permite.

    Cuidado: es sensible a unas pocas observaciones con error muy grande y es asimétrico (una
    subestimación pesa a lo sumo 1, es decir 100 %, mientras que una sobreestimación no tiene
    tope). Conviene reportarla como métrica secundaria y usar `mdape` como métrica titular.
    """
    true, pred = _validate_prices(y_true, y_pred)
    with np.errstate(all="ignore"):
        result = float(np.mean(_relative_errors(true, pred)))
    return _finite(result, "mape")


def mdape(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mediana del error porcentual absoluto (fracción, no porcentaje).

    Definición: MdAPE = mediana de { |ŷᵢ − yᵢ| / yᵢ }.

    Por qué se usa en AVMs: resume el error típico sin que lo arrastren unos pocos avisos mal
    publicados o con errores de tipeo, como los que F4.6 prevé detectar. La mitad de las
    estimaciones tiene un error relativo menor o igual que este valor.
    """
    true, pred = _validate_prices(y_true, y_pred)
    with np.errstate(all="ignore"):
        result = float(np.median(_relative_errors(true, pred)))
    return _finite(result, "mdape")


def pe_within(y_true: ArrayLike, y_pred: ArrayLike, tol: float) -> float:
    """Fracción de predicciones dentro de ±tol del precio publicado (PE, "percent error").

    Definición: PE(tol) = (1/n) · #{ i : |ŷᵢ − yᵢ| / yᵢ ≤ tol }. `tol` es una fracción (PE10:
    `tol=0.10`; PE20: `tol=0.20`) y debe ser finita y >= 0. El resultado está en [0, 1] y no
    decrece cuando `tol` aumenta.

    El borde es inclusivo también en punto flotante: la comparación admite un margen relativo de
    1e-12 sobre `tol`, para que un error que en teoría vale exactamente `tol` no quede afuera por
    redondeo (con floats, |0,77 − 0,7| / 0,7 da 0,10000000000000009 y no 0,1). El margen es
    órdenes de magnitud menor que cualquier diferencia real entre precios.

    Por qué se usa en AVMs: responde la pregunta que entiende el usuario final ("¿qué fracción
    de las estimaciones cae dentro de ±10 % o ±20 % del precio publicado?"), y no la distorsionan
    unas pocas observaciones con error enorme. PE10 y PE20 son los nombres que usa el ROADMAP
    (F10.1); que además sean una convención de la industria de valuación automatizada: [referencia
    a verificar].
    """
    true, pred = _validate_prices(y_true, y_pred)
    tolerance = _validate_tolerance(tol)
    limit = tolerance * (1.0 + _PE_ROUNDING_SLACK)
    return float(np.mean(_relative_errors(true, pred) <= limit))


def rmse_log(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Raíz del error cuadrático medio en escala logarítmica (logaritmo natural).

    Definición: RMSE_log = √( (1/n) · Σ (ln ŷᵢ − ln yᵢ)² ). Recibe precios en unidades naturales
    y aplica el logaritmo adentro.

    Por qué se usa en AVMs: el target del modelo es log(USD/m²) (F8.1); si se entrena con pérdida
    cuadrática sobre ese target, esta es la métrica que el modelo minimiza. En escala log el error
    es relativo y simétrico: subestimar y sobreestimar por el mismo factor pesa igual. Para
    errores chicos, su valor es aproximadamente el error relativo típico (0,10 ≈ 10 %).
    """
    true, pred = _validate_prices(y_true, y_pred)
    with np.errstate(all="ignore"):
        result = float(np.sqrt(np.mean((np.log(pred) - np.log(true)) ** 2)))
    return _finite(result, "rmse_log")


# --------------------------------------------------------------------------------------------
# Métricas de intervalos de predicción
# --------------------------------------------------------------------------------------------


def _validate_interval(low: ArrayLike, high: ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Límites finitos, del mismo largo y con low <= high. No exige que sean positivos."""
    lower = _as_1d_float(low, "low")
    upper = _as_1d_float(high, "high")
    if lower.shape != upper.shape:
        raise ValueError(
            f"low y high deben tener el mismo largo (recibidos {lower.size} y {upper.size})"
        )
    if not np.all(lower <= upper):
        raise ValueError("low debe ser <= high en todos los elementos")
    return lower, upper


def interval_coverage(y: ArrayLike, low: ArrayLike, high: ArrayLike) -> float:
    """Cobertura empírica de los intervalos de predicción (fracción en [0, 1]).

    Definición: cobertura = (1/n) · Σ 1[ lowᵢ ≤ yᵢ ≤ highᵢ ]. El intervalo es cerrado: `y` igual a
    `low` o a `high` cuenta como cubierto. `y` es el precio publicado (> 0); `low` y `high` deben
    ser finitos con `low <= high`, pero no hace falta que sean positivos.

    Por qué se usa en AVMs: un intervalo con nivel nominal de, por ejemplo, 80 % tiene que cubrir
    cerca del 80 % de los precios publicados en datos no vistos; si cubre menos, el rango de
    error que se le muestra al usuario es engañoso. Esta función solo mide la cobertura real:
    compararla con el nivel nominal es tarea de quien la llama (F9.3).
    """
    target = _as_1d_float(y, "y")
    lower = _as_1d_float(low, "low")
    upper = _as_1d_float(high, "high")
    if not target.shape == lower.shape == upper.shape:
        raise ValueError(
            "y, low y high deben tener el mismo largo "
            f"(recibidos {target.size}, {lower.size} y {upper.size})"
        )
    _require_positive(target, "y")
    lower, upper = _validate_interval(lower, upper)
    return float(np.mean((lower <= target) & (target <= upper)))


def mean_interval_width(
    low: ArrayLike,
    high: ArrayLike,
    y_pred: ArrayLike | None = None,
    *,
    relative: bool = False,
) -> float:
    """Ancho medio de los intervalos de predicción, absoluto o relativo a la predicción.

    Definiciones:
    - absoluto (`relative=False`): (1/n) · Σ (highᵢ − lowᵢ), en las unidades de los precios.
    - relativo (`relative=True`): (1/n) · Σ (highᵢ − lowᵢ) / ŷᵢ, donde ŷ es la predicción puntual
      (`y_pred`, que en ese caso es obligatoria y debe ser > 0). Es una fracción de la predicción.

    Pasar `y_pred` con `relative=False` es un error: no se ignora en silencio.

    Por qué se usa en AVMs: la cobertura sola se puede lograr con intervalos absurdamente anchos,
    así que hay que mirarla junto con el ancho. El ancho relativo permite comparar propiedades de
    precios distintos y verificar que los intervalos sean más anchos donde hay menos datos
    (F9.4).
    """
    lower, upper = _validate_interval(low, high)
    if not relative:
        if y_pred is not None:
            raise ValueError("y_pred solo se usa con relative=True")
        with np.errstate(all="ignore"):
            result = float(np.mean(upper - lower))
        return _finite(result, "mean_interval_width")
    if y_pred is None:
        raise ValueError("relative=True requiere y_pred")
    pred = _as_1d_float(y_pred, "y_pred")
    if pred.shape != lower.shape:
        raise ValueError(
            f"y_pred debe tener el mismo largo que low y high (recibidos {pred.size}, {lower.size})"
        )
    _require_positive(pred, "y_pred")
    with np.errstate(all="ignore"):
        result = float(np.mean((upper - lower) / pred))
    return _finite(result, "mean_interval_width")
