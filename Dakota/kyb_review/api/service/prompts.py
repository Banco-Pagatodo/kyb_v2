# api/service/prompts.py
"""
Sistema de versionado y gestión de prompts.
Permite tracking de versiones, A/B testing y auditoría.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
PROMPTS_HISTORY_FILE = os.path.join(PROMPTS_DIR, "history.json")


class PromptCategory(str, Enum):
    """Categorías de prompts."""
    EXTRACTION = "extraction"       # Extracción de campos
    VALIDATION = "validation"       # Validación de datos
    RECONCILIATION = "reconciliation"  # Reconciliación de documentos
    LEGAL_OPINION = "legal_opinion"    # Opiniones legales


@dataclass
class PromptVersion:
    """Representa una versión específica de un prompt."""
    version: str
    template: str
    description: str
    category: PromptCategory
    doc_types: List[str]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    is_active: bool = True
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "category": self.category.value
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS POR DOCUMENTO
# ═══════════════════════════════════════════════════════════════════════════════

# Diccionario central de prompts con versionado
PROMPT_REGISTRY: Dict[str, PromptVersion] = {}


def _register_prompt(name: str, prompt: PromptVersion) -> None:
    """Registra un prompt en el registry."""
    PROMPT_REGISTRY[name] = prompt


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS DE EXTRACCIÓN
# ─────────────────────────────────────────────────────────────────────────────

_register_prompt("csf_extraction", PromptVersion(
    version="1.0.0",
    category=PromptCategory.EXTRACTION,
    doc_types=["csf"],
    description="Extrae campos de Constancia de Situación Fiscal",
    template="""Analiza el siguiente texto extraído de una Constancia de Situación Fiscal (CSF) del SAT y extrae la información en formato JSON.

TEXTO OCR:
{ocr_text}

INSTRUCCIONES:
1. Extrae TODOS los campos disponibles
2. Si un campo no está presente, usa null
3. Para fechas, usa formato YYYY-MM-DD
4. Para RFC, asegúrate de incluir la homoclave completa (13 caracteres para personas morales, 12 para físicas)

CAMPOS A EXTRAER:
{{
    "rfc": "RFC completo con homoclave",
    "denominacion_razon_social": "Nombre o razón social",
    "regimen_capital": "SA de CV, S de RL, etc.",
    "fecha_inicio_operaciones": "Fecha de inicio",
    "situacion_contribuyente": "Activo, Suspendido, etc.",
    "fecha_ultimo_cambio_situacion": "Fecha del último cambio",
    "nombre_comercial": "Nombre comercial si aplica",
    "regimenes_fiscales": ["Lista de regímenes fiscales"],
    "domicilio_fiscal": {{
        "calle": "",
        "numero_exterior": "",
        "numero_interior": "",
        "colonia": "",
        "codigo_postal": "",
        "localidad": "",
        "municipio": "",
        "estado": "",
        "entre_calle": "",
        "y_calle": ""
    }},
    "actividades_economicas": [
        {{
            "orden": 1,
            "actividad": "Descripción",
            "porcentaje": 100,
            "fecha_inicio": "YYYY-MM-DD"
        }}
    ]
}}

Responde SOLO con el JSON, sin explicaciones adicionales."""
))


_register_prompt("ine_extraction", PromptVersion(
    version="1.0.0",
    category=PromptCategory.EXTRACTION,
    doc_types=["ine", "ine_reverso"],
    description="Extrae campos de INE/Credencial de Elector",
    template="""Analiza el siguiente texto extraído de una credencial INE y extrae la información.

TEXTO OCR:
{ocr_text}

CAMPOS ESPERADOS:
{{
    "nombre": "Nombre completo",
    "apellido_paterno": "",
    "apellido_materno": "",
    "clave_elector": "18 caracteres alfanuméricos",
    "curp": "18 caracteres",
    "numero_registro": "",
    "fecha_nacimiento": "DD/MM/YYYY",
    "sexo": "H o M",
    "domicilio": {{
        "calle": "",
        "numero": "",
        "colonia": "",
        "codigo_postal": "",
        "municipio": "",
        "estado": ""
    }},
    "vigencia": "YYYY"
}}

Responde SOLO con el JSON válido."""
))


_register_prompt("acta_extraction", PromptVersion(
    version="1.0.0",
    category=PromptCategory.EXTRACTION,
    doc_types=["acta_constitutiva"],
    description="Extrae información de Acta Constitutiva",
    template="""Analiza el siguiente texto de un Acta Constitutiva y extrae la información relevante.

TEXTO OCR:
{ocr_text}

INFORMACIÓN A EXTRAER:
1. Datos de la escritura (número, fecha, notario, estado)
2. Datos de la sociedad (denominación, objeto social, duración, domicilio)
3. Capital social (monto, moneda, número de acciones)
4. Socios/Accionistas (nombre, participación)
5. Administración (tipo, miembros del consejo o administrador único)
6. Poderes y facultades otorgados
7. Representante legal designado

Formato JSON esperado:
{{
    "escritura": {{
        "numero": "",
        "fecha": "YYYY-MM-DD",
        "notario": "",
        "notaria_numero": "",
        "estado": ""
    }},
    "sociedad": {{
        "denominacion": "",
        "tipo_sociedad": "SA de CV, S de RL, etc.",
        "objeto_social": "",
        "duracion": "99 años o perpetua",
        "domicilio": ""
    }},
    "capital_social": {{
        "monto": 0,
        "moneda": "MXN",
        "acciones_totales": 0,
        "valor_nominal_accion": 0
    }},
    "socios": [
        {{
            "nombre": "",
            "acciones": 0,
            "porcentaje": 0,
            "tipo": "fundador/accionista"
        }}
    ],
    "administracion": {{
        "tipo": "Administrador Único/Consejo de Administración",
        "miembros": [
            {{
                "nombre": "",
                "cargo": "",
                "vigencia": ""
            }}
        ]
    }},
    "representante_legal": {{
        "nombre": "",
        "poderes": ["lista de facultades"]
    }}
}}

Responde SOLO con el JSON."""
))


_register_prompt("poder_extraction", PromptVersion(
    version="1.0.0",
    category=PromptCategory.EXTRACTION,
    doc_types=["poder_notarial"],
    description="Extrae información de Poder Notarial",
    template="""Analiza el texto del Poder Notarial y extrae:

TEXTO OCR:
{ocr_text}

INFORMACIÓN REQUERIDA:
{{
    "escritura": {{
        "numero": "",
        "fecha": "YYYY-MM-DD",
        "notario": "",
        "estado": ""
    }},
    "poderdante": {{
        "nombre": "",
        "tipo": "Persona Física/Persona Moral",
        "rfc": "",
        "representante": ""
    }},
    "apoderado": {{
        "nombre": "",
        "rfc": ""
    }},
    "tipo_poder": "General/Especial",
    "facultades": [
        "Lista de facultades otorgadas"
    ],
    "limitaciones": [
        "Restricciones al poder"
    ],
    "revocable": true,
    "vigencia": "Indefinida o fecha límite"
}}

Responde SOLO con JSON válido."""
))


_register_prompt("estado_cuenta_extraction", PromptVersion(
    version="1.0.0",
    category=PromptCategory.EXTRACTION,
    doc_types=["estado_cuenta"],
    description="Extrae información de Estado de Cuenta Bancario",
    template="""Analiza el Estado de Cuenta bancario y extrae la información.

TEXTO OCR:
{ocr_text}

CAMPOS A EXTRAER:
{{
    "banco": "Nombre del banco",
    "titular": "Nombre del titular de la cuenta",
    "numero_cuenta": "",
    "clabe": "18 dígitos",
    "periodo": {{
        "inicio": "YYYY-MM-DD",
        "fin": "YYYY-MM-DD"
    }},
    "saldo_inicial": 0.00,
    "saldo_final": 0.00,
    "domicilio": {{
        "calle": "",
        "numero": "",
        "colonia": "",
        "codigo_postal": "",
        "municipio": "",
        "estado": ""
    }},
    "tipo_cuenta": "Cheques/Ahorro/Inversión"
}}

Responde SOLO con el JSON."""
))


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS DE VALIDACIÓN
# ─────────────────────────────────────────────────────────────────────────────

_register_prompt("general_validation", PromptVersion(
    version="1.0.0",
    category=PromptCategory.VALIDATION,
    doc_types=["all"],
    description="Validación general de campos extraídos",
    template="""Valida los siguientes datos extraídos de un documento {doc_type}.

DATOS EXTRAÍDOS:
{extracted_data}

TEXTO ORIGINAL OCR:
{ocr_text}

VALIDACIONES REQUERIDAS:
1. Verifica que cada campo extraído tenga evidencia en el texto OCR
2. Califica la confianza de cada campo (0-100%)
3. Identifica campos faltantes o inconsistentes
4. Detecta posibles errores de OCR

FORMATO DE RESPUESTA:
{{
    "validaciones": [
        {{
            "campo": "nombre_del_campo",
            "valor_extraido": "valor",
            "evidencia_ocr": "texto encontrado en OCR",
            "confianza": 95,
            "notas": "observaciones si aplica"
        }}
    ],
    "campos_faltantes": ["lista de campos no encontrados"],
    "inconsistencias": ["lista de problemas detectados"],
    "score_general": 85
}}"""
))


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS DE RECONCILIACIÓN
# ─────────────────────────────────────────────────────────────────────────────

_register_prompt("cross_document_reconciliation", PromptVersion(
    version="1.0.0",
    category=PromptCategory.RECONCILIATION,
    doc_types=["all"],
    description="Reconciliación entre múltiples documentos",
    template="""Compara y reconcilia la información de los siguientes documentos:

DOCUMENTO 1 ({doc1_type}):
{doc1_data}

DOCUMENTO 2 ({doc2_type}):
{doc2_data}

VALIDACIONES:
1. Compara campos comunes (RFC, nombre, domicilio, etc.)
2. Identifica discrepancias
3. Determina cuál valor es más confiable
4. Califica la consistencia general

RESPUESTA:
{{
    "campos_coincidentes": [
        {{
            "campo": "nombre",
            "valor_doc1": "",
            "valor_doc2": "",
            "coincide": true
        }}
    ],
    "discrepancias": [
        {{
            "campo": "",
            "valor_doc1": "",
            "valor_doc2": "",
            "valor_sugerido": "",
            "razon": ""
        }}
    ],
    "score_consistencia": 90
}}"""
))


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS DE OPINIÓN LEGAL
# ─────────────────────────────────────────────────────────────────────────────

_register_prompt("legal_opinion_existence", PromptVersion(
    version="1.0.0",
    category=PromptCategory.LEGAL_OPINION,
    doc_types=["acta_constitutiva", "poder_notarial"],
    description="Opinión legal sobre existencia de persona moral",
    template="""Genera una opinión legal sobre la existencia de la siguiente persona moral:

DATOS DE LA SOCIEDAD:
{company_data}

DOCUMENTOS ANALIZADOS:
{documents_summary}

OPINIÓN LEGAL DEBE INCLUIR:
1. Verificación de constitución legal válida
2. Vigencia de la sociedad
3. Situación fiscal actual
4. Verificación de representación legal
5. Facultades del representante

FORMATO:
{{
    "dictamen": "FAVORABLE/DESFAVORABLE/CON_OBSERVACIONES",
    "resumen_ejecutivo": "Párrafo resumiendo la opinión",
    "verificaciones": [
        {{
            "aspecto": "Constitución legal",
            "resultado": "VERIFICADO/NO_VERIFICADO/PARCIAL",
            "evidencia": "Descripción",
            "observaciones": ""
        }}
    ],
    "riesgos_identificados": ["lista de riesgos"],
    "recomendaciones": ["lista de recomendaciones"],
    "documentos_faltantes": ["lista si aplica"]
}}"""
))


# ═══════════════════════════════════════════════════════════════════════════════
# GESTOR DE PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

class PromptManager:
    """
    Gestor centralizado de prompts con versionado.
    Singleton para mantener estado consistente.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._history: List[dict] = []
        self._load_history()
        self._initialized = True

    def _load_history(self) -> None:
        """Carga historial de uso de prompts."""
        try:
            if os.path.exists(PROMPTS_HISTORY_FILE):
                with open(PROMPTS_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # El archivo puede ser una lista directa o un dict con key "history"
                    if isinstance(data, list):
                        self._history = data
                    elif isinstance(data, dict) and "history" in data:
                        self._history = data["history"]
                    else:
                        self._history = []
        except Exception as e:
            logger.warning(f"Could not load prompt history: {e}")
            self._history = []

    def _save_history(self) -> None:
        """Guarda historial de uso."""
        try:
            os.makedirs(PROMPTS_DIR, exist_ok=True)
            with open(PROMPTS_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._history[-1000:], f, indent=2)  # Últimos 1000
        except Exception as e:
            logger.warning(f"Could not save prompt history: {e}")

    def get_prompt(
        self,
        name: str,
        variables: Dict[str, Any] = None
    ) -> str:
        """
        Obtiene un prompt formateado con variables.

        Args:
            name: Nombre del prompt registrado
            variables: Variables para formatear el template

        Returns:
            Prompt formateado listo para usar
        """
        if name not in PROMPT_REGISTRY:
            raise ValueError(f"Prompt '{name}' not found in registry")

        prompt_version = PROMPT_REGISTRY[name]
        template = prompt_version.template

        # Formatear con variables si se proporcionan
        if variables:
            try:
                template = template.format(**variables)
            except KeyError as e:
                logger.warning(f"Missing variable in prompt: {e}")

        # Registrar uso
        self._record_usage(name, prompt_version.version)

        return template

    def _record_usage(self, name: str, version: str) -> None:
        """Registra uso de un prompt."""
        self._history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "prompt_name": name,
            "version": version
        })

        # Guardar periódicamente
        if len(self._history) % 100 == 0:
            self._save_history()

    def get_prompt_info(self, name: str) -> Optional[dict]:
        """Obtiene información de un prompt."""
        if name not in PROMPT_REGISTRY:
            return None
        return PROMPT_REGISTRY[name].to_dict()

    def list_prompts(
        self,
        category: PromptCategory = None,
        doc_type: str = None
    ) -> List[dict]:
        """Lista prompts disponibles con filtros opcionales."""
        results = []

        for name, prompt in PROMPT_REGISTRY.items():
            if category and prompt.category != category:
                continue
            if doc_type and doc_type not in prompt.doc_types and "all" not in prompt.doc_types:
                continue

            results.append({
                "name": name,
                **prompt.to_dict()
            })

        return results

    def get_usage_stats(self) -> dict:
        """Obtiene estadísticas de uso de prompts."""
        from collections import Counter

        usage_count = Counter()
        version_usage = {}

        for entry in self._history:
            name = entry["prompt_name"]
            version = entry["version"]

            usage_count[name] += 1

            if name not in version_usage:
                version_usage[name] = Counter()
            version_usage[name][version] += 1

        return {
            "total_invocations": len(self._history),
            "by_prompt": dict(usage_count),
            "by_version": {k: dict(v) for k, v in version_usage.items()}
        }

    def update_prompt_metrics(
        self,
        name: str,
        metrics: Dict[str, Any]
    ) -> None:
        """
        Actualiza métricas de rendimiento de un prompt.
        Útil para A/B testing.
        """
        if name not in PROMPT_REGISTRY:
            return

        prompt = PROMPT_REGISTRY[name]
        prompt.metrics.update(metrics)

        logger.info(f"Updated metrics for prompt '{name}': {metrics}")


# ═══════════════════════════════════════════════════════════════════════════════
# INSTANCIA GLOBAL
# ═══════════════════════════════════════════════════════════════════════════════

prompt_manager = PromptManager()


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CONVENIENCIA
# ═══════════════════════════════════════════════════════════════════════════════

def get_extraction_prompt(doc_type: str, ocr_text: str) -> str:
    """
    Obtiene el prompt de extracción apropiado para un tipo de documento.

    Args:
        doc_type: Tipo de documento (csf, ine, acta_constitutiva, etc.)
        ocr_text: Texto OCR a procesar

    Returns:
        Prompt formateado
    """
    # Mapeo de tipos a nombres de prompt
    prompt_mapping = {
        "csf": "csf_extraction",
        "ine": "ine_extraction",
        "ine_reverso": "ine_extraction",
        "acta_constitutiva": "acta_extraction",
        "poder_notarial": "poder_extraction",
        "estado_cuenta": "estado_cuenta_extraction",
    }

    prompt_name = prompt_mapping.get(doc_type)
    if not prompt_name:
        logger.warning(f"No specific prompt for doc_type: {doc_type}")
        prompt_name = "general_validation"  # Fallback

    return prompt_manager.get_prompt(prompt_name, {"ocr_text": ocr_text})


def get_validation_prompt(
    doc_type: str,
    extracted_data: dict,
    ocr_text: str
) -> str:
    """
    Obtiene prompt de validación.
    """
    return prompt_manager.get_prompt("general_validation", {
        "doc_type": doc_type,
        "extracted_data": json.dumps(extracted_data, ensure_ascii=False, indent=2),
        "ocr_text": ocr_text
    })


def get_reconciliation_prompt(
    doc1_type: str, doc1_data: dict,
    doc2_type: str, doc2_data: dict
) -> str:
    """
    Obtiene prompt de reconciliación entre documentos.
    """
    return prompt_manager.get_prompt("cross_document_reconciliation", {
        "doc1_type": doc1_type,
        "doc1_data": json.dumps(doc1_data, ensure_ascii=False, indent=2),
        "doc2_type": doc2_type,
        "doc2_data": json.dumps(doc2_data, ensure_ascii=False, indent=2)
    })
