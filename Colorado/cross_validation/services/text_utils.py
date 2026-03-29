"""
Utilidades de normalización de texto, comparación fuzzy y parsing de fechas.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  CONSTANTES
# ═══════════════════════════════════════════════════════════════════

# Sufijos societarios a eliminar para comparar razones sociales
_SUFIJOS_SOCIETARIOS = [
    "SOCIEDAD ANONIMA PROMOTORA DE INVERSION DE CAPITAL VARIABLE",
    # Formas completas largas (primero para evitar reemplazos parciales)
    "SOCIEDAD ANONIMA PROMOTORA DE INVERSION DE CAPITAL VARIABLE",
    "SOCIEDAD ANONIMA DE CAPITAL VARIABLE",
    "SOCIEDAD FINANCIERA DE OBJETO MULTIPLE ENTIDAD NO REGULADA",
    "SOCIEDAD FINANCIERA DE OBJETO MULTIPLE",
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "PROMOTORA DE INVERSION DE CAPITAL VARIABLE",
    "ENTIDAD NO REGULADA",
    # Abreviaciones
    "SAPI DE CV",
    "SA DE CV",
    "S A P I DE C V",
    "S A P I DE CV",
    "S A DE C V",
    "S A DE CV",
    "SA PI DE CV",
    "SRL DE CV",
    "SOFOM ENR",
    "SOFOM",
    "SAPI",
    "SRL",
    "SA",
    "SC",
    "SOCIEDAD ANONIMA",
    "SOCIEDAD CIVIL",
]

# Abreviaturas de dirección → forma expandida
_ABREV_DIRECCION = {
    "AV": "AVENIDA", "AVE": "AVENIDA", "BLVD": "BOULEVARD",
    "BLV": "BOULEVARD", "C": "CALLE", "CLL": "CALLE",
    "COL": "COLONIA", "NTE": "NORTE", "PTE": "PONIENTE",
    "OTE": "ORIENTE", "INT": "INTERIOR", "EXT": "EXTERIOR",
    "NUM": "NUMERO", "NO": "NUMERO", "ESQ": "ESQUINA",
    "FRACC": "FRACCIONAMIENTO", "DEPTO": "DEPARTAMENTO",
    "DTO": "DEPARTAMENTO", "PB": "PLANTA BAJA",
    "MZA": "MANZANA", "MZ": "MANZANA", "LT": "LOTE",
    "EDIF": "EDIFICIO", "PISO": "PISO", "OF": "OFICINA",
}

# Meses en español
_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
    # Abreviaturas de 3 letras (formatos bancarios: 01/JUL/2025)
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


# ═══════════════════════════════════════════════════════════════════
#  NORMALIZACIÓN DE TEXTO
# ═══════════════════════════════════════════════════════════════════

def strip_accents(s: str) -> str:
    """Elimina diacríticos (á→a, ñ→n, etc.)."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def normalizar_texto(s: str) -> str:
    """Normaliza texto: mayúsculas, sin acentos, sin caracteres especiales."""
    if not s:
        return ""
    s = strip_accents(str(s)).upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalizar_razon_social(s: str) -> str:
    """Normaliza razón social eliminando sufijos societarios.

    Maneja abreviaturas con/sin puntos (S.A. → SA, S. de R.L. → SRL,
    C.V. → CV) y variantes textuales comunes antes de eliminar sufijos
    completos.  Permite cotejo correcto ante homonimias, cambios de
    denominación y abreviaturas legales (LGSM).
    """
    if not s:
        return ""
    norm = normalizar_texto(s)
    # ── Paso 0: Eliminar sufijos societarios con letras sueltas al FINAL ──
    # Esto maneja casos como "EMPRESA X S A P I DE C V" donde las letras
    # están separadas por espacios y se pegan erróneamente.
    # Patrón: detectar secuencia de letras sueltas típicas de tipo societario al final
    sufijos_finales = [
        r"\s+S\s+A\s+P\s+I\s+DE\s+C\s*V\s*$",
        r"\s+S\s+A\s+P\s+I\s+DE\s+CV\s*$",
        r"\s+SAPI\s+DE\s+CV\s*$",
        r"\s+SAPI\s+DE\s+C\s*V\s*$",
        r"\s+S\s+A\s+DE\s+C\s*V\s*$",
        r"\s+S\s+A\s+DE\s+CV\s*$",
        r"\s+SA\s+DE\s+CV\s*$",
        r"\s+SA\s+DE\s+C\s*V\s*$",
        r"\s+S\s+DE\s+R\s*L\s+DE\s+C\s*V\s*$",
        r"\s+SRL\s+DE\s+CV\s*$",
    ]
    for pat in sufijos_finales:
        norm = re.sub(pat, "", norm, flags=re.IGNORECASE).strip()
    # ── Paso 1: unificar abreviaturas con/sin puntos ──
    # "S.A.P.I. DE C.V." → "SAPI DE CV", "S. DE R.L." → "S DE RL"
    norm = re.sub(r"(?<=\b[A-Z])\.\s*", " ", norm)   # "S. A. " → "S A "
    norm = re.sub(r"(?<=\b[A-Z])\.", "", norm)         # "S.A." → "SA"
    norm = re.sub(r"\s+", " ", norm).strip()
    # Contraer letras sueltas: "S A P I" → "SAPI", "S A" → "SA"
    # Solo cuando son letras individuales consecutivas (no precedidas/seguidas por palabra larga)
    norm = re.sub(
        r"\b([A-Z])\s+([A-Z])\s+([A-Z])\s+([A-Z])\b",
        r"\1\2\3\4", norm,
    )
    norm = re.sub(
        r"\b([A-Z])\s+([A-Z])\s+([A-Z])\b",
        r"\1\2\3", norm,
    )
    norm = re.sub(
        r"\b([A-Z])\s+([A-Z])\b(?!\w)",
        r"\1\2", norm,
    )
    # "S DE RL" → "SRL", "S DE R L" → "SRL" (ya colapsado arriba)
    norm = re.sub(r"\bS\s+DE\s+RL\b", "SRL", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    # ── Paso 2: eliminar sufijos societarios (word-boundary-aware) ──
    # Usar regex con \b para evitar eliminar "SA" dentro de "EMPRESA", etc.
    for sufijo in sorted(_SUFIJOS_SOCIETARIOS, key=len, reverse=True):
        pattern = r"\b" + re.escape(sufijo) + r"\b"
        norm = re.sub(pattern, "", norm).strip()
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def normalizar_direccion(s: str) -> str:
    """Normaliza dirección expandiendo abreviaturas."""
    if not s:
        return ""
    norm = normalizar_texto(s)
    words = norm.split()
    result = [_ABREV_DIRECCION.get(w, w) for w in words]
    return " ".join(result)


# ═══════════════════════════════════════════════════════════════════
#  COMPARACIÓN DE TEXTOS
# ═══════════════════════════════════════════════════════════════════

def similitud(a: str, b: str) -> float:
    """Calcula similitud entre dos strings (0.0 a 1.0)."""
    if not a or not b:
        return 0.0
    na = normalizar_texto(a)
    nb = normalizar_texto(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def es_similar(a: str, b: str, umbral: float = 0.85) -> bool:
    """Verifica si dos strings son suficientemente similares."""
    return similitud(a, b) >= umbral


def comparar_nombres(a: str, b: str, umbral: float = 0.85) -> tuple[bool, float]:
    """
    Compara dos nombres de persona, considerando inversión de orden.
    Returns: (son_similares, similitud)
    """
    na = normalizar_texto(a)
    nb = normalizar_texto(b)
    if not na or not nb:
        return False, 0.0
    if na == nb:
        return True, 1.0

    sim = SequenceMatcher(None, na, nb).ratio()
    if sim >= umbral:
        return True, sim

    # Intentar con orden invertido (NOMBRE APELLIDOS vs APELLIDOS NOMBRE)
    parts_a = na.split()
    if len(parts_a) >= 2:
        # Probar moviendo el primer token al final
        invertido = " ".join(parts_a[1:] + parts_a[:1])
        sim2 = SequenceMatcher(None, invertido, nb).ratio()
        if sim2 > sim:
            sim = sim2
        # Probar moviendo los últimos 2 tokens al inicio
        if len(parts_a) >= 3:
            invertido2 = " ".join(parts_a[-2:] + parts_a[:-2])
            sim3 = SequenceMatcher(None, invertido2, nb).ratio()
            if sim3 > sim:
                sim = sim3

    return sim >= umbral, sim


def comparar_razones_sociales(a: str, b: str) -> tuple[bool, float, str]:
    """
    Compara dos razones sociales normalizadas.
    Returns: (coinciden, similitud, descripcion)
    """
    na = normalizar_razon_social(a)
    nb = normalizar_razon_social(b)
    if not na or not nb:
        return False, 0.0, "Uno o ambos valores vacíos"
    if na == nb:
        return True, 1.0, "Coincidencia exacta"
    sim = SequenceMatcher(None, na, nb).ratio()
    if sim >= 0.85:
        return True, sim, f"Variación menor ({sim:.0%})"
    return False, sim, f"No coinciden ({sim:.0%}): '{na}' vs '{nb}'"


def comparar_codigos_postales(a: str, b: str) -> bool:
    """Compara dos códigos postales normalizados."""
    if not a or not b:
        return False
    # Extraer solo dígitos
    da = re.sub(r"\D", "", str(a))
    db = re.sub(r"\D", "", str(b))
    return da == db and len(da) == 5


# ═══════════════════════════════════════════════════════════════════
#  PARSING DE FECHAS
# ═══════════════════════════════════════════════════════════════════

def parsear_fecha(s: Any) -> date | None:
    """
    Parsea una fecha flexible. Intenta múltiples formatos mexicanos.
    Devuelve None si no se puede parsear.
    """
    if s is None:
        return None
    if isinstance(s, (date, datetime)):
        return s if isinstance(s, date) else s.date()

    s = str(s).strip()
    if not s or s.lower() in ("n/a", "null", "none", ""):
        return None

    # Rango de fechas: "01/09/2025 - 30/09/2025" → tomar la última
    if " - " in s:
        parts = s.split(" - ")
        resultado = parsear_fecha(parts[-1].strip())
        if resultado:
            return resultado

    # ISO: 2026-02-24
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len("2026-02-24 00:00:00")], fmt).date()
        except (ValueError, IndexError):
            pass

    # DD/MM/YYYY o DD-MM-YYYY
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    upper = strip_accents(s).upper()

    # DD/MMM/YYYY — formato bancario: 31/JUL/2025, 01-ENE-2026
    m = re.match(r"(\d{1,2})[/\-]([A-Z]{3,})[/\-](\d{4})", upper)
    if m:
        dia, mes_str, anio = m.groups()
        mes = _MESES.get(mes_str)
        if mes:
            try:
                return date(int(anio), mes, int(dia))
            except ValueError:
                pass

    # "24 De Febrero De 2026"
    m = re.match(r"(\d{1,2})\s+DE\s+(\w+)\s+DE\s+(\d{4})", upper)
    if m:
        dia, mes_str, anio = m.groups()
        mes = _MESES.get(mes_str)
        if mes:
            try:
                return date(int(anio), mes, int(dia))
            except ValueError:
                pass

    # "Febrero 2026" → primer día del mes
    m = re.match(r"(\w+)\s+(\d{4})", upper)
    if m:
        mes_str, anio = m.groups()
        mes = _MESES.get(mes_str)
        if mes:
            return date(int(anio), mes, 1)

    # "02/2026" o "01-2026" → primer día del mes
    m = re.match(r"(\d{1,2})[/\-](\d{4})", s)
    if m:
        mes, anio = m.groups()
        try:
            return date(int(anio), int(mes), 1)
        except ValueError:
            pass

    # Solo año: "2030" → 31 de diciembre
    if re.match(r"^\d{4}$", s):
        return date(int(s), 12, 31)

    return None


def meses_desde(fecha: date, referencia: date | None = None) -> int:
    """Calcula cuántos meses han pasado desde una fecha."""
    if referencia is None:
        referencia = date.today()
    return (referencia.year - fecha.year) * 12 + (referencia.month - fecha.month)


def es_vigente(fecha_vencimiento: date, referencia: date | None = None) -> bool:
    """Verifica si una fecha de vencimiento aún es vigente."""
    if referencia is None:
        referencia = date.today()
    return fecha_vencimiento >= referencia


# ═══════════════════════════════════════════════════════════════════
#  EXTRACCIÓN DE VALORES DE datos_extraidos
# ═══════════════════════════════════════════════════════════════════

def get_valor(datos: dict, campo: str) -> Any:
    """
    Extrae el valor de un campo de datos_extraidos.
    Los campos siguen el patrón: {"campo": {"valor": X, "confiabilidad": Y}}
    """
    if not datos:
        return None
    field = datos.get(campo)
    if field is None:
        return None
    if isinstance(field, dict):
        v = field.get("valor")
        if v is None or v == "" or v == "N/A":
            return None
        return v
    return field


def get_confiabilidad(datos: dict, campo: str) -> float:
    """Extrae la confiabilidad de un campo (0-100)."""
    if not datos:
        return 0.0
    field = datos.get(campo)
    if field is None:
        return 0.0
    if isinstance(field, dict):
        return float(field.get("confiabilidad", 0.0))
    return 0.0


def get_valor_str(datos: dict, campo: str) -> str:
    """Extrae el valor como string, devuelve '' si no existe o es None."""
    v = get_valor(datos, campo)
    if v is None:
        return ""
    return str(v).strip()


# ── Detección de titulares corruptos ─────────────────────────────

_TITULAR_BASURA = [
    "BENEFICIARIO", "DATO NO CERTIFICADO", "ESTE DOCUMENTO",
    "PARA EFECTOS", "INFORMACION", "ESTIMADO CLIENTE",
]


def es_titular_corrupto(titular: str) -> bool:
    """Detecta si un titular extraído de estado de cuenta es basura/disclaimer.

    Se usa en bloque1 y bloque6 — centralizado aquí para evitar duplicación.
    """
    if not titular:
        return True
    if "\n" in titular or "\r" in titular:
        return True
    if len(titular) > 60:
        return True
    norm = normalizar_texto(titular)
    return any(b in norm for b in _TITULAR_BASURA)
