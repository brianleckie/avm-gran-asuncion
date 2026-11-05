"""Reglas de outliers a priori (F4.6): los bordes de cada cota, escritos a mano."""

from decimal import Decimal

import pytest

from avm.contract import PropertyType
from avm.pipeline.outliers import Outlier, outlier_rule

HOUSE, APARTMENT, DUPLEX = PropertyType.HOUSE, PropertyType.APARTMENT, PropertyType.DUPLEX


def check(kind: PropertyType, built: str, usd_m2: str) -> Outlier | None:
    return outlier_rule(kind, Decimal(built), Decimal(usd_m2))


@pytest.mark.parametrize("kind", [HOUSE, APARTMENT, DUPLEX])
def test_the_minimum_area_is_15_m2_for_every_type_and_is_inclusive(kind: PropertyType) -> None:
    assert check(kind, "15", "1000") is None
    assert check(kind, "14.99", "1000") is Outlier.BUILT_TOO_SMALL


@pytest.mark.parametrize(
    ("kind", "maximum"), [(APARTMENT, "600"), (DUPLEX, "1000"), (HOUSE, "2000")]
)
def test_the_maximum_area_depends_on_the_type_and_is_inclusive(
    kind: PropertyType, maximum: str
) -> None:
    assert check(kind, maximum, "1000") is None
    assert check(kind, str(Decimal(maximum) + Decimal("0.01")), "1000") is Outlier.BUILT_TOO_LARGE


def test_the_same_area_can_pass_for_a_house_and_fail_for_an_apartment() -> None:
    assert check(HOUSE, "601", "1000") is None
    assert check(APARTMENT, "601", "1000") is Outlier.BUILT_TOO_LARGE


@pytest.mark.parametrize("kind", [HOUSE, APARTMENT, DUPLEX])
def test_usd_per_m2_must_be_between_150_and_8000_for_every_type(kind: PropertyType) -> None:
    assert check(kind, "100", "150") is None
    assert check(kind, "100", "149.99") is Outlier.USD_M2_TOO_LOW
    assert check(kind, "100", "8000") is None
    assert check(kind, "100", "8000.01") is Outlier.USD_M2_TOO_HIGH


def test_a_listing_is_counted_in_the_first_rule_it_fails() -> None:
    assert check(HOUSE, "10", "5") is Outlier.BUILT_TOO_SMALL
    assert check(HOUSE, "5000", "9000") is Outlier.BUILT_TOO_LARGE
