"""Pide una lista explícita de URLs de UNA fuente y guarda las páginas en data/raw/recon/<fuente>/.

Uso (desde la raíz del repo):
    $env:PYTHONPATH = "scripts"
    uv run python -m recon.fetch <fuente> <nombre>=<url> [<nombre>=<url> ...]

Nunca se guarda HTML crudo (CLAUDE.md, D1): cada página pasa por el sanitizador de la fuente antes
de escribirse, y una fuente sin sanitizador no se guarda. Para scrapear de verdad se usa
`avm.scraping.base.BaseScraper`; esta herramienta queda para reconocer una fuente nueva.

Necesita data/raw/recon/<fuente>/robots.txt: es el que se bajó en la compuerta de red, y las
requests de la compuerta ya están en el ledger. Corta en la primera URL prohibida, bloqueada o
fuera de presupuesto: no saltea y sigue.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from avm.scraping.sanitize import SanitizationError
from recon.client import MAX_REQUESTS_PER_SOURCE, Ledger, ReconClient, ReconError
from recon.sanitize import SANITIZERS

RECON_DIR = Path("data/raw/recon")


def sanitize_body(source: str, body: bytes) -> bytes:
    """Cuerpo listo para guardar. Sin sanitizador para la fuente no se guarda nada."""
    sanitizer = SANITIZERS.get(source)
    if sanitizer is None:
        raise ReconError(f"no hay sanitizador para {source}: no se guarda HTML crudo")
    return sanitizer(body.decode("utf-8", errors="replace")).encode("utf-8")


def main(argv: list[str]) -> int:
    source, *pairs = argv
    targets = [pair.split("=", 1) for pair in pairs]
    out_dir = RECON_DIR / source
    robots_txt = (out_dir / "robots.txt").read_text(encoding="utf-8")
    ledger = Ledger(RECON_DIR / "ledger.json")
    client = ReconClient(source, ledger, robots_txt)

    # Validar todo antes de la primera request: una URL prohibida aborta la tanda entera.
    for _, url in targets:
        client.check(url)
    if source not in SANITIZERS:
        print(f"STOP: no hay sanitizador para {source}: no se guarda HTML crudo")
        return 2
    if ledger.count(source) + len(targets) > MAX_REQUESTS_PER_SOURCE:
        print(f"la tanda supera el tope: {ledger.count(source)} usadas + {len(targets)}")
        return 2

    for name, url in targets:
        try:
            response = client.get(url)
            body = sanitize_body(source, response.body)
        except (ReconError, SanitizationError) as exc:
            print(f"STOP {name}: {exc}")
            return 1
        (out_dir / f"{name}.body").write_bytes(body)
        (out_dir / f"{name}.meta.json").write_text(
            json.dumps(
                {"url": url, "status": response.status, "headers": response.headers}, indent=2
            ),
            encoding="utf-8",
        )
        used = f"{ledger.count(source)}/{MAX_REQUESTS_PER_SOURCE}"
        location = response.headers.get("location", "")
        print(f"{name}: {response.status} {len(body)} B (usadas {used}) {location}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
