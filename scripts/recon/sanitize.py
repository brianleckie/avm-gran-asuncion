"""Convierte páginas crudas en fixtures: recorta lo irrelevante y reemplaza datos personales.

Uso (desde la raíz del repo):
    $env:PYTHONPATH = "scripts"
    uv run python -m recon.sanitize clasipar <crudo>=<fixture> [<crudo>=<fixture> ...]

Reemplazos: teléfonos -> [TELEFONO], emails -> [EMAIL], links de WhatsApp -> [WHATSAPP], nombres
de anunciantes (personas o inmobiliarias) -> [NOMBRE], su slug de /empresa/ -> [EMPRESA] y sus
logos y fotos de perfil -> [LOGO] / [FOTO_PERFIL]. Las
reglas de nombres dependen de la estructura observada en cada fuente, así que el resultado se
revisa a mano: el test tests/scraping/test_fixtures_pii.py cubre teléfonos y emails, no nombres.

Recorte: se quitan <script> (salvo JSON-LD), <style>, <svg>, <iframe>, <noscript> y comentarios.
Se conservan los <span> con font-size:0 (marca de agua de Clasipar): son parte de la estructura
real que el parser de F3.4 tiene que saber ignorar. Se escribe en UTF-8 con finales de línea LF.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from avm.contract.pii import EMAIL, PHONE

RECON_DIR = Path("data/raw/recon")
FIXTURES_DIR = Path("tests/fixtures")
MAX_FIXTURE_BYTES = 450_000

# Teléfonos y emails: los mismos patrones con los que RawListing rechaza datos personales.
# WhatsApp va aparte porque acá hay que reemplazar el link entero, no solo detectarlo.
WHATSAPP = re.compile(r"(?:https?:)?//(?:wa\.me|api\.whatsapp\.com)/[^\s\"'<]*", re.I)

_DROP = re.compile(
    r"<script(?![^>]*application/ld\+json)[^>]*>.*?</script>"
    r"|<(style|svg|iframe|noscript)\b[^>]*>.*?</\1>"
    r"|<!--.*?-->",
    re.S | re.I,
)


def trim(page: str) -> str:
    page = _DROP.sub("", page)
    return re.sub(r"\n\s*\n+", "\n", page)


def scrub_contacts(page: str) -> str:
    page = WHATSAPP.sub("[WHATSAPP]", page)
    page = EMAIL.sub("[EMAIL]", page)
    return PHONE.sub("[TELEFONO]", page)


def scrub_clasipar_names(page: str) -> str:
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


SCRUBBERS = {"clasipar": scrub_clasipar_names}


def build(source: str, raw_name: str, fixture_name: str) -> Path:
    page = (RECON_DIR / source / f"{raw_name}.body").read_text(encoding="utf-8")
    page = SCRUBBERS[source](scrub_contacts(trim(page)))
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
