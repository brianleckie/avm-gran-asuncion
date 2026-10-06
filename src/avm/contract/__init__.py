"""Contrato de datos: schemas pydantic que son la fuente de verdad del proyecto.

Versión 0.1.1, PROPUESTA pendiente de revisión (docs/adr/006-contrato-v0.1.md).
"""

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
    WarningCode,
)
from avm.contract.listing import Listing
from avm.contract.prediction import (
    PRICE_LABEL,
    PredictionRequest,
    PredictionResponse,
    PredictionWarning,
)
from avm.contract.raw_listing import RawListing
from avm.contract.version import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "PRICE_LABEL",
    "AdvertiserType",
    "City",
    "CoordinateFlag",
    "Currency",
    "GeoPrecision",
    "Listing",
    "NeighborhoodMatch",
    "OperationType",
    "PredictionRequest",
    "PredictionResponse",
    "PredictionWarning",
    "PropertyType",
    "Provenance",
    "RawListing",
    "Source",
    "StreetSurface",
    "WarningCode",
]
