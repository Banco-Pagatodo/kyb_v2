"""
Configuración del agente de validación cruzada.
Lee variables de entorno y proporciona defaults para desarrollo.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Buscar .env en varias ubicaciones posibles
_service_root = Path(__file__).resolve().parent.parent          # Colorado/cross_validation/
_project_root = _service_root.parent.parent                     # Agents/
for env_path in [
    _service_root / ".env",                                     # Colorado/cross_validation/.env  (propio)
    _project_root / ".env",                                     # Agents/.env  (raíz compartida)
    _project_root / "Dakota" / "kyb_review" / ".env",
    _project_root / "Dakota" / "kyb_review" / "api" / "service" / ".env",
    Path.cwd() / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)
        break

# ── Base de datos ────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "kyb")
DB_USER = os.getenv("DB_USER", "kyb_app")
DB_PASS = os.getenv("DB_PASS", "")

# ── Umbrales de validación ───────────────────────────────────────
UMBRAL_SIMILITUD_NOMBRE = 0.85
UMBRAL_SIMILITUD_DIRECCION = 0.75
UMBRAL_CONFIABILIDAD_BAJA = 70.0
MESES_VIGENCIA_DOMICILIO = 3
MESES_VIGENCIA_CSF = 3
MESES_VIGENCIA_EDO_CTA = 3

# ── Umbrales de comparación manual vs OCR (Bloque 11) ────────────
UMBRAL_SIMILITUD_MANUAL_OCR = 0.80
UMBRAL_SIMILITUD_DIRECCION_MANUAL_OCR = 0.70

# ── API ──────────────────────────────────────────────────────────
API_HOST = os.getenv("CROSS_VAL_HOST", "0.0.0.0")
API_PORT = int(os.getenv("CROSS_VAL_PORT", "8011"))

# ── Documentos mínimos requeridos ────────────────────────────────
DOCS_MINIMOS = [
    "csf",
    "fiel",
    "ine",
    "estado_cuenta",
    "domicilio",
    "acta_constitutiva",
    "poder",
]

DOCS_COMPLEMENTARIOS = [
    "reforma_estatutos",
    "reforma",
    "ine_reverso",
    "ine_propietario_real",
    "domicilio_rl",
    "domicilio_propietario_real",
]
