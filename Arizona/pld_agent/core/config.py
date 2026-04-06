"""
Configuración del agente PLD.
Lee variables de entorno y proporciona defaults para desarrollo.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Buscar .env en varias ubicaciones posibles
_service_root = Path(__file__).resolve().parent.parent          # Arizona/pld_agent/
_project_root = _service_root.parent.parent                     # Agents/
for env_path in [
    _service_root / ".env",                                     # Arizona/pld_agent/.env  (propio)
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
API_HOST = os.getenv("PLD_HOST", "0.0.0.0")
API_PORT = int(os.getenv("PLD_PORT", "8012"))

# ── Documentos obligatorios PLD (Disposición 4ª DCG Art.115 LIC) ─
DOCS_OBLIGATORIOS_PLD: list[str] = [
    "acta_constitutiva",
    "csf",
    "domicilio",
    "poder",
    "ine",
]

# estado_cuenta también puede funcionar como comprobante de domicilio;
# domicilio_rl y domicilio_propietario_real son variantes de comprobante de domicilio
DOCS_DOMICILIO_ALTERNATIVOS: list[str] = [
    "domicilio", "domicilio_rl", "domicilio_propietario_real", "estado_cuenta",
]

# INE alternativas: distingue INE del RL vs propietario real
DOCS_INE_ALTERNATIVOS: list[str] = ["ine", "ine_propietario_real"]

# Documentos extra requeridos para clientes de alto riesgo
DOCS_ALTO_RIESGO: list[str] = [
    # "estados_financieros",
    # "declaraciones_sat",
    # Pendiente de integración — accionistas ya está cubierto por acta/reforma
]

# ── Campos de datos obligatorios por categoría ───────────────────
# Cada tupla es (campo_display, doc_type, campo_key)
CAMPOS_OBLIGATORIOS: list[tuple[str, str, str]] = [
    ("Denominación / razón social", "csf", "denominacion_razon_social"),
    ("RFC con homoclave", "csf", "rfc"),
    ("e.firma (FIEL) — número de serie", "fiel", "no_serie"),
    # giro_mercantil se extrae del CSF; actividad_economica tiene alias a giro_mercantil
    ("Objeto social / giro mercantil", "csf", "actividad_economica"),
    ("Fecha de constitución", "acta_constitutiva", "fecha_constitucion"),
]

# Campos donde cualquier fuente basta
CAMPOS_DOMICILIO: list[tuple[str, str]] = [
    ("calle", "calle"),
    ("numero_exterior", "numero_exterior"),
    ("colonia", "colonia"),
    ("codigo_postal", "codigo_postal"),
    ("municipio_delegacion", "municipio_delegacion"),
    ("entidad_federativa", "entidad_federativa"),
]

# ── Alias de campos (Dakota puede extraer con nombres diferentes) ────
# Mapea nombre_arizona -> [alias_dakota1, alias_dakota2, ...]
CAMPOS_ALIAS: dict[str, list[str]] = {
    # CSF
    "denominacion_razon_social": ["razon_social", "nombre_razon_social", "denominacion_social"],
    "domicilio": ["domicilio_fiscal"],  # CSF usa domicilio_fiscal como key
    # FIEL
    "no_serie": ["numero_serie_certificado", "numero_serie", "serie_certificado"],
    # Acta constitutiva
    "objeto_social": ["giro_mercantil", "actividad_principal", "objeto"],
    "fecha_constitucion": ["fecha_creacion", "fecha_escritura"],
    # Domicilio (campos internos)
    "numero_exterior": ["num_exterior", "no_exterior", "numero_ext"],
    "numero_interior": ["num_interior", "no_interior", "numero_int"],
    "municipio_delegacion": ["municipio", "delegacion", "alcaldia", "ciudad"],
    "entidad_federativa": ["estado", "entidad"],
    "codigo_postal": ["cp", "c_p"],
    # Actividad económica (CSF usa giro_mercantil)
    "actividad_economica": ["giro_mercantil", "actividades_economicas", "giro"],
}
