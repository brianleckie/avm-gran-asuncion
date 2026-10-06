"""Sanitizador de fixtures: recorte y reemplazo de datos personales, con fragmentos sintéticos.

Los fragmentos imitan la estructura observada en Clasipar (F3.1); los nombres son inventados.
"""

from recon.sanitize import scrub_clasipar_names, scrub_contacts, trim

E = "https://clasipar.paraguay.com/empresa/"

DETAIL_HEADER = (
    '<div class="infoAnunciante__header"> <figure> <a href="' + E + 'juana-perez-123" '
    'title="Juana Perez"> <img src="//clasicdn.paraguay.com/corporate/2021/01/08/abc.jpg" '
    'alt="Juana Perez"> </a> </figure> <h5> Juana Perez<br> <small>x</small> </h5> </div>'
)
PARTICULAR_HEADER = (
    '<div class="infoAnunciante__header"> <figure> <img '
    'src="//clasicdn.paraguay.com/users/2026/05/18/abc.jpg" title="Pedro Gomez"> </figure> '
    "<h5>Pedro Gomez</h5> </div>"
)
LISTING_CARD = (
    '<p class="small"> Vendido por <a href="' + E + 'inmo-ejemplo-sa-99">Inmo Ejemplo SA</a> </p>'
    '<span class="box-anuncio__logo"> <figure> <a href="' + E + 'inmo-ejemplo-sa-99" '
    'title="Inmo Ejemplo SA"> <img src="//clasicdn.paraguay.com/corporate/2024/07/04/x.jpg" '
    'alt="Inmo Ejemplo SA"> </a> </figure> <a href="' + E + 'inmo-ejemplo-sa-99" '
    'class="btn btn-link" title="Inmo Ejemplo SA">Premium</a> </span>'
)
NAMES = ("Juana", "Perez", "Pedro", "Gomez", "Inmo Ejemplo", "inmo-ejemplo", "juana-perez")


def assert_no_names(text: str) -> None:
    for name in NAMES:
        assert name not in text, f"quedó {name!r} en {text!r}"


def test_detail_header_of_an_agency() -> None:
    out = scrub_clasipar_names(DETAIL_HEADER)
    assert_no_names(out)
    assert "/corporate/" not in out
    assert "[NOMBRE]" in out and E + "[EMPRESA]" in out


def test_detail_header_of_a_private_seller() -> None:
    out = scrub_clasipar_names(PARTICULAR_HEADER)
    assert_no_names(out)
    assert 'src="[FOTO_PERFIL]"' in out


def test_listing_card_sold_by_logo_and_premium() -> None:
    out = scrub_clasipar_names(LISTING_CARD)
    assert_no_names(out)
    assert "Vendido por" in out and ">Premium</a>" in out
    assert 'src="[LOGO]"' in out


def test_contacts_are_replaced() -> None:
    text = "Llamar 0981 123 456, fijo (595 21) 414 1690, a@b.com.py o https://wa.me/595981123456"
    out = scrub_contacts(text)
    assert out == "Llamar [TELEFONO], fijo [TELEFONO], [EMAIL] o [WHATSAPP]"


def test_contacts_leave_prices_alone() -> None:
    text = "Gs. 1.050.000.000 o US$. 235.000,00"
    assert scrub_contacts(text) == text


def test_trim_keeps_json_ld_and_watermark() -> None:
    page = (
        "<script>var x=1;</script><style>a{}</style><!-- c -->"
        '<script type="application/ld+json">{"a": 1}</script>'
        '<span style="font-size:0 !important;" class="zz">marca</span>'
    )
    out = trim(page)
    assert "var x" not in out and "a{}" not in out and "<!--" not in out
    assert "application/ld+json" in out and "font-size:0" in out
