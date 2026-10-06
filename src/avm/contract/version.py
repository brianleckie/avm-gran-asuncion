"""Versión semántica del contrato de datos (F1.8).

Política (ADR-006):
- MENOR (0.x.0): agregar un valor a un enum o un campo opcional. Los datos viejos siguen validando.
- MAYOR: quitar o renombrar un campo o un valor de enum, o volver obligatorio un campo opcional.
  Requiere un ADR y una migración.
- PATCH: documentación o validaciones que no cambian qué datos son válidos.
"""

from typing import Final

CONTRACT_VERSION: Final = "0.1.1"
