"""Superficies de un aviso (F4.3): todas las expresiones de un texto y el valor de un tag.

`parse_area` devuelve UNA sola expresión por texto. Para ver también la segunda ("120 m²
construidos sobre terreno de 360 m²") `find_areas` parte el texto en un fragmento por expresión
candidata y corre `parse_area` en cada uno. Es la misma idea que `scripts/pilot_report.py`.

El tag estructurado de Clasipar trae el número solo ("470"), sin unidad: `tag_area` lo lee con las
reglas de números y el tope de `parse_area` (agregándole la unidad).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from avm.pipeline.parsing import ParsedArea, parse_area

_UNIT: Final = r"m(?:ts?|etros?)?\.?\s*(?:[2²]|cuadrados?)(?![a-z0-9])"
# Candidatos: un superconjunto de lo que reconoce `parse_area` (número + unidad cuadrada, o
# dimensiones "AxB"). Los que `parse_area` rechaza se descartan después.
_CANDIDATE: Final = re.compile(
    rf"[0-9][0-9.,]*\s*{_UNIT}|(?<![0-9.,])[0-9][0-9.,]*+(?:\s*[x×]\s*[0-9][0-9.,]*+)+",
    re.IGNORECASE,
)
_WINDOW: Final = 25  # el mismo que usa `parse_area` para buscar la palabra de tipo
_TAG_VALUE: Final = re.compile(r"[0-9][0-9.,]*")


def find_areas(text: str) -> list[ParsedArea]:
    """Todas las superficies de `text`, en orden de aparición (no solo la primera)."""
    spans = [(match.start(), match.end()) for match in _CANDIDATE.finditer(text)]
    found: list[ParsedArea] = []
    for index, (start, end) in enumerate(spans):
        low = max(spans[index - 1][1] if index else 0, start - _WINDOW)
        high = min(spans[index + 1][0] if index + 1 < len(spans) else len(text), end + _WINDOW)
        area = parse_area(text[low:high])
        if area is not None:
            found.append(area)
    return found


def tag_area(raw: str | None) -> Decimal | None:
    """m² de un tag estructurado ("470", "1.200"); None si no es un número interpretable."""
    if raw is None or _TAG_VALUE.fullmatch(raw.strip()) is None:
        return None
    area = parse_area(f"{raw.strip()} m2")
    return area.m2 if area is not None else None
