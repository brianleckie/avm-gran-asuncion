"""Guardia de `deploy/model/` (ADR-008): falla si el artefacto publicado tiene forma de aviso.

`deploy/model/` se versiona en git y viaja a Railway, así que solo puede contener parámetros del
modelo, agregados y referencias geográficas (docs/interfaces.md, I4). Nunca filas de avisos
(ADR-007). Reglas:

1. Solo archivos de una lista cerrada: `model.<ext>`, `calibration.json`, `gazetteer.csv`,
   `geo_features.csv`, `metadata.json` y `ATTRIBUTION*`. Sin subcarpetas ni otros archivos.
2. `gazetteer.csv` y `geo_features.csv` solo con las columnas de I2 / I3.
3. En CSV, JSON y texto: sin URLs, emails, teléfonos paraguayos ni valores con forma de
   `listing_key` (`<fuente>:<id>`), y sin claves de aviso en el JSON.
4. Sin textos largos (umbral heurístico `MAX_TEXT_CHARS`, no una medida del dominio).

Límite: los archivos `model.*` son opacos. Se valida el nombre y la extensión, y en los de texto
se buscan URLs, emails y teléfonos; el contenido de un binario no se inspecciona, así que la
revisión del modelo por Oscar sigue siendo el control real (ADR-008).

Uso: `uv run python scripts/check_deploy_model.py [carpeta]` (por defecto `deploy/model`). Si la
carpeta no existe (todavía no hay modelo) sale con 0.
"""

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path("deploy/model")

# Heurística: ningún valor de metadata, gazetteer o features necesita más que esto.
MAX_TEXT_CHARS = 200

FIXED_FILES = frozenset({"calibration.json", "gazetteer.csv", "geo_features.csv", "metadata.json"})
MODEL_EXTENSIONS = frozenset(
    {".txt", ".json", ".joblib", ".pkl", ".bin", ".ubj", ".lgb", ".onnx", ".skops"}
)
TEXT_MODEL_EXTENSIONS = frozenset({".txt", ".json"})

# I2 (docs/interfaces.md). I3: city, neighborhood, geo_precision + dist_* / n_*.
GAZETTEER_COLUMNS = frozenset(
    {"city", "neighborhood", "aliases", "lat", "lon", "centroid_method", "osm_id", "source"}
)
GEO_FEATURES_FIXED = frozenset({"city", "neighborhood", "geo_precision"})
GEO_FEATURES_PATTERN = re.compile(r"^(dist|n)_[a-z0-9_]+$")

FORBIDDEN_JSON_KEYS = frozenset(
    {
        "listing_key",
        "source_id",
        "cluster_id",
        "url",
        "urls",
        "title",
        "phone",
        "telefono",
        "email",
        "advertiser",
        "advertiser_type",
        "is_sponsored",
        "price_usd",
    }
)

URL = re.compile(r"(?:https?:/{0,2}|www\.)\S+", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Móvil paraguayo (09xx xxx xxx) o +595: heurística, no cubre todos los formatos.
PHONE = re.compile(r"(?<!\d)(?:\+?595[\s.-]?|0)9\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)")
LISTING_KEY = re.compile(r"^[A-Za-z_]+:\d+$")


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _scan_contact(where: str, value: str) -> list[str]:
    problems: list[str] = []
    if URL.search(value):
        problems.append(f"{where}: contiene una URL")
    if EMAIL.search(value):
        problems.append(f"{where}: contiene un email")
    if PHONE.search(value):
        problems.append(f"{where}: contiene un teléfono")
    return problems


def _scan_value(where: str, value: str) -> list[str]:
    problems = _scan_contact(where, value)
    if LISTING_KEY.match(value.strip()):
        problems.append(f"{where}: tiene forma de listing_key (<fuente>:<id>)")
    if len(value) > MAX_TEXT_CHARS:
        problems.append(f"{where}: texto de {len(value)} caracteres (máx. {MAX_TEXT_CHARS})")
    return problems


def _check_csv(path: Path) -> list[str]:
    problems: list[str] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None) or []
        if path.name == "gazetteer.csv":
            extra = [c for c in header if c not in GAZETTEER_COLUMNS]
        else:
            extra = [
                c
                for c in header
                if c not in GEO_FEATURES_FIXED and not GEO_FEATURES_PATTERN.match(c)
            ]
        if extra:
            problems.append(f"{path.name}: columnas fuera de la interfaz (I2/I3): {sorted(extra)}")
        for number, row in enumerate(reader, start=2):
            for column, cell in zip(header, row, strict=False):
                if cell and not _is_number(cell):
                    problems += _scan_value(f"{path.name} fila {number} [{column}]", cell)
    return problems


def _walk_json(where: str, node: Any) -> list[str]:
    problems: list[str] = []
    if isinstance(node, dict):
        for key, item in node.items():
            if str(key).lower() in FORBIDDEN_JSON_KEYS:
                problems.append(f"{where}: clave prohibida {key!r}")
            problems += _walk_json(f"{where}.{key}", item)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            problems += _walk_json(f"{where}[{index}]", item)
    elif isinstance(node, str):
        problems += _scan_value(where, node)
    return problems


def _check_json(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return [f"{path.name}: no es un JSON válido en UTF-8"]
    return _walk_json(path.name, data)


def _check_free_text(path: Path) -> list[str]:
    """Archivos de texto sin estructura (modelo .txt, ATTRIBUTION): URLs, emails y teléfonos."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{path.name}: no es texto UTF-8"]
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        problems += _scan_contact(f"{path.name} línea {number}", line)
    return problems


def _is_allowed(path: Path) -> bool:
    name = path.name
    if name in FIXED_FILES or name.startswith("ATTRIBUTION"):
        return True
    return path.stem == "model" and path.suffix.lower() in MODEL_EXTENSIONS


def check_dir(model_dir: Path) -> list[str]:
    """Lista de problemas (vacía = el artefacto es publicable)."""
    problems: list[str] = []
    for path in sorted(model_dir.iterdir()):
        if path.is_dir():
            problems.append(f"{path.name}/: las subcarpetas no están permitidas")
        elif not _is_allowed(path):
            problems.append(f"{path.name}: archivo fuera de la lista permitida")
        elif path.name.endswith(".csv"):
            problems += _check_csv(path)
        elif path.name in {"calibration.json", "metadata.json"}:
            problems += _check_json(path)
        elif path.name.startswith("ATTRIBUTION") or path.suffix.lower() in TEXT_MODEL_EXTENSIONS:
            problems += _check_free_text(path)
    return problems


def main(argv: list[str]) -> int:
    model_dir = Path(argv[0]) if argv else DEFAULT_DIR
    if not model_dir.is_dir():
        print(f"{model_dir} no existe: todavía no hay modelo publicado (la API queda en 503).")
        return 0
    problems = check_dir(model_dir)
    for problem in problems:
        print(f"FALLA {problem}")
    if problems:
        print(f"{len(problems)} problema(s): {model_dir} NO se puede publicar.")
        return 1
    print(f"OK: {model_dir} cumple la guardia (ADR-008).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
