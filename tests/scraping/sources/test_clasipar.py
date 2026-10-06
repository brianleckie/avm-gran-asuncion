"""Parser de Clasipar contra fixtures reales (F3.4) y URLs de búsqueda (F3.3).

Los valores esperados están escritos A MANO leyendo el HTML de cada fixture; ninguno sale de
correr el parser. Cada bloque dice de qué parte del fixture sale. Los casos sintéticos (HTML en
línea, con nombres, teléfonos y sitios inventados) están rotulados como tales.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from avm.contract import City, PropertyType, RawListing, Source
from avm.contract.pii import find_pii
from avm.scraping.sources.clasipar import (
    ClasiparParseError,
    ListingPage,
    ListingRef,
    compute_content_hash,
    merge_refs,
    page_url,
    parse_detail,
    parse_listing_page,
    sanitize_clasipar_html,
    search_urls,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "clasipar"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
PORTAL = "https://clasipar.paraguay.com"

URL_1 = f"{PORTAL}/inmuebles/casas/casa-a-la-venta-en-villa-aurelia-asuncion-2919242"
URL_2 = f"{PORTAL}/inmuebles/duplex/vendo-hermosa-casa-a-estrenar-en-luque-2926791"
URL_3 = (
    f"{PORTAL}/inmuebles/departamentos/"
    "departamento-de-2-dormitorios-68-m2-en-edificio-marlin-san-lorenzo-2214004"
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def detail(name: str, url: str, **kwargs: object) -> RawListing:
    return parse_detail(fixture(name), url, NOW, **kwargs)  # type: ignore[arg-type]


# ================================================================================== listado
# listado.html: página 1 de "casas en venta en Asunción" (`<article class="box-anuncio ...">`).


@pytest.fixture(scope="module")
def listing() -> ListingPage:
    return parse_listing_page(fixture("listado.html"))


def test_listing_has_37_cards_13_sponsored_and_24_organic(listing: ListingPage) -> None:
    # 37 `<article class="box-anuncio...">`: 24 con la clase sola, 7 `--premium` (6 con el orden
    # "box-anuncio box-anuncio--premium" y 1 con "box-anuncio--premium box-anuncio") y 6
    # `--destacado`.
    assert len(listing.refs) == 37
    assert sum(ref.patrocinado for ref in listing.refs) == 13
    assert sum(not ref.patrocinado for ref in listing.refs) == 24
    assert len({ref.source_id for ref in listing.refs}) == 37  # ningún aviso repetido en la página


def test_listing_pagination_and_results(listing: ListingPage) -> None:
    # `<link rel="next" href=".../localidad:asuncion-3/page-2">` en el <head>.
    assert listing.next_url == (
        f"{PORTAL}/inmuebles/casas/intencion:vendo-t_s/localidad:asuncion-3/page-2"
    )
    # `<li class="active"><a data-page="1">`; el mayor `data-page` de `ul#pagination` es 111.
    assert (listing.current_page, listing.last_page) == (1, 111)
    # `<p><small><strong>2.773 Resultados</strong></small></p>`
    assert listing.total_results == 2773
    assert listing.has_more


def test_listing_first_card_is_premium_in_pesos(listing: ListingPage) -> None:
    # Primer <article>: clase "box-anuncio box-anuncio--premium".
    assert listing.refs[0] == ListingRef(
        url=f"{PORTAL}/inmuebles/casas/casa-de-3-dormitorios-a-refaccionar-en-recoleta-asuncion-2892275",
        source_id="2892275",  # sufijo numérico del href
        patrocinado=True,
        title_raw="CASA DE 3 DORMITORIOS A REFACCIONAR EN RECOLETA - ASUNCIÓN",  # a.titAnuncio
        price_raw="Gs. 1.200.000.000",  # p.price
        operation_raw="Vendo",  # primer <strong> del <h6>
        advertiser_type_raw="Inmobiliaria",  # segundo <strong> del <h6> ("Ofrecido por:")
    )


def test_listing_second_card_is_premium(listing: ListingPage) -> None:
    ref = listing.refs[1]  # segundo <article>, también premium
    assert ref.url.endswith("/venta-de-hermosa-casa-zona-cristo-rey-2926305")
    assert (ref.source_id, ref.patrocinado) == ("2926305", True)
    assert (ref.title_raw, ref.price_raw) == (
        "VENTA DE HERMOSA CASA, ZONA CRISTO REY",
        "Gs. 795.000.000",
    )


def test_listing_featured_card_in_dollars(listing: ListingPage) -> None:
    ref = listing.refs[6]  # séptimo <article>: el primero con clase "box-anuncio--destacado"
    assert ref.url.endswith("/vendo-casa-casa-en-pb-2-suites-b-san-cristobal-cod-756-2682793")
    assert (ref.source_id, ref.patrocinado) == ("2682793", True)
    assert ref.price_raw == "US$. 298.000,00"
    assert ref.title_raw is not None and ref.title_raw.startswith(
        "VENDO CASA CASA EN P.B. 2 SUITES"
    )
    assert (ref.operation_raw, ref.advertiser_type_raw) == ("Vendo", "Inmobiliaria")


def test_listing_organic_card_from_an_agency(listing: ListingPage) -> None:
    ref = listing.refs[14]  # <article class="box-anuncio"> con "Ofrecido por: Inmobiliaria"
    assert ref.url.endswith("/vendo-propiedad-sobre-espana-en-asuncion-barrio-san-roque-2964105")
    assert (ref.source_id, ref.patrocinado) == ("2964105", False)
    assert ref.title_raw == "Vendo propiedad sobre España en Asuncion barrio san Roque"
    assert (ref.price_raw, ref.operation_raw, ref.advertiser_type_raw) == (
        "US$. 235.000,00",
        "Vendo",
        "Inmobiliaria",
    )


def test_listing_organic_card_from_a_private_seller(listing: ListingPage) -> None:
    ref = listing.refs[18]  # <article class="box-anuncio"> con "Ofrecido por: Particular"
    assert ref.url.endswith("/vendo-imponente-vivienda-en-las-lomascarmelitas-2952522")
    assert (ref.source_id, ref.patrocinado) == ("2952522", False)
    assert ref.title_raw == "Vendo imponente vivienda en Las Lomas(Carmelitas)"
    assert (ref.price_raw, ref.advertiser_type_raw) == ("US$. 1.050.000,00", "Particular")


def test_listing_last_card(listing: ListingPage) -> None:
    ref = listing.refs[-1]  # el 37.º <article>
    assert ref.url.endswith("/vendo-casa-en-asuncion-barrio-obrero-cod-4769-2499184")
    assert (ref.source_id, ref.patrocinado) == ("2499184", False)
    assert ref.price_raw == "US$. 220.000,00"


def test_listing_advertiser_types_and_currencies_add_up(listing: ListingPage) -> None:
    # En el HTML: 25 tarjetas "Inmobiliaria" y 12 "Particular"; 25 precios "US$." y 12 "Gs.".
    types = [ref.advertiser_type_raw for ref in listing.refs]
    assert (types.count("Inmobiliaria"), types.count("Particular")) == (25, 12)
    prices = [ref.price_raw or "" for ref in listing.refs]
    assert sum(price.startswith("US$.") for price in prices) == 25
    assert sum(price.startswith("Gs.") for price in prices) == 12
    assert {ref.operation_raw for ref in listing.refs} == {"Vendo"}


def test_listing_sanitized_page_gives_the_same_refs(listing: ListingPage) -> None:
    assert parse_listing_page(sanitize_clasipar_html(fixture("listado.html"))) == listing


# ----------------------------------------------------------------------------- listado sintético
# HTML inventado: las tarjetas imitan la estructura de Clasipar con avisos y precios ficticios.


def card(
    number: int,
    *,
    cls: str = "box-anuncio",
    price: str = "Gs. 100.000.000",
    h6: str = "<strong>Vendo</strong> | Ofrecido por: <strong>Particular</strong>",
) -> str:
    return (
        f'<article class="{cls}"><a href="{PORTAL}/inmuebles/casas/casa-ficticia-{number}" '
        f'class="titAnuncio">Casa ficticia {number}</a><p class="price">{price}</p>'
        f"<h6>{h6}</h6></article>"
    )


def test_last_page_without_rel_next_and_with_a_price_to_consult() -> None:
    page = parse_listing_page(f"<html><body>{card(1, price='Consultar precio.')}</body></html>")
    assert page.next_url is None and not page.has_more
    assert (page.current_page, page.last_page, page.total_results) == (None, None, None)
    assert page.refs[0].price_raw == "Consultar precio."  # el parser no interpreta precios


def test_pagination_without_rel_next_falls_back_to_the_active_page() -> None:
    html = (
        '<ul id="pagination"><li class="active"><a data-page="2">2</a></li>'
        '<li><a data-page="3">3</a></li><li><a data-page="x">x</a></li></ul>'
    )
    page = parse_listing_page(html)
    assert (page.current_page, page.last_page) == (2, 3) and page.has_more
    last = parse_listing_page(html.replace('data-page="2"', 'data-page="3"'))
    assert (last.current_page, last.last_page) == (3, 3) and not last.has_more


def test_results_text_without_thousands_separator() -> None:
    page = parse_listing_page(
        "<small><strong>Ordenar por</strong></small>"
        "<p><small><strong>67 Resultados</strong></small></p>"
    )
    assert page.total_results == 67


def test_card_without_link_is_a_parse_error() -> None:
    with pytest.raises(ClasiparParseError, match="tarjeta"):
        parse_listing_page('<article class="box-anuncio"><p class="price">Gs. 1</p></article>')
    with pytest.raises(ClasiparParseError, match="tarjeta"):
        parse_listing_page(
            '<article class="box-anuncio">'
            '<a href="/inmuebles/casas/sin-id" class="titAnuncio">x</a>'
            "</article>"
        )


def test_relative_card_links_are_made_absolute() -> None:
    html = (
        '<article class="box-anuncio">'
        '<a href="/inmuebles/casas/casa-ficticia-7" class="titAnuncio">x</a></article>'
    )
    assert parse_listing_page(html).refs[0].url == f"{PORTAL}/inmuebles/casas/casa-ficticia-7"


def test_card_with_only_one_label_has_no_advertiser_type() -> None:
    page = parse_listing_page(f"<html>{card(3, h6='<strong>Vendo</strong>')}</html>")
    assert (page.refs[0].operation_raw, page.refs[0].advertiser_type_raw) == ("Vendo", None)
    bare = parse_listing_page(f"<html>{card(4, h6='')}</html>")
    assert (bare.refs[0].operation_raw, bare.refs[0].advertiser_type_raw) == (None, None)


def test_merge_refs_deduplicates_by_source_id_and_keeps_the_sponsored_mark() -> None:
    page_one = parse_listing_page(
        card(1, cls="box-anuncio box-anuncio--premium")
        + card(2)
        + card(3, cls="box-anuncio--destacado box-anuncio")
    )
    page_two = parse_listing_page(
        card(1, cls="box-anuncio box-anuncio--premium")
        + card(4)
        + card(2, cls="box-anuncio box-anuncio--destacado")
    )
    merged = merge_refs([*page_one.refs, *page_two.refs])
    assert [ref.source_id for ref in merged] == ["1", "2", "3", "4"]  # sin repetidos, en orden
    # El aviso 2 apareció primero como orgánico y después como destacado: queda patrocinado.
    assert [ref.patrocinado for ref in merged] == [True, True, True, False]
    assert merged[1].title_raw == "Casa ficticia 2" and merged[1].price_raw == "Gs. 100.000.000"
    assert merge_refs([]) == []


# ================================================================================== detalle
# Valores leídos del HTML de cada fixture. `ref=None`: el detalle no trae la operación ni el tipo
# de anunciante del aviso (lo que se ve ahí es de 3 avisos relacionados).

DETAIL_1_DESCRIPTION = "\n".join(
    [
        # p.desc-user, una línea por <br>, sin la marca de agua (span font-size:0) ni líneas vacías.
        "Casa a la venta en Villa Aurelia",
        "A una cuadra de la Avda E. Ayala",
        "Zona residencial",
        "Dimenciones 379 m2",
        "Frente 12 mts",
        "Fondo 32",
        "Planta baja",
        "Garage para 2 vehiculos bajo techo",
        "Sala",
        "Baño social",
        "Jardín interno",
        "Cocina independiente",
        "2 dormitorios",
        "1 Baño compartido",
        "Estar social amplio",
        "Escritorio con baño",
        "Piscina",
        "Quincho con parrilla",
        "Pequeño patio",
        "Area Servicio y lavadero con baño",
        "Planta Alta",
        "1 Dormitorio en suite super amplio con vestidor y salita",
        "*Inversión: Gs. 1.200.000.000.-*",
        "ID: 38434 vf",
    ]
)

DETAIL_2_DESCRIPTION = "\n".join(
    [
        "VENDO CASA TIPO CHALET EN LUQUE",
        "Bo. Maramburé – Guayaiví casi Av. Hernandarias",
        "Excelente ubicación:",
        "• A solo 50 m de Av. Hernandarias",
        "• A 100 m de Quinta Los Olivos",
        "Casa tipo chalet en dúplex",
        "La propiedad cuenta con:",
        "- Estacionamiento para 2 vehículos",
        "- Acceso peatonal independiente",
        "- Sala",
        "- Comedor",
        "- Cocina integrada",
        "- 3 dormitorios",
        "- 1 dormitorio en suite",
        "- 1 baño familiar",
        "- Gran parrilla",
        "- Patio",
        "Extras incluidos:",
        "• Muebles de cocina (altos y bajos)",
        "• Termocalefón de 80 litros",  # el span de marca de agua partía esta línea en dos
        "• Placares en dormitorios",
        "• Aire acondicionado en todos los ambientes",
        "Terreno: 180 m²",
        "Construcción: 90 m²",
        "Precio: Gs. 530.000.000",
        "Id: 48617",
    ]
)

DETAIL_3_DESCRIPTION = "\n".join(
    [
        "Departamento de 2 dormtorios en Villa Universitaria, San Lorenzo, Paraguay",
        "Departamento de 2 dormitorios (1 en suite) desde 68 m2, 1 baño social/familiar, "
        "sala/comedor/kichenette, balcón gourmet equpado con parrilla y pileta.",
        "Amenities: Piscina con deck. Quinchos climatizado y Exterior. Gimnasio. Coworking. "
        "Lavanderia Comun",
        "Zona común: Estacionamiento. Generador. 2 Ascensores. Guardia 24hrs. CCTV",
        "Precios desde USD 75.130. Cochera con costo adicional desde USD 9.500 y baulera USD 1.500",
        "Las fotos son referenciales y los precios están sujetos a variación y disponibilidad",
        "Para más detalles dale clic a este link:",
        "[URL]",  # el sitio de la inmobiliaria se reemplaza al sanitizar (D1)
        "A:39SQEE/CP:2214004",
    ]
)

# (fixture, url, campos esperados). Todo lo no listado es None.
CASES = {
    "detalle_1": (
        "detalle_1.html",
        URL_1,
        {
            "source_id": "2919242",  # ficha "Nro. de Anuncio:"
            "title_raw": "Casa a la venta en Villa Aurelia - Asunción",  # h1.tit-anuncio
            "description_raw": DETAIL_1_DESCRIPTION,
            "price_raw": "Gs. 1.200.000.000",  # h3.user-price
            "bedrooms_raw": "2",  # span.ads_tag "Dormitorios: 2"
            "bathrooms_raw": None,  # no hay tag "Baños"; el JSON-LD lo trae vacío
            "property_type_raw": "casas",  # /inmuebles/casas/ en la URL
            "city_raw": "Asunción",  # ficha "Ciudad:"
            "neighborhood_raw": "Villa Aurelia",  # ficha "Zona"
            "latitude_raw": "-25.314827172122374",  # JSON-LD House
            "longitude_raw": "-57.56149041173563",
            "published_at_raw": "03/09/2026",  # ficha "Publicado el:"
            "attributes_raw": {"Habitación en suite": "1", "Quincho": "SI"},  # tags restantes
        },
    ),
    "detalle_2": (
        "detalle_2.html",
        URL_2,
        {
            "source_id": "2926791",
            "title_raw": "VENDO HERMOSA CASA A ESTRENAR EN LUQUE",
            "description_raw": DETAIL_2_DESCRIPTION,
            "price_raw": "Gs. 530.000.000",
            "bedrooms_raw": None,  # sin span.ads_tag en este aviso
            "bathrooms_raw": None,
            "property_type_raw": "duplex",
            "city_raw": "Luque",
            "neighborhood_raw": "Luque",  # la "Zona" repite la ciudad
            "latitude_raw": None,  # JSON-LD con "" -> ausencia de dato
            "longitude_raw": None,
            "published_at_raw": "18/09/2026",
            "attributes_raw": {"Departamento": "Central"},  # ficha "Departamento:" (geográfico)
        },
    ),
    "detalle_3": (
        "detalle_3.html",
        URL_3,
        {
            "source_id": "2214004",
            "title_raw": "Departamento de 2 dormitorios 68 m2 en Edificio Marlin San Lorenzo",
            "description_raw": DETAIL_3_DESCRIPTION,
            "price_raw": "US$. 75.130,00",
            "bedrooms_raw": "2",
            "bathrooms_raw": "1",  # tag "Baños: 1"
            "property_type_raw": "departamentos",
            "city_raw": "San Lorenzo",
            "neighborhood_raw": "Villa Universitaria, Ingavi, San Lorenzo",
            "latitude_raw": "-25.333423079011098",  # JSON-LD Apartment
            "longitude_raw": "-57.53240427163919",
            "published_at_raw": "15/09/2026",
            "attributes_raw": {
                "Departamento": "Central",
                "Habitación en suite": "1",
                "Piscina": "SI",
                "Quincho": "SI",
            },
        },
    ),
}

CONTENT_FIELDS = (
    "title_raw",
    "description_raw",
    "price_raw",
    "currency_raw",
    "built_area_raw",
    "land_area_raw",
    "bedrooms_raw",
    "bathrooms_raw",
    "garages_raw",
    "property_type_raw",
    "operation_raw",
    "city_raw",
    "neighborhood_raw",
    "address_raw",
    "latitude_raw",
    "longitude_raw",
    "published_at_raw",
    "advertiser_type_raw",
)


def expected_content(case: str) -> dict[str, object]:
    _, url, fields = CASES[case]
    content: dict[str, object] = {name: None for name in CONTENT_FIELDS}
    content.update(fields)
    content.update(
        {"source": "clasipar", "url": url, "attributes_raw": dict(fields["attributes_raw"])}
    )  # type: ignore[arg-type]
    return content


@pytest.mark.parametrize("case", list(CASES))
def test_detail_fields_match_the_values_read_from_the_html(case: str) -> None:
    name, url, fields = CASES[case]
    raw = detail(name, url)
    assert raw.source is Source.CLASIPAR and raw.url == url and raw.scraped_at == NOW
    for field in CONTENT_FIELDS:
        assert getattr(raw, field) == fields.get(field), field
    assert raw.attributes_raw == fields["attributes_raw"]
    assert raw.source_id == fields["source_id"]


@pytest.mark.parametrize("case", list(CASES))
def test_content_hash_is_the_sha256_of_the_canonical_json_of_the_content(case: str) -> None:
    # Se recalcula acá con las reglas de D2 (claves ordenadas, UTF-8, sin espacios) sobre los
    # valores escritos a mano: no depende de la función que se prueba.
    name, url, fields = CASES[case]
    content = expected_content(case)
    content["source_id"] = fields["source_id"]
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert detail(name, url).content_hash == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("case", list(CASES))
def test_compute_content_hash_matches_the_stored_one(case: str) -> None:
    name, url, _ = CASES[case]
    raw = detail(name, url)
    assert compute_content_hash(raw) == raw.content_hash
    assert re.fullmatch(r"[0-9a-f]{64}", raw.content_hash)


def test_detail_with_the_card_takes_operation_and_advertiser_type_from_it() -> None:
    ref = ListingRef(
        url=URL_3,
        source_id="2214004",
        patrocinado=True,
        operation_raw="Vendo",
        advertiser_type_raw="Inmobiliaria",
    )
    raw = detail("detalle_3.html", URL_3, ref=ref)
    assert (raw.operation_raw, raw.advertiser_type_raw) == ("Vendo", "Inmobiliaria")
    expected = dict(CASES["detalle_3"][2]["attributes_raw"])  # type: ignore[arg-type]
    assert raw.attributes_raw == {**expected, "patrocinado": "si"}  # D5


def test_a_card_that_is_not_sponsored_adds_no_mark() -> None:
    ref = ListingRef(url=URL_1, source_id="2919242", patrocinado=False, operation_raw="Vendo")
    raw = detail("detalle_1.html", URL_1, ref=ref)
    assert "patrocinado" not in raw.attributes_raw and raw.operation_raw == "Vendo"


def test_related_listings_do_not_leak_into_the_main_listing() -> None:
    # detalle_1.html muestra 3 avisos relacionados: dos "DOY EN ALQUILER" (US$. 5.000,00 y
    # US$. 2.300,00) y un terreno "VENDO" (US$. 70.000,00), todos "Ofrecido por: Inmobiliaria".
    raw = detail("detalle_1.html", URL_1)
    assert raw.price_raw == "Gs. 1.200.000.000"
    assert raw.operation_raw is None and raw.advertiser_type_raw is None
    everything = " ".join(str(value) for value in raw.model_dump().values())
    for related in ("ALQUILO", "alquiler", "ALQUILER", "TERRENO", "5.000,00", "70.000,00"):
        assert related not in everything


def test_visits_are_not_extracted() -> None:
    # Las 3 fichas traen "Nro. de Visitas:" (35, 24 y 94): es volátil y no va a attributes_raw.
    for name, url, _ in CASES.values():
        assert "Nro. de Visitas" not in detail(name, url).attributes_raw


def test_the_watermark_is_dropped_by_style_not_by_class() -> None:
    # La clase del span cambia en cada página ("3mmkjr8y", "hk9lcj6x", "7kl0qmk").
    raw = detail("detalle_1.html", URL_1)
    for marker in ("Clasipar.com", "Fuente del anuncio", "Encontrá todo lo que necesitas"):
        assert marker not in (raw.title_raw or "") and marker not in (raw.description_raw or "")


def test_detail_of_sanitized_and_already_sanitized_html_is_the_same() -> None:
    # detalle_1 y detalle_2 se sanitizaron con la versión anterior ([NOMBRE]); detalle_3, con la
    # nueva. Volver a sanitizar no cambia lo que el parser extrae.
    for name, url, _ in CASES.values():
        html = fixture(name)
        assert parse_detail(sanitize_clasipar_html(html), url, NOW) == parse_detail(html, url, NOW)


# ----------------------------------------------------------------------------- content_hash


def test_same_listing_with_other_visits_and_watermark_class_has_the_same_hash() -> None:
    original = fixture("detalle_1.html")
    # Mismo aviso, otra visita: "Nro. de Visitas:" pasa de 35 a 4812.
    visited = original.replace("<h6>35</h6>", "<h6>4812</h6>")
    # Mismo aviso, otra página: la clase de la marca de agua cambia en cada request.
    reclassed = original.replace("3mmkjr8y", "q9w8e7r6")
    # Mismo aviso, dos scrapes distintos.
    later = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
    base = parse_detail(original, URL_1, NOW)
    assert visited != original and reclassed != original
    assert parse_detail(visited, URL_1, NOW).content_hash == base.content_hash
    assert parse_detail(reclassed, URL_1, NOW).content_hash == base.content_hash
    assert parse_detail(original, URL_1, later).content_hash == base.content_hash


def test_a_price_change_changes_the_hash() -> None:
    original = fixture("detalle_1.html")
    cheaper = original.replace(
        '<h3 class="user-price">Gs. 1.200.000.000</h3>',
        '<h3 class="user-price">Gs. 1.100.000.000</h3>',
    )
    assert cheaper != original
    assert (
        parse_detail(cheaper, URL_1, NOW).content_hash
        != parse_detail(original, URL_1, NOW).content_hash
    )


def test_a_description_or_attribute_change_changes_the_hash() -> None:
    original = fixture("detalle_3.html")
    base = parse_detail(original, URL_3, NOW).content_hash
    assert (
        parse_detail(original.replace("Gimnasio", "Gimnasio y sauna"), URL_3, NOW).content_hash
        != base
    )
    assert (
        parse_detail(
            original.replace("<strong>SI</strong>", "<strong>NO</strong>", 1), URL_3, NOW
        ).content_hash
        != base
    )


def test_the_sponsored_mark_does_not_change_the_hash() -> None:
    plain = ListingRef(url=URL_1, source_id="2919242", patrocinado=False, operation_raw="Vendo")
    sponsored = ListingRef(url=URL_1, source_id="2919242", patrocinado=True, operation_raw="Vendo")
    no_ref = detail("detalle_1.html", URL_1)
    with_plain = detail("detalle_1.html", URL_1, ref=plain)
    with_sponsored = detail("detalle_1.html", URL_1, ref=sponsored)
    assert with_plain.content_hash == with_sponsored.content_hash
    assert with_sponsored.attributes_raw.get("patrocinado") == "si"
    # La operación sí es contenido: con y sin tarjeta el hash difiere.
    assert no_ref.content_hash != with_plain.content_hash


# ----------------------------------------------------------------------------- PII y sintéticos


@pytest.mark.parametrize("case", list(CASES))
def test_no_raw_listing_produced_from_the_fixtures_contains_personal_data(case: str) -> None:
    name, url, _ = CASES[case]
    raw = detail(name, url)
    texts = [value for value in raw.model_dump().values() if isinstance(value, str)]
    texts += [f"{key} {value}" for key, value in raw.attributes_raw.items()]
    for text in texts:
        assert not find_pii(text), text[:60]
    assert "[URL]" not in " ".join(texts) or case == "detalle_3"


def synthetic(description: str = "Casa linda", extra_head: str = "", extra_body: str = "") -> str:
    """Detalle mínimo e inventado, con la estructura de Clasipar."""
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@type": "House", "latitude": "-25.3", '
        '"longitude": "-57.5"}</script>' + extra_head + "</head><body>"
        '<h1 class="tit-anuncio">Casa ficticia</h1><h3 class="user-price">Gs. 100.000.000</h3>'
        '<div class="grid anuncio-detalles">'
        '<div class="grid__item"><span>Nro. de Anuncio:</span> <h6>555</h6></div>'
        '<div class="grid__item"><span>Ciudad:</span> <h6>Luque</h6></div></div>'
        f'<p class="desc-user">{description}</p>' + extra_body + "</body></html>"
    )


SYNTHETIC_URL = f"{PORTAL}/inmuebles/casas/casa-ficticia-555"


def test_personal_data_in_the_text_is_replaced_before_building_the_raw_listing() -> None:
    # Sintético: teléfono, email, WhatsApp y sitio de terceros inventados en la descripción.
    description = (
        "Llamar al 0981 123 456<br>escribir a ejemplo@correo.example.py<br>"
        "https://wa.me/595981123456<br>mas fotos en https://sitio-ficticio.example/casa-1<br>"
        "Gs. 100.000.000"
    )
    raw = parse_detail(synthetic(description), SYNTHETIC_URL, NOW)
    assert raw.description_raw == (
        "Llamar al [TELEFONO]\nescribir a [EMAIL]\n[WHATSAPP]\nmas fotos en [URL]\nGs. 100.000.000"
    )
    assert not find_pii(raw.description_raw or "")


def test_the_advertiser_block_is_never_extracted() -> None:
    # Sintético: bloque de anunciante con un nombre, un perfil y un logo inventados.
    block = (
        '<div class="infoAnunciante__header"><a href="https://clasipar.paraguay.com/empresa/inmo-ficticia-77">'
        '<img src="//cdn.example/corporate/x.jpg" alt="Inmo Ficticia SA"></a>'
        "<h5>Inmo Ficticia SA</h5></div>"
        '<ul class="infoAnunciante__datos"><li><b id="phone_number">*********</b></li></ul>'
    )
    html = synthetic(extra_body=block)
    raw = parse_detail(html, SYNTHETIC_URL, NOW)
    assert "Inmo" not in json.dumps(raw.model_dump(mode="json"), ensure_ascii=False)
    sanitized = sanitize_clasipar_html(html)
    assert (
        "Inmo" not in sanitized and "/empresa/" not in sanitized and "/corporate/" not in sanitized
    )
    assert parse_detail(sanitized, SYNTHETIC_URL, NOW) == raw


def test_minimal_listing_has_only_what_the_page_gives() -> None:
    raw = parse_detail(synthetic(), SYNTHETIC_URL, NOW)
    assert (raw.source_id, raw.title_raw, raw.price_raw, raw.city_raw) == (
        "555",
        "Casa ficticia",
        "Gs. 100.000.000",
        "Luque",
    )
    assert (raw.latitude_raw, raw.longitude_raw) == ("-25.3", "-57.5")
    assert raw.attributes_raw == {} and raw.property_type_raw == "casas"


def test_source_id_comes_from_the_url_when_the_sheet_has_none() -> None:
    html = synthetic().replace("<span>Nro. de Anuncio:</span> <h6>555</h6>", "")
    assert parse_detail(html, SYNTHETIC_URL, NOW).source_id == "555"


def test_a_listing_without_any_id_is_a_parse_error() -> None:
    html = synthetic().replace("<span>Nro. de Anuncio:</span> <h6>555</h6>", "")
    with pytest.raises(ClasiparParseError, match="Nro. de Anuncio"):
        parse_detail(html, f"{PORTAL}/inmuebles/casas/sin-id", NOW)


def test_a_sheet_id_that_disagrees_with_the_url_is_a_parse_error() -> None:
    with pytest.raises(ClasiparParseError, match="no coincide"):
        parse_detail(synthetic(), f"{PORTAL}/inmuebles/casas/casa-ficticia-999", NOW)


def test_property_type_falls_back_to_the_breadcrumb_when_the_url_has_no_category() -> None:
    # detalle_3: JSON-LD BreadcrumbList, posición 2: "Inmuebles / Departamentos".
    raw = detail("detalle_3.html", f"{PORTAL}/anuncio-2214004")
    assert raw.property_type_raw == "Departamentos"


def test_property_type_is_none_without_url_category_or_breadcrumb() -> None:
    raw = parse_detail(synthetic(), f"{PORTAL}/anuncio-555", NOW)
    assert raw.property_type_raw is None


@pytest.mark.parametrize(
    "breadcrumb",
    [
        '{"@type": "BreadcrumbList", "itemListElement": null}',
        '{"@type": "BreadcrumbList", "itemListElement": ["texto", {"position": 1}]}',
        '{"@type": "BreadcrumbList", "itemListElement": [{"position": 2, "item": "texto"}]}',
        '{"@type": "BreadcrumbList", "itemListElement": '
        '[{"position": 2, "item": {"name": "Clasipar"}}]}',
    ],
)
def test_a_malformed_breadcrumb_is_ignored(breadcrumb: str) -> None:
    head = f'<script type="application/ld+json">{breadcrumb}</script>'
    assert (
        parse_detail(synthetic(extra_head=head), f"{PORTAL}/anuncio-555", NOW).property_type_raw
        is None
    )


def test_json_ld_with_unescaped_newlines_is_read_and_broken_json_is_skipped() -> None:
    # Sintético: la fuente deja saltos de línea sin escapar dentro de los strings.
    loose = (
        '<script type="application/ld+json">'
        '{"@type": "House", "name": "uno\ndos", "latitude": "-25.9"}</script>'
    )
    broken = '<script type="application/ld+json">{esto no es json</script>'
    html = synthetic().replace(
        '<script type="application/ld+json">{"@type": "House", "latitude": "-25.3", '
        '"longitude": "-57.5"}</script>',
        broken + loose,
    )
    raw = parse_detail(html, SYNTHETIC_URL, NOW)
    assert (raw.latitude_raw, raw.longitude_raw) == ("-25.9", None)


def test_json_ld_as_a_list_is_supported() -> None:
    html = synthetic().replace(
        '{"@type": "House", "latitude": "-25.3", "longitude": "-57.5"}',
        '[7, {"@type": "Apartment", "latitude": "-25.1", "longitude": "-57.1"}]',
    )
    assert parse_detail(html, SYNTHETIC_URL, NOW).latitude_raw == "-25.1"


def test_sheet_items_without_a_pair_or_with_an_empty_value_are_skipped() -> None:
    sheet = (
        '<div class="anuncio-detalles"><div class="grid__item"><button>Ver Mapa</button></div>'
        '<div class="grid__item"><span>Zona</span> <h6>  </h6></div></div>'
    )
    html = synthetic().replace("</body>", sheet + "</body>")
    assert parse_detail(html, SYNTHETIC_URL, NOW).neighborhood_raw is None


def test_tags_without_a_value_or_label_are_skipped() -> None:
    tags = (
        '<span class="ads_tag"><a>Piscina: <strong>SI</strong></a></span>'
        '<span class="ads_tag"><a>Sin valor</a></span>'
        '<span class="ads_tag"><a>: <strong>3</strong></a></span>'
    )
    raw = parse_detail(synthetic(extra_body=tags), SYNTHETIC_URL, NOW)
    assert raw.attributes_raw == {"Piscina": "SI"}


def test_a_non_utc_timestamp_is_rejected_by_the_contract() -> None:
    from datetime import timedelta, timezone

    local = datetime(2026, 10, 6, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
    with pytest.raises(ValidationError):
        parse_detail(synthetic(), SYNTHETIC_URL, local)


# ================================================================================== búsqueda

EXPECTED_SEARCH_URLS = [
    # Los 12 patrones de docs/sources.md §2.3, escritos a mano.
    f"{PORTAL}/inmuebles/casas/intencion:vendo-t_s/localidad:asuncion-3",
    f"{PORTAL}/inmuebles/casas/intencion:vendo-t_s/localidad:luque-30",
    f"{PORTAL}/inmuebles/casas/intencion:vendo-t_s/localidad:san-lorenzo-35",
    f"{PORTAL}/inmuebles/casas/intencion:vendo-t_s/localidad:fernando-de-la-mora-23",
    f"{PORTAL}/inmuebles/departamentos/intencion:vendo-t_s/localidad:asuncion-3",
    f"{PORTAL}/inmuebles/departamentos/intencion:vendo-t_s/localidad:luque-30",
    f"{PORTAL}/inmuebles/departamentos/intencion:vendo-t_s/localidad:san-lorenzo-35",
    f"{PORTAL}/inmuebles/departamentos/intencion:vendo-t_s/localidad:fernando-de-la-mora-23",
    f"{PORTAL}/inmuebles/duplex/intencion:vendo-t_s/localidad:asuncion-3",
    f"{PORTAL}/inmuebles/duplex/intencion:vendo-t_s/localidad:luque-30",
    f"{PORTAL}/inmuebles/duplex/intencion:vendo-t_s/localidad:san-lorenzo-35",
    f"{PORTAL}/inmuebles/duplex/intencion:vendo-t_s/localidad:fernando-de-la-mora-23",
]


def test_search_urls_are_the_twelve_documented_ones() -> None:
    targets = search_urls()
    assert [target.url for target in targets] == EXPECTED_SEARCH_URLS
    assert len({target.url for target in targets}) == 12
    assert "residencias-mansiones" not in " ".join(target.url for target in targets)


def test_search_urls_cover_every_type_and_city_once() -> None:
    pairs = {(target.property_type, target.city) for target in search_urls()}
    assert pairs == {(kind, city) for kind in PropertyType for city in City}
    assert (
        search_urls()[0].property_type is PropertyType.HOUSE
        and search_urls()[0].city is City.ASUNCION
    )


def test_page_url() -> None:
    base = EXPECTED_SEARCH_URLS[0]
    assert page_url(base, 1) == base
    assert page_url(base, 2) == f"{base}/page-2"  # el patrón que sigue rel="next" en el fixture
    with pytest.raises(ValueError, match="al menos 1"):
        page_url(base, 0)
