"""Tipos y base compartidos por los schemas del contrato."""

from datetime import datetime, timedelta
from typing import Annotated, ClassVar, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from avm.contract.pii import find_pii

# Tope de superficie: el mismo que usa avm.pipeline.parsing (fuera de (0, 100.000] m² es inválido).
MAX_AREA_M2 = 100_000


class ContractModel(BaseModel):
    """Base de todos los schemas: inmutable, sin campos extra y sin datos personales.

    - `extra="forbid"`: un parser no puede colar campos (por ejemplo, un teléfono).
    - Ningún texto (campos string y claves/valores de diccionarios) puede contener teléfonos,
      emails ni links de WhatsApp (CLAUDE.md). Ni los mensajes de error ni el input en el error
      repiten el dato, para que no termine en un log.
    - No se recortan espacios en forma global: los campos crudos y la URL quedan como vinieron.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    # Campos que no son texto libre y no se revisan (un sha256 puede empezar con "0981...").
    _PII_EXEMPT: ClassVar[frozenset[str]] = frozenset({"content_hash"})

    @model_validator(mode="after")
    def _no_personal_data(self) -> Self:
        for name, value in self:
            if name in self._PII_EXEMPT:
                continue
            if isinstance(value, str):
                texts = [value]
            elif isinstance(value, dict):
                texts = [f"{key} {item}" for key, item in value.items()]
            else:
                continue
            for text in texts:
                if found := find_pii(text):
                    raise ValueError(f"{name} contiene datos personales ({', '.join(found)})")
        return self


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
