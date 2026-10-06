"""Matcher de robots.txt: comodines, grupos por user-agent y precedencia de reglas."""

import pytest
from recon.robots import is_allowed, rules_for

# Recorte de reglas reales observadas en la compuerta de F3.1 (InfoCasas y Clasipar).
INFOCASAS = """
User-agent: PyCurl
Disallow:/
User-agent: SemrushBot-SA
Disallow: /
User-agent: *
Disallow: /mobile/
Disallow: /sitio/?mid=propiedades*
Disallow: /venta/*-y-*
Sitemap: https://www.infocasas.com.py/sitemap.xml
"""

CLASIPAR = """
User-Agent: *
Disallow: /error/
Disallow: /app/

User-agent: bingbot
Disallow: /
"""

TOKEN = "AVM-GranAsuncion-Academic"


def test_our_token_falls_into_the_wildcard_group() -> None:
    group, rules = rules_for(INFOCASAS, TOKEN)
    assert group == "*"
    assert len(rules) == 3


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.infocasas.com.py/venta/casas/asuncion", True),
        ("https://www.infocasas.com.py/venta/casas-y-departamentos/asuncion", False),
        ("https://www.infocasas.com.py/mobile/x", False),
        ("https://www.infocasas.com.py/sitio/?mid=propiedades&id=1", False),
        ("https://www.infocasas.com.py/", True),
    ],
)
def test_wildcard_rules(url: str, allowed: bool) -> None:
    _, rules = rules_for(INFOCASAS, TOKEN)
    assert is_allowed(rules, url) is allowed


def test_named_group_wins_over_wildcard() -> None:
    group, rules = rules_for(CLASIPAR, "bingbot")
    assert group == "bingbot"
    assert not is_allowed(rules, "https://clasipar.paraguay.com/")


def test_longest_rule_wins_and_allow_breaks_ties() -> None:
    text = "User-agent: *\nDisallow: /venta/\nAllow: /venta/casas\nDisallow: /x\nAllow: /x\n"
    _, rules = rules_for(text, TOKEN)
    assert is_allowed(rules, "https://h/venta/casas/asuncion")
    assert not is_allowed(rules, "https://h/venta/otros")
    assert is_allowed(rules, "https://h/x")


def test_dollar_anchors_the_end() -> None:
    _, rules = rules_for("User-agent: *\nDisallow: /*.pdf$\n", TOKEN)
    assert not is_allowed(rules, "https://h/a.pdf")
    assert is_allowed(rules, "https://h/a.pdf?x=1")


def test_empty_disallow_allows_everything() -> None:
    _, rules = rules_for("User-agent: *\nDisallow:\n", TOKEN)
    assert rules == []
    assert is_allowed(rules, "https://h/anything")
