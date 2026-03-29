"""
Modelos de datos para el sistema de validación de requisitos documentales KYB.

Este módulo define las estructuras de datos para validación de requisitos
documentales según normativa mexicana para personas morales.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
from datetime import datetime, date
from enum import Enum


class RequirementStatus(str, Enum):
    """Estado de cumplimiento de un requisito documental"""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"


class VigenciaType(str, Enum):
    """Tipos de vigencia para documentos"""
    SIN_VENCIMIENTO = "sin_vencimiento"
    TRES_MESES = "tres_meses"
    VIGENTE = "vigente"
    VARIABLE = "variable"


class DocumentRequirement(BaseModel):
    """
    Requisito documental según normativa KYB México.
    
    Representa un documento requerido o condicional con sus reglas de validación.
    """
    
    documento: str
    requerimiento: Literal["Requerido", "Condicional"]
    vigencia_maxima: VigenciaType
    requisitos_especificos: List[str]
    
    # Campos de validación
    presente: bool = False
    vigente: bool = False
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    
    # Resultado de validación
    status: RequirementStatus = RequirementStatus.MISSING
    errores: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """
    Resultado completo de validación de requisitos KYB.
    
    Contiene el análisis completo del expediente con scores,
    errores, recomendaciones y decisión de auto-aprobación.
    """
    
    expediente_id: str
    fecha_validacion: datetime = Field(default_factory=datetime.utcnow)
    
    # Score general
    validation_score: float = Field(ge=0.0, le=1.0, description="Score de 0 a 1")
    total_requisitos: int
    requisitos_cumplidos: int
    requisitos_fallidos: int
    requisitos_warning: int
    
    # Resultado por documento
    documentos: List[DocumentRequirement]
    
    # Decisión
    auto_aprobable: bool
    requiere_revision_manual: bool
    
    # Errores críticos
    errores_criticos: List[str] = Field(default_factory=list)
    
    # Recomendaciones
    recomendaciones: List[str] = Field(default_factory=list)


class ValidationRule(BaseModel):
    """
    Regla de validación de requisitos KYB.
    
    Define una validación específica con su severidad y lógica.
    """
    
    rule_id: str
    documento_tipo: str
    severity: Literal["critical", "high", "medium", "low"]
    description: str
    validation_logic: str
    error_message: str


class SingleDocumentValidation(BaseModel):
    """
    Resultado de validación KYB para un documento individual.
    
    Se usa cuando se procesa un solo documento via endpoint individual.
    """
    
    documento_tipo: str
    es_requerido: bool
    status: RequirementStatus
    vigente: bool = False
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    
    # Validación de tipo de documento
    documento_tipo_correcto: bool = True
    confianza_tipo: float = Field(ge=0.0, le=1.0, default=1.0)
    
    # Errores encontrados
    errores: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    # Score de compliance (1.0 = cumple todo)
    compliance_score: float = Field(ge=0.0, le=1.0, default=0.0)
    
    # Requisitos específicos evaluados - nuevo formato por campo
    campos_validados: Dict[str, str] = Field(
        default_factory=dict,
        description="Estado de cada campo validado: 'compliant' o 'non_compliant'"
    )
    
    # Recomendaciones
    recomendaciones: List[str] = Field(default_factory=list)
