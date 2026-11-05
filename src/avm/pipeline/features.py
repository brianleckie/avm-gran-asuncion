"""Features que salen del aviso crudo (F4.5): amenities tri-estado, calle y conteos.

Tri-estado (ADR-006, punto 5): `True` = el aviso lo dice, `False` = lo niega de forma explícita,
`None` = no lo menciona (NO es "no lo tiene"). Para cada amenity:

1. Si el aviso trae el tag del portal (`Piscina: SI`, `Quincho: SI`), el tag manda: SI → 1, NO → 0.
2. Sin tag, regex sobre título + descripción. Una mención positiva → 1. Una mención negada
   ("sin piscina", "no tiene quincho", "ni piscina") → 0. Si el texto tiene las dos cosas
   (una mención positiva y otra negada) es contradictorio y queda `None`.

La negación es una heurística sobre la misma cláusula (el texto se corta en , . ; : / - y saltos de
línea): se mira hasta 4 palabras antes de la mención. Un "con"/"tiene"/"cuenta con"... pegado a la
mención la hace positiva salvo que lo preceda un "no".

Se devuelve también el origen de cada valor (`tag` o `regex`) para contarlo en el reporte.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from avm.contract import StreetSurface

Origin = Literal["tag", "regex"]

_CLAUSE_SPLIT: Final = re.compile(r"[.,;:!?()/\n\r\-–—]+")
_WORD: Final = re.compile(r"[0-9a-z]+")
_NEGATORS: Final = frozenset({"sin", "ni", "no", "carece"})
_POSITIVE_LINKS: Final = frozenset(
    {"con", "tiene", "tienen", "posee", "poseen", "incluye", "cuenta", "dispone", "hay"}
)
_NEGATION_WINDOW: Final = 4

AMENITY_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "has_pool": re.compile(r"\bpiscinas?\b"),
    "has_quincho": re.compile(r"\bquinchos?\b"),
    "is_new": re.compile(r"\ba estrenar\b|\bestrenar\b"),
    "in_gated_community": re.compile(r"\bbarrio cerrado\b|\bcondominios?\b"),
    "has_elevator": re.compile(r"\bascensor(?:es)?\b"),
}
# Tags del portal (`attributes_raw`) que dicen lo mismo que un amenity.
AMENITY_TAGS: Final = {"has_pool": "piscina", "has_quincho": "quincho"}

_STREET_CONTEXT: Final = frozenset(
    {"calle", "calles", "avenida", "avenidas", "camino", "caminos", "acceso", "accesos"}
)
_STREET_SURFACES: Final = {
    StreetSurface.PAVED: re.compile(r"\b(pavimentad[oa]s?|pavimento|asfaltad[oa]s?|asfalto)\b"),
    StreetSurface.COBBLESTONE: re.compile(r"\b(empedrad[oa]s?|empedrado)\b"),
    StreetSurface.DIRT: re.compile(r"\btierra\b"),
}
_STREET_WINDOW: Final = 4


def normalize_text(text: str) -> str:
    """Minúscula y sin tildes; la puntuación se conserva (corta cláusulas)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _clauses(text: str) -> list[str]:
    return [clause for clause in _CLAUSE_SPLIT.split(normalize_text(text)) if clause.strip()]


def _is_negated(before: list[str]) -> bool:
    """¿La mención que sigue a las palabras `before` (de su cláusula) está negada?"""
    before = before[-_NEGATION_WINDOW:]
    index = len(before) - 1
    while index >= 0 and before[index] in _POSITIVE_LINKS:
        index -= 1
    if index < len(before) - 1:  # un "con"/"tiene"... pegado a la mención
        return index >= 0 and before[index] == "no"
    return any(word in _NEGATORS for word in before)


def tri_state_from_text(text: str, pattern: re.Pattern[str]) -> bool | None:
    """True / False / None según las menciones de `pattern` en `text` (ver docstring del módulo)."""
    positive = negated = False
    for clause in _clauses(text):
        for match in pattern.finditer(clause):
            before = _WORD.findall(clause[: match.start()])
            if _is_negated(before):
                negated = True
            else:
                positive = True
    if positive and negated:
        return None
    if positive:
        return True
    return False if negated else None


def _tag_value(attributes: Mapping[str, str], label: str) -> bool | None:
    for key, value in attributes.items():
        if normalize_text(key).strip() == label:
            answer = normalize_text(value).strip()
            if answer == "si":
                return True
            if answer == "no":
                return False
    return None


@dataclass(frozen=True, slots=True)
class Amenities:
    """Los cinco amenities tri-estado y de dónde salió cada uno (None = no mencionado)."""

    values: dict[str, bool | None]
    origins: dict[str, Origin | None]


def extract_amenities(text: str, attributes: Mapping[str, str]) -> Amenities:
    """Amenities de un aviso: tag del portal primero, regex sobre `text` si no hay tag."""
    values: dict[str, bool | None] = {}
    origins: dict[str, Origin | None] = {}
    for name, pattern in AMENITY_PATTERNS.items():
        tag = _tag_value(attributes, AMENITY_TAGS[name]) if name in AMENITY_TAGS else None
        if tag is not None:
            values[name], origins[name] = tag, "tag"
            continue
        found = tri_state_from_text(text, pattern)
        values[name] = found
        origins[name] = "regex" if found is not None else None
    return Amenities(values, origins)


def extract_street_surface(text: str) -> StreetSurface | None:
    """Superficie de la calle dicha en el texto; None si no se dice o hay dos distintas."""
    found: set[StreetSurface] = set()
    for clause in _clauses(text):
        for surface, pattern in _STREET_SURFACES.items():
            for match in pattern.finditer(clause):
                before = _WORD.findall(clause[: match.start()])
                after = _WORD.findall(clause[match.end() :])
                near = before[-_STREET_WINDOW:] + after[:_STREET_WINDOW]
                if _STREET_CONTEXT.intersection(near) and not _is_negated(before):
                    found.add(surface)
    return found.pop() if len(found) == 1 else None


def parse_count(raw: str | None) -> int | None:
    """Entero de un campo crudo ("3"); None si no es solo dígitos."""
    if raw is None:
        return None
    value = raw.strip()
    return int(value) if value.isascii() and value.isdigit() else None
