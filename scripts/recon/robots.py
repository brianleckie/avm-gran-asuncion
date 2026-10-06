"""Matcher mínimo de robots.txt (RFC 9309) con soporte de `*` y `$`.

`urllib.robotparser` compara por prefijo y no interpreta comodines, así que con reglas como
`Disallow: /venta/*-y-*` (InfoCasas) daría por permitidas URLs prohibidas.

- Se elige el grupo cuyo `User-agent` aparece dentro del token del producto (sin distinguir
  mayúsculas); el más específico (nombre más largo) gana. Si ninguno matchea, el grupo `*`.
- Gana la regla de patrón más largo; ante empate, `Allow`. Sin reglas que matcheen: permitido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Rule:
    allow: bool
    pattern: str


def _groups(text: str) -> list[tuple[list[str], list[Rule]]]:
    groups: list[tuple[list[str], list[Rule]]] = []
    agents: list[str] = []
    rules: list[Rule] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:  # empieza un grupo nuevo
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents:
            if value:  # "Disallow:" vacío no prohíbe nada
                rules.append(Rule(allow=key == "allow", pattern=value))
    if agents:
        groups.append((agents, rules))
    return groups


def rules_for(text: str, product_token: str) -> tuple[str, list[Rule]]:
    """Devuelve (nombre del grupo aplicado, reglas) para `product_token`."""
    token = product_token.lower()
    best: tuple[str, list[Rule]] | None = None
    wildcard: list[Rule] = []
    for agents, rules in _groups(text):
        for agent in agents:
            if agent == "*":
                wildcard.extend(rules)
            elif agent in token and (best is None or len(agent) > len(best[0])):
                best = (agent, rules)
    return best if best is not None else ("*", wildcard)


def _to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def is_allowed(rules: list[Rule], url: str) -> bool:
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    matches = [rule for rule in rules if _to_regex(rule.pattern).match(path)]
    if not matches:
        return True
    best = max(matches, key=lambda rule: (len(rule.pattern), rule.allow))
    return best.allow
