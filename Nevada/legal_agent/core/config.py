"""
Configuración del agente Nevada (Dictamen Jurídico).
Lee variables de entorno y proporciona defaults para desarrollo.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Buscar .env en varias ubicaciones posibles
_service_root = Path(__file__).resolve().parent.parent          # Nevada/legal_agent/
_project_root = _service_root.parent.parent                     # Agents/
for env_path in [
    _service_root / ".env",                                     # Nevada/legal_agent/.env  (propio)
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

# ── API ──────────────────────────────────────────────────────────
API_HOST = os.getenv("LEGAL_HOST", "0.0.0.0")
API_PORT = int(os.getenv("LEGAL_PORT", "8013"))

# ── Azure OpenAI ─────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ── Knowledge base ──────────────────────────────────────────────
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
