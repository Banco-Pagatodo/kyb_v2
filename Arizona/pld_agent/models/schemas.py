"""
Modelos Pydantic para el agente PLD.
Etapa 1: Verificación de completitud documental.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumeraciones ────────────────────────────────────────────────

class EtapaPLD(str, Enum):
    """Etapas del proceso PLD."""
    ETAPA_1_COMPLETITUD = "ETAPA_1_COMPLETITUD"
    ETAPA_2_SCREENING = "ETAPA_2_SCREENING"
    ETAPA_3_VERIFICACION = "ETAPA_3_VERIFICACION"
    ETAPA_4_BENEFICIARIO = "ETAPA_4_BENEFICIARIO"
    ETAPA_5_NOTICIAS = "ETAPA_5_NOTICIAS"
    ETAPA_6_RIESGO = "ETAPA_6_RIESGO"
    ETAPA_7_DICTAMEN = "ETAPA_7_DICTAMEN"
    ETAPA_8_DOCUMENTACION = "ETAPA_8_DOCUMENTACION"


class ResultadoCompletitud(str, Enum):
    """Resultado de la verificación de completitud."""
    COMPLETO = "COMPLETO"
    INCOMPLETO = "INCOMPLETO"
    PARCIAL = "PARCIAL"  # Tiene lo mínimo pero faltan datos complementarios


class SeveridadPLD(str, Enum):
    """Severidad de un hallazgo PLD."""
    CRITICA = "CRITICA"        # Bloquea el proceso
    ALTA = "ALTA"              # Requiere acción antes de continuar
    MEDIA = "MEDIA"            # Requiere seguimiento
    INFORMATIVA = "INFORMATIVA"  # Solo para registro


class DictamenPLD(str, Enum):
    """Dictamen final del análisis PLD (Etapa 7)."""
    APROBADO_PLD = "APROBADO_PLD"
    APROBADO_EDD = "APROBADO_EDD"
    ESCALADO_COMITE = "ESCALADO_COMITE"
    RECHAZADO_PLD = "RECHAZADO_PLD"
    PENDIENTE = "PENDIENTE"  # Aún no se ha emitido dictamen final


# ── Modelos de datos Etapa 1 ─────────────────────────────────────

class ItemCompletitud(BaseModel):
    """Un elemento verificado de completitud."""
    codigo: str = Field(description="Código de verificación, e.g. A1.1, A2.3")
    categoria: str = Field(description="DOCUMENTO, DATO_OBLIGATORIO, DOMICILIO, PERSONAS")
    elemento: str = Field(description="Nombre descriptivo del elemento verificado")
    presente: bool = Field(description="True si el elemento se encontró en el expediente")
    fuente: str = Field(default="", description="Documento/tabla donde se encontró")
    detalle: str = Field(default="", description="Valor o comentario adicional")
    severidad: SeveridadPLD = Field(default=SeveridadPLD.CRITICA)


class PersonaIdentificada(BaseModel):
    """Persona encontrada en el expediente relevante para PLD."""
    nombre: str = Field(description="Nombre completo")
    rol: str = Field(description="apoderado, representante_legal, accionista, consejero, administrador")
    fuente: str = Field(default="", description="Documento donde se identificó")
    tipo_persona: str = Field(default="fisica", description="fisica o moral")
    porcentaje: float | None = Field(default=None, description="% accionario (accionistas)")
    requiere_screening: bool = Field(default=True, description="True = pasará por Etapa 2")


class VerificacionCompletitud(BaseModel):
    """Resultado completo de la Etapa 1 — Completitud Documental."""
    empresa_id: str
    rfc: str
    razon_social: str
    fecha_analisis: datetime
    etapa: EtapaPLD = Field(default=EtapaPLD.ETAPA_1_COMPLETITUD)
    resultado: ResultadoCompletitud
    items: list[ItemCompletitud] = Field(default_factory=list)
    personas_identificadas: list[PersonaIdentificada] = Field(default_factory=list)
    documentos_presentes: list[str] = Field(default_factory=list)
    documentos_faltantes: list[str] = Field(default_factory=list)

    # Contadores
    total_items: int = 0
    items_presentes: int = 0
    items_faltantes: int = 0
    items_criticos_faltantes: int = 0

    # Datos de la validación cruzada previa (Colorado)
    dictamen_colorado: str = Field(default="", description="Dictamen de Colorado si existe")
    validacion_cruzada_disponible: bool = Field(default=False)
    hallazgos_colorado_criticos: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Hallazgos críticos fallidos de Colorado relevantes para PLD",
    )
    hallazgos_colorado: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Todos los hallazgos de Colorado (codigo, severidad, pasa, mensaje, bloque, etc.)",
    )
    resumen_colorado: dict[str, Any] = Field(
        default_factory=dict,
        description="Resumen por bloque de la validación cruzada de Colorado",
    )

    # Recomendaciones
    recomendaciones: list[str] = Field(default_factory=list)

    # Poder para abrir cuentas bancarias
    poder_cuenta_bancaria: bool | None = Field(
        default=None,
        description="True si se detecta poder para abrir/operar cuentas bancarias",
    )


class ExpedientePLD(BaseModel):
    """Datos de empresa con documentos y validación cruzada para análisis PLD."""
    empresa_id: str
    rfc: str
    razon_social: str
    documentos: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="doc_type → datos_extraidos",
    )
    doc_types_presentes: list[str] = Field(default_factory=list)

    # Datos de Colorado (si existen)
    validacion_cruzada: dict[str, Any] | None = Field(
        default=None,
        description="Registro completo de validaciones_cruzadas",
    )
    datos_clave: dict[str, Any] | None = Field(
        default=None,
        description="resumen_bloques.datos_clave de Colorado",
    )


class AnalisisPLDDB(BaseModel):
    """Modelo para persistencia — tabla analisis_pld (migración 0009)."""
    id: str
    empresa_id: str
    rfc: str
    razon_social: str
    dictamen: str
    total_pasan: int = 0
    total_criticos: int = 0
    total_altos: int = 0
    total_medios: int = 0
    total_informativos: int = 0
    hallazgos: list[dict[str, Any]] = Field(default_factory=list)
    recomendaciones: list[str] = Field(default_factory=list)
    documentos_presentes: list[str] = Field(default_factory=list)
    screening_ejecutado: bool = False
    screening_results: dict[str, Any] | None = None
    reporte_texto: str | None = None
    resumen_bloques: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
