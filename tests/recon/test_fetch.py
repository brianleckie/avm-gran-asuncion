"""recon.fetch: nunca guarda HTML crudo (CLAUDE.md, D1). Sin red: el envío es una función falsa."""

from pathlib import Path

import pytest
from recon.client import Ledger, ReconClient, ReconError, Response

from avm.contract.pii import find_pii
from recon import fetch

PORTAL = "https://clasipar.paraguay.com"
ROBOTS = "User-agent: *\nDisallow: /app/\n"

# HTML inventado con la estructura de Clasipar: bloque de anunciante, logo y contactos.
RAW_PAGE = (
    "<html><body><h1>Casa ficticia</h1>"
    '<div class="infoAnunciante__header"><h5>Inmo Ficticia SA</h5>'
    '<a href="https://clasipar.paraguay.com/empresa/inmo-ficticia-9">perfil</a>'
    '<img src="//cdn.example/corporate/logo.jpg" alt="Inmo Ficticia SA"></div>'
    '<p class="desc-user">Llamar al 0981 123 456 o a vendedor@ejemplo.example.py</p>'
    "</body></html>"
)


class FakeServer:
    def __init__(self, body: str = RAW_PAGE) -> None:
        self.body = body.encode("utf-8")
        self.calls: list[str] = []

    def __call__(self, url: str) -> Response:
        self.calls.append(url)
        return Response(200, {}, self.body)


@pytest.fixture
def recon_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(fetch, "RECON_DIR", tmp_path)
    for source in ("clasipar", "infocasas"):
        (tmp_path / source).mkdir()
        (tmp_path / source / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    return tmp_path


def use_server(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    def make_client(source: str, ledger: Ledger, robots_txt: str) -> ReconClient:
        return ReconClient(
            source, ledger, robots_txt, send=server, sleep=lambda seconds: None, clock=lambda: 0.0
        )

    monkeypatch.setattr(fetch, "ReconClient", make_client)


def test_the_page_is_sanitized_before_it_is_written(
    recon_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeServer()
    use_server(monkeypatch, server)
    assert fetch.main(["clasipar", f"casa={PORTAL}/inmuebles/casas/casa-ficticia-1"]) == 0
    assert server.calls == [f"{PORTAL}/inmuebles/casas/casa-ficticia-1"]
    saved = (recon_dir / "clasipar" / "casa.body").read_text(encoding="utf-8")
    assert "Casa ficticia" in saved
    for leftover in ("Inmo", "/empresa/", "/corporate/", "0981", "vendedor@"):
        assert leftover not in saved
    assert not find_pii(saved)
    # Ningún archivo de la carpeta tiene el cuerpo crudo.
    for path in recon_dir.rglob("*"):
        if path.is_file():
            assert "Inmo Ficticia" not in path.read_text(encoding="utf-8")
    assert "casa: 200" in capsys.readouterr().out


def test_a_source_without_a_sanitizer_is_not_saved(
    recon_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeServer()
    use_server(monkeypatch, server)
    assert fetch.main(["infocasas", "casa=https://www.infocasas.com.py/venta/casas/asuncion"]) == 2
    assert server.calls == []  # ni siquiera se pide
    assert not list((recon_dir / "infocasas").glob("*.body"))
    assert "no se guarda HTML crudo" in capsys.readouterr().out


def test_sanitize_body_refuses_unknown_sources() -> None:
    with pytest.raises(ReconError, match="HTML crudo"):
        fetch.sanitize_body("otra", b"<html></html>")


def test_a_page_that_cannot_be_sanitized_stops_the_batch(
    recon_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # La cadena "api.whatsapp.com" sin barra no se reemplaza, pero el detector la ve: falla cerrado.
    use_server(monkeypatch, FakeServer('<html><a href="https://api.whatsapp.com">x</a></html>'))
    assert fetch.main(["clasipar", f"casa={PORTAL}/inmuebles/casas/casa-ficticia-1"]) == 1
    assert not (recon_dir / "clasipar" / "casa.body").exists()
    assert "STOP casa" in capsys.readouterr().out


def test_a_batch_over_the_budget_is_rejected(
    recon_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeServer()
    use_server(monkeypatch, server)
    monkeypatch.setattr(fetch, "MAX_REQUESTS_PER_SOURCE", 1)
    urls = [f"n{i}={PORTAL}/inmuebles/casas/casa-ficticia-{i}" for i in (1, 2)]
    assert fetch.main(["clasipar", *urls]) == 2
    assert server.calls == [] and "supera el tope" in capsys.readouterr().out
