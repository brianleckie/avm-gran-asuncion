"""Parsers de texto crudo de avisos: precio (adelanto de F4.1).

Son funciones puras, sin red ni estado. Devuelven dataclasses propias de este módulo y no usan
`avm.contract`: la adaptación al contrato se hace en F1. Es un parser inicial, todavía NO validado
contra fixtures reales (F3.4). Esperan el texto del campo de precio, no el aviso completo: ante
varios números gana el primero.

Reglas de números (helper `_parse_number`)
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
  "₲", "guaraníes", "pyg"). Un "$" solo NO se interpreta: currency=None. Si hay varias monedas
  gana la primera. NO se adivina la moneda por magnitud: eso es una decisión del pipeline y
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
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Currency = Literal["USD", "PYG"]

_MAX_NUMBER_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ParsedPrice:
    """Precio de oferta tal como lo publica el aviso, sin convertir de moneda."""

    amount: Decimal
    currency: Currency | None
    is_from_price: bool
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
    def scaled(self) -> Decimal | None:
        if self.number is None:
            return None
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
    if first.number is None or second.number is None:
        return None
    if not _is_range_connector(text[first.end : second.start]):
        return None
    lower = first.scaled
    if first.factor is None and second.factor is not None:
        # "USD 100 - 120 mil": el primer número hereda la magnitud del segundo.
        reread = _parse_number(first.token, has_magnitude=True)
        if reread is not None and reread <= second.number:
            lower = reread * second.factor
    upper = second.scaled
    if lower is None or upper is None or upper < lower:
        return None
    return lower


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
    if len(quantities) > 1:
        lower_bound = _range_lower_bound(text, first, quantities[1])
        if lower_bound is not None:
            amount, is_from_price = lower_bound, True

    if amount is None or amount <= 0:
        return None
    return ParsedPrice(amount=amount, currency=currency, is_from_price=is_from_price, raw=raw)
