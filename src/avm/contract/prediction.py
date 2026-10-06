"""PredictionRequest / PredictionResponse (F1.5): entrada y salida de POST /predict.

La respuesta es un precio de OFERTA estimado (ADR-001): la leyenda es un campo fijo de la
respuesta, no un texto que el frontend pueda omitir.

El request no admite coordenadas: el formulario pide barrio, no dirección (ADR-003). Exige
`built_area_m2` porque el valor total se obtiene como USD/m² × m² (F8.1); que el denominador del
target sea la superficie construida es una decisión provisoria (ADR-006, P13).
"""

from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from avm.contract.common import MAX_AREA_M2, ContractModel, NonBlankStr
from avm.contract.enums import City, PropertyType, StreetSurface, WarningCode
from avm.contract.version import CONTRACT_VERSION

PRICE_LABEL: Final = "precio de oferta estimado"

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
AreaM2 = Annotated[float, Field(gt=0, le=MAX_AREA_M2, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]


class PredictionRequest(ContractModel):
    """Inmueble a estimar. Ciudad y tipo fuera del alcance (ADR-002) son inválidos."""

    city: City
    neighborhood: NonBlankStr | None = Field(
        None, description="Barrio del gazetteer; si es desconocido se cae a la ciudad (F11.3)."
    )
    property_type: PropertyType
    built_area_m2: AreaM2
    land_area_m2: AreaM2 | None = None
    bedrooms: Count | None = None
    bathrooms: Count | None = None
    garages: Count | None = None
    has_pool: bool | None = None
    has_quincho: bool | None = None
    is_new: bool | None = None
    in_gated_community: bool | None = None
    has_elevator: bool | None = None
    street_surface: StreetSurface | None = None


class PredictionWarning(ContractModel):
    """Advertencia de una predicción: código cerrado más un mensaje para mostrar al usuario."""

    code: WarningCode
    message: NonBlankStr


class PredictionResponse(ContractModel):
    """Estimación puntual e intervalo, por m² y total, en USD."""

    label: Literal["precio de oferta estimado"] = PRICE_LABEL
    usd_per_m2: PositiveFloat
    p_low: PositiveFloat = Field(description="Límite inferior del intervalo de USD/m².")
    p_high: PositiveFloat = Field(description="Límite superior del intervalo de USD/m².")
    total_usd: PositiveFloat
    total_low: PositiveFloat
    total_high: PositiveFloat
    coverage_nominal: float = Field(gt=0, lt=1, description="Cobertura nominal del intervalo.")
    warnings: tuple[PredictionWarning, ...] = ()
    model_version: NonBlankStr
    contract_version: SemVer = CONTRACT_VERSION

    @model_validator(mode="after")
    def _check_intervals(self) -> Self:
        if not self.p_low <= self.usd_per_m2 <= self.p_high:
            raise ValueError("se requiere p_low <= usd_per_m2 <= p_high")
        if not self.total_low <= self.total_usd <= self.total_high:
            raise ValueError("se requiere total_low <= total_usd <= total_high")
        return self
