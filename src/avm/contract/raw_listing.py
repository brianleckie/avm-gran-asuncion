"""RawListing (F1.2): lo que devuelve un parser, antes de cualquier limpieza.

Todo el contenido es texto crudo opcional. Un valor que el portal da estructurado también se guarda
como string (ej. m² construidos "400"): así el mismo schema representa una fuente con JSON
estructurado (InfoCasas) y una de puro texto (Clasipar, docs/sources.md §3). Interpretar los
valores es trabajo del pipeline (F4), que registra la procedencia en Listing.

Ningún campo de texto puede contener teléfonos, emails ni links de WhatsApp: el parser tiene que
sanitizar antes de construir el objeto (CLAUDE.md, F3.5). Los mensajes de error no repiten el
input para que un dato personal rechazado no termine en un log.
"""

from typing import Self

from pydantic import ConfigDict, Field, model_validator

from avm.contract.common import (
    ContentHash,
    ContractModel,
    HttpUrlStr,
    NonBlankStr,
    RawText,
    UtcDatetime,
)
from avm.contract.enums import Source
from avm.contract.pii import find_pii


class RawListing(ContractModel):
    """Aviso tal como lo extrae el parser de una fuente."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    source: Source
    source_id: NonBlankStr = Field(description="Id del aviso en la fuente (dedup exacto, F5.1).")
    url: HttpUrlStr = Field(description="URL del aviso, idéntica al crudo (sin normalizar).")
    scraped_at: UtcDatetime = Field(description="Momento del scrape, en UTC.")
    content_hash: ContentHash = Field(description="sha256 del contenido crudo (F3.6).")

    title_raw: RawText = None
    description_raw: RawText = None
    price_raw: RawText = Field(None, description="Precio como lo publica el portal.")
    currency_raw: RawText = Field(None, description="Moneda si el portal la da en un campo aparte.")
    built_area_raw: RawText = Field(None, description="m² construidos si vienen estructurados.")
    land_area_raw: RawText = Field(None, description="m² de terreno si vienen estructurados.")
    bedrooms_raw: RawText = None
    bathrooms_raw: RawText = None
    garages_raw: RawText = None
    property_type_raw: RawText = Field(None, description="Categoría o tipo según el portal.")
    operation_raw: RawText = None
    city_raw: RawText = None
    neighborhood_raw: RawText = Field(None, description="Barrio o zona como lo da el portal.")
    address_raw: RawText = None
    latitude_raw: RawText = None
    longitude_raw: RawText = None
    published_at_raw: RawText = None
    advertiser_type_raw: RawText = None
    attributes_raw: dict[NonBlankStr, NonBlankStr] = Field(
        default_factory=dict,
        description="Otros pares clave-valor del portal (tags, ficha técnica).",
    )

    @model_validator(mode="after")
    def _no_personal_data(self) -> Self:
        texts = [(name, value) for name, value in self if isinstance(value, str)]
        texts += [(f"attributes_raw[{k!r}]", f"{k} {v}") for k, v in self.attributes_raw.items()]
        for name, text in texts:
            if found := find_pii(text):
                raise ValueError(f"{name} contiene datos personales ({', '.join(found)})")
        return self
