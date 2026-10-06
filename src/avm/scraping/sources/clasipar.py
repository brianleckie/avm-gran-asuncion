"""Clasipar (clasipar.paraguay.com): sanitizador, parser offline y URLs de búsqueda (F3.4, F3.3).

Todo lo específico de la fuente vive acá. Los selectores salen de docs/sources.md (§2.3 a §2.7) y
están documentados en la sección "Selectores implementados (F3.4)" del mismo archivo. El parser
trabaja sobre el HTML YA SANITIZADO de la caché (D1), pero también acepta HTML sin sanitizar: nunca
extrae el nombre ni los datos de contacto del anunciante, y pasa todo texto por `scrub_contacts` y
`scrub_urls` antes de construir el `RawListing` (D3); el rechazo de `avm.contract` queda como red
de seguridad.

Qué hay dónde (docs/sources.md §2.4):
- Tarjeta del listado: URL, título, precio, operación y tipo de anunciante ("Ofrecido por").
- Detalle del aviso: ficha, atributos, descripción y JSON-LD. NO tiene la operación ni el tipo de
  anunciante del aviso: lo que aparece ahí es de 3 avisos relacionados y de una plantilla JS. Por
  eso `parse_detail` los toma de la tarjeta (`ListingRef`).

`content_hash` (D2): sha256 de un JSON canónico (claves ordenadas, UTF-8, sin espacios extra) con
todos los campos de contenido del `RawListing`, salvo `scraped_at`, `content_hash` y los atributos
volátiles. Dos requests del mismo aviso sin cambios reales dan el mismo hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Any, Final
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from avm.contract import City, PropertyType, RawListing, Source
from avm.scraping.sanitize import sanitize_html, scrub_contacts, scrub_urls

HOST: Final = "clasipar.paraguay.com"
BASE_URL: Final = f"https://{HOST}"

# Nodos con datos del anunciante (nombre, perfil, logo, contacto enmascarado) que no se persisten.
ADVERTISER_SELECTORS: Final = (
    ".infoAnunciante__header",  # detalle: nombre, foto o logo y link al perfil
    ".infoAnunciante__datos",  # detalle: formulario con teléfono y email enmascarados
    "span.box-anuncio__logo",  # tarjeta de listado: logo con el nombre en alt y title
    'a[href*="/empresa/"]',  # "Vendido por <nombre>" y cualquier otro link al perfil
)
# Logos de empresa y fotos de perfil: identifican al anunciante aunque se borre su nombre.
ADVERTISER_IMG_SRC: Final = ("/corporate/", "/users/")

# Textos libres donde un anunciante puede dejar el link a su sitio o a sus redes (D1): la
# descripción, el JSON-LD (repite la descripción) y los <meta> de descripción.
URL_SCRUB_SELECTORS: Final = ("p.desc-user", 'script[type="application/ld+json"]', "meta[content]")
# Links que NO se reemplazan: el propio portal, su CDN y el vocabulario de schema.org del JSON-LD.
ALLOWED_URL_HOSTS: Final = ("clasipar.paraguay.com", "clasicdn.paraguay.com", "schema.org")

# Tags (`span.ads_tag`) con la superficie estructurada que carga el anunciante (docs/sources.md
# §8.4 y docs/pilot/2026-10-06.md §7). Solo estas dos etiquetas, que son inequívocas, se llevan a
# su campo del RawListing; cualquier otra etiqueta con "superficie" queda en `attributes_raw` hasta
# que se decida qué significa. Clave: la etiqueta en minúsculas (`casefold`).
AREA_TAGS: Final = {
    "superficie construida": "built_area_raw",
    "superficie de terreno m2": "land_area_raw",
}

# Atributos que cambian sin que cambie el aviso: no entran al content_hash.
VOLATILE_ATTRIBUTES: Final = frozenset({"patrocinado", "Nro. de Visitas"})
SPONSORED_KEY: Final = "patrocinado"

_WATERMARK: Final = 'span[style*="font-size:0"]'  # marca de agua: por estilo, no por clase
_SPONSORED_CLASSES: Final = ("box-anuncio--premium", "box-anuncio--destacado")
_PROPERTY_TYPES: Final = ("House", "Apartment")
_BR = re.compile(r"<br\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_ID_SUFFIX = re.compile(r"-(\d+)/?$")
_CATEGORY = re.compile(r"^/inmuebles/([^/]+)/")
_RESULTS = re.compile(r"^(\d[\d.]*)\s+Resultados$")


class ClasiparParseError(ValueError):
    """La página no tiene la estructura esperada (cambió el HTML de la fuente)."""


def sanitize_clasipar_html(page: str) -> str:
    """HTML de Clasipar apto para la caché: sin datos de anunciantes ni contactos (D1)."""
    return sanitize_html(
        page,
        drop_selectors=ADVERTISER_SELECTORS,
        drop_img_src=ADVERTISER_IMG_SRC,
        scrub_urls_in=URL_SCRUB_SELECTORS,
        allowed_url_hosts=ALLOWED_URL_HOSTS,
    )


# ---------------------------------------------------------------------------------- helpers


def _scrub(text: str) -> str:
    """Contactos -> placeholders y links a sitios de terceros -> [URL] (D1, D3)."""
    return scrub_urls(scrub_contacts(text), ALLOWED_URL_HOSTS)


def _lines(node: LexborNode | None) -> list[str]:
    """Líneas de texto de un nodo (los <br> separan líneas), sin la marca de agua."""
    if node is None:
        return []
    for mark in node.css(_WATERMARK):
        mark.decompose()
    text = unescape(_TAGS.sub("", _BR.sub("\n", node.html or "")))
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _inline(node: LexborNode | None) -> str | None:
    """Texto de un nodo en una sola línea, sin la marca de agua y con contactos reemplazados."""
    text = " ".join(_lines(node))
    return _scrub(text) if text else None


def _source_id_from_url(url: str) -> str | None:
    match = _ID_SUFFIX.search(urlsplit(url).path)
    return match.group(1) if match else None


def _is_sponsored(card: LexborNode) -> bool:
    classes = (card.attributes.get("class") or "").split()
    return any(name in classes for name in _SPONSORED_CLASSES)


# ---------------------------------------------------------------------------------- listado


@dataclass(frozen=True, slots=True)
class ListingRef:
    """Referencia a un aviso, tomada de su tarjeta en una página de listado."""

    url: str
    source_id: str
    patrocinado: bool
    title_raw: str | None = None
    price_raw: str | None = None
    operation_raw: str | None = None
    advertiser_type_raw: str | None = None


@dataclass(frozen=True, slots=True)
class ListingPage:
    """Una página de listado. Las páginas de una búsqueda se recorren con `next_url`."""

    refs: tuple[ListingRef, ...]
    next_url: str | None
    current_page: int | None
    last_page: int | None
    total_results: int | None

    @property
    def has_more(self) -> bool:
        """Hay una página siguiente: por `rel="next"` o porque la actual no es la última."""
        if self.next_url is not None:
            return True
        return (
            self.current_page is not None
            and self.last_page is not None
            and self.current_page < self.last_page
        )


def _card_ref(card: LexborNode) -> ListingRef:
    anchor = card.css_first("a.titAnuncio")
    href = (anchor.attributes.get("href") if anchor is not None else None) or ""
    url = urljoin(BASE_URL, href.strip())
    source_id = _source_id_from_url(url)
    if anchor is None or source_id is None:
        raise ClasiparParseError("una tarjeta del listado no tiene link ni id de aviso")
    strongs = [" ".join(strong.text().split()) for strong in card.css("h6 strong")]
    return ListingRef(
        url=url,
        source_id=source_id,
        patrocinado=_is_sponsored(card),
        title_raw=_inline(anchor),
        price_raw=_inline(card.css_first("p.price")),
        operation_raw=(strongs[0] or None) if strongs else None,
        advertiser_type_raw=(strongs[1] or None) if len(strongs) > 1 else None,
    )


def _pagination(tree: LexborHTMLParser) -> tuple[int | None, int | None]:
    pages = [
        int(page)
        for link in tree.css("ul#pagination a[data-page]")
        if (page := link.attributes.get("data-page")) and page.isdigit()
    ]
    active = tree.css_first("ul#pagination li.active a[data-page]")
    current = active.attributes.get("data-page") if active is not None else None
    return (int(current) if current and current.isdigit() else None), (
        max(pages) if pages else None
    )


def _total_results(tree: LexborHTMLParser) -> int | None:
    for strong in tree.css("small strong"):
        match = _RESULTS.match(" ".join(strong.text().split()))
        if match:
            return int(match.group(1).replace(".", ""))
    return None


def parse_listing_page(html: str) -> ListingPage:
    """Tarjetas (orgánicas y patrocinadas) de una página de listado, más la paginación."""
    tree = LexborHTMLParser(html)
    refs = tuple(_card_ref(card) for card in tree.css("article.box-anuncio"))
    link = tree.css_first('link[rel="next"]')
    next_href = (link.attributes.get("href") if link is not None else None) or None
    current, last = _pagination(tree)
    return ListingPage(
        refs=refs,
        next_url=urljoin(BASE_URL, next_href) if next_href else None,
        current_page=current,
        last_page=last,
        total_results=_total_results(tree),
    )


def merge_refs(refs: Iterable[ListingRef]) -> list[ListingRef]:
    """Deduplica por `source_id` conservando el orden; es patrocinado si alguna aparición lo es."""
    merged: dict[str, ListingRef] = {}
    for ref in refs:
        seen = merged.get(ref.source_id)
        if seen is None:
            merged[ref.source_id] = ref
        elif ref.patrocinado and not seen.patrocinado:
            merged[ref.source_id] = ListingRef(
                url=seen.url,
                source_id=seen.source_id,
                patrocinado=True,
                title_raw=seen.title_raw,
                price_raw=seen.price_raw,
                operation_raw=seen.operation_raw,
                advertiser_type_raw=seen.advertiser_type_raw,
            )
    return list(merged.values())


# ---------------------------------------------------------------------------------- detalle


def _ficha(tree: LexborHTMLParser) -> dict[str, str]:
    """Pares etiqueta-valor de la ficha (`.anuncio-detalles`), sin los ":" finales."""
    ficha: dict[str, str] = {}
    for item in tree.css(".anuncio-detalles .grid__item"):
        label, value = item.css_first("span"), item.css_first("h6")
        if label is None or value is None:
            continue  # el botón "Ver Mapa" no es un par
        key = " ".join(label.text().split()).rstrip(":").strip()
        text = " ".join(value.text().split())
        if key and text:
            ficha[key] = text
    return ficha


def _tags(tree: LexborHTMLParser) -> dict[str, str]:
    """Atributos del aviso (`span.ads_tag`): "Dormitorios: 2", "Quincho: SI"..."""
    tags: dict[str, str] = {}
    for tag in tree.css("span.ads_tag"):
        strong = tag.css_first("strong")
        label = " ".join(tag.text().split()).partition(":")[0].strip()
        value = " ".join(strong.text().split()) if strong is not None else ""
        if label and value:
            tags[label] = value
    return tags


def _json_ld(tree: LexborHTMLParser) -> Iterator[dict[str, Any]]:
    """Objetos JSON-LD. Vienen mal formados (saltos de línea sin escapar): strict=False."""
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text(), strict=False)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                yield item


def _coordinate(ld: Mapping[str, Any], key: str) -> str | None:
    value = ld.get(key)
    return _scrub(value) if isinstance(value, str) and value.strip() else None


def _category_from_breadcrumb(tree: LexborHTMLParser) -> str | None:
    """Segmento de categoría del breadcrumb JSON-LD ("Inmuebles / Casas" -> "Casas")."""
    for item in _json_ld(tree):
        if item.get("@type") != "BreadcrumbList":
            continue
        for element in item.get("itemListElement") or []:
            is_second = isinstance(element, dict) and element.get("position") == 2
            entry = element.get("item") if is_second else None
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str) and " / " in name:
                return name.partition(" / ")[2].strip() or None
    return None


def _property_type_raw(url: str, tree: LexborHTMLParser) -> str | None:
    match = _CATEGORY.match(urlsplit(url).path)
    return match.group(1) if match else _category_from_breadcrumb(tree)


def _canonical_hash(content: Mapping[str, Any]) -> str:
    fields = dict(content)
    fields["attributes_raw"] = {
        key: value
        for key, value in (fields.get("attributes_raw") or {}).items()
        if key not in VOLATILE_ATTRIBUTES
    }
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_content_hash(listing: RawListing) -> str:
    """Recalcula el content_hash (D2) de un RawListing: sirve para verificar el almacenado."""
    return _canonical_hash(listing.model_dump(mode="json", exclude={"scraped_at", "content_hash"}))


def parse_detail(
    html: str, url: str, scraped_at: datetime, *, ref: ListingRef | None = None
) -> RawListing:
    """Página de detalle de un aviso -> `RawListing`.

    `ref` es la tarjeta del mismo aviso en el listado: de ahí salen la operación y el tipo de
    anunciante (el detalle no los trae) y la marca de patrocinado (D5, volátil: no entra al hash).
    """
    tree = LexborHTMLParser(html)
    ficha, tags = _ficha(tree), _tags(tree)
    url_id = _source_id_from_url(url)
    source_id = ficha.get("Nro. de Anuncio") or url_id
    if source_id is None:
        raise ClasiparParseError("el aviso no tiene Nro. de Anuncio ni id en la URL")
    if url_id is not None and source_id != url_id:
        raise ClasiparParseError("el Nro. de Anuncio no coincide con el id de la URL")

    ld = next((item for item in _json_ld(tree) if item.get("@type") in _PROPERTY_TYPES), {})
    description = [_scrub(line) for line in _lines(tree.css_first("p.desc-user"))]
    areas = {
        AREA_TAGS[key.casefold()]: _scrub(value)
        for key, value in tags.items()
        if key.casefold() in AREA_TAGS
    }
    attributes = {
        key: _scrub(value)
        for key, value in tags.items()
        if key not in ("Dormitorios", "Baños") and key.casefold() not in AREA_TAGS
    }
    if "Departamento" in ficha:  # el departamento geográfico ("Central"), no el tipo de inmueble
        attributes["Departamento"] = _scrub(ficha["Departamento"])
    if ref is not None and ref.patrocinado:
        attributes[SPONSORED_KEY] = "si"

    def scrubbed(value: str | None) -> str | None:
        return _scrub(value) if value else None

    content: dict[str, Any] = {
        "source": Source.CLASIPAR.value,
        "source_id": source_id,
        "url": url,
        "title_raw": _inline(tree.css_first("h1.tit-anuncio")),
        "description_raw": "\n".join(description) or None,
        "price_raw": _inline(tree.css_first("h3.user-price")),
        "currency_raw": None,  # va dentro del string del precio
        "built_area_raw": areas.get("built_area_raw"),  # tag "Superficie construida", si lo hay
        "land_area_raw": areas.get("land_area_raw"),  # tag "Superficie de terreno m2", si lo hay
        "bedrooms_raw": scrubbed(tags.get("Dormitorios")),
        "bathrooms_raw": scrubbed(tags.get("Baños")),
        "garages_raw": None,
        "property_type_raw": _property_type_raw(url, tree),
        "operation_raw": ref.operation_raw if ref is not None else None,
        "city_raw": scrubbed(ficha.get("Ciudad")),
        "neighborhood_raw": scrubbed(ficha.get("Zona")),
        "address_raw": None,
        "latitude_raw": _coordinate(ld, "latitude"),
        "longitude_raw": _coordinate(ld, "longitude"),
        "published_at_raw": scrubbed(ficha.get("Publicado el")),
        "advertiser_type_raw": ref.advertiser_type_raw if ref is not None else None,
        "attributes_raw": attributes,
    }
    return RawListing(**content, scraped_at=scraped_at, content_hash=_canonical_hash(content))


# ---------------------------------------------------------------------------------- búsqueda

_CATEGORY_SLUG: Final = {
    PropertyType.HOUSE: "casas",
    PropertyType.APARTMENT: "departamentos",
    PropertyType.DUPLEX: "duplex",
}
_LOCALITY_SLUG: Final = {
    City.ASUNCION: "asuncion-3",
    City.LUQUE: "luque-30",
    City.SAN_LORENZO: "san-lorenzo-35",
    City.FERNANDO_DE_LA_MORA: "fernando-de-la-mora-23",
}


@dataclass(frozen=True, slots=True)
class SearchTarget:
    """Una búsqueda de venta: tipo de inmueble × ciudad."""

    property_type: PropertyType
    city: City
    url: str


def search_urls() -> tuple[SearchTarget, ...]:
    """Las 12 búsquedas de venta (3 tipos × 4 ciudades) de docs/sources.md §2.3.

    No incluye `residencias-mansiones` (categoría no relevada).
    """
    return tuple(
        SearchTarget(
            property_type=property_type,
            city=city,
            url=f"{BASE_URL}/inmuebles/{category}/intencion:vendo-t_s/localidad:{locality}",
        )
        for property_type, category in _CATEGORY_SLUG.items()
        for city, locality in _LOCALITY_SLUG.items()
    )


def page_url(search_url: str, page: int) -> str:
    """URL de la página `page` de una búsqueda: la primera no lleva sufijo, las demás `/page-N`."""
    if page < 1:
        raise ValueError("la página tiene que ser al menos 1")
    return search_url if page == 1 else f"{search_url}/page-{page}"
