"""Valores cerrados del contrato. Los valores van en español porque son datos del dominio.

La justificación de cada enum está en docs/adr/006-contrato-v0.1.md. Agregar un valor es un cambio
menor de CONTRACT_VERSION; quitarlo o renombrarlo es un cambio mayor.
"""

from enum import StrEnum


class Source(StrEnum):
    """Portal de origen del aviso. `sintetico` es el generador de F2."""

    CLASIPAR = "clasipar"
    INFOCASAS = "infocasas"
    SYNTHETIC = "sintetico"


class City(StrEnum):
    """Ciudades del alcance (ADR-002). Cualquier otra ciudad es inválida."""

    ASUNCION = "asuncion"
    LUQUE = "luque"
    SAN_LORENZO = "san_lorenzo"
    FERNANDO_DE_LA_MORA = "fernando_de_la_mora"


class PropertyType(StrEnum):
    """Tipos de inmueble del alcance (ADR-002)."""

    HOUSE = "casa"
    APARTMENT = "departamento"
    DUPLEX = "duplex"


class OperationType(StrEnum):
    """Operación del alcance (ADR-002). Solo venta: un alquiler es inválido por construcción."""

    SALE = "venta"


class Currency(StrEnum):
    """Monedas observadas en F3.1 (docs/sources.md §5)."""

    USD = "USD"
    PYG = "PYG"


class Provenance(StrEnum):
    """De dónde salió un valor: un campo del portal o texto libre (título, descripción)."""

    STRUCTURED = "estructurado"
    TEXT = "texto"


class GeoPrecision(StrEnum):
    """Resolución de la ubicación del aviso (ADR-003, ampliado por ADR-006 con `ciudad`).

    - exacta / aproximada: hay coordenadas; `exacta` solo si se validó la precisión de la fuente.
    - barrio: sin coordenadas, con barrio normalizado.
    - ciudad: sin coordenadas ni barrio normalizado (F3.1: avisos donde el "barrio" es la ciudad).
    """

    EXACT = "exacta"
    APPROXIMATE = "aproximada"
    NEIGHBORHOOD = "barrio"
    CITY = "ciudad"


class CoordinateFlag(StrEnum):
    """Señales de que unas coordenadas no son la ubicación real del inmueble.

    `compartidas`: idénticas a las de otro aviso distinto (F3.1, docs/sources.md §1.5).
    """

    SHARED = "compartidas"


class NeighborhoodMatch(StrEnum):
    """Método con el que se normalizó el barrio (F4.4). Nada se asigna en silencio."""

    EXACT = "exacto"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    MANUAL = "manual"
    UNMATCHED = "sin_match"


class AdvertiserType(StrEnum):
    """Tipo de anunciante. No es un dato personal: el nombre nunca se guarda."""

    PRIVATE = "particular"
    AGENCY = "inmobiliaria"


class StreetSurface(StrEnum):
    """Superficie de la calle (F4.5)."""

    PAVED = "pavimento"
    COBBLESTONE = "empedrado"
    DIRT = "tierra"


class WarningCode(StrEnum):
    """Advertencias de una predicción (F11.3, F7.2, F9.4)."""

    UNKNOWN_NEIGHBORHOOD = "barrio_desconocido"
    CITY_FALLBACK = "fallback_ciudad"
    LOW_DATA = "pocos_datos"
