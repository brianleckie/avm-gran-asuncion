"""Tests de los parsers de precio y superficie (adelanto de F4.1 y F4.3).

Los casos salen de los formatos pedidos en la tarea y de las reglas documentadas en
`avm.pipeline.parsing`; todavía no hay fixtures de HTML real (F3.4), así que esto NO valida
los parsers contra datos reales.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from avm.pipeline.parsing import ParsedPrice, parse_price

D = Decimal


# --------------------------------------------------------------------------------------------
# parse_price
# --------------------------------------------------------------------------------------------

# (raw, amount, currency, is_from_price)
PRICE_REQUESTED_FORMATS = [
    ("USD 150.000", D(150000), "USD", False),
    ("U$S 150.000", D(150000), "USD", False),
    ("US$150.000", D(150000), "USD", False),
    ("u$d 150 mil", D(150000), "USD", False),
    ("USD 1,5 millones", D(1500000), "USD", False),
    ("Gs. 1.200.000.000", D(1200000000), "PYG", False),
    ("₲ 1.200.000.000", D(1200000000), "PYG", False),
    ("1.200 millones de guaraníes", D(1200000000), "PYG", False),
    ("G 850.000.000", D(850000000), "PYG", False),
    ("desde USD 85.000", D(85000), "USD", True),
]


@pytest.mark.parametrize(("raw", "amount", "currency", "is_from"), PRICE_REQUESTED_FORMATS)
def test_parse_price_requested_formats(raw, amount, currency, is_from):
    assert parse_price(raw) == ParsedPrice(amount, currency, is_from, raw)


PRICE_CURRENCY_VARIANTS = [
    ("150.000 USD", D(150000), "USD"),
    ("  usd   150.000  ", D(150000), "USD"),
    ("U$ 150.000", D(150000), "USD"),
    ("150.000 dólares", D(150000), "USD"),
    ("150.000 Dólares americanos", D(150000), "USD"),
    ("Gs 1.200.000.000", D(1200000000), "PYG"),
    ("g. 850.000.000", D(850000000), "PYG"),
    ("PYG 1.200.000.000", D(1200000000), "PYG"),
    ("850.000.000 guaraníes", D(850000000), "PYG"),
    ("850.000.000 Guaranies", D(850000000), "PYG"),
]


@pytest.mark.parametrize(("raw", "amount", "currency"), PRICE_CURRENCY_VARIANTS)
def test_parse_price_currency_variants(raw, amount, currency):
    result = parse_price(raw)
    assert result is not None
    assert (result.amount, result.currency, result.is_from_price) == (amount, currency, False)


# Sin moneda explícita: currency=None. No se adivina por magnitud (decisión pendiente del pipeline).
PRICE_WITHOUT_CURRENCY = [
    ("150.000", D(150000)),
    ("1.200.000.000", D(1200000000)),
    ("150 mil", D(150000)),
    # "$" solo es ambiguo: no se asume USD.
    ("$ 150.000", D(150000)),
    ("$150.000", D(150000)),
]


@pytest.mark.parametrize(("raw", "amount"), PRICE_WITHOUT_CURRENCY)
def test_parse_price_without_currency_is_none_currency(raw, amount):
    result = parse_price(raw)
    assert result is not None
    assert result.amount == amount
    assert result.currency is None


# Separadores: "." miles y "," decimal (convención paraguaya); "150,000" anglosajón por contexto.
PRICE_SEPARATORS = [
    ("USD 150.000", D(150000)),
    ("USD 1.200.000", D(1200000)),
    ("USD 1.200,50", D("1200.50")),
    ("USD 1,200.50", D("1200.50")),
    ("USD 150,5", D("150.5")),
    ("USD 150.5", D("150.5")),
    ("USD 0,5 millones", D(500000)),
    ("USD 0.5 millones", D(500000)),
    # Coma + exactamente 3 dígitos y sin palabra de magnitud: miles anglosajón.
    ("USD 150,000", D(150000)),
    ("USD 1,200,000", D(1200000)),
    ("Gs. 850,000,000", D(850000000)),
    # Cierres tipográficos comunes.
    ("USD 150.000.-", D(150000)),
    ("U$S 150.000,-", D(150000)),
    ("Gs. 1.200.000.000.", D(1200000000)),
]


@pytest.mark.parametrize(("raw", "amount"), PRICE_SEPARATORS)
def test_parse_price_separators(raw, amount):
    result = parse_price(raw)
    assert result is not None
    assert result.amount == amount


def test_parse_price_comma_with_magnitude_is_decimal():
    # Con palabra de magnitud la coma se lee como decimal (convención paraguaya):
    # "1,500 millones" = 1,5 millones. Es una lectura ambigua y se documenta como supuesto.
    result = parse_price("USD 1,500 millones")
    assert result is not None
    assert result.amount == D(1500000)


PRICE_MAGNITUDES = [
    ("USD 150 mil", D(150000)),
    ("USD 1 millón", D(1000000)),
    ("USD 1 millon", D(1000000)),
    ("USD 2,5 millones", D(2500000)),
    ("USD 1,2 mill.", D(1200000)),
    ("USD 2 mil millones", D(2000000000)),
    ("Gs. 850 millones", D(850000000)),
    ("USD 150mil", D(150000)),
    ("USD 150 MIL", D(150000)),
]


@pytest.mark.parametrize(("raw", "amount"), PRICE_MAGNITUDES)
def test_parse_price_magnitude_words(raw, amount):
    result = parse_price(raw)
    assert result is not None
    assert result.amount == amount


def test_parse_price_mil_must_be_a_whole_word():
    # "milanesa" no es "mil": el 150 queda sin escalar.
    result = parse_price("USD 150 milanesa")
    assert result is not None
    assert result.amount == D(150)


@pytest.mark.parametrize("raw", ["desde USD 85.000", "Desde: USD 85.000", "A partir de USD 85.000"])
def test_parse_price_from_price(raw):
    result = parse_price(raw)
    assert result is not None
    assert result.amount == D(85000)
    assert result.is_from_price is True


# Rangos: se devuelve el límite inferior con is_from_price=True (misma semántica que "desde").
PRICE_RANGES = [
    ("USD 100.000 - 120.000", D(100000), "USD"),
    ("USD 100.000 – 120.000", D(100000), "USD"),
    ("USD 100.000-120.000", D(100000), "USD"),
    ("USD 100.000 a USD 120.000", D(100000), "USD"),
    ("USD 100.000 hasta 120.000", D(100000), "USD"),
    ("entre USD 100.000 y 120.000", D(100000), "USD"),
    ("Gs. 800.000.000 - Gs. 1.000.000.000", D(800000000), "PYG"),
    ("desde USD 85.000 hasta USD 120.000", D(85000), "USD"),
    # La magnitud final se hereda al primer número si este no la trae.
    ("USD 100 - 120 mil", D(100000), "USD"),
    ("USD 1,2 - 1,5 millones", D(1200000), "USD"),
    ("USD 1,200 - 1,500 millones", D(1200000), "USD"),
    # Si el primero es mayor que el segundo, no hay herencia: cada uno conserva su escala.
    ("Gs. 800.000.000 - 1.000 millones", D(800000000), "PYG"),
]


@pytest.mark.parametrize(("raw", "amount", "currency"), PRICE_RANGES)
def test_parse_price_range_returns_lower_bound_as_from_price(raw, amount, currency):
    result = parse_price(raw)
    assert result is not None
    assert result.amount == amount
    assert result.currency == currency
    assert result.is_from_price is True


@pytest.mark.parametrize(
    ("raw", "amount", "currency"),
    [
        # Dos monedas: gana la primera expresión.
        ("USD 150.000 / Gs. 1.100.000.000", D(150000), "USD"),
        ("Gs. 1.100.000.000 (USD 150.000)", D(1100000000), "PYG"),
        # Un segundo número que no es un rango (menor, o sin conector) no marca "desde".
        ("USD 150.000 y 2 dormitorios", D(150000), "USD"),
        ("USD 150.000 negociable 3 dormitorios", D(150000), "USD"),
        # "a convenir" con moneda explícita sí se parsea.
        ("USD 150.000 a convenir", D(150000), "USD"),
    ],
)
def test_parse_price_first_expression_wins_and_is_not_a_range(raw, amount, currency):
    result = parse_price(raw)
    assert result is not None
    assert (result.amount, result.currency, result.is_from_price) == (amount, currency, False)


PRICE_NONE_CASES = [
    "",
    "   ",
    "consultar",
    "Consultar",
    "CONSULTAR",
    "a convenir",
    "A CONVENIR",
    "precio a consultar",
    "Precio a Consultar",
    "a tratar",
    "consulte",
    # Frase de "sin precio" y ninguna moneda: no se rescata un número suelto.
    "2 dormitorios, consultar",
    # Sin número.
    "USD",
    "Gs.",
    "desde",
    # Monto imposible.
    "USD 0",
    "Gs. 0",
    "USD 0,00",
    "USD -150.000",
    "US$-150.000",
    # Números mal formados.
    "USD 1.2.3",
    "USD 1.20.000",
    "USD 12,3,4",
    "USD " + "9" * 40,
    "---",
    "!!!",
]


@pytest.mark.parametrize("raw", PRICE_NONE_CASES)
def test_parse_price_returns_none(raw):
    assert parse_price(raw) is None


def test_parse_price_keeps_raw_untouched():
    raw = "  U$S 150.000  "
    result = parse_price(raw)
    assert result is not None
    assert result.raw == raw


def test_parsed_price_is_frozen_and_amount_is_decimal():
    result = parse_price("USD 150.000")
    assert result is not None
    assert isinstance(result.amount, Decimal)
    with pytest.raises(FrozenInstanceError):
        result.amount = D(1)  # type: ignore[misc]
