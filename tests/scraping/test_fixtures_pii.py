"""Ningún fixture puede contener teléfonos paraguayos, emails ni links de WhatsApp (CLAUDE.md).

Los nombres de anunciantes no se pueden detectar con un regex: se reemplazan con
scripts/recon/sanitize.py y se revisan a mano.
"""

from pathlib import Path

import pytest

from avm.contract.pii import PATTERNS

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Los mismos patrones con los que RawListing rechaza datos personales (avm.contract.pii).
PII_PATTERNS = PATTERNS


def find_pii(text: str) -> list[str]:
    return [
        f"{name}: {m.group(0)!r}" for name, rx in PII_PATTERNS.items() for m in rx.finditer(text)
    ]


FIXTURES = sorted(p for p in FIXTURES_DIR.rglob("*") if p.is_file() and p.name != ".gitkeep")


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.relative_to(FIXTURES_DIR).as_posix())
def test_fixture_has_no_personal_data(path: Path) -> None:
    found = find_pii(path.read_text(encoding="utf-8", errors="replace"))
    assert not found, f"{path.name} contiene datos personales: {found[:5]}"


@pytest.mark.parametrize(
    "text",
    [
        "Llamar al 0981 123 456",
        "Tel: 0981-123-456",
        "WhatsApp +595 981 123456",
        "595981123456",
        "Oficina: 021 414 1690",
        "Tel. (595 21) 414 1690",
        "contacto: vendedor@ejemplo.com.py",
        "https://wa.me/595981123456",
    ],
)
def test_detector_catches_synthetic_pii(text: str) -> None:
    assert find_pii(text)


@pytest.mark.parametrize(
    "text",
    [
        "Gs. 1.200.000.000",
        "Gs. 1.050.000.000",
        "US$. 235.000,00",
        "Nro. de Anuncio: 2919242",
        "/inmuebles/casas/en-venta-casa-en-recoleta-v021-2095375",
        '"latitude": "-25.314827172122374"',
        "[TELEFONO] [EMAIL]",
    ],
)
def test_detector_ignores_prices_and_placeholders(text: str) -> None:
    assert not find_pii(text)
