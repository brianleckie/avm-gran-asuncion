"""Versión del contrato y enums."""

import re

import avm.contract as contract
from avm.contract import CONTRACT_VERSION, City, OperationType, PropertyType


def test_contract_version_is_semver_and_exported() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", CONTRACT_VERSION)
    assert CONTRACT_VERSION == "0.1.0"
    assert "CONTRACT_VERSION" in contract.__all__


def test_scope_enums_match_adr_002() -> None:
    assert {c.value for c in City} == {"asuncion", "luque", "san_lorenzo", "fernando_de_la_mora"}
    assert {t.value for t in PropertyType} == {"casa", "departamento", "duplex"}
    assert {o.value for o in OperationType} == {"venta"}
