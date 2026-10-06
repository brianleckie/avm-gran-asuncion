"""Tipos y base compartidos por los schemas del contrato."""

from datetime import datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
)

# Tope de superficie: el mismo que usa avm.pipeline.parsing (fuera de (0, 100.000] m² es inválido).
MAX_AREA_M2 = 100_000


class ContractModel(BaseModel):
    """Base: inmutable y sin campos extra (un parser no puede colar, por ejemplo, un teléfono).

    No se recortan espacios en forma global: los campos crudos y la URL quedan como vinieron.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("no puede estar vacío")
    return value


def _http_url(value: str) -> str:
    """Valida sin normalizar: la URL se guarda idéntica al crudo (deduplicación exacta, F5.1)."""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("debe ser una URL http(s) absoluta")
    if any(char.isspace() for char in value):
        raise ValueError("la URL no puede contener espacios")
    return value


def _utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("debe estar en UTC (offset +00:00)")
    return value


def _blank_to_none(value: object) -> object:
    """Texto crudo: un string vacío o con solo espacios es ausencia de dato (JSON-LD con "")."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _rule(text: str) -> object:
    """Documenta en el JSON Schema una validación propia (la lee el diccionario de datos, F1.6)."""
    return Field(json_schema_extra={"x-validacion": text})


NonBlankStr = Annotated[str, AfterValidator(_non_blank), _rule("no vacío")]
HttpUrlStr = Annotated[
    str, AfterValidator(_http_url), _rule("URL http(s) absoluta, sin espacios, sin normalizar")
]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_utc), _rule("con zona horaria, en UTC")]
RawText = Annotated[str | None, BeforeValidator(_blank_to_none), _rule("texto crudo; vacío → null")]
ContentHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$"), _rule("sha256 hexadecimal")]
