"""Listing (F1.3): aviso limpio y tipado, dentro del alcance de ADR-002.

El alcance lo garantizan los tipos: operación, tipo de inmueble y ciudad son enums que solo admiten
los valores incluidos, así que un alquiler o una ciudad fuera de alcance no validan.

Los campos clave (precio, moneda, m², barrio, coordenadas) llevan su procedencia: un campo del
portal (`estructurado`) o texto libre (`texto`). Las amenities son tri-estado: `None` significa que
el aviso no lo menciona, no que no lo tenga.

Precio (ADR-004 / ADR-005): siempre se guardan el monto y la moneda originales. Con moneda
desconocida (`price_currency=None`) el aviso es válido pero no tiene `price_usd` y tiene que
conservar `price_raw`, que es lo que permite decidir después sin volver a scrapear. Qué hacer con
esos avisos lo decide el ADR-005, y cualquiera de sus alternativas entra sin romper este schema
(ver docs/adr/006-contrato-v0.1.md).

No hay campo de target (USD/m²): se calcula en F8.1. Tampoco `cluster_id`: va en una tabla de
mapeo aparte (source + source_id → cluster_id, F5.3).
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator

from avm.contract.common import (
    MAX_AREA_M2,
    ContentHash,
    ContractModel,
    HttpUrlStr,
    NonBlankStr,
    UtcDatetime,
)
from avm.contract.enums import (
    AdvertiserType,
    City,
    CoordinateFlag,
    Currency,
    GeoPrecision,
    NeighborhoodMatch,
    OperationType,
    PropertyType,
    Provenance,
    Source,
    StreetSurface,
)

PositiveDecimal = Annotated[Decimal, Field(gt=0)]
AreaM2 = Annotated[Decimal, Field(gt=0, le=MAX_AREA_M2)]
Count = Annotated[int, Field(ge=0)]

# price_usd tiene que ser price_amount / cotización, salvo redondeo.
_FX_RELATIVE_TOLERANCE = Decimal("1e-6")
_MATCHED = frozenset(
    {
        NeighborhoodMatch.EXACT,
        NeighborhoodMatch.ALIAS,
        NeighborhoodMatch.FUZZY,
        NeighborhoodMatch.MANUAL,
    }
)


def _paired(value: object, provenance: object, name: str) -> None:
    if (value is None) != (provenance is None):
        raise ValueError(f"{name}: el valor y su procedencia van juntos (los dos o ninguno)")


class Listing(ContractModel):
    """Aviso limpio, tipado y dentro del alcance."""

    # Trazabilidad al crudo
    source: Source
    source_id: NonBlankStr
    url: HttpUrlStr
    scraped_at: UtcDatetime
    content_hash: ContentHash

    # Alcance (ADR-002)
    operation: OperationType = OperationType.SALE
    property_type: PropertyType
    property_type_raw: NonBlankStr | None = Field(
        None, description="Categoría del portal, que no garantiza el tipo real (sources.md §6.7)."
    )
    city: City

    # Barrio (F4.4, ADR-003)
    neighborhood_raw: NonBlankStr | None = None
    neighborhood_provenance: Provenance | None = None
    neighborhood_norm: NonBlankStr | None = Field(None, description="Nombre en el gazetteer.")
    neighborhood_match: NeighborhoodMatch | None = None

    # Precio (ADR-004, ADR-005)
    price_amount: PositiveDecimal = Field(description="Monto original, en su moneda.")
    price_currency: Currency | None = Field(description="None: moneda desconocida (ADR-005).")
    price_raw: NonBlankStr | None = Field(None, description="Texto original del precio.")
    price_provenance: Provenance
    currency_provenance: Provenance | None = None
    is_from_price: bool = Field(description='"desde" o rango: el precio es un mínimo.')
    price_usd: PositiveDecimal | None = None
    fx_rate_pyg_per_usd: PositiveDecimal | None = None
    fx_date: date | None = None

    # Superficies
    built_area_m2: AreaM2 | None = None
    built_area_provenance: Provenance | None = None
    land_area_m2: AreaM2 | None = None
    land_area_provenance: Provenance | None = None

    # Características
    bedrooms: Count | None = None
    bathrooms: Count | None = None
    garages: Count | None = None
    has_pool: bool | None = None
    has_quincho: bool | None = None
    is_new: bool | None = Field(None, description='"A estrenar".')
    in_gated_community: bool | None = Field(None, description="Condominio o barrio cerrado.")
    has_elevator: bool | None = None
    street_surface: StreetSurface | None = None
    advertiser_type: AdvertiserType | None = None
    published_at: date | None = Field(
        None, description="Fecha que publica el portal; puede ser de republicación (§2.5)."
    )

    # Ubicación (ADR-003, ADR-006)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    coordinates_provenance: Provenance | None = None
    coordinate_flags: tuple[CoordinateFlag, ...] = ()
    geo_precision: GeoPrecision

    @model_validator(mode="after")
    def _check_neighborhood(self) -> Self:
        if self.neighborhood_norm is not None and self.neighborhood_match not in _MATCHED:
            raise ValueError(
                "neighborhood_norm requiere un neighborhood_match que no sea sin_match"
            )
        if self.neighborhood_norm is None and self.neighborhood_match in _MATCHED:
            raise ValueError("neighborhood_match indica un match pero falta neighborhood_norm")
        _paired(self.neighborhood_raw, self.neighborhood_provenance, "neighborhood_raw")
        return self

    @model_validator(mode="after")
    def _check_price(self) -> Self:
        _paired(self.price_currency, self.currency_provenance, "price_currency")
        fx = (self.fx_rate_pyg_per_usd, self.fx_date)
        if self.price_currency is None:
            if self.price_usd is not None or any(v is not None for v in fx):
                raise ValueError("con moneda desconocida no hay price_usd ni cotización (ADR-005)")
            if self.price_raw is None:
                # ADR-005: el texto crudo es lo que permite decidir después sin volver a scrapear.
                raise ValueError("con moneda desconocida hace falta price_raw (ADR-005)")
        elif self.price_currency is Currency.USD:
            if self.price_usd != self.price_amount:
                raise ValueError("en USD, price_usd tiene que ser igual a price_amount")
            if any(v is not None for v in fx):
                raise ValueError("un precio en USD no lleva cotización")
        else:
            if self.price_usd is None or self.fx_rate_pyg_per_usd is None or self.fx_date is None:
                raise ValueError("en PYG hacen falta price_usd, fx_rate_pyg_per_usd y fx_date")
            expected = self.price_amount / self.fx_rate_pyg_per_usd
            if abs(self.price_usd - expected) > expected * _FX_RELATIVE_TOLERANCE:
                raise ValueError("price_usd no coincide con price_amount / fx_rate_pyg_per_usd")
        return self

    @model_validator(mode="after")
    def _check_areas(self) -> Self:
        _paired(self.built_area_m2, self.built_area_provenance, "built_area_m2")
        _paired(self.land_area_m2, self.land_area_provenance, "land_area_m2")
        return self

    @model_validator(mode="after")
    def _check_geo(self) -> Self:
        has_coordinates = self.latitude is not None
        if has_coordinates != (self.longitude is not None):
            raise ValueError("latitude y longitude van juntas (las dos o ninguna)")
        _paired(self.latitude, self.coordinates_provenance, "coordenadas")
        if self.coordinate_flags and not has_coordinates:
            raise ValueError("coordinate_flags requiere coordenadas")
        if len(set(self.coordinate_flags)) != len(self.coordinate_flags):
            raise ValueError("coordinate_flags no admite repetidos")

        with_coordinates = {GeoPrecision.EXACT, GeoPrecision.APPROXIMATE}
        if has_coordinates and self.geo_precision not in with_coordinates:
            raise ValueError("con coordenadas, geo_precision es exacta o aproximada")
        if not has_coordinates and self.geo_precision in with_coordinates:
            raise ValueError("sin coordenadas, geo_precision es barrio o ciudad")
        if self.geo_precision is GeoPrecision.NEIGHBORHOOD and self.neighborhood_norm is None:
            raise ValueError("geo_precision=barrio requiere neighborhood_norm")
        if self.geo_precision is GeoPrecision.CITY and self.neighborhood_norm is not None:
            raise ValueError("con neighborhood_norm la precisión es barrio, no ciudad")
        if self.geo_precision is GeoPrecision.EXACT and self.coordinate_flags:
            raise ValueError("unas coordenadas marcadas como sospechosas no pueden ser exactas")
        return self
