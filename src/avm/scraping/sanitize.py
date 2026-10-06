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
from collections.abc import Callable, Collection, Sequence
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from avm.contract.pii import EMAIL, PHONE, find_pii

# Más amplio que el detector de avm.contract.pii: acepta el link con o sin esquema ("wa.me/…").
WHATSAPP = re.compile(r"(?:https?:)?(?://)?(?:wa\.me|api\.whatsapp\.com)/[^\s\"'<\\]*", re.I)
# Link con esquema o "www.": el sitio de un anunciante identifica a quien publica (D1). Acepta
# "https:" sin barras: así reescribe Clasipar los links dentro del JSON-LD.
URL = re.compile(r"(?:https?:/{0,2}|www\.)[^\s<>\"'\\]+", re.I)

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


def scrub_urls(text: str, allowed_hosts: Collection[str]) -> str:
    """Reemplaza por [URL] los links a hosts que no son `allowed_hosts` (ni sus subdominios)."""

    def replace(match: re.Match[str]) -> str:
        link = match.group(0)
        if "//" not in link:  # "www.sitio.com" o "https:sitio.com" (sin barras)
            link = "//" + link.partition(":")[2] if link.lower().startswith("http") else f"//{link}"
        host = (urlsplit(link).hostname or "").lower()
        # Si no se puede determinar el host se reemplaza: ante la duda, no se persiste.
        if host and any(host == ok or host.endswith(f".{ok}") for ok in allowed_hosts):
            return match.group(0)
        return "[URL]"

    return URL.sub(replace, text)


def trim(page: str) -> str:
    """Quita <script> (salvo JSON-LD), <style>, <svg>, <iframe>, <noscript> y comentarios."""
    page = _DROP.sub("", page)
    return re.sub(r"\n\s*\n+", "\n", page)


def _rewrite(node: LexborNode, fix: Callable[[str], str]) -> None:
    """Aplica `fix` al contenido de un nodo: al atributo `content` de un <meta>, o a su HTML."""
    if node.tag == "meta":
        content = node.attributes.get("content")
        if content:
            node.attrs["content"] = fix(content)
        return
    replacement = LexborHTMLParser(fix(node.html or "")).css_first(node.tag or "")
    if replacement is None:  # no se pudo reescribir: ante la duda se elimina el nodo entero
        node.decompose()
    else:
        node.replace_with(replacement)


def sanitize_html(
    page: str,
    *,
    drop_selectors: Sequence[str],
    drop_img_src: Sequence[str] = (),
    scrub_urls_in: Sequence[str] = (),
    allowed_url_hosts: Collection[str] = (),
) -> str:
    """HTML apto para la caché: recortado, sin los nodos de anunciante y sin contactos.

    - `drop_selectors`: selectores CSS de los nodos que se eliminan completos.
    - `drop_img_src`: fragmentos de `src`; las imágenes que los contengan se eliminan (logos y
      fotos de perfil, que identifican al anunciante aunque se borre su nombre).
    - `scrub_urls_in`: selectores de los nodos de texto libre (descripción, JSON-LD, `<meta>`)
      donde se reemplaza por [URL] todo link a un host fuera de `allowed_url_hosts`. Los `href` y
      `src` del resto del HTML no se tocan.
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
    for selector in scrub_urls_in:
        for node in tree.css(selector):
            _rewrite(node, lambda text: scrub_urls(text, allowed_url_hosts))
    cleaned = scrub_contacts(tree.html or "")
    _assert_clean(cleaned)
    return cleaned


def _assert_clean(page: str) -> None:
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in page:
            raise SanitizationError(f"quedó una referencia a un anunciante ({fragment})")
    if found := find_pii(page):
        raise SanitizationError(f"quedaron datos personales ({', '.join(found)})")
