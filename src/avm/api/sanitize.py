"""Metadata pública: lo que sale por GET /model-info no incluye rutas locales."""

import re
from datetime import date, datetime
from pathlib import PurePath
from typing import Any

_PATH_KEY = re.compile(
    r"(^|_)(path|paths|dir|dirs|directory|folder|file|files)($|_)", re.IGNORECASE
)
_PATH_VALUE = re.compile(r"^([A-Za-z]:[\\/]|\\\\|/|~[\\/]|\.{1,2}[\\/])|[\\]")


def _is_path_string(value: str) -> bool:
    return bool(_PATH_VALUE.search(value))


def public_metadata(value: Any) -> Any:
    """Copia JSON-segura: descarta claves de rutas y strings con forma de ruta."""
    if isinstance(value, dict):
        return {
            str(key): public_metadata(item)
            for key, item in value.items()
            if not _PATH_KEY.search(str(key))
            and not (isinstance(item, str) and _is_path_string(item))
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [
            public_metadata(item)
            for item in value
            if not (isinstance(item, str) and _is_path_string(item))
        ]
    if isinstance(value, PurePath):
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
