"""Validación por lotes (F1.7): separa registros válidos de inválidos sin cortar en el primero.

Pensado para el pipeline y el reporte de calidad (F4.7): cuántos avisos no cumplen el contrato y
por qué. Los errores no incluyen el valor de entrada, para no copiar datos personales a un log.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True, slots=True)
class RecordError:
    index: int
    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchResult[M: BaseModel]:
    valid: list[M] = field(default_factory=list)
    errors: list[RecordError] = field(default_factory=list)


def validate_records[M: BaseModel](
    model: type[M], records: Iterable[Mapping[str, object]]
) -> BatchResult[M]:
    """Valida cada registro contra `model`; los inválidos quedan en `errors` con su posición."""
    result: BatchResult[M] = BatchResult()
    for index, record in enumerate(records):
        try:
            result.valid.append(model.model_validate(record))
        except ValidationError as exc:
            messages = tuple(
                f"{'.'.join(str(part) for part in error['loc']) or '<modelo>'}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            result.errors.append(RecordError(index=index, messages=messages))
    return result
