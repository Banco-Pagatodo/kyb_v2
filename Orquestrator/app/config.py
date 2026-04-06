"""
Configuración del Orquestrador (flujo Dakota).

Lee variables de entorno desde .env y expone constantes.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env relativo a este archivo
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

# ── URLs de los agentes ──────────────────────────────────────────────────
DAKOTA_BASE_URL: str = os.getenv("DAKOTA_BASE_URL", "http://localhost:8010")
COLORADO_BASE_URL: str = os.getenv("COLORADO_BASE_URL", "http://localhost:8011")
ARIZONA_BASE_URL: str = os.getenv("ARIZONA_BASE_URL", "http://localhost:8012")

# ── Autenticación Dakota ─────────────────────────────────────────
DAKOTA_API_KEY: str = os.getenv("DAKOTA_API_KEY", "")

# ── Timeouts (segundos) ─────────────────────────────────────────
DAKOTA_TIMEOUT: float = float(os.getenv("DAKOTA_TIMEOUT", "300"))
COLORADO_TIMEOUT: float = float(os.getenv("COLORADO_TIMEOUT", "300"))
ARIZONA_TIMEOUT: float = float(os.getenv("ARIZONA_TIMEOUT", "120"))

# ── Prefijos de API de cada agente ─────────────────────────────
DAKOTA_API_PREFIX: str = "/kyb/api/v1.0.0"
COLORADO_API_PREFIX: str = "/api/v1/validacion"
ARIZONA_API_PREFIX: str = "/api/v1/pld"
COMPLIANCE_API_PREFIX: str = "/api/v1/compliance"   # Compliance vive dentro de Arizona

# ── Nevada (Dictamen Jurídico) ────────────────────────────────────────
NEVADA_BASE_URL: str = os.getenv("NEVADA_BASE_URL", "http://localhost:8013")
NEVADA_TIMEOUT: float = float(os.getenv("NEVADA_TIMEOUT", "120"))
NEVADA_API_PREFIX: str = "/api/v1/legal"

# ── CORS ─────────────────────────────────────────────────────────────────
_default_origins = "http://localhost:8501,http://localhost:3000"
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

# ── Retry / Circuit Breaker ──────────────────────────────────────────────
RETRY_MAX_ATTEMPTS: int = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_WAIT_MIN: float = float(os.getenv("RETRY_WAIT_MIN", "1"))
RETRY_WAIT_MAX: float = float(os.getenv("RETRY_WAIT_MAX", "10"))
CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_RECOVERY: float = float(os.getenv("CIRCUIT_BREAKER_RECOVERY", "60"))

# ── Puerto del orquestrador ──────────────────────────────────────────────
ORQUESTRATOR_PORT: int = int(os.getenv("ORQUESTRATOR_PORT", "8002"))

# ── Tipos de documento soportados por Dakota ─────────────────────────────
DAKOTA_DOC_TYPES: set[str] = {
    "csf", "fiel", "acta_constitutiva", "poder_notarial",
    "reforma_estatutos", "estado_cuenta", "domicilio",
    "ine", "ine_reverso", "ine_propietario_real",
    "domicilio_rl", "domicilio_propietario_real",
}

# ── Base de datos PostgreSQL (compartida con los agentes) ────────────────
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
DB_NAME: str = os.getenv("DB_NAME", "kyb")
DB_USER: str = os.getenv("DB_USER", "kyb_app")
DB_PASS: str = os.getenv("DB_PASS", "")
