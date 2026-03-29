"""
Funciones de normalización de texto reutilizables.

Centraliza la lógica de normalización de nombres, RFC y razón social
para evitar duplicación entre módulos (blacklist_screening, etapa1, etc.).
"""
from __future__ import annotations

import re


_ACCENT_MAP: dict[str, str] = {
    "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
    "À": "A", "È": "E", "Ì": "I", "Ò": "O", "Ù": "U",
    "Ä": "A", "Ë": "E", "Ï": "I", "Ö": "O", "Ü": "U",
    "Ñ": "N",
}


def normalizar_nombre(nombre: str) -> str:
    """
    Normaliza un nombre para búsqueda y comparación.

    - Mayúsculas
    - Sin acentos
    - Sin caracteres especiales
    - Espacios simples
    """
    if not nombre:
        return ""

    nombre = nombre.upper()

    for acento, letra in _ACCENT_MAP.items():
        nombre = nombre.replace(acento, letra)

    nombre = re.sub(r"[^A-Z0-9\s]", " ", nombre)

    return " ".join(nombre.split())


def normalizar_rfc(rfc: str) -> str:
    """Normaliza RFC para comparación."""
    if not rfc:
        return ""
    return re.sub(r"[^A-Z0-9]", "", rfc.upper())


_SUFIJOS_LEGALES = [
    r"\bS\s*A\s*P\s*I\s*DE\s*C\s*V\b",
    r"\bS\s*A\s*DE\s*C\s*V\b",
    r"\bS\s*A\s*B\s*DE\s*C\s*V\b",
    r"\bS\s*DE\s*R\s*L\s*DE\s*C\s*V\b",
    r"\bS\s*DE\s*R\s*L\b",
    r"\bS\s*C\b",
    r"\bA\s*C\b",
    r"\bS\s*A\s*S\b",
    r"\bS\s*A\b",
]


def normalizar_razon_social(razon: str) -> str:
    """
    Normaliza razón social de persona moral.
    Quita sufijos legales comunes para mejor matching.
    """
    if not razon:
        return ""

    razon = normalizar_nombre(razon)

    for sufijo in _SUFIJOS_LEGALES:
        razon = re.sub(sufijo, "", razon)

    return " ".join(razon.split())
