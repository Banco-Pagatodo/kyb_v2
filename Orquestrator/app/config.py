"""
Configuración del Orquestrador.

Lee variables de entorno desde .env y expone constantes.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env relativo a este archivo
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# ── URLs de los agentes ──────────────────────────────────────────────────
DAKOTA_BASE_URL: str = os.getenv("DAKOTA_BASE_URL", "http://localhost:8010")
COLORADO_BASE_URL: str = os.getenv("COLORADO_BASE_URL", "http://localhost:8011")
ARIZONA_BASE_URL: str = os.getenv("ARIZONA_BASE_URL", "http://localhost:8012")

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

# ── API externa PagaTodo (Hub) ───────────────────────────────────────────
PAGATODO_HUB_BASE_URL: str = os.getenv(
    "PAGATODO_HUB_BASE_URL",
    "https://sandbox-hub.pagatodo.com",
)
PAGATODO_HUB_API_KEY: str = os.getenv("PAGATODO_HUB_API_KEY", "")
PAGATODO_HUB_TIMEOUT: float = float(os.getenv("PAGATODO_HUB_TIMEOUT", "60"))

# Mapeo: DocumentType externo (PagaTodo Hub /ocr) → doc_type interno KYB.
# Prefijos en el sistema externo:
#   RL_ = Representante Legal
#   PR_ = Propietario Real
#   EM_ = Empresa (persona moral)
# Nota: el sistema externo NO distingue INE reverso; se asume que el
#       documento INE contiene ambas caras (anverso + reverso) en un solo
#       archivo, lo cual ya se detecta en Colorado V4.5.
PAGATODO_DOCTYPE_MAP: dict[str, str] = {
    "Csf":              "csf",
    "Fiel":             "fiel",
    "ActaCons":         "acta_constitutiva",
    "PoderNotarial":    "poder",
    "ReformaEstatustos": "reforma",
    "EdoCuenta":        "estado_cuenta",
    "RL_FrenteIne":     "ine",
    "PR_FrenteIne":     "ine_propietario_real",
    "EM_ComDomicilio":  "domicilio",
    "RL_ComDomicilio":  "domicilio_rl",
    "PR_ComDomicilio":  "domicilio_propietario_real",
}

# Inverso: doc_type interno → DocumentType externo
DOCTYPE_MAP_INVERSO: dict[str, str] = {v: k for k, v in PAGATODO_DOCTYPE_MAP.items()}

# ── Base de datos PostgreSQL (compartida con los agentes) ────────────────
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
DB_NAME: str = os.getenv("DB_NAME", "kyb")
DB_USER: str = os.getenv("DB_USER", "kyb_app")
DB_PASS: str = os.getenv("DB_PASS", "")
