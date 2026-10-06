"""Configuración compartida del scraping (F3.2): identidad, cortesía y detección de bloqueos.

Los valores de cortesía son MÍNIMOS: un scraper puede ser más conservador, nunca menos
(`BaseScraper` rechaza valores más bajos). Los marcadores de bloqueo salen de docs/sources.md
(§2.7): Clasipar no mostró challenges en 22 requests, y trae un reCAPTCHA en los formularios de
cualquier aviso, por eso las palabras genéricas solo cuentan en páginas chicas.
"""

from typing import Final

# Identificable y fijo: nada de headers de navegador ni rotación de user-agent (CLAUDE.md).
USER_AGENT: Final = (
    "AVM-GranAsuncion-Academic/0.1 "
    "(proyecto universitario; contacto: https://github.com/brianleckie)"
)
# Token de producto: es lo que robots.txt compara contra los `User-agent:`.
PRODUCT_TOKEN: Final = USER_AGENT.split("/", 1)[0]

# Cortesía (mínimos). El ledger de F3.1 respetó 6 s entre requests sin bloqueos en 22 requests.
MIN_DELAY_S: Final = 6.0
JITTER_MAX_S: Final = 1.0
MAX_RETRIES: Final = 2
TIMEOUT_S: Final = 20.0

# Bloqueo: estos estados detienen la corrida entera, sin reintentos.
BLOCK_STATUSES: Final = frozenset({403, 429})
# Marcadores de páginas de challenge; se buscan en minúsculas en el comienzo del cuerpo.
CHALLENGE_MARKERS: Final = ("cf-chl", "challenge-platform", "just a moment...")
# Marcadores genéricos: solo cuentan en páginas chicas (un challenge pesa pocos KB), porque un
# aviso normal trae un reCAPTCHA en el formulario de contacto.
SMALL_PAGE_MARKERS: Final = ("captcha", "attention required", "access denied")
SMALL_PAGE_BYTES: Final = 30_000
# Cuántos caracteres del cuerpo se revisan buscando marcadores.
BODY_SCAN_CHARS: Final = 20_000
