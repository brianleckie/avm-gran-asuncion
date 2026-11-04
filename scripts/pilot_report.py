"""Reporte del piloto de Clasipar (F3.3) -> docs/pilot/<fecha>.md. SOLO AGREGADOS.

Uso (desde la raíz del repo, sin red):
    uv run python scripts/pilot_report.py                    # el último snapshot de data/interim
    uv run python scripts/pilot_report.py --date 2026-10-06

Lee, de `data/` (gitignored), lo que dejó `python -m avm.scraping.run`:
- `interim/<fecha>/clasipar/raw_listings.jsonl` y `crawl_manifest.json` (el plan de muestreo),
- `raw/<fecha>/clasipar/requests.jsonl` (resultado y duración de cada request) y la caché de HTML
  sanitizada (solo para buscar la superficie como campo estructurado, punto 7).

Privacidad y propiedad intelectual (ADR-007, ToS de Clasipar): el reporte NO reproduce títulos,
descripciones ni ningún otro texto de los avisos. Solo conteos y porcentajes, nombres de campos de
la fuente y PATRONES de formato de superficie ("N m2", "N mts2 de terreno"): los números se
reemplazan por N y toda palabra de contexto que no esté en `VOCABULARY` (vocabulario de
superficie y conectores) se reemplaza por W, así que ningún nombre ni dirección puede filtrarse.
Los precios son precios de OFERTA publicados, no precios de transacción.

La sección 11 (conclusión) la escribe una persona a partir de los números. Si el archivo de salida
ya existe y la tiene, se conserva al regenerar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from avm.contract import RawListing
from avm.pipeline.parsing import ParsedArea, ParsedPrice, parse_area, parse_price
from avm.scraping.sources.clasipar import _ficha, _json_ld, _tags  # selectores de F3.4

SOURCE = "clasipar"
TYPES = ("casa", "departamento", "duplex")
TYPE_LABEL = {"casa": "casa", "departamento": "departamento", "duplex": "dúplex"}
CITIES = ("asuncion", "luque", "san_lorenzo", "fernando_de_la_mora")
CITY_LABEL = {
    "asuncion": "Asunción",
    "luque": "Luque",
    "san_lorenzo": "San Lorenzo",
    "fernando_de_la_mora": "Fernando de la Mora",
}
CONCLUSION_HEADING = "## 11. Conclusión"
CONCLUSION_PLACEHOLDER = (
    f"{CONCLUSION_HEADING}\n\n_Pendiente: se escribe a mano con los números de arriba "
    "(máximo 5 líneas)._\n"
)

# Campos de RawListing que siempre están (los fija el parser): no se miden en la completitud.
ALWAYS_SET = frozenset({"source", "source_id", "url", "scraped_at", "content_hash"})

# Único vocabulario que sobrevive en el contexto de un patrón: superficie, tipos de inmueble y
# conectores. Cualquier otra palabra (nombres, calles, barrios) se reemplaza por "W".
_VOCABULARY_WORDS = """
    terreno terrenos lote lotes superficie sup total construido construidos construida construidas
    construcción construccion cubierto cubiertos cubierta cubiertas edificado edificados edificada
    útil util útiles utiles propio propios habitable aprox aproximada aproximadamente desde hasta
    cada por planta plantas piso pisos sobre fracción fraccion mts mt m metros metro cuadrados
    cuadrado de del la el los las en con y a e o un una c x casa departamento depto dpto duplex
    dúplex dormitorios dormitorio baños baño frente fondo cochera cocheras
    """
VOCABULARY = frozenset(_VOCABULARY_WORDS.split())

# Etiquetas de campos estructurados que podrían traer la superficie (punto 7).
AREA_LABEL = re.compile(
    r"superficie|m2|m²|mts|metros|terreno|constru|lote|floor|size|area|surface", re.I
)

# Indicios de nombres de personas (punto 10). Solo se cuentan.
PRIVACY_PATTERNS = {
    "Sr.": re.compile(r"\bsr\.", re.I),
    "Sra.": re.compile(r"\bsra\.", re.I),
    "Lic.": re.compile(r"\blic\.", re.I),
    "Arq.": re.compile(r"\barq\.", re.I),
    "Dr./Dra.": re.compile(r"\bdra?\.", re.I),
    "Ing.": re.compile(r"\bing\.", re.I),
    "consultar con": re.compile(r"consultar\s+con", re.I),
    "hablar con": re.compile(r"hablar\s+con", re.I),
}
LOCATIONS = ("ficha (`.anuncio-detalles`)", "tags (`span.ads_tag`)", "JSON-LD")
PLACEHOLDERS = ("[TELEFONO]", "[EMAIL]", "[WHATSAPP]", "[URL]")

# --------------------------------------------------------------------------------- superficie

_UNIT = r"m(?:ts?|etros?)?\.?\s*(?:[2²]|cuadrados?)(?![a-z0-9])"
# Candidatos a superficie: un superconjunto de lo que reconoce `parse_area` (número + unidad
# cuadrada, o dimensiones "AxB"). Los que `parse_area` rechaza se descartan después.
_CANDIDATE = re.compile(
    rf"[0-9][0-9.,]*\s*{_UNIT}|(?<![0-9.,])[0-9][0-9.,]*+(?:\s*[x×]\s*[0-9][0-9.,]*+)+",
    re.I,
)
_WORD = re.compile(r"[^\W\d_]+")
# Un número de la expresión, no el dígito de la unidad ("m2", "mts2"): ese va pegado a una letra.
# El lado de unas dimensiones ("12x30") también va pegado a la "x" y sí es un número.
_NUMBER = re.compile(r"(?:(?<![^\W\d_])|(?<=[x×]))[0-9][0-9.,]*")
_WINDOW = 25  # el mismo que usa parse_area para buscar la palabra de tipo


@dataclass(frozen=True, slots=True)
class Found:
    """Una superficie encontrada en un texto, con el patrón de formato de su expresión."""

    area: ParsedArea
    where: str  # "titulo" o "descripcion"
    pattern: str  # patrón de formato (números -> N, contexto filtrado)
    expression: str  # solo la expresión, sin contexto ("N m2", "N x N mts")


def _pattern(fragment: str, start: int, end: int) -> tuple[str, str]:
    """(patrón con contexto, expresión sola) de la expresión `fragment[start:end]`."""
    expression = " ".join(_NUMBER.sub("N", fragment[start:end].casefold()).split())
    before = _WORD.findall(re.split(r"[0-9]", fragment[:start])[-1])[-2:]
    after = _WORD.findall(re.split(r"[0-9]", fragment[end:], maxsplit=1)[0])[:2]

    def keep(word: str) -> str:
        return word.casefold() if word.casefold() in VOCABULARY else "W"

    return " ".join([*map(keep, before), expression, *map(keep, after)]), expression


def find_areas(text: str, where: str) -> list[Found]:
    """Todas las superficies de `text`, no solo la primera.

    `parse_area` devuelve una sola expresión por texto. Acá se parte el texto en un fragmento por
    candidato (con la ventana de 25 caracteres que usa `parse_area` para el tipo, cortada donde
    empieza o termina el candidato vecino) y se corre `parse_area` en cada uno.
    """
    spans = [(match.start(), match.end()) for match in _CANDIDATE.finditer(text)]
    found = []
    for index, (start, end) in enumerate(spans):
        low = max(spans[index - 1][1] if index else 0, start - _WINDOW)
        high = min(spans[index + 1][0] if index + 1 < len(spans) else len(text), end + _WINDOW)
        fragment = text[low:high]
        area = parse_area(fragment)
        if area is not None:
            pattern, expression = _pattern(fragment, start - low, end - low)
            found.append(Found(area, where, pattern, expression))
    return found


# --------------------------------------------------------------------------------- filas


@dataclass(frozen=True, slots=True)
class Row:
    listing: RawListing
    ptype: str
    city: str
    pages: tuple[int, ...]  # páginas del listado de las que salió el aviso (según el plan)
    price: ParsedPrice | None
    areas: tuple[Found, ...]  # `parse_area` sobre el título y sobre la descripción completos
    line_areas: tuple[Found, ...]  # lo mismo, línea por línea (solo para medir una idea de F4.3)
    tag_built: Decimal | None = None  # tag estructurado "Superficie construida" (attributes_raw)
    tag_land: Decimal | None = None  # tag estructurado "Superficie de terreno m2"

    @property
    def sponsored(self) -> bool:
        return self.listing.attributes_raw.get("patrocinado") == "si"

    @property
    def origin(self) -> str:
        if not self.pages:
            return "sin plan"
        if self.pages == (1,):
            return "página 1"
        return "ambas" if 1 in self.pages else "aleatoria"

    @property
    def price_ok(self) -> bool:
        return self.price is not None and self.price.currency is not None

    @property
    def built_values(self) -> set[Any]:
        return {found.area.m2 for found in self.areas if found.area.kind == "construida"}

    @property
    def has_unkinded(self) -> bool:
        return any(found.area.kind is None for found in self.areas)

    def available(self, *, unkinded_as_built: bool = False, with_tag: bool = False) -> bool:
        """Precio parseable + moneda conocida + m² construidos identificados.

        Por defecto los m² construidos salen del texto (título y descripción). `with_tag` suma el
        tag estructurado y `unkinded_as_built` la regla alternativa de los departamentos: las dos
        son solo medidas.
        """
        built = bool(self.built_values) or (with_tag and self.tag_built is not None)
        if unkinded_as_built and self.ptype == "departamento" and not built:
            built = self.has_unkinded
        return self.price_ok and built


def tag_area(attributes: dict[str, str], wanted: str) -> Decimal | None:
    """Superficie de un tag estructurado ("Superficie construida", "Superficie de terreno m2")."""
    for key, value in attributes.items():
        if "superficie" in key.casefold() and wanted in key.casefold():
            area = parse_area(value) or parse_area(f"{value} m2")  # el tag trae el número solo
            return area.m2 if area is not None else None
    return None


def build_rows(listings: Sequence[RawListing], manifest: dict[str, Any]) -> list[Row]:
    plan: dict[str, tuple[str, str, tuple[int, ...]]] = {}
    for target in manifest["targets"]:
        for item in target["sampled"]:
            plan[item["source_id"]] = (
                target["property_type"],
                target["city"],
                tuple(item["pages"]),
            )
    rows = []
    for listing in listings:
        ptype, city, pages = plan.get(listing.source_id, ("?", "?", ()))
        title = find_areas(listing.title_raw or "", "titulo")
        description = listing.description_raw or ""
        by_line = [f for line in description.splitlines() for f in find_areas(line, "descripcion")]
        areas = (*title, *find_areas(description, "descripcion"))
        price = parse_price(listing.price_raw) if listing.price_raw else None
        attributes = listing.attributes_raw
        rows.append(
            Row(
                listing,
                ptype,
                city,
                pages,
                price,
                areas,
                (*title, *by_line),
                tag_area(attributes, "constru"),
                tag_area(attributes, "terreno"),
            )
        )
    return rows


# --------------------------------------------------------------------------------- formato


def pct(part: int, whole: int) -> str:
    return "n/d" if whole == 0 else f"{100 * part / whole:.1f} %".replace(".", ",")


def frac(part: int, whole: int) -> str:
    return f"{part}/{whole} ({pct(part, whole)})"


def table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Percentil por rango más cercano (sobre valores ya ordenados)."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def seconds(value: float) -> str:
    return f"{value:.2f} s".replace(".", ",")


def minutes(delta_seconds: float) -> str:
    return f"{delta_seconds / 60:.1f} min".replace(".", ",")


def by_type(rows: Sequence[Row]) -> list[tuple[str, list[Row]]]:
    return [(TYPE_LABEL[t], [row for row in rows if row.ptype == t]) for t in TYPES]


def by_city(rows: Sequence[Row]) -> list[tuple[str, list[Row]]]:
    return [(CITY_LABEL[c], [row for row in rows if row.city == c]) for c in CITIES]


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(ch for ch in plain if not unicodedata.combining(ch)).split())


# --------------------------------------------------------------------------------- secciones


def section_execution(manifest: dict[str, Any], requests: Sequence[dict[str, Any]]) -> list[str]:
    lines = ["## 1. Ejecución", ""]
    results = Counter(entry["result"] for entry in requests)
    sent = len(requests) - results["cache"] - results["robots"]
    statuses = Counter(entry["status"] for entry in requests if entry["status"] is not None)
    details = manifest["details"]
    lines += [
        f"- Requests enviadas por `BaseScraper` (robots.txt y reintentos incluidos): {sent} de un "
        f"presupuesto de {manifest['budget']}; el log registra además {results['cache']} "
        f"respuestas de caché y {results['robots']} pedidos prohibidos por robots.txt, que no "
        "se enviaron.",
        "- Por resultado: " + ", ".join(f"{k} {v}" for k, v in sorted(results.items())) + ".",
        "- Por status HTTP: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())) + ".",
    ]
    stopped = manifest["stopped"]
    lines.append(
        "- Corrida completa, sin cortes."
        if stopped is None
        else f"- **La corrida se cortó** (`{stopped}`): {manifest['stop_reason']}."
    )
    started = datetime.fromisoformat(manifest["started_at"])
    finished = manifest["finished_at"]
    end = (
        datetime.fromisoformat(finished) if finished else datetime.fromisoformat(requests[-1]["ts"])
    )
    lines += [f"- Duración total: {minutes((end - started).total_seconds())}.", ""]

    def kind_of(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "robots.txt"
        return "listados" if "intencion:" in url else "detalles"

    latencies: dict[str, list[float]] = {}
    for entry in requests:
        if entry.get("duration_s") is not None:
            latencies.setdefault(kind_of(entry["url"]), []).append(entry["duration_s"])
    latencies["todas"] = [value for values in latencies.values() for value in values]
    rows = []
    for name in ("listados", "detalles", "robots.txt", "todas"):
        values = sorted(latencies.get(name, []))
        if values:
            rows.append(
                [
                    name,
                    len(values),
                    seconds(statistics.fmean(values)),
                    seconds(percentile(values, 0.5)),
                    seconds(percentile(values, 0.95)),
                    seconds(values[-1]),
                ]
            )
    lines += [
        "Latencia por request (solo el intercambio HTTP, sin la demora entre requests; "
        "p50 y p95 por rango más cercano):",
        "",
    ]
    lines += table(["Tipo de request", "n", "Media", "p50", "p95", "Máx."], rows)
    rejected = details["rejected_by_error"]
    lines += [
        f"- Detalles muestreados: {details['planned']}; pedidos: {details['attempted']}; "
        f"sin pedir por el corte: {details['not_attempted']}.",
        f"- **Válidos: {frac(details['valid'], details['attempted'])}**; rechazados por la "
        f"validación o el parser: {details['rejected']}.",
    ]
    if rejected:
        lines.append(
            "  - Por tipo de error (un aviso puede sumar varios): "
            + ", ".join(f"`{key}` {value}" for key, value in sorted(rejected.items()))
            + "."
        )
    if details["fetch_errors"]:
        lines.append(
            "- Pedidos de detalle que no devolvieron página: "
            + ", ".join(
                f"`{key}` {value}" for key, value in sorted(details["fetch_errors"].items())
            )
            + "."
        )
    failed = [t for t in manifest["targets"] if t["errors"]]
    if failed:
        lines.append(
            f"- Búsquedas con errores en el listado: {len(failed)} de {len(manifest['targets'])}."
        )
    return [*lines, ""]


def random_pages(target: dict[str, Any]) -> list[int]:
    """Páginas aleatorias de una búsqueda: `random_pages` o, en manifests viejos, `random_page`."""
    if "random_pages" in target:
        return list(target["random_pages"])
    return [] if target["random_page"] is None else [target["random_page"]]


def random_pages_label(target: dict[str, Any]) -> str:
    pages = random_pages(target)
    if not pages:
        return "—"
    return str(pages[0]) if len(pages) == 1 else f"{len(pages)} págs."


def is_pilot_design(manifest: dict[str, Any]) -> bool:
    """Página 1 más UNA aleatoria. Los manifests anteriores a `--pages-per-target` no lo traen."""
    return manifest.get("pages_per_target", 2) == 2


def section_sample(manifest: dict[str, Any], rows: Sequence[Row]) -> list[str]:
    lines = ["## 2. Muestra", ""]
    data = []
    for target in manifest["targets"]:
        mine = [r for r in rows if (r.ptype, r.city) == (target["property_type"], target["city"])]
        origin = Counter(r.origin for r in mine)
        data.append(
            [
                TYPE_LABEL[target["property_type"]],
                CITY_LABEL[target["city"]],
                target["total_results"] if target["total_results"] is not None else "n/d",
                target["last_page"] if target["last_page"] is not None else "n/d",
                random_pages_label(target),
                target["pool_size"],
                f"{len(mine)}{' (corta)' if target['short'] else ''}",
                origin["página 1"],
                origin["aleatoria"],
                origin["ambas"],
                sum(r.sponsored for r in mine),
            ]
        )
    lines += table(
        [
            "Tipo",
            "Ciudad",
            "Resultados",
            "Últ. pág.",
            "Pág. aleatoria",
            "Pool",
            "Válidos",
            "De pág. 1",
            "De la aleatoria",
            "De ambas",
            "Patrocinados",
        ],
        data,
    )
    origin = Counter(r.origin for r in rows)
    if is_pilot_design(manifest):
        pool_note = '- "Pool" son las referencias únicas de la página 1 y de la aleatoria'
        bias_note = (
            "- **Sesgo del diseño:** la página 1 aporta cerca de la mitad del pool y es una "
            "página especial (orden por defecto del portal, patrocinados); no es una muestra "
            "uniforme de cada búsqueda. Por eso el punto 6 repite la tasa solo con los avisos "
            "de la página aleatoria."
        )
    else:  # K > 2 páginas: la fracción del pool que aporta la página 1 depende de K
        pool_note = '- "Pool" son las referencias únicas de la página 1 y de las aleatorias'
        bias_note = (
            "- **Sesgo del diseño:** la página 1 es una página especial (orden por defecto del "
            "portal, patrocinados); no es una muestra uniforme de cada búsqueda. Por eso el "
            "punto 6 repite la tasa solo con los avisos de las páginas aleatorias."
        )
    lines += [
        f"- Total de avisos válidos: {len(rows)}. De la página 1: {origin['página 1']}; de la "
        f"página aleatoria: {origin['aleatoria']}; presentes en ambas: {origin['ambas']}; "
        f"sin plan: {origin['sin plan']}.",
        f"- Patrocinados (D5): {frac(sum(r.sponsored for r in rows), len(rows))}.",
        f"{pool_note} (menos las ya planificadas por otra búsqueda); "
        '"corta" marca las que tienen menos que `--per-target`.',
        bias_note,
        "",
    ]
    return lines


def _present(listing: RawListing, name: str) -> bool:
    value = getattr(listing, name)
    return bool(value) if isinstance(value, dict) else value is not None


def section_completeness(rows: Sequence[Row]) -> list[str]:
    fields = [name for name in RawListing.model_fields if name not in ALWAYS_SET]
    groups = [*by_type(rows), ("Total", list(rows))]
    header = ["Campo", *[f"{label} (n={len(group)})" for label, group in groups]]
    data = [
        [
            f"`{name}`",
            *[
                pct(sum(_present(r.listing, name) for r in group), len(group))
                for _, group in groups
            ],
        ]
        for name in fields
    ]
    return [
        "## 3. Completitud por campo",
        "",
        "Porcentaje de avisos con el campo presente (no nulo; `attributes_raw`, no vacío). "
        "`source`, `source_id`, `url`, `scraped_at` y `content_hash` siempre están.",
        "",
        *table(header, data),
    ]


def _price_class(row: Row) -> str:
    if not row.listing.price_raw:
        return "sin precio"
    if row.price is None:
        text = row.listing.price_raw
        if "consult" in text.casefold():
            return "consultar"
        return "monto cero" if "0" in text and not re.search(r"[1-9]", text) else "no parseable"
    return "parseable"


def section_price(rows: Sequence[Row]) -> list[str]:
    groups = [*by_type(rows), ("Total", list(rows))]
    data = []
    for label, group in groups:
        classes = Counter(_price_class(r) for r in group)
        parsed = [r.price for r in group if r.price is not None]
        data.append(
            [
                f"{label} (n={len(group)})",
                frac(classes["parseable"], len(group)),
                sum(p.currency == "USD" for p in parsed),
                sum(p.currency == "PYG" for p in parsed),
                sum(p.currency is None for p in parsed),
                sum(p.is_from_price for p in parsed),
                classes["consultar"],
                classes["monto cero"],
                classes["no parseable"] + classes["sin precio"],
            ]
        )
    return [
        "## 4. Precio",
        "",
        "`parse_price` sobre `price_raw`. Son precios de oferta publicados.",
        "",
        *table(
            [
                "Tipo",
                "Parseables",
                "USD",
                "PYG",
                "Sin moneda (`currency=None`)",
                '"Desde" o rango (`is_from_price`)',
                '"Consultar"',
                "Monto cero",
                "Otros no parseables",
            ],
            data,
        ),
    ]


def _pairs(found: Iterable[Found]) -> set[tuple[Any, str | None]]:
    return {(f.area.m2, f.area.kind) for f in found}


def _kinds_of(row: Row) -> list[str | None]:
    return [found.area.kind for found in row.areas]


def _distinct_areas(row: Row) -> list[tuple[str, str | None]]:
    """(m², tipo) por cada m² distinto; si el mismo valor aparece con y sin tipo, gana el tipo."""
    best: dict[Any, str | None] = {}
    for found in row.areas:
        if best.get(found.area.m2) is None:
            best[found.area.m2] = found.area.kind
    return [(str(m2), kind) for m2, kind in best.items()]


def consistency(rows: Sequence[Row]) -> tuple[int, int, int]:
    """(textos revisados, discrepancias en la primera expresión, solo en fragmentos)."""
    checked = mismatched = extra = 0
    for row in rows:
        for text, where in (
            (row.listing.title_raw, "titulo"),
            (row.listing.description_raw, "descripcion"),
        ):
            if not text:
                continue
            checked += 1
            full = parse_area(text)
            mine = [f for f in row.areas if f.where == where]
            if full is None:
                extra += bool(mine)
            elif not mine or (mine[0].area.m2, mine[0].area.kind) != (full.m2, full.kind):
                mismatched += 1
    return checked, mismatched, extra


def section_area(rows: Sequence[Row]) -> list[str]:
    lines = [
        "## 5. Superficie (P13: ¿se puede identificar los m² construidos?)",
        "",
        "`parse_area` sobre `title_raw` y `description_raw`. Como `parse_area` devuelve una sola "
        "expresión por texto, cada texto se parte en fragmentos (uno por expresión candidata) y se "
        "corre `parse_area` en cada uno, para ver también la segunda superficie de un aviso. "
        "La superficie también puede venir como tag estructurado: ver el punto 7 y, para su "
        "efecto sobre el target, el punto 6.",
        "",
    ]
    groups = [*by_type(rows), ("Total", list(rows))]
    data = []
    for label, group in groups:
        any_area = [r for r in group if r.areas]
        built = [r for r in group if "construida" in _kinds_of(r)]
        land = [r for r in group if "terreno" in _kinds_of(r)]
        only_none = [r for r in any_area if all(k is None for k in _kinds_of(r))]
        data.append(
            [
                f"{label} (n={len(group)})",
                frac(len(any_area), len(group)),
                frac(len(built), len(group)),
                frac(len(land), len(group)),
                frac(len([r for r in built if r in land]), len(group)),
                frac(len(only_none), len(group)),
                sum(any(f.where == "titulo" for f in r.areas) for r in group),
                sum(any(f.where == "descripcion" for f in r.areas) for r in group),
            ]
        )
    lines += table(
        [
            "Tipo",
            "≥ 1 superficie",
            "Con `construida`",
            "Con `terreno`",
            "Con ambas",
            "Solo `kind=None`",
            "En el título",
            "En la descripción",
        ],
        data,
    )
    data = []
    for label, group in groups:
        by_line = sum(any(f.area.kind == "construida" for f in r.line_areas) for r in group)
        changed = sum(_pairs(r.areas) != _pairs(r.line_areas) for r in group)
        data.append(
            [
                f"{label} (n={len(group)})",
                frac(sum("construida" in _kinds_of(r) for r in group), len(group)),
                frac(by_line, len(group)),
                changed,
            ]
        )
    lines += [
        "**Medida adicional, solo informativa (idea para F4.3, no se adopta):** `parse_area` "
        "decide el tipo con la palabra más cercana en una ventana de 25 caracteres que NO se corta "
        "en el salto de línea ni en la etiqueta de la superficie siguiente. Aplicarlo línea por "
        "línea da esto:",
        "",
        *table(
            [
                "Tipo",
                "Con `construida` (texto completo)",
                "Con `construida` (línea por línea)",
                "Avisos con alguna superficie clasificada distinto",
            ],
            data,
        ),
    ]
    checked, mismatched, extra = consistency(rows)
    lines += [
        f"Chequeo del fragmentado: de {checked} textos, {mismatched} donde la primera superficie "
        f"difiere de la de `parse_area` sobre el texto completo (debería ser 0) y {extra} donde "
        "`parse_area` sobre el texto completo da `None` pero algún fragmento sí da superficie.",
        "",
    ]
    patterns = Counter(f.pattern for r in rows for f in r.areas if f.area.kind is None)
    lines += [
        f"**Patrones de formato más frecuentes entre las superficies con `kind=None`** "
        f"({sum(patterns.values())} superficies, {len(patterns)} patrones distintos; números → N, "
        "contexto fuera del vocabulario de superficie → W):",
        "",
        *table(
            ["#", "Patrón", "Superficies"],
            [[i, f"`{pattern}`", n] for i, (pattern, n) in enumerate(patterns.most_common(10), 1)],
        ),
    ]
    expressions = Counter(f.expression for r in rows for f in r.areas if f.area.kind is None)
    lines += [
        "**Solo la expresión, sin contexto** (las mismas superficies `kind=None`; sirve para ver "
        "qué unidades y formatos tiene que entender F4.3):",
        "",
        *table(
            ["#", "Expresión", "Superficies"],
            [[i, f"`{e}`", n] for i, (e, n) in enumerate(expressions.most_common(10), 1)],
        ),
    ]
    two = [r for r in rows if len(_distinct_areas(r)) >= 2]
    combos = Counter(" + ".join(sorted(str(kind) for _, kind in _distinct_areas(r))) for r in two)
    lines += [
        f"**Avisos con dos o más superficies distintas:** {frac(len(two), len(rows))}. "
        "Clasificación de sus valores (`None` = sin tipo):",
        "",
    ]
    lines += (
        table(["Tipos de las superficies", "Avisos"], combos.most_common())
        if combos
        else ["Ninguno.", ""]
    )
    return lines


def _group_stats(group: Sequence[Row], *, alt: bool) -> list[object]:
    price = sum(r.price_ok for r in group)
    built = sum(bool(r.built_values) for r in group)
    strict = sum(r.available() for r in group)
    row: list[object] = [frac(price, len(group)), frac(built, len(group)), frac(strict, len(group))]
    if alt:
        row.append(frac(sum(r.available(unkinded_as_built=True) for r in group), len(group)))
    return row


def projection(
    manifest: dict[str, Any], rows: Sequence[Row], *, with_tag: bool = False
) -> tuple[list[list[object]], float, float, float, int]:
    """Filas por target, Σ total_results, estimación, desvío estándar y targets sin datos."""
    data: list[list[object]] = []
    total = estimate = variance = 0.0
    skipped = 0
    for target in manifest["targets"]:
        mine = [r for r in rows if (r.ptype, r.city) == (target["property_type"], target["city"])]
        population = target["total_results"]
        if not mine or population is None:
            skipped += 1
            data.append(
                [
                    TYPE_LABEL[target["property_type"]],
                    CITY_LABEL[target["city"]],
                    population if population is not None else "n/d",
                    len(mine),
                    "—",
                    "—",
                    "n/d",
                ]
            )
            continue
        hits = sum(r.available(with_tag=with_tag) for r in mine)
        rate = hits / len(mine)
        total += population
        estimate += population * rate
        variance += population**2 * rate * (1 - rate) / len(mine)
        data.append(
            [
                TYPE_LABEL[target["property_type"]],
                CITY_LABEL[target["city"]],
                population,
                len(mine),
                hits,
                pct(hits, len(mine)),
                f"{population * rate:.0f}",
            ]
        )
    return data, total, estimate, math.sqrt(variance), skipped


def _tag_stats(group: Sequence[Row]) -> list[object]:
    size = len(group)
    return [
        frac(sum(r.tag_built is not None for r in group), size),
        frac(sum(r.available() for r in group), size),
        frac(sum(r.available(with_tag=True) for r in group), size),
        frac(sum(r.available(with_tag=True, unkinded_as_built=True) for r in group), size),
    ]


def tag_vs_text(rows: Sequence[Row]) -> tuple[int, int]:
    """(avisos con el tag y m² construidos en el texto, de esos, con valores que no coinciden)."""
    both = [r for r in rows if r.tag_built is not None and r.built_values]
    return len(both), sum(r.tag_built not in r.built_values for r in both)


def section_tag_target(rows: Sequence[Row]) -> list[str]:
    """Efecto del tag estructurado "Superficie construida" sobre el target (solo medida)."""
    header = [
        "Con el tag",
        "Target (solo texto)",
        "Target (texto o tag)",
        "Target (texto o tag, y `kind=None` en deptos)",
    ]
    data = [[f"{label} (n={len(group)})", *_tag_stats(group)] for label, group in by_type(rows)]
    data.append([f"Total (n={len(rows)})", *_tag_stats(rows)])
    cities = [[f"{label} (n={len(group)})", *_tag_stats(group)] for label, group in by_city(rows)]
    return [
        '**Tag estructurado "Superficie construida" como fuente adicional de m² construidos** '
        "(solo medida: el parser hoy lo deja en `attributes_raw`, no en `built_area_raw`). Es un "
        "campo que carga el anunciante, con el número solo (punto 7).",
        "",
        *table(["Tipo", *header], data),
        *table(["Ciudad", *header], cities),
    ]


def section_target(manifest: dict[str, Any], rows: Sequence[Row]) -> list[str]:
    lines = [
        "## 6. Target disponible",
        "",
        "Target disponible = precio parseable + moneda conocida + m² construidos identificados "
        "(al menos una superficie de tipo `construida` en el título o la descripción). La regla "
        "alternativa **solo se mide, no se adopta**: para departamentos, aceptar también una "
        "superficie `kind=None` como construida. Más abajo se mide aparte el tag estructurado "
        '"Superficie construida" que apareció en el punto 7. **No se verificó a mano que los m² '
        "clasificados como `construida` lo sean:** `parse_area` puede confundir etiquetas "
        "contiguas (punto 5) y hay avisos con más de un valor `construida`.",
        "",
    ]
    header = ["", "Precio + moneda", "m² construidos", "Target disponible"]
    alt_header = [*header, "Con la regla alternativa (solo departamentos)"]
    type_groups = by_type(rows)
    data = []
    for label, group in type_groups:
        stats = _group_stats(group, alt=True)
        if label != TYPE_LABEL["departamento"]:
            stats[3] = "—"
        data.append([f"{label} (n={len(group)})", *stats])
    total_alt = sum(r.available(unkinded_as_built=True) for r in rows)
    data.append(
        [
            f"Total (n={len(rows)})",
            *_group_stats(rows, alt=False),
            frac(total_alt, len(rows)) + " (regla solo en deptos)",
        ]
    )
    lines += ["**Por tipo de inmueble**", "", *table(["Tipo", *alt_header[1:]], data)]
    data = []
    for label, group in by_city(rows):
        stats = _group_stats(group, alt=True)
        data.append([f"{label} (n={len(group)})", *stats])
    lines += [
        "**Por ciudad** (la regla alternativa aplica solo a los departamentos de cada ciudad)",
        "",
        *table(["Ciudad", *alt_header[1:]], data),
    ]
    data = []
    for ptype in TYPES:
        for city in CITIES:
            group = [r for r in rows if (r.ptype, r.city) == (ptype, city)]
            data.append(
                [
                    TYPE_LABEL[ptype],
                    CITY_LABEL[city],
                    len(group),
                    *_group_stats(group, alt=False)[2:],
                ]
            )
    lines += [
        "**Por tipo y ciudad** (regla estricta)",
        "",
        *table(["Tipo", "Ciudad", "n", "Target disponible"], data),
    ]

    lines += section_tag_target(rows)
    available = [r for r in rows if r.available()]
    conflicts = sum(len(r.built_values) > 1 for r in rows)
    from_price = sum(bool(r.price and r.price.is_from_price) for r in available)
    with_both, differ = tag_vs_text(rows)
    lines += [
        f"- Avisos con el tag y con m² construidos en el texto: {with_both}; en {differ} los "
        "valores no coinciden.",
        f"- Avisos con más de un valor distinto de m² construidos (cuentan como identificados): "
        f"{conflicts}.",
        f'- De los {len(available)} con target disponible, {from_price} tienen precio "desde" o '
        "rango (el builder del dataset los excluye, ADR-006).",
        "",
        "**Por origen del aviso** (los de la página 1 están sobrerrepresentados en el pool):",
        "",
    ]
    origin_rows = [
        [origin, len(group), frac(sum(r.available() for r in group), len(group))]
        for origin in ("página 1", "aleatoria", "ambas")
        if (group := [r for r in rows if r.origin == origin])
    ]
    lines += table(["Origen", "n", "Target disponible"], origin_rows)

    lines += ["**Proyección a `total_results`** (por búsqueda: total × tasa de la muestra)", ""]
    data, total, estimate, deviation, skipped = projection(manifest, rows)
    lines += table(
        ["Tipo", "Ciudad", "Resultados (portal)", "Válidos", "Disponibles", "Tasa", "Proyección"],
        data,
    )
    low, high = max(0.0, estimate - 1.96 * deviation), estimate + 1.96 * deviation
    lines += [
        f"- Σ resultados declarados por el portal: {total:.0f}"
        + (f" (sin contar {skipped} búsquedas sin datos)" if skipped else "")
        + f". Proyección de avisos con target disponible: **{estimate:.0f}** "
        f"(intervalo aproximado del 95 %: {low:.0f} a {high:.0f}; normal estratificado, tratando "
        "a la muestra como aleatoria dentro de cada búsqueda).",
        "- **Qué no captura el intervalo:** `total_results` no está deduplicado, no está filtrado "
        "por alcance (incluye terrenos y locales dentro de las categorías; docs/sources.md §2.3) y "
        "la muestra sobrerrepresenta la página 1. Es un orden de magnitud, no una cifra.",
    ]
    _, _, with_tag, tag_deviation, _ = projection(manifest, rows, with_tag=True)
    lines += [
        "- Con el tag estructurado como fuente adicional de m² construidos (solo medida): "
        f"**{with_tag:.0f}** (intervalo aproximado del 95 %: "
        f"{max(0.0, with_tag - 1.96 * tag_deviation):.0f} a "
        f"{with_tag + 1.96 * tag_deviation:.0f}).",
    ]
    random_rows = [r for r in rows if r.origin == "aleatoria"]
    population_by_type: dict[str, int] = {}
    for target in manifest["targets"]:
        if target["total_results"] is not None:
            population_by_type[target["property_type"]] = (
                population_by_type.get(target["property_type"], 0) + target["total_results"]
            )
    data = []
    projected = 0.0
    for ptype in TYPES:
        group = [r for r in random_rows if r.ptype == ptype]
        hits = sum(r.available() for r in group)
        if group:
            projected += population_by_type.get(ptype, 0) * hits / len(group)
        data.append(
            [
                TYPE_LABEL[ptype],
                population_by_type.get(ptype, 0),
                len(group),
                hits,
                pct(hits, len(group)),
                f"{population_by_type.get(ptype, 0) * hits / len(group):.0f}" if group else "n/d",
            ]
        )
    lines += [
        "",
        "Variante con solo los avisos de la página aleatoria, tasa por tipo (ciudades juntas):",
        "",
        *table(
            ["Tipo", "Resultados (portal)", "Válidos", "Disponibles", "Tasa", "Proyección"], data
        ),
        f"- Σ de esa variante: **{projected:.0f}**.",
        "",
    ]
    return lines


def structured_area_hits(
    rows: Sequence[Row], html_dir: Path | None
) -> tuple[int, Counter[str], Counter[str]]:
    """(detalles revisados, detalles con la etiqueta por ubicación, etiquetas por ubicación)."""
    scanned = 0
    pages: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    if html_dir is None:
        return 0, pages, labels
    for row in rows:
        path = html_dir / f"{hashlib.sha256(row.listing.url.encode('utf-8')).hexdigest()}.html"
        if not path.is_file():
            continue
        scanned += 1
        tree = LexborHTMLParser(path.read_text(encoding="utf-8"))
        found: dict[str, set[str]] = {
            LOCATIONS[0]: {k for k in _ficha(tree) if AREA_LABEL.search(k)},
            LOCATIONS[1]: {k for k in _tags(tree) if AREA_LABEL.search(k)},
            LOCATIONS[2]: {k for ld in _json_ld(tree) for k in ld if AREA_LABEL.search(k)},
        }
        for place, names in found.items():
            if names:
                pages[place] += 1
            for name in names:
                labels[f"{place}: {name[:40]}"] += 1
    return scanned, pages, labels


def section_structured(rows: Sequence[Row], html_dir: Path | None) -> list[str]:
    scanned, pages, labels = structured_area_hits(rows, html_dir)
    lines = ["## 7. Pista X3: ¿la superficie viene como campo estructurado?", ""]
    groups = [*by_type(rows), ("Total", list(rows))]
    lines += [
        "Según `attributes_raw` (los `span.ads_tag` que guarda el parser), por tipo de inmueble. "
        "El valor es el número solo, sin unidad; acá solo se cuenta su presencia:",
        "",
        *table(
            ["Tipo", 'Con "Superficie construida"', 'Con "Superficie de terreno m2"', "Con alguna"],
            [
                [
                    f"{label} (n={len(group)})",
                    frac(sum(r.tag_built is not None for r in group), len(group)),
                    frac(sum(r.tag_land is not None for r in group), len(group)),
                    frac(
                        sum(r.tag_built is not None or r.tag_land is not None for r in group),
                        len(group),
                    ),
                ]
                for label, group in groups
            ],
        ),
    ]
    if scanned == 0:
        return [*lines, "No se pudo revisar: la caché de HTML sanitizada no está disponible.", ""]
    lines += [
        f"Se revisó la caché sanitizada de {scanned} detalles buscando etiquetas de la ficha, "
        "`span.ads_tag` o claves del JSON-LD que nombren superficie, m², terreno o construcción "
        "(solo se reportan nombres de campo, nunca valores).",
        "",
    ]
    if not labels:
        lines += [
            "**Ningún detalle trae la superficie como campo estructurado** en ninguna de las tres "
            "ubicaciones.",
            "",
        ]
        return lines
    lines += table(
        ["Ubicación", "Detalles con alguna etiqueta"],
        [[place, frac(pages[place], scanned)] for place in LOCATIONS],
    )
    lines += table(["Etiqueta", "Detalles"], labels.most_common(20))
    return lines


def section_neighborhood(rows: Sequence[Row]) -> list[str]:
    def same_as_city(row: Row) -> bool:
        value = row.listing.neighborhood_raw
        if not value:
            return False
        cities = {_normalize(CITY_LABEL.get(row.city, "")), _normalize(row.listing.city_raw or "")}
        return _normalize(value) in cities - {""}

    data = []
    for kind, groups in (
        ("Tipo", by_type(rows)),
        ("Ciudad", by_city(rows)),
        ("", [("Total", list(rows))]),
    ):
        for label, group in groups:
            with_zone = [r for r in group if r.listing.neighborhood_raw]
            data.append(
                [
                    f"{kind} {label}".strip() + f" (n={len(group)})",
                    frac(len(with_zone), len(group)),
                    frac(sum(same_as_city(r) for r in with_zone), len(with_zone)),
                ]
            )
    return [
        "## 8. Barrio",
        "",
        '`neighborhood_raw` es la "Zona" de la ficha. "Igual a la ciudad" compara sin tildes ni '
        "mayúsculas con la ciudad de la ficha o la de la búsqueda.",
        "",
        *table(["Grupo", "Con `neighborhood_raw`", "De esos, igual a la ciudad"], data),
    ]


def section_coordinates(rows: Sequence[Row]) -> list[str]:
    def pair(row: Row) -> tuple[str, str] | None:
        lat, lon = row.listing.latitude_raw, row.listing.longitude_raw
        return (lat.strip(), lon.strip()) if lat and lon else None

    data = []
    for label, group in [*by_type(rows), ("Total", list(rows))]:
        data.append(
            [
                f"{label} (n={len(group)})",
                frac(sum(pair(r) is not None for r in group), len(group)),
                sum(
                    (r.listing.latitude_raw is None) != (r.listing.longitude_raw is None)
                    for r in group
                ),
            ]
        )
    owners: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if (coordinates := pair(row)) is not None:
            owners.setdefault(coordinates, set()).add(row.listing.source_id)
    shared = {c: ids for c, ids in owners.items() if len(ids) > 1}
    with_coordinates = sum(len(ids) for ids in owners.values())
    return [
        "## 9. Coordenadas",
        "",
        *table(["Tipo", "Con lat y lon", "Con solo una de las dos"], data),
        f"- Pares (lat, lon) compartidos por avisos distintos: {len(shared)} pares, que cubren "
        f"{sum(len(ids) for ids in shared.values())} avisos de {with_coordinates} con coordenadas.",
        "",
    ]


def section_privacy(rows: Sequence[Row]) -> list[str]:
    descriptions = [r.listing.description_raw or "" for r in rows]
    titles = [r.listing.title_raw or "" for r in rows]
    hits = Counter()
    any_hit = 0
    for text in descriptions:
        matched = [name for name, pattern in PRIVACY_PATTERNS.items() if pattern.search(text)]
        any_hit += bool(matched)
        hits.update(matched)
    data = [[name, hits[name]] for name in PRIVACY_PATTERNS]
    placeholder = [
        [name, sum(name in text for text in descriptions), sum(name in text for text in titles)]
        for name in PLACEHOLDERS
    ]
    return [
        "## 10. Privacidad (F3.5)",
        "",
        "Solo conteos. Indicios de nombres de personas en la descripción (el contrato y el "
        "sanitizador no los detectan):",
        "",
        f"- Descripciones con al menos un indicio: **{frac(any_hit, len(rows))}**.",
        "",
        *table(["Indicio", "Descripciones"], data),
        "Placeholders que dejó el sanitizador (teléfonos, emails, WhatsApp y links a terceros "
        "reemplazados antes de construir el `RawListing`):",
        "",
        *table(["Placeholder", "Descripciones", "Títulos"], placeholder),
    ]


# --------------------------------------------------------------------------------- reporte


def render(
    manifest: dict[str, Any],
    listings: Sequence[RawListing],
    requests: Sequence[dict[str, Any]],
    html_dir: Path | None,
    conclusion: str | None,
) -> str:
    rows = build_rows(listings, manifest)
    pages = manifest.get("pages_per_target")  # los manifests del piloto no lo traen
    pages_flag = f"--pages-per-target {pages} " if pages is not None else ""
    if is_pilot_design(manifest):
        random_part = "UNA página aleatoria"
    elif pages == 1:
        random_part = "ninguna página aleatoria"
    else:
        random_part = f"hasta {pages - 1} páginas aleatorias, sin reposición,"
    lines = [
        f"# Piloto de Clasipar (F3.3): reporte de la corrida del {manifest['snapshot_date']}",
        "",
        "Archivo generado por `scripts/pilot_report.py`. **Solo agregados**: no reproduce títulos, "
        "descripciones ni ningún texto de los avisos (ToS de Clasipar, ADR-007). Los precios son "
        "precios de oferta publicados, no de transacción.",
        "",
        f"- Corrida: `--source {manifest['source']} --budget {manifest['budget']} {pages_flag}"
        f"--per-target {manifest['per_target']} --seed {manifest['seed']}`; contrato "
        f"v{manifest['contract_version']}.",
        f"- Muestreo: por búsqueda (tipo × ciudad), la página 1 más {random_part} en "
        f"[2, última], y {manifest['per_target']} avisos sin reposición de la unión (plan "
        "completo en `crawl_manifest.json`, local).",
        "",
        *section_execution(manifest, requests),
        *section_sample(manifest, rows),
        *section_completeness(rows),
        *section_price(rows),
        *section_area(rows),
        *section_target(manifest, rows),
        *section_structured(rows, html_dir),
        *section_neighborhood(rows),
        *section_coordinates(rows),
        *section_privacy(rows),
        conclusion if conclusion is not None else CONCLUSION_PLACEHOLDER,
    ]
    return "\n".join(lines).rstrip() + "\n"


def existing_conclusion(output: Path) -> str | None:
    """La sección 11 del reporte anterior, si existe (la escribe una persona)."""
    if not output.is_file():
        return None
    text = output.read_text(encoding="utf-8")
    start = text.find(CONCLUSION_HEADING)
    return text[start:].rstrip() + "\n" if start >= 0 else None


def latest_snapshot(root: Path) -> str:
    candidates = sorted(
        path.parent.parent.name
        for path in (root / "data" / "interim").glob(f"*/{SOURCE}/crawl_manifest.json")
    )
    if not candidates:
        raise SystemExit("no hay ningún snapshot en data/interim: correr el crawler primero")
    return candidates[-1]


def build(root: Path, date: str) -> Path:
    interim = root / "data" / "interim" / date / SOURCE
    raw = root / "data" / "raw" / date / SOURCE
    manifest = json.loads((interim / "crawl_manifest.json").read_text(encoding="utf-8"))
    listings = [
        RawListing.model_validate_json(line)
        for line in (interim / "raw_listings.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requests = [
        json.loads(line)
        for line in (raw / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    output = root / "docs" / "pilot" / f"{date}.md"
    report = render(
        manifest, listings, requests, raw if raw.is_dir() else None, existing_conclusion(output)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8", newline="\n")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="fecha del snapshot (YYYY-MM-DD); por defecto, la última")
    parser.add_argument("--root", type=Path, default=Path("."), help="raíz del repo")
    args = parser.parse_args(argv)
    output = build(args.root, args.date or latest_snapshot(args.root))
    print(f"escrito {output}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
