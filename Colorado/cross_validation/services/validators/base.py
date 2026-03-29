"""
Helpers compartidos por todos los validadores.
"""
from __future__ import annotations

from typing import Any
from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor, get_confiabilidad, get_valor_str  # re-export


def h(
    codigo: str,
    nombre: str,
    bloque: int,
    bloque_nombre: str,
    pasa: bool | None,
    severidad: Severidad,
    mensaje: str,
    **detalles: Any,
) -> Hallazgo:
    """Construye un Hallazgo de forma concisa."""
    return Hallazgo(
        codigo=codigo,
        nombre=nombre,
        bloque=bloque,
        bloque_nombre=bloque_nombre,
        pasa=pasa,
        severidad=severidad,
        mensaje=mensaje,
        detalles=detalles,
    )


def doc_disponible(exp: ExpedienteEmpresa, doc_type: str) -> bool:
    """Verifica si un tipo de documento está presente en el expediente."""
    return doc_type in exp.documentos


def obtener_datos(exp: ExpedienteEmpresa, doc_type: str) -> dict[str, Any]:
    """Obtiene datos_extraidos de un tipo de documento. Devuelve {} si no existe."""
    return exp.documentos.get(doc_type, {})


def obtener_reforma(exp: ExpedienteEmpresa) -> dict[str, Any]:
    """Obtiene reforma (prioriza reforma_estatutos sobre reforma)."""
    return exp.documentos.get("reforma_estatutos", exp.documentos.get("reforma", {}))
