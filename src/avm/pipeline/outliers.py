"""Reglas de outliers A PRIORI (F4.6). Aprobadas por el equipo el 2026-11-05.

Son detectores de errores de ESCALA: un cero de más, el terreno cargado como construido, guaraníes
leídos como dólares o al revés. Los números son supuestos del equipo, NO datos de mercado ni se
calcularon mirando la distribución del dataset; y no se recalibran después de verla: si una regla
descarta mucho, se informa en el reporte, no se cambia (ADR-005 B y ADR-006 sobre F4.6, leakage).
Son constantes fijas: no dependen del target de ningún fold, así que aplicarlas antes del split no
filtra información.

- m² construidos: por debajo de `MIN_BUILT_M2` no es una vivienda en venta (dato mal cargado, otra
  unidad); por encima de `MAX_BUILT_M2[tipo]` suele ser un cero de más o el terreno como construido.
  El máximo es menor en departamentos y dúplex que en casas por la naturaleza física del inmueble.
- USD/m²: mismo rango para los tres tipos a propósito (rangos distintos por tipo meterían
  conocimiento de mercado que no tenemos: la diferencia entre tipos la aprende el modelo). Atrapa
  errores de escala de al menos un orden de magnitud; no pretende limpiar precios "caros" o
  "baratos".

Un aviso se cuenta en la primera regla que falla, en este orden: `OUTLIER_ORDER`. Los límites son
inclusivos: se descarta lo que queda estrictamente fuera.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Final

from avm.contract import PropertyType

MIN_BUILT_M2: Final = Decimal(15)
MAX_BUILT_M2: Final = {
    PropertyType.APARTMENT: Decimal(600),
    PropertyType.DUPLEX: Decimal(1000),
    PropertyType.HOUSE: Decimal(2000),
}
MIN_USD_PER_M2: Final = Decimal(150)
MAX_USD_PER_M2: Final = Decimal(8000)


class Outlier(StrEnum):
    BUILT_TOO_SMALL = "outlier_m2_construidos_minimo"
    BUILT_TOO_LARGE = "outlier_m2_construidos_maximo"
    USD_M2_TOO_LOW = "outlier_usd_por_m2_minimo"
    USD_M2_TOO_HIGH = "outlier_usd_por_m2_maximo"


OUTLIER_ORDER: Final = tuple(Outlier)


def outlier_rule(
    property_type: PropertyType, built_area_m2: Decimal, usd_per_m2: Decimal
) -> Outlier | None:
    """La primera regla de outlier que incumple el aviso, o None si pasa todas."""
    if built_area_m2 < MIN_BUILT_M2:
        return Outlier.BUILT_TOO_SMALL
    if built_area_m2 > MAX_BUILT_M2[property_type]:
        return Outlier.BUILT_TOO_LARGE
    if usd_per_m2 < MIN_USD_PER_M2:
        return Outlier.USD_M2_TOO_LOW
    if usd_per_m2 > MAX_USD_PER_M2:
        return Outlier.USD_M2_TOO_HIGH
    return None
