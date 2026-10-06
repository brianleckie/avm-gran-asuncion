"""Sanitización de texto y HTML antes de persistirlos o de armar un RawListing (D1, D3).

Reglas (CLAUDE.md): nunca se persisten teléfonos, emails, WhatsApp ni datos de anunciantes.
- `scrub_contacts` reemplaza teléfonos, emails y links de WhatsApp en un texto. Lo usa el parser
  antes de construir el `RawListing` (el rechazo de `avm.contract` queda como red de seguridad) y
  `sanitize_html`.
- `sanitize_html` prepara el HTML que se escribe en la caché: recorta lo irrelevante, elimina los
  nodos de anunciante que le indique cada fuente y falla cerrado (`SanitizationError`) si después
  queda un rastro. Lo que sí identifica a cada fuente (los selectores) vive en su módulo, en
  `avm.scraping.sources`.

Los nombres de personas no se detectan con un regex: el sanitizador elimina los bloques donde
aparecen (según la estructura observada de cada fuente), así que un nombre escrito en texto libre
(título o descripción) no se puede quitar.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from selectolax.lexbor import LexborHTMLParser

from avm.contract.pii import EMAIL, PHONE, find_pii

# Más amplio que el detector de avm.contract.pii: acepta el link con o sin esquema ("wa.me/…").
WHATSAPP = re.compile(r"(?:https?:)?(?://)?(?:wa\.me|api\.whatsapp\.com)/[^\s\"'<]*", re.I)

# Rastros de un anunciante que no pueden quedar en lo que se persiste: el slug de su perfil, el
# logo de una empresa y la foto de un usuario.
FORBIDDEN_FRAGMENTS = ("/empresa/", "/corporate/", "/users/")

_DROP = re.compile(
    r"<script(?![^>]*application/ld\+json)[^>]*>.*?</script>"
    r"|<(style|svg|iframe|noscript)\b[^>]*>.*?</\1>"
    r"|<!--.*?-->",
    re.S | re.I,
)


class SanitizationError(RuntimeError):
    """Después de sanitizar quedó un rastro de datos personales: no se debe persistir."""


def scrub_contacts(text: str) -> str:
    """Teléfonos -> [TELEFONO], emails -> [EMAIL], links de WhatsApp -> [WHATSAPP]."""
    text = WHATSAPP.sub("[WHATSAPP]", text)
    text = EMAIL.sub("[EMAIL]", text)
    return PHONE.sub("[TELEFONO]", text)


def trim(page: str) -> str:
    """Quita <script> (salvo JSON-LD), <style>, <svg>, <iframe>, <noscript> y comentarios."""
    page = _DROP.sub("", page)
    return re.sub(r"\n\s*\n+", "\n", page)


def sanitize_html(
    page: str, *, drop_selectors: Sequence[str], drop_img_src: Sequence[str] = ()
) -> str:
    """HTML apto para la caché: recortado, sin los nodos de anunciante y sin contactos.

    - `drop_selectors`: selectores CSS de los nodos que se eliminan completos.
    - `drop_img_src`: fragmentos de `src`; las imágenes que los contengan se eliminan (logos y
      fotos de perfil, que identifican al anunciante aunque se borre su nombre).
    Lanza `SanitizationError` si el resultado todavía tiene un rastro de anunciante o un contacto.
    El mensaje nunca repite el dato.
    """
    tree = LexborHTMLParser(trim(page))
    for selector in drop_selectors:
        # Se vuelve a consultar por selector: un nodo ya eliminado con su padre no existe más.
        for node in tree.css(selector):
            node.decompose()
    for image in tree.css("img"):
        src = image.attributes.get("src") or ""
        if any(fragment in src for fragment in drop_img_src):
            image.decompose()
    cleaned = scrub_contacts(tree.html or "")
    _assert_clean(cleaned)
    return cleaned


def _assert_clean(page: str) -> None:
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in page:
            raise SanitizationError(f"quedó una referencia a un anunciante ({fragment})")
    if found := find_pii(page):
        raise SanitizationError(f"quedaron datos personales ({', '.join(found)})")
