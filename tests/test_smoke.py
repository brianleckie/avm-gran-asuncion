"""Smoke test: el paquete y todos sus subpaquetes se importan y tienen docstring."""

import importlib

import pytest

PACKAGES = [
    "avm",
    "avm.contract",
    "avm.synth",
    "avm.scraping",
    "avm.scraping.sources",
    "avm.pipeline",
    "avm.geo",
    "avm.model",
    "avm.api",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports_and_has_docstring(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__ is not None
    assert module.__doc__.strip()
