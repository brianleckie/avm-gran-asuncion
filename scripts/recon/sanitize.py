"""Convierte páginas crudas en fixtures: recorta lo irrelevante y elimina datos personales.

Uso (desde la raíz del repo):
    $env:PYTHONPATH = "scripts"
    uv run python -m recon.sanitize clasipar <crudo>=<fixture> [<crudo>=<fixture> ...]

Usa el MISMO sanitizador que la caché del scraper (`avm.scraping.sources.clasipar`): elimina los
bloques de anunciante (nombre, perfil, logo, foto y contacto enmascarado), las imágenes de logo y
de perfil, y reemplaza teléfonos -> [TELEFONO], emails -> [EMAIL] y WhatsApp -> [WHATSAPP]. Falla
cerrado si queda un rastro. Los nombres de personas escritos en texto libre (título o descripción)
no se pueden detectar con un regex: el resultado se revisa a mano, y el test
tests/scraping/test_fixtures_pii.py cubre teléfonos y emails, no nombres.

Recorte: se quitan <script> (salvo JSON-LD), <style>, <svg>, <iframe>, <noscript> y comentarios.
Se conservan los <span> con font-size:0 (marca de agua de Clasipar): son parte de la estructura
real que el parser tiene que saber ignorar. Se escribe en UTF-8 con finales de línea LF.

Los fixtures detalle_1, detalle_2 y listado se generaron con la versión anterior
(`scrub_clasipar_names`, que reemplaza nombres por [NOMBRE] en lugar de eliminar los bloques).
Esa función queda por compatibilidad con sus tests y NO se usa en producción ni en `build`.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

from avm.scraping.sources.clasipar import sanitize_clasipar_html

RECON_DIR = Path("data/raw/recon")
FIXTURES_DIR = Path("tests/fixtures")
MAX_FIXTURE_BYTES = 450_000

# Una fuente sin sanitizador no se puede guardar: nunca se persiste HTML crudo (CLAUDE.md).
SANITIZERS: dict[str, Callable[[str], str]] = {"clasipar": sanitize_clasipar_html}


def scrub_clasipar_names(page: str) -> str:
    """Versión anterior (placeholders [NOMBRE]); ver el docstring del módulo."""
    empresa = r"https://clasipar\.paraguay\.com/empresa/"
    # Slug del anunciante (incluye su nombre).
    page = re.sub(empresa + r"[^\"'\s<]+", "https://clasipar.paraguay.com/empresa/[EMPRESA]", page)
    # <a href=".../empresa/..." title="NOMBRE">NOMBRE</a>  ("Vendido por", logo, "Premium")
    page = re.sub(
        r'(<a href="https://clasipar\.paraguay\.com/empresa/\[EMPRESA\]"[^>]*?)title="[^"]*"',
        r'\1title="[NOMBRE]"',
        page,
    )
    page = re.sub(
        r'(<a href="https://clasipar\.paraguay\.com/empresa/\[EMPRESA\]"[^>]*>)(?!\s*<)[^<]+(</a>)',
        lambda m: m.group(1) + ("Premium" if "btn-link" in m.group(1) else "[NOMBRE]") + m.group(2),
        page,
    )
    # Logo/avatar del anunciante: alt/title con su nombre, y la foto de perfil del usuario.
    page = re.sub(
        r'(<span class="box-anuncio__logo">.*?</span>)',
        lambda m: re.sub(r'(alt|title)="[^"]*"', r'\1="[NOMBRE]"', m.group(1)),
        page,
        flags=re.S,
    )
    # Logos de inmobiliarias: la imagen identifica al anunciante aunque se borre el nombre.
    page = re.sub(r'src="[^"]*/corporate/[^"]*"', 'src="[LOGO]"', page)
    header = re.compile(r'(<div class="infoAnunciante__header">)(.*?)(</h5>)', re.S)

    def _header(m: re.Match[str]) -> str:
        inner = re.sub(r'(alt|title)="[^"]*"', r'\1="[NOMBRE]"', m.group(2))
        inner = re.sub(r'src="[^"]*/users/[^"]*"', 'src="[FOTO_PERFIL]"', inner)
        inner = re.sub(r"(<h5>)\s*[^<]+", r"\1 [NOMBRE]", inner)
        return m.group(1) + inner + m.group(3)

    return header.sub(_header, page)


def build(source: str, raw_name: str, fixture_name: str) -> Path:
    page = (RECON_DIR / source / f"{raw_name}.body").read_text(encoding="utf-8")
    page = SANITIZERS[source](page)
    size = len(page.encode("utf-8"))
    if size > MAX_FIXTURE_BYTES:
        raise SystemExit(
            f"{raw_name}: {size} B > {MAX_FIXTURE_BYTES} B, guardar solo el bloque útil"
        )
    out = FIXTURES_DIR / source / f"{fixture_name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


def main(argv: list[str]) -> None:
    source, *pairs = argv
    for pair in pairs:
        raw_name, fixture_name = pair.split("=", 1)
        out = build(source, raw_name, fixture_name)
        print(f"{out}: {out.stat().st_size} B")


if __name__ == "__main__":
    main(sys.argv[1:])
