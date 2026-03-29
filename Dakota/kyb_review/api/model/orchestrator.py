"""
Modelos para el Orchestrator de onboarding KYB.

Este módulo define las estructuras de datos para el flujo unificado de
procesamiento y validación de documentos.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ReviewVerdict(str, Enum):
    """Veredicto final del proceso de revisión."""
    APPROVED = "APPROVED"                    # Auto-aprobado, no requiere revisión
    REVIEW_REQUIRED = "REVIEW_REQUIRED"      # Requiere revisión manual
    REJECTED = "REJECTED"                    # Rechazado por errores críticos irrecuperables


class DocumentStage(str, Enum):
    """Etapa del procesamiento de un documento."""
    PENDING = "PENDING"             # Pendiente de procesar
    GUARDRAILS = "GUARDRAILS"       # Validando formato/tamaño
    EXTRACTING = "EXTRACTING"       # Extrayendo datos con OCR
    VALIDATING = "VALIDATING"       # Validando especificaciones
    COMPLETED = "COMPLETED"         # Completado exitosamente
    FAILED = "FAILED"               # Falló en alguna etapa


class ErrorSeverity(str, Enum):
    """Severidad del error."""
    CRITICAL = "critical"       # Bloquea el proceso completamente
    HIGH = "high"               # Error importante pero no bloqueante
    MEDIUM = "medium"           # Advertencia significativa
    LOW = "low"                 # Advertencia menor


class ValidationDetail(BaseModel):
    """Detalle de una validación específica ejecutada."""
    tipo: str = Field(..., description="Tipo de validación: vigencia, protocolizacion, campos, rfc, etc.")
    passed: bool = Field(..., description="Si la validación pasó o falló")
    mensaje: str = Field(..., description="Descripción del resultado de la validación")
    datos: Dict[str, Any] = Field(default_factory=dict, description="Datos adicionales de la validación")


class DocumentError(BaseModel):
    """Error encontrado en un documento."""
    documento: str
    stage: DocumentStage
    severity: ErrorSeverity
    mensaje: str
    campo: Optional[str] = None
    sugerencia: Optional[str] = None


class DocumentResult(BaseModel):
    """Resultado del procesamiento de un documento individual."""
    documento_tipo: str
    archivo: str
    stage: DocumentStage = DocumentStage.PENDING
    
    # Resultado de guardrails
    guardrails_passed: bool = False
    guardrails_error: Optional[str] = None
    
    # Resultado de extracción
    datos_extraidos: Dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: Optional[float] = None
    
    # Resultado de validación individual
    validation_passed: bool = False
    errores: List[DocumentError] = Field(default_factory=list)
    
    # Detalle de validaciones ejecutadas
    validaciones: List[ValidationDetail] = Field(
        default_factory=list,
        description="Detalle de todas las validaciones ejecutadas (pasadas y fallidas)"
    )
    
    # Timestamps
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    processing_time_ms: Optional[int] = None


class OnboardingReviewRequest(BaseModel):
    """Request para el endpoint de revisión de onboarding."""
    expediente_id: str = Field(..., description="ID único del expediente")
    fail_fast: bool = Field(
        default=True, 
        description="Si True, detiene el proceso en el primer error crítico"
    )


class OnboardingReviewResponse(BaseModel):
    """Respuesta completa del proceso de revisión de onboarding."""
    expediente_id: str
    verdict: ReviewVerdict
    
    # Resumen ejecutivo
    resumen: str = Field(
        ..., 
        description="Resumen ejecutivo del resultado en lenguaje natural"
    )
    
    # Métricas globales
    documentos_procesados: int = 0
    documentos_exitosos: int = 0
    documentos_fallidos: int = 0
    errores_criticos: int = 0
    
    # Resultados detallados por documento
    documentos: List[DocumentResult] = Field(default_factory=list)
    
    # Todos los errores consolidados
    todos_errores: List[DocumentError] = Field(default_factory=list)
    
    # Recomendaciones
    recomendaciones: List[str] = Field(default_factory=list)
    
    # Puede auto-aprobarse?
    auto_aprobable: bool = False
    
    # Timestamps
    started_at: datetime
    completed_at: datetime
    total_processing_time_ms: int


# ═══════════════════════════════════════════════════════════════════════════════
# MAPEO DE TIPOS DE DOCUMENTO
# ═══════════════════════════════════════════════════════════════════════════════

# Documentos requeridos (obligatorios)
REQUIRED_DOCUMENTS = {
    "csf",
    "acta_constitutiva",
    "ine",
    "poder",
    "comprobante_domicilio"
}

# Documentos condicionales (opcionales)
CONDITIONAL_DOCUMENTS = {
    "fiel",
    "estado_cuenta", 
    "reforma"
}

# Mapeo de nombres amigables
DOCUMENT_NAMES = {
    "csf": "Constancia de Situación Fiscal",
    "acta_constitutiva": "Acta Constitutiva",
    "ine": "INE del Representante Legal",
    "poder": "Poder Notarial",
    "comprobante_domicilio": "Comprobante de Domicilio",
    "fiel": "FIEL (Firma Electrónica Avanzada)",
    "estado_cuenta": "Estado de Cuenta Bancario",
    "reforma": "Reforma de Estatutos"
}
