"""Sanitizador de HTML y texto (D1, D3). Sin red: fragmentos sintéticos con nombres inventados."""

import pytest

from avm.contract.pii import find_pii
from avm.scraping.sanitize import SanitizationError, sanitize_html, scrub_contacts, trim

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
