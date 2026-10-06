"""Detección de datos personales (teléfonos paraguayos, emails, WhatsApp) en texto.

Lo usan RawListing (rechaza el objeto si los encuentra), el test de fixtures y el sanitizador de
scripts/recon. Los nombres de personas no se pueden detectar con un regex: los quita el parser.
"""

import re

# Celulares (09xx xxx xxx, +595 9xx...) y fijos (021 xxx xxx, (595 21) xxx xxxx). El lookbehind
# evita confundir grupos de un precio ("1.200.000.000") o ids dentro de un slug ("v021-2095375").
PHONE = re.compile(
    r"(?<![\w.,/-])(?:\+?595|0)[\s.-]?9\d{2}[\s.-]?\d{3}[\s.-]?\d{3}"
    r"|(?<![\w.,/-])(?:\(?\+?595[\s.-]?|\(?0)[2-8]\d\)?[\s.-]?\d{3}[\s.-]?\d{3,4}"
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WHATSAPP = re.compile(r"wa\.me/|api\.whatsapp\.com", re.I)

PATTERNS = {"teléfono": PHONE, "email": EMAIL, "WhatsApp": WHATSAPP}


def find_pii(text: str) -> list[str]:
    """Tipos de dato personal encontrados en `text` (sin repetir el dato en sí)."""
    return [kind for kind, pattern in PATTERNS.items() if pattern.search(text)]
