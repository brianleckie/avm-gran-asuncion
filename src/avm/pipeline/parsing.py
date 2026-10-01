"""Parsers de texto crudo de avisos: precio (adelanto de F4.1) y superficie (adelanto de F4.3).

Son funciones puras, sin red ni estado. Devuelven dataclasses propias de este módulo y no usan
`avm.contract`: la adaptación al contrato se hace en F1. Es un parser inicial, todavía NO validado
contra fixtures reales (F3.4). Esperan el texto del campo (precio o superficie), no el aviso
completo: ante varias expresiones gana la primera.

Reglas de números (helper `_parse_number`)
El formato "." miles / "," decimal ("convención paraguaya") es un supuesto de la tarea F4.1, no un
hecho verificado: se valida contra fixtures reales en F3.4.
- Si aparecen "." y ",", el último de los dos es el decimal y el otro separa miles
  ("1.200,50" y "1,200.50" valen 1200,50).
- Solo ".": separa miles (convención paraguaya) si el primer grupo tiene 1-3 dígitos, no empieza
  en 0 y los demás grupos tienen exactamente 3 dígitos ("150.000", "1.200.000.000"). Si no, es
  decimal ("1.5", "12.25", "0.500").
- Solo ",": es decimal ("1,5", "120,5"). Excepción anglosajona: una coma con exactamente 3
  dígitos detrás y SIN palabra de magnitud separa miles ("150,000" y "1,200,000" valen 150000 y
  1200000). Con palabra de magnitud la coma es decimal (convención paraguaya): "1,500 millones"
  vale 1,5 millones. Es una lectura ambigua y se toma como supuesto, no como hecho.
- Se toleran los cierres tipográficos ".-" y ",-". Un número de más de 30 caracteres, o con
  grupos mal formados ("1.2.3", "1.20.000"), no se interpreta (None).

Reglas de parse_price
- Moneda: USD ("usd", "u$s", "u$d", "us$", "u$", "dólares") o PYG ("gs", "g" pegada a un número,
  "₲", "guaraníes", "pyg"). Un "$" solo NO se interpreta: currency=None. Si el texto mezcla
  monedas distintas (doble precio, "USD 150.000 / Gs. 1.100.000.000") gana la primera expresión y
  no se lee como rango. NO se adivina la moneda por magnitud: es una decisión del pipeline y
  queda pendiente (ver ROADMAP, F4.2).
- Palabras de magnitud: "mil" (x10^3), "millón/millones/mill." (x10^6), "mil millones" (x10^9).
- "consultar", "a convenir", "a tratar" o similares, sin ninguna moneda, y también el texto
  vacío o sin números: None. Con moneda explícita ("USD 150.000 a convenir") se parsea el monto.
- "desde" / "a partir de": is_from_price=True.
- Rangos ("USD 100.000 - 120.000", "a", "hasta", "entre ... y ..."): se devuelve el LÍMITE
  INFERIOR con is_from_price=True, la misma semántica que "desde" (el precio publicado es >= ese
  monto). Si el primer número no trae palabra de magnitud y el segundo sí, el primero la hereda
  siempre que quede menor o igual ("USD 100 - 120 mil" -> 100.000). Un segundo número menor que el
  primero no es un rango ("USD 150.000 y 2 dormitorios"). Descartar o no los is_from_price es
  decisión del pipeline.
- Monto <= 0 o negativo ("USD -150.000"): None.

Reglas de parse_area (los números siguen las mismas reglas de arriba, sin palabras de magnitud)
- Hace falta una unidad cuadrada ("m2", "m²", "mt2", "mts2", "mts²", "metros cuadrados") o unas
  dimensiones "AxB" ("12x30", "12 x 30 mts", "12×30"). Un número solo ("120") o una medida lineal
  ("120 mts", "12 mts de frente") no es una superficie: None. Tres dimensiones ("10x12x3"): None.
- Dimensiones: m2 = A x B. El tipo por defecto es "terreno" (dimensiones de lote).
- Tipo por palabras cercanas, en una ventana de 25 caracteres a cada lado que se corta en el
  dígito más próximo: "construidos/cubiertos/edificados/construcción" -> "construida";
  "terreno/lote/superficie total" -> "terreno". Gana la pista MÁS CERCANA a la expresión; si las
  de ambos lados empatan con tipos distintos, kind=None. Sin pistas: None (en dimensiones,
  "terreno").
- Con varias expresiones ("120 m² construidos sobre terreno de 360 m²") se devuelve la primera;
  la función no devuelve listas.
- Rangos de superficie ("120 - 150 m²", "entre 120 y 150 m²", "120 m² - 150 m²"): None, porque
  ParsedArea no tiene flag de "desde". Otros números pegados ("120 m² - 3 dormitorios") no son
  un rango.
- Fuera de (0, 100.000] m2 ("0 m²", "-120 m²", "100.001 m²"): None. No se cubren hectáreas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Currency = Literal["USD", "PYG"]
AreaKind = Literal["construida", "terreno"]

_MAX_NUMBER_LENGTH = 30
_MAX_AREA_M2 = Decimal(100_000)
_CUE_WINDOW = 25


@dataclass(frozen=True, slots=True)
class ParsedPrice:
    """Precio de oferta tal como lo publica el aviso, sin convertir de moneda."""

    amount: Decimal
    currency: Currency | None
    is_from_price: bool
    raw: str


@dataclass(frozen=True, slots=True)
class ParsedArea:
    """Superficie en m² tal como la publica el aviso."""

    m2: Decimal
    kind: AreaKind | None
    raw: str


# --------------------------------------------------------------------------------------------
# Números y palabras de magnitud
# --------------------------------------------------------------------------------------------

# Número + palabra de magnitud opcional. Solo dígitos ASCII: los demás no se interpretan.
_QUANTITY = re.compile(
    r"(?P<token>[0-9][0-9.,]*)"
    r"(?:\s*(?P<magnitude>mil\s+mill(?:ones|[oó]n)|mill(?:ones|[oó]n)|mill\.?|mil)(?![a-z]))?"
)


@dataclass(frozen=True, slots=True)
class _Quantity:
    token: str
    start: int
    end: int  # incluye la palabra de magnitud
    number: Decimal | None  # None si el token está mal formado
    factor: Decimal | None  # None si no trae palabra de magnitud

    @property
    def scaled(self) -> Decimal:
        """Número por su magnitud. Solo para tokens bien formados: los llamadores ya filtraron."""
        assert self.number is not None
        return self.number * (self.factor if self.factor is not None else Decimal(1))


def _is_grouped(text: str, sep: str) -> bool:
    """True si `text` es un entero con `sep` como separador de miles (grupos de 3 dígitos)."""
    first, *rest = text.split(sep)
    return (
        first.isdigit()
        and 1 <= len(first) <= 3
        and not first.startswith("0")
        and bool(rest)
        and all(len(group) == 3 and group.isdigit() for group in rest)
    )


def _parse_number(token: str, *, has_magnitude: bool) -> Decimal | None:
    """Interpreta un token numérico según las reglas del docstring del módulo."""
    token = token.rstrip(".,")
    if not token or len(token) > _MAX_NUMBER_LENGTH:
        return None
    if token.isdigit():
        return Decimal(token)

    has_dot, has_comma = "." in token, "," in token
    if has_dot and has_comma:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        integer, _, fraction = token.rpartition(decimal_sep)
        if _is_grouped(integer, thousands_sep) and fraction.isdigit():
            return Decimal(f"{integer.replace(thousands_sep, '')}.{fraction}")
        return None

    sep = "." if has_dot else ","
    if _is_grouped(token, sep) and not (sep == "," and has_magnitude):
        return Decimal(token.replace(sep, ""))
    integer, _, fraction = token.partition(sep)
    if integer.isdigit() and fraction.isdigit():
        return Decimal(f"{integer}.{fraction}")
    return None


def _magnitude_factor(word: str) -> Decimal:
    if word.startswith("mill"):
        return Decimal(10**6)
    if "mill" in word:  # "mil millones"
        return Decimal(10**9)
    return Decimal(10**3)


def _find_quantities(text: str) -> list[_Quantity]:
    quantities = []
    for match in _QUANTITY.finditer(text):
        word = match.group("magnitude")
        token = match.group("token")
        quantities.append(
            _Quantity(
                token=token,
                start=match.start(),
                end=match.end(),
                number=_parse_number(token, has_magnitude=word is not None),
                factor=_magnitude_factor(word) if word is not None else None,
            )
        )
    return quantities


def _normalize(raw: str) -> str:
    """NFKC (convierte "m²" en "m2") y minúsculas."""
    return unicodedata.normalize("NFKC", raw).casefold().strip()


# --------------------------------------------------------------------------------------------
# parse_price
# --------------------------------------------------------------------------------------------

_USD = r"(?<![a-z])us\s?\$|(?<![a-z])u\s?\$\s?[sd]?|(?<![a-z])usd(?![a-z])|d[oó]lar(?:es)?"
_PYG = (
    r"₲|(?<![a-z])gs(?![a-z])|(?<![a-z])g(?=\.?\s*[0-9])|guaran[ií](?:es)?|(?<![a-z])pyg(?![a-z])"
)
_CURRENCY = re.compile(rf"(?P<usd>{_USD})|(?P<pyg>{_PYG})")
_NO_PRICE = re.compile(r"(?<![a-z])(?:consult(?:ar|e|a)|a\s+convenir|a\s+tratar)(?![a-z])")
_FROM = re.compile(r"(?<![a-z])(?:desde|a\s+partir\s+de)(?![a-z])")
_RANGE_CONNECTORS = frozenset({"-", "–", "—", "a", "al", "hasta", "y", "e"})


def _detect_currency(text: str) -> Currency | None:
    match = _CURRENCY.search(text)
    if match is None:
        return None
    return "USD" if match.lastgroup == "usd" else "PYG"


def _mixes_currencies(text: str) -> bool:
    """True si aparecen USD y PYG en el mismo texto (doble precio, no un rango)."""
    return len({match.lastgroup for match in _CURRENCY.finditer(text)}) > 1


def _is_negative(text: str, start: int) -> bool:
    """True si un "-" pegado al número lo niega ("USD -150.000"), y no es un guion separador."""
    if start == 0 or text[start - 1] != "-":
        return False
    return start == 1 or text[start - 2].isspace() or text[start - 2] in "$₲"


def _is_range_connector(segment: str) -> bool:
    without_currency = _CURRENCY.sub("", segment)
    return re.sub(r"[\s.:]+", "", without_currency) in _RANGE_CONNECTORS


def _range_lower_bound(text: str, first: _Quantity, second: _Quantity) -> Decimal | None:
    """Límite inferior si `first` y `second` forman un rango; None si no lo forman."""
    if second.number is None:  # `first` ya se validó en parse_price
        return None
    if not _is_range_connector(text[first.end : second.start]):
        return None
    lower = first.scaled
    if first.factor is None and second.factor is not None:
        # "USD 100 - 120 mil": el primer número hereda la magnitud del segundo.
        reread = _parse_number(first.token, has_magnitude=True)
        if reread is not None and reread <= second.number:
            lower = reread * second.factor
    return lower if second.scaled >= lower else None


def parse_price(raw: str) -> ParsedPrice | None:
    """Interpreta un precio publicado ("USD 150.000", "Gs. 1.200.000.000", "desde USD 85.000").

    Devuelve None si no hay un monto positivo interpretable (ver reglas en el docstring del
    módulo). `raw` se conserva tal cual en el resultado.
    """
    text = _normalize(raw)
    currency = _detect_currency(text)
    if currency is None and _NO_PRICE.search(text):
        return None

    quantities = _find_quantities(text)
    if not quantities:
        return None
    first = quantities[0]
    if first.number is None or _is_negative(text, first.start):
        return None

    amount = first.scaled
    is_from_price = _FROM.search(text) is not None
    if len(quantities) > 1 and not _mixes_currencies(text):
        lower_bound = _range_lower_bound(text, first, quantities[1])
        if lower_bound is not None:
            amount, is_from_price = lower_bound, True

    if amount <= 0:
        return None
    return ParsedPrice(amount=amount, currency=currency, is_from_price=is_from_price, raw=raw)


# --------------------------------------------------------------------------------------------
# parse_area
# --------------------------------------------------------------------------------------------

_SQUARE_UNIT = r"m(?:ts?|etros?)?\.?\s*(?:2|cuadrados?)(?![a-z0-9])"
_AREA = re.compile(rf"(?P<token>[0-9][0-9.,]*)\s*{_SQUARE_UNIT}")
# Cadena "AxB" ("12x30", "12 x 30 mts", "12×30") con unidad lineal opcional. Se captura la cadena
# entera y después se exige que tenga exactamente 2 lados: un lookahead contra la tercera
# dimensión se evade por backtracking ("10x12x3" -> 10x1). Los cuantificadores posesivos (*+) y el
# lookbehind impiden que el match empiece o termine a mitad de un número.
_DIMENSIONS = re.compile(
    r"(?<![0-9.,])(?P<chain>[0-9][0-9.,]*+(?:\s*[x×]\s*[0-9][0-9.,]*+)+)"
    r"(?:\s*(?:mts?|metros|m)(?![a-z0-9]))?"
)
_DIMENSION_SEPARATOR = re.compile(r"\s*[x×]\s*")
_RANGE_BEFORE_AREA = re.compile(r"[0-9][0-9.,]*(?:\s*[-–—]|\s+(?:a|al|hasta|y|e)(?![a-z]))\s*$")
_RANGE_AFTER_AREA = re.compile(
    rf"(?:\s*[-–—]|\s+(?:a|al|hasta|y|e)(?![a-z]))\s*[0-9][0-9.,]*\s*{_SQUARE_UNIT}"
)
_KIND_CUES = re.compile(
    r"(?P<built>(?<![a-z])(?:construid[oa]s?|construcci[oó]n|cubiert[oa]s?|edificad[oa]s?)(?![a-z]))"
    r"|(?P<land>(?<![a-z])(?:terrenos?|lotes?|superficie\s+total|sup\.?\s+total)(?![a-z]))"
)


def _nearest_cue(window: str, *, after: bool) -> tuple[AreaKind, int] | None:
    """Pista de tipo más cercana a la expresión dentro de `window`, con su distancia en chars."""
    matches = list(_KIND_CUES.finditer(window))
    if not matches:
        return None
    match = matches[0] if after else matches[-1]
    distance = match.start() if after else len(window) - match.end()
    return ("construida" if match.lastgroup == "built" else "terreno"), distance


def _detect_kind(text: str, start: int, end: int, *, default: AreaKind | None) -> AreaKind | None:
    """Tipo de superficie según las palabras cercanas; `default` solo si no hay ninguna pista."""
    before_window = re.split(r"[0-9]", text[max(0, start - _CUE_WINDOW) : start])[-1]
    after_window = re.split(r"[0-9]", text[end : end + _CUE_WINDOW], maxsplit=1)[0]
    before = _nearest_cue(before_window, after=False)
    after = _nearest_cue(after_window, after=True)
    if before is None and after is None:
        return default
    if before is not None and after is not None and before[0] != after[0]:
        if before[1] == after[1]:
            return None
        return before[0] if before[1] < after[1] else after[0]
    cue = before or after
    return cue[0] if cue is not None else None


def parse_area(raw: str) -> ParsedArea | None:
    """Interpreta una superficie publicada ("120 m²", "1.200 m2", "12x30", "360 m² de terreno").

    Devuelve None si no hay una superficie interpretable en (0, 100.000] m² (ver reglas en el
    docstring del módulo). `raw` se conserva tal cual en el resultado.
    """
    text = _normalize(raw)
    dimensions = _DIMENSIONS.search(text)
    square = _AREA.search(text)

    if dimensions is not None and (square is None or dimensions.start() <= square.start()):
        sides = _DIMENSION_SEPARATOR.split(dimensions.group("chain"))
        if len(sides) != 2:  # tres o más dimensiones: no es un lote rectangular
            return None
        side_a = _parse_number(sides[0], has_magnitude=False)
        side_b = _parse_number(sides[1], has_magnitude=False)
        if side_a is None or side_b is None:
            return None
        m2 = side_a * side_b
        kind = _detect_kind(text, dimensions.start(), dimensions.end(), default="terreno")
    elif square is not None:
        if _is_negative(text, square.start()):
            return None
        if _RANGE_BEFORE_AREA.search(text[: square.start()]):
            return None
        if _RANGE_AFTER_AREA.match(text, square.end()):
            return None
        number = _parse_number(square.group("token"), has_magnitude=False)
        if number is None:
            return None
        m2 = number
        kind = _detect_kind(text, square.start(), square.end(), default=None)
    else:
        return None

    if not 0 < m2 <= _MAX_AREA_M2:
        return None
    return ParsedArea(m2=m2, kind=kind, raw=raw)
