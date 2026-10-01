"""Tests de los parsers de precio y superficie (adelanto de F4.1 y F4.3).

Los casos salen de los formatos pedidos en la tarea y de las reglas documentadas en
`avm.pipeline.parsing`; todavía no hay fixtures de HTML real (F3.4), así que esto NO valida
los parsers contra datos reales.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from avm.pipeline.parsing import ParsedArea, ParsedPrice, parse_area, parse_price

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
        # Monedas distintas en los extremos: es doble precio, no un rango.
        ("U$S 150.000 - Gs. 1.100.000.000", D(150000), "USD"),
        ("150.000 USD - 1.100.000.000 Gs", D(150000), "USD"),
        ("Gs. 1.100.000.000 hasta USD 150.000", D(1100000000), "PYG"),
        # Un segundo número que no es un rango (menor, o sin conector) no marca "desde".
        ("USD 150.000 y 2 dormitorios", D(150000), "USD"),
        ("USD 150.000 negociable 3 dormitorios", D(150000), "USD"),
        # "a convenir" con moneda explícita sí se parsea.
        ("USD 150.000 a convenir", D(150000), "USD"),
        # Segundo número mal formado: no hay rango y se queda el primero.
        ("USD 100.000 - 1.2.3", D(100000), "USD"),
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
    "USD 1.2,3",
    "USD 1,2.3",
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


# --------------------------------------------------------------------------------------------
# parse_area
# --------------------------------------------------------------------------------------------

# (raw, m2, kind)
AREA_REQUESTED_FORMATS = [
    ("120 m²", D(120), None),
    ("120m2", D(120), None),
    ("120 mts2", D(120), None),
    ("120 mt2", D(120), None),
    ("1.200 m²", D(1200), None),
    ("120,5 m²", D("120.5"), None),
    ("12x30", D(360), "terreno"),
    ("12 x 30 mts", D(360), "terreno"),
]


@pytest.mark.parametrize(("raw", "m2", "kind"), AREA_REQUESTED_FORMATS)
def test_parse_area_requested_formats(raw, m2, kind):
    assert parse_area(raw) == ParsedArea(m2, kind, raw)


AREA_UNIT_VARIANTS = [
    ("120M2", D(120)),
    ("120 M²", D(120)),
    ("120 mts²", D(120)),
    ("120 m 2", D(120)),
    ("120 metros cuadrados", D(120)),
    ("1.200 metros cuadrados", D(1200)),
    ("120 m². aprox.", D(120)),
    ("12.5 m²", D("12.5")),
    # Coma + 3 dígitos sin magnitud: miles anglosajón, como en los precios.
    ("1,200 m²", D(1200)),
    ("3 dormitorios, 120 m²", D(120)),
]


@pytest.mark.parametrize(("raw", "m2"), AREA_UNIT_VARIANTS)
def test_parse_area_unit_and_number_variants(raw, m2):
    result = parse_area(raw)
    assert result is not None
    assert result.m2 == m2


AREA_KINDS = [
    ("120 m² construidos", "construida"),
    ("120 m2 cubiertos", "construida"),
    ("120 m2 edificados", "construida"),
    ("Superficie construida: 120 m²", "construida"),
    ("Construcción: 120 m²", "construida"),
    ("Terreno: 360 m²", "terreno"),
    ("360 m² de terreno", "terreno"),
    ("Lote de 360 m²", "terreno"),
    ("Superficie total: 360 m²", "terreno"),
    ("Sup. total 360 m2", "terreno"),
    ("360 metros cuadrados de terreno", "terreno"),
    # Con varias expresiones gana la primera, con la pista más cercana a ella.
    ("120 m² construidos sobre terreno de 360 m²", "construida"),
    ("Terreno de 360 m² con casa de 120 m² construidos", "terreno"),
    ("Terreno 360 m² / Construcción 120 m²", "terreno"),
]


@pytest.mark.parametrize(("raw", "kind"), AREA_KINDS)
def test_parse_area_kind_from_nearby_words(raw, kind):
    result = parse_area(raw)
    assert result is not None
    assert result.kind == kind


def test_parse_area_conflicting_cues_at_same_distance_give_no_kind():
    # "Construcción" antes y "Terreno" después, a la misma distancia: pistas contradictorias.
    result = parse_area("Construcción 120 m² Terreno 360 m²")
    assert result is not None
    assert (result.m2, result.kind) == (D(120), None)


AREA_DIMENSIONS = [
    ("12x30", D(360), "terreno"),
    ("12 X 30", D(360), "terreno"),
    ("12×30", D(360), "terreno"),
    ("12 x 30 m", D(360), "terreno"),
    ("12,5 x 30 mts", D("375.0"), "terreno"),
    ("Lote 12x30", D(360), "terreno"),
    ("Terreno de 12 x 30 mts", D(360), "terreno"),
    # Una pista explícita de construcción pisa el "terreno" por defecto de las dimensiones.
    ("10x12 construidos", D(120), "construida"),
]


@pytest.mark.parametrize(("raw", "m2", "kind"), AREA_DIMENSIONS)
def test_parse_area_dimensions(raw, m2, kind):
    result = parse_area(raw)
    assert result is not None
    assert (result.m2, result.kind) == (m2, kind)


def test_parse_area_dimensions_with_conflicting_cues_give_no_kind():
    result = parse_area("construidos 10x12 terreno")
    assert result is not None
    assert (result.m2, result.kind) == (D(120), None)


@pytest.mark.parametrize(
    ("raw", "m2"),
    [
        # 100.000 exacto es válido.
        ("100.000 m²", D(100000)),
        ("0,5 m²", D("0.5")),
    ],
)
def test_parse_area_accepts_boundary_values(raw, m2):
    result = parse_area(raw)
    assert result is not None
    assert result.m2 == m2


# Un descriptivo después de la superficie ("- 3 dormitorios") no es un rango.
@pytest.mark.parametrize(
    ("raw", "m2"),
    [("120 m² - 3 dormitorios", D(120)), ("3 dormitorios - 150 m²", D(150))],
)
def test_parse_area_other_numbers_next_to_it_are_not_a_range(raw, m2):
    result = parse_area(raw)
    assert result is not None
    assert result.m2 == m2


AREA_NONE_CASES = [
    "",
    "   ",
    "terreno",
    "consultar",
    "m²",
    # Sin unidad cuadrada ni dimensiones.
    "120",
    "120 metros",
    "12 mts de frente",
    "120 mts",
    # Valores imposibles.
    "0 m²",
    "0,0 m²",
    "-120 m²",
    "100.001 m²",
    "120.000 m²",
    "1.000.000 m²",
    "12x0",
    "0x30",
    "1000x1000",
    # Números mal formados.
    "1.2.3 m²",
    "1.2.3x30",
    "12x1.2.3",
    "9" * 40 + " m²",
    # Tres dimensiones: no es un lote rectangular (regresión: un lookahead se evadía por backtrack).
    "10x12x3",
    "10 x 12 x 3 m",
    # Rangos de superficie: ParsedArea no tiene flag de "desde".
    "120 - 150 m²",
    "120 a 150 m²",
    "120 m² - 150 m²",
    "entre 120 y 150 m²",
    "120 m2 hasta 150 m2",
]


@pytest.mark.parametrize("raw", AREA_NONE_CASES)
def test_parse_area_returns_none(raw):
    assert parse_area(raw) is None


def test_parsed_area_is_frozen_and_keeps_raw():
    raw = "  120 m²  "
    result = parse_area(raw)
    assert result is not None
    assert isinstance(result.m2, Decimal)
    assert result.raw == raw
    with pytest.raises(FrozenInstanceError):
        result.m2 = D(1)  # type: ignore[misc]


# --------------------------------------------------------------------------------------------
# Property tests (hypothesis)
# --------------------------------------------------------------------------------------------

# Texto arbitrario, texto sesgado a los caracteres del dominio y frases armadas con fragmentos
# reales: estos últimos llegan a más ramas del parser que el texto puramente aleatorio.
ARBITRARY_TEXT = st.text(max_size=80)
DOMAIN_ALPHABET_TEXT = st.text(alphabet="0123456789.,-–xX×mtsUSDGgd$₲²/: ", max_size=40)


def _phrases(fragments: str):
    """Frases de hasta 8 fragmentos (separados por "|" en `fragments`) unidos por espacios."""
    return st.lists(st.sampled_from(fragments.split("|")), max_size=8).map(" ".join)


PRICE_PHRASES = _phrases(
    "USD|U$S|US$|u$d|Gs.|G|₲|$|guaraníes|dólares|mil|millones|millón|mill.|desde|a partir de"
    "|hasta|entre|y|a|-|–|.-|consultar|a convenir|150.000|1.200.000.000|1,5|150,000|120,5|12|30"
    "|0|100000|2 dormitorios"
)
AREA_PHRASES = _phrases(
    "m²|m2|mts2|mt2|mts|metros cuadrados|x|×|-|–|a|y|hasta|entre|120|360|1.200|120,5|12|30|0|-5"
    "|100000|100001|construidos|cubiertos|terreno|lote|superficie total|construcción|de|frente"
    "|3 dormitorios"
)
# "<cue> <número> <unidad> <cue>" y "<cue> AxB <cue>": mayormente interpretables, con variaciones.
AREA_TEMPLATES = st.builds(
    "{} {} {} {}".format,
    st.sampled_from(["", "terreno", "construcción", "lote de", "superficie total:", "120 m2 -"]),
    st.sampled_from(["120", "1.200", "120,5", "360", "12 x 30", "12x30", "0", "100.001", "-5"]),
    st.sampled_from(["m²", "m2", "mts2", "mt2", "metros cuadrados", "mts", "", "m2 -"]),
    st.sampled_from(["", "construidos", "cubiertos", "de terreno", "lote", "y 150 m2"]),
)
ANY_PRICE_TEXT = st.one_of(ARBITRARY_TEXT, DOMAIN_ALPHABET_TEXT, PRICE_PHRASES)
ANY_AREA_TEXT = st.one_of(ARBITRARY_TEXT, DOMAIN_ALPHABET_TEXT, AREA_PHRASES, AREA_TEMPLATES)


@settings(max_examples=500, deadline=None)
@given(raw=ANY_PRICE_TEXT)
def test_parse_price_never_raises_and_amount_is_positive(raw):
    result = parse_price(raw)
    if result is not None:
        assert isinstance(result.amount, Decimal)
        assert result.amount > 0
        assert result.currency in ("USD", "PYG", None)
        assert result.raw == raw


@settings(max_examples=500, deadline=None)
@given(raw=ANY_AREA_TEXT)
def test_parse_area_never_raises_and_m2_is_in_range(raw):
    result = parse_area(raw)
    if result is not None:
        assert isinstance(result.m2, Decimal)
        assert 0 < result.m2 <= 100_000
        assert result.kind in ("construida", "terreno", None)
        assert result.raw == raw


@given(n=st.integers(min_value=1, max_value=10**12))
def test_parse_price_roundtrips_paraguayan_thousands(n):
    result = parse_price(f"USD {n:,}".replace(",", "."))
    assert result is not None
    assert (result.amount, result.currency, result.is_from_price) == (D(n), "USD", False)


@given(n=st.integers(min_value=1, max_value=10**9))
def test_parse_price_roundtrips_magnitude_words(n):
    thousands = parse_price(f"USD {n} mil")
    millions = parse_price(f"Gs. {n} millones")
    assert thousands is not None
    assert millions is not None
    assert thousands.amount == D(n) * 1_000
    assert millions.amount == D(n) * 1_000_000


@given(n=st.integers(min_value=1, max_value=100_000))
def test_parse_area_roundtrips_paraguayan_thousands(n):
    result = parse_area(f"{n:,} m²".replace(",", "."))
    assert result is not None
    assert result.m2 == D(n)


@given(
    side_a=st.integers(min_value=1, max_value=316), side_b=st.integers(min_value=1, max_value=316)
)
def test_parse_area_dimensions_are_the_product_of_the_sides(side_a, side_b):
    result = parse_area(f"{side_a}x{side_b}")
    if side_a * side_b <= 100_000:
        assert result == ParsedArea(D(side_a * side_b), "terreno", f"{side_a}x{side_b}")
    else:
        assert result is None
