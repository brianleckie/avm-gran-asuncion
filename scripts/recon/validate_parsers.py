"""Pasa strings crudos reales de precio y superficie por parse_price / parse_area (F3.1).

Uso (desde la raíz del repo):
    $env:PYTHONPATH = "src;scripts"
    uv run python -m recon.validate_parsers <fuente> [--ver]

Lee el crudo de data/raw/recon/<fuente>/ y muestra solo conteos y los formatos que fallan: no
guarda nada. Cuando la página trae el valor estructurado (JSON embebido), un parseo cuenta como
"ok" solo si coincide con ese valor; si no, cuenta como "fallo" (con motivo). No toca parsing.py.
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from avm.pipeline.parsing import parse_area, parse_price

RECON_DIR = Path("data/raw/recon")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_CURRENCY_NAMES = {"U$S": "USD", "Gs.": "PYG"}


@dataclass(frozen=True, slots=True)
class Sample:
    kind: str  # "precio" | "superficie"
    raw: str
    # Valores estructurados válidos en la misma página (None si la fuente no los expone).
    expected: frozenset[tuple[Decimal, str | None]] | frozenset[Decimal] | None


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<!--.*?-->|<[^>]+>", "", fragment)).strip()


def infocasas_samples(page: str) -> Iterator[Sample]:
    match = _NEXT_DATA.search(page)
    if match is None:
        return
    fetch_result = json.loads(match.group(1))["props"]["pageProps"].get("fetchResult")
    if not fetch_result or "searchFast" not in fetch_result:
        return  # no es un listado (home, FAQ)
    items = fetch_result["searchFast"]["data"]
    prices = frozenset(
        (Decimal(x["price"]["amount"]), _CURRENCY_NAMES.get(x["price"]["currency"]["name"]))
        for x in items
    )
    areas = frozenset(Decimal(x[k]) for x in items for k in ("m2", "m2Built") if x.get(k))
    for raw in re.findall(r'<p class="main-price">(.*?)</p>', page, re.S):
        yield Sample("precio", _text(raw), prices)
    for raw in re.findall(r"<strong>([^<]*(?:<!--[^>]*-->[^<]*)*m²)</strong>", page):
        yield Sample("superficie", _text(raw), areas)


_WATERMARK = re.compile(r'<span style="font-size:0 !important;"[^>]*>.*?</span>', re.S)
_AREA_HINT = re.compile(r"\d\s*(?:m2|m²|mt2|mts2|mts²|metros cuadrados)|\d\s*[x×]\s*\d", re.I)


def clasipar_samples(page: str) -> Iterator[Sample]:
    """Clasipar no expone valores estructurados de precio ni superficie: expected=None.

    Superficie: no hay campo propio; se toman las líneas de título y descripción que mencionan
    m² o dimensiones AxB, que es lo que tendría que leer el pipeline.
    """
    page = _WATERMARK.sub("", page)  # marca de agua invisible: no es parte del texto
    for raw in re.findall(r'<(?:p|h3) class="(?:price|user-price)">(.*?)</(?:p|h3)>', page, re.S):
        yield Sample("precio", _text(raw), None)
    titles = re.findall(r'class="titAnuncio"[^>]*>(.*?)</a>', page, re.S)
    descriptions = re.findall(r'<p class="desc-user">(.*?)</p>', page, re.S)
    for block in titles + descriptions:
        for line in re.split(r"<br\s*/?>|\n", block):
            line = _text(line)
            if _AREA_HINT.search(line):
                yield Sample("superficie", line, None)


EXTRACTORS = {"infocasas": infocasas_samples, "clasipar": clasipar_samples}


def check(sample: Sample) -> tuple[bool, str]:
    if sample.kind == "precio":
        parsed = parse_price(sample.raw)
        if parsed is None:
            return False, "None"
        if sample.expected is not None and (parsed.amount, parsed.currency) not in sample.expected:
            return False, f"no coincide con el JSON ({parsed.amount} {parsed.currency})"
        detail = f"moneda={parsed.currency}"
        return True, detail + (" desde" if parsed.is_from_price else "")
    parsed_area = parse_area(sample.raw)
    if parsed_area is None:
        return False, "None"
    if sample.expected is not None and parsed_area.m2 not in sample.expected:
        return False, f"no coincide con el JSON ({parsed_area.m2})"
    return True, f"kind={parsed_area.kind}"


def main(source: str, verbose: bool = False) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    # Se cuentan ocurrencias: un aviso destacado repetido en varias páginas cuenta varias veces.
    samples = [
        sample
        for path in sorted((RECON_DIR / source).glob("*.body"))
        for sample in EXTRACTORS[source](path.read_text(encoding="utf-8", errors="replace"))
    ]
    if verbose:  # para revisar a mano las fuentes sin valores estructurados
        for s in samples:
            parsed = parse_price(s.raw) if s.kind == "precio" else parse_area(s.raw)
            print(f"[{s.kind}] {s.raw!r} -> {parsed}")
    for kind in ("precio", "superficie"):
        results = [(s, *check(s)) for s in samples if s.kind == kind]
        ok = [r for r in results if r[1]]
        print(f"== {source} / {kind}: {len(ok)}/{len(results)} ok")
        print("   ok por detalle:", dict(Counter(r[2] for r in ok)))
        failures = Counter((r[2], r[0].raw) for r in results if not r[1])
        for (reason, raw), n in failures.most_common(30):
            print(f"   FALLA x{n}: {raw!r} -> {reason}")
        shapes = Counter(re.sub(r"\d", "9", s.raw) for s, *_ in results)
        print("   formatos:", dict(shapes.most_common(12)))


if __name__ == "__main__":
    main(sys.argv[1], verbose="--ver" in sys.argv[2:])
