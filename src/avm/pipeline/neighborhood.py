"""Normalización de barrios contra el gazetteer (F4.4, I2 de docs/interfaces.md).

La "Zona" de Clasipar es texto libre y a veces repite la ciudad. Se normaliza (minúscula, sin
tildes, sin "barrio"/"b°") y se busca DENTRO de la ciudad del aviso, en este orden:

1. exacto: igual al nombre canónico;
2. alias: igual a una variante de la columna `aliases` (separadas por `|`);
3. fuzzy: `rapidfuzz.fuzz.ratio` >= `FUZZY_THRESHOLD` contra nombres y alias. Si los dos mejores
   candidatos son barrios DISTINTOS con el mismo puntaje, es ambiguo y no se asigna;
4. si no, `sin_match` y sin barrio: nada se asigna en silencio (ADR-006, punto 7).

Sin gazetteer (`--gazetteer none`) todo queda `sin_match`. Una Zona igual a la ciudad también queda
`sin_match` (geo_precision=ciudad) y se cuenta aparte.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from rapidfuzz import fuzz, process

from avm.contract import City, NeighborhoodMatch

FUZZY_THRESHOLD: Final = 90.0  # puntaje mínimo de `fuzz.ratio` (0 a 100) para un match fuzzy

_BARRIO_TOKEN: Final = re.compile(r"(?<![^\W_])b[°º]\.?|\b(?:barrio|zona)\b")
_NOT_ALNUM: Final = re.compile(r"[^0-9a-z]+")
MANUAL_ALIASES: Final = Path(__file__).with_name("neighborhood_aliases.csv")


class Reason(StrEnum):
    """Por qué un aviso quedó con o sin barrio (para el reporte de calidad)."""

    MATCHED = "con_match"
    NO_ZONE = "sin_zona"
    SAME_AS_CITY = "igual_a_la_ciudad"
    NO_GAZETTEER = "sin_gazetteer"
    NO_MATCH = "no_matchea"
    AMBIGUOUS = "ambiguo"


@dataclass(frozen=True, slots=True)
class NeighborhoodResult:
    name: str | None  # nombre canónico de I2; None si no hay match
    match: NeighborhoodMatch
    reason: Reason


def normalize_name(text: str, *, city: City | None = None) -> str:
    """Normaliza escritura y, con contexto, retira la ciudad de la zona."""
    lowered = _BARRIO_TOKEN.sub(" ", text.casefold())
    for pattern, replacement in (
        (r"\bv\.(?=\s|$)", "villa"),
        (r"\bsta\b\.?", "santa"),
        (r"\bgral\b\.?", "general"),
    ):
        lowered = re.sub(pattern, replacement, lowered)
    decomposed = unicodedata.normalize("NFKD", lowered)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = _NOT_ALNUM.sub(" ", plain).strip()
    if city is not None:
        city_name = normalize_name(city.value.replace("_", " "))
        pattern = rf"\b{re.escape(city_name)}\b"
        if re.search(pattern, plain):
            plain = re.sub(pattern, " ", plain)
            plain = re.sub(r"\b(?:central|paraguay)\b", " ", plain)
    return " ".join(plain.split())


@dataclass(frozen=True, slots=True)
class _CityIndex:
    canonical: dict[str, str] = field(default_factory=dict)  # normalizado -> canónico
    aliases: dict[str, str] = field(default_factory=dict)  # normalizado -> canónico
    manual: dict[str, str] = field(default_factory=dict)
    ambiguous: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class Gazetteer:
    """Barrios canónicos y alias por ciudad (I2). Vacío = `--gazetteer none`."""

    cities: dict[City, _CityIndex] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.cities


def load_gazetteer(
    path: Path | None, *, manual_aliases_path: Path | None = MANUAL_ALIASES
) -> Gazetteer:
    """Lee `gazetteer.csv` (I2). None = sin gazetteer. Falla ante un alias ambiguo."""
    if path is None:
        return Gazetteer()
    cities: dict[City, _CityIndex] = defaultdict(_CityIndex)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            city = City(row["city"])
            canonical = row["neighborhood"].strip()
            if not canonical:
                continue
            index = cities[city]
            canonical_key = normalize_name(canonical)
            if index.canonical.get(canonical_key, canonical) != canonical:
                index.ambiguous.add(canonical_key)
            index.canonical[canonical_key] = canonical
            for alias in (row.get("aliases") or "").split("|"):
                key = normalize_name(alias)
                if not key:
                    continue
                if index.aliases.get(key, canonical) != canonical:
                    if (
                        key in index.canonical
                        or normalize_name(index.aliases[key]) == canonical_key
                    ):
                        index.ambiguous.add(key)
                    else:
                        raise ValueError(f"alias ambiguo en {city.value}: apunta a dos barrios")
                index.aliases[key] = canonical
    if manual_aliases_path is not None:
        with manual_aliases_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                city = City(row["city"])
                index = cities.get(city)
                canonical = row["neighborhood"]
                if index is None or canonical not in index.canonical.values():
                    continue  # El mismo cargador admite gazetteers sintéticos o parciales.
                key = normalize_name(row["alias"])
                if index.manual.get(key, canonical) != canonical:
                    raise ValueError(f"alias manual ambiguo en {city.value}")
                index.manual[key] = canonical
    return Gazetteer(dict(cities))


def _city_names(city: City, city_raw: str | None) -> set[str]:
    names = {normalize_name(city.value.replace("_", " "))}
    if city_raw:
        names.add(normalize_name(city_raw))
    return names


def match_neighborhood(
    zone: str | None, city: City, gazetteer: Gazetteer, *, city_raw: str | None = None
) -> NeighborhoodResult:
    """Barrio canónico de la Zona de un aviso de `city`; ver las reglas en el docstring."""
    unmatched = NeighborhoodMatch.UNMATCHED
    key = normalize_name(zone) if zone else ""
    if not key:
        return NeighborhoodResult(None, unmatched, Reason.NO_ZONE)
    if key in _city_names(city, city_raw):
        return NeighborhoodResult(None, unmatched, Reason.SAME_AS_CITY)
    contextual_key = normalize_name(zone or "", city=city)
    if not contextual_key:
        return NeighborhoodResult(None, unmatched, Reason.SAME_AS_CITY)
    index = gazetteer.cities.get(city)
    if gazetteer.is_empty:
        return NeighborhoodResult(None, unmatched, Reason.NO_GAZETTEER)
    if index is None:
        return NeighborhoodResult(None, unmatched, Reason.NO_MATCH)
    if city == City.FERNANDO_DE_LA_MORA and contextual_key in {"norte", "sur"}:
        return NeighborhoodResult(None, unmatched, Reason.AMBIGUOUS)
    if key in index.manual:
        return NeighborhoodResult(index.manual[key], NeighborhoodMatch.MANUAL, Reason.MATCHED)
    key = contextual_key
    if key in index.ambiguous:
        return NeighborhoodResult(None, unmatched, Reason.AMBIGUOUS)
    if key in index.canonical:
        return NeighborhoodResult(index.canonical[key], NeighborhoodMatch.EXACT, Reason.MATCHED)
    if key in index.aliases:
        return NeighborhoodResult(index.aliases[key], NeighborhoodMatch.ALIAS, Reason.MATCHED)

    choices = {**index.aliases, **index.canonical}  # el canónico gana si coincide con un alias
    choices = {key: value for key, value in choices.items() if key not in index.ambiguous}
    best: dict[str, float] = {}
    for name, score, _ in process.extract(
        key, list(choices), scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD, limit=None
    ):
        canonical = choices[name]
        best[canonical] = max(best.get(canonical, 0.0), score)
    if not best:
        return NeighborhoodResult(None, unmatched, Reason.NO_MATCH)
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return NeighborhoodResult(None, unmatched, Reason.AMBIGUOUS)
    return NeighborhoodResult(ranked[0][0], NeighborhoodMatch.FUZZY, Reason.MATCHED)
