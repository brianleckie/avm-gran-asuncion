"""Sanitizador de HTML y texto (D1, D3). Sin red: fragmentos sintéticos con nombres inventados."""

import pytest

from avm.contract.pii import find_pii
from avm.scraping.sanitize import (
    SanitizationError,
    sanitize_html,
    scrub_contacts,
    scrub_urls,
    trim,
)

DROP = ("div.anunciante", 'a[href*="/empresa/"]')
IMAGES = ("/corporate/", "/users/")

PAGE = (
    "<html><head><script>var x = 1;</script><style>a{}</style><!-- comentario -->"
    '<script type="application/ld+json">{"name": "Casa"}</script></head><body>'
    '<h1>Casa <span style="font-size:0 !important;" class="zz">marca</span>en venta</h1>'
    '<div class="anunciante"><h5>Juana Perez</h5>'
    '<a href="https://portal.test/empresa/inmo-ejemplo-9">Inmo Ejemplo</a>'
    '<img src="//cdn.test/corporate/2021/logo.jpg" alt="Juana Perez"></div>'
    '<img src="//cdn.test/users/2026/avatar.jpg" alt="Pedro Gomez">'
    '<img src="//cdn.test/pictures/2026/foto.jpg" alt="Casa">'
    "<p>Llamar al 0981 123 456 o a vendedor@ejemplo.com.py, https://wa.me/595981123456</p>"
    "</body></html>"
)


def sanitize(page: str = PAGE) -> str:
    return sanitize_html(page, drop_selectors=DROP, drop_img_src=IMAGES)


def test_advertiser_nodes_and_images_are_removed() -> None:
    out = sanitize()
    for leftover in ("Juana", "Perez", "Pedro", "Gomez", "Inmo Ejemplo", "inmo-ejemplo"):
        assert leftover not in out
    assert "/corporate/" not in out and "/users/" not in out
    assert "/empresa/" not in out


def test_unrelated_images_and_content_are_kept() -> None:
    out = sanitize()
    assert "//cdn.test/pictures/2026/foto.jpg" in out
    assert "en venta" in out


def test_contacts_are_scrubbed() -> None:
    out = sanitize()
    assert "[TELEFONO]" in out and "[EMAIL]" in out and "[WHATSAPP]" in out
    assert not find_pii(out)


def test_scripts_styles_and_comments_are_dropped_but_json_ld_and_watermark_stay() -> None:
    out = sanitize()
    assert "var x" not in out and "a{}" not in out and "comentario" not in out
    assert "application/ld+json" in out
    assert "font-size:0" in out


def test_residual_advertiser_reference_fails_closed() -> None:
    page = '<a href="https://portal.test/empresa/inmo-ejemplo-9">x</a>'
    with pytest.raises(SanitizationError, match="anunciante") as error:
        sanitize_html(page, drop_selectors=())
    assert "inmo-ejemplo" not in str(error.value)


def test_residual_personal_data_fails_closed() -> None:
    # El reemplazo exige "api.whatsapp.com/…"; sin la barra el detector lo ve y el reemplazo no.
    page = '<a href="https://api.whatsapp.com">x</a>'
    with pytest.raises(SanitizationError, match="WhatsApp"):
        sanitize_html(page, drop_selectors=())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://wa.me/595981123456", "[WHATSAPP]"),
        ("//wa.me/595981123456", "[WHATSAPP]"),
        ("wa.me/595981123456", "[WHATSAPP]"),
        ("https://api.whatsapp.com/send?phone=595981123456", "[WHATSAPP]"),
        (
            "Llamar 0981 123 456, fijo (595 21) 414 1690, a@b.com.py",
            "Llamar [TELEFONO], fijo [TELEFONO], [EMAIL]",
        ),
        ("Gs. 1.050.000.000 o US$. 235.000,00", "Gs. 1.050.000.000 o US$. 235.000,00"),
    ],
)
def test_scrub_contacts(text: str, expected: str) -> None:
    assert scrub_contacts(text) == expected


def test_trim_collapses_blank_lines() -> None:
    assert trim("a\n\n\n   \nb") == "a\nb"


def test_empty_page_is_fine() -> None:
    assert isinstance(sanitize_html("", drop_selectors=DROP), str)


ALLOWED = ("portal.test", "schema.org")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ver https://sitio.example/ficha-1.", "ver [URL]"),
        ("ver https:sitio.example.pyficha-1 fin", "ver [URL] fin"),  # JSON-LD de Clasipar
        ("www.sitio.example/a", "[URL]"),
        ("https://portal.test/inmuebles/x-1", "https://portal.test/inmuebles/x-1"),
        ("https://sub.portal.test/a", "https://sub.portal.test/a"),
        ("http://schema.org", "http://schema.org"),
        ("https://portal.test.otro.example/a", "[URL]"),  # el host propio solo es prefijo
        ("https:///", "[URL]"),  # sin host: ante la duda se reemplaza
        ("sin links, solo 120 m2", "sin links, solo 120 m2"),
    ],
)
def test_scrub_urls(text: str, expected: str) -> None:
    assert scrub_urls(text, ALLOWED) == expected


EXTERNAL = (
    '<html><head><meta name="description" content="mas info https://sitio.example/ficha">'
    '<script type="application/ld+json">{"@context": "http://schema.org", "description": '
    '"ver https:sitio.example.pyficha-1 fin"}</script></head><body>'
    '<p class="desc-user">uno<br>ver https://sitio.example/ficha<br>dos '
    '<span style="font-size:0 !important;">https://portal.test/aviso-1</span></p>'
    '<a href="https://red.example/perfil">compartir</a></body></html>'
)


def test_external_links_are_replaced_only_in_the_free_text_nodes() -> None:
    out = sanitize_html(
        EXTERNAL,
        drop_selectors=(),
        scrub_urls_in=("p.desc-user", 'script[type="application/ld+json"]', "meta[content]"),
        allowed_url_hosts=ALLOWED,
    )
    assert "sitio.example" not in out
    assert out.count("[URL]") == 3
    assert "http://schema.org" in out and "https://portal.test/aviso-1" in out
    assert "uno<br>ver [URL]<br>dos" in out  # la estructura del texto no cambia
    assert "https://red.example/perfil" in out  # los href del resto del HTML no se tocan


def test_json_ld_stays_valid_json_after_scrubbing() -> None:
    import json
    import re

    out = sanitize_html(
        EXTERNAL,
        drop_selectors=(),
        scrub_urls_in=('script[type="application/ld+json"]',),
        allowed_url_hosts=ALLOWED,
    )
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', out, re.S)
    assert match is not None
    data = json.loads(match.group(1), strict=False)
    assert data["description"] == "ver [URL] fin" and data["@context"] == "http://schema.org"


def test_a_meta_without_content_is_left_alone() -> None:
    page = '<html><head><meta name="description" content=""><meta charset="utf-8"></head></html>'
    out = sanitize_html(
        page, drop_selectors=(), scrub_urls_in=("meta[content]",), allowed_url_hosts=ALLOWED
    )
    assert 'content=""' in out


def test_a_node_that_cannot_be_rewritten_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ante la duda no se deja el link: si la reescritura no produce un nodo, se elimina.
    monkeypatch.setattr("avm.scraping.sanitize.scrub_urls", lambda text, allowed: "")
    out = sanitize_html(
        '<p class="desc-user">ver https://sitio.example/a</p><p class="otro">intacto</p>',
        drop_selectors=(),
        scrub_urls_in=("p.desc-user",),
        allowed_url_hosts=ALLOWED,
    )
    assert "sitio.example" not in out and "desc-user" not in out and "intacto" in out


def test_without_scrub_urls_in_links_are_left_alone() -> None:
    out = sanitize_html(EXTERNAL, drop_selectors=())
    assert "https://sitio.example/ficha" in out
