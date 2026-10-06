"""Genera docs/data_dictionary.md desde los schemas del contrato (F1.6).

Uso (desde la raíz del repo):
    uv run python scripts/gen_data_dictionary.py           # reescribe el archivo
    uv run python scripts/gen_data_dictionary.py --check   # falla si está desactualizado

Lee el JSON Schema que genera pydantic (`model_json_schema()`) y lo vuelca en tablas markdown.
La salida es determinística: mismo contrato, mismo archivo. No editar el .md a mano.
"""

from __future__ import annotations

import inspect
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import avm.contract as contract
from avm.contract import (
    CONTRACT_VERSION,
    Listing,
    PredictionRequest,
    PredictionResponse,
    PredictionWarning,
    RawListing,
)

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "data_dictionary.md"
MODELS: tuple[type[BaseModel], ...] = (
    RawListing,
    Listing,
    PredictionRequest,
    PredictionResponse,
    PredictionWarning,
)
_CONSTRAINTS = (
    ("exclusiveMinimum", "> {}"),
    ("minimum", ">= {}"),
    ("exclusiveMaximum", "< {}"),
    ("maximum", "<= {}"),
    ("pattern", "patrón `{}`"),
    ("const", "fijo: `{}`"),
)


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _is_decimal(options: list[dict[str, Any]]) -> bool:
    types = {option.get("type") for option in options}
    return types == {"number", "string"} and any("pattern" in o for o in options)


def _describe(prop: dict[str, Any]) -> tuple[str, bool, list[str]]:
    """(tipo, admite null, restricciones) de una propiedad del JSON Schema."""
    options = prop.get("anyOf", [prop])
    nullable = any(option.get("type") == "null" for option in options)
    options = [option for option in options if option.get("type") != "null"]
    constraints: list[str] = []
    if _is_decimal(options):
        type_name = "decimal"
        options = [option for option in options if option.get("type") == "number"]
    else:
        names = []
        for option in options:
            if "$ref" in option:
                names.append(f"`{option['$ref'].rsplit('/', 1)[-1]}`")
            elif option.get("type") == "array":
                item = option["items"]
                inner = item["$ref"].rsplit("/", 1)[-1] if "$ref" in item else item.get("type")
                names.append(f"lista de `{inner}`")
            elif option.get("type") == "object":
                names.append("objeto clave-valor (string → string)")
            else:
                fmt = option.get("format")
                names.append(fmt if fmt in ("date", "date-time") else option.get("type", "?"))
        type_name = " \\| ".join(names)
    for option in options:
        for key, template in _CONSTRAINTS:
            if key in option:
                constraints.append(template.format(option[key]))
    if "x-validacion" in prop:
        constraints.append(prop["x-validacion"])
    return type_name, nullable, constraints


def render_model(model: type[BaseModel]) -> list[str]:
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    lines = [f"## {model.__name__}", "", inspect.cleandoc(model.__doc__ or ""), ""]
    lines += [
        "| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, prop in schema["properties"].items():
        type_name, nullable, constraints = _describe(prop)
        default = (
            f"`{json.dumps(prop['default'], ensure_ascii=False)}`" if "default" in prop else ""
        )
        lines.append(
            f"| `{name}` | {type_name} | {'sí' if name in required else 'no'} | "
            f"{'sí' if nullable else 'no'} | {_cell(default)} | {_cell('; '.join(constraints))} | "
            f"{_cell(prop.get('description', ''))} |"
        )
    return [*lines, ""]


def render_enums() -> list[str]:
    lines = ["## Enums", "", "| Enum | Valores | Descripción |", "|---|---|---|"]
    enums = sorted(
        (
            obj
            for obj in vars(contract).values()
            if isinstance(obj, type) and issubclass(obj, StrEnum)
        ),
        key=lambda enum: enum.__name__,
    )
    for enum in enums:
        values = ", ".join(f"`{member.value}`" for member in enum)
        doc = inspect.cleandoc(enum.__doc__ or "")
        lines.append(f"| `{enum.__name__}` | {values} | {_cell(doc)} |")
    return [*lines, ""]


def render() -> str:
    lines = [
        "# Diccionario de datos",
        "",
        f"Contrato v{CONTRACT_VERSION}, PROPUESTA pendiente de revisión "
        "(docs/adr/006-contrato-v0.1.md).",
        "",
        "**Archivo generado** por `scripts/gen_data_dictionary.py` desde `src/avm/contract/`: no",
        "editarlo a mano. Las reglas entre campos (por ejemplo, valor y procedencia van juntos)",
        "están en los docstrings de `src/avm/contract/` y en el ADR-006; el JSON Schema no las",
        "expresa.",
        "",
    ]
    lines += render_enums()
    for model in MODELS:
        lines += render_model(model)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(f"{OUTPUT} está desactualizado: correr scripts/gen_data_dictionary.py")
            return 1
        return 0
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"escrito {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
