"""
Modelos Pydantic v2 para el Dictamen Jurídico (Nevada).

Mapeados 1:1 con las secciones del template DJ-1 de Banco PagaTodo.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
#  Sub-modelos por sección del Dictamen
# ═══════════════════════════════════════════════════════════════════

class DatosEscritura(BaseModel):
    """Datos de una escritura notarial (constitución o reforma)."""
    escritura_numero: str | None = None
    escritura_fecha: str | None = None
    numero_notario: str | None = None
    nombre_notario: str | None = None
    residencia_notario: str | None = None
    folio_mercantil: str | None = None
    fecha_folio_mercantil: str | None = None
    lugar_folio_mercantil: str | None = None
    volumen_tomo: str | None = None
    antecedentes_resumen: str | None = None
    orden_del_dia: str | None = None


class ActividadGiro(BaseModel):
    """Actividad o giro de la empresa — sección del dictamen."""
    actividad_giro: str | None = None
    sufrio_modificaciones: bool = False
    observaciones: str | None = None
    instrumento_cambio: str | None = None
    fuente_documento: str | None = None  # acta_constitutiva o reforma


class AccionistaDJ(BaseModel):
    """Un accionista en la tenencia accionaria."""
    nombre: str
    porcentaje: float | None = None
    es_extranjero: bool = False
    tipo_persona: Literal["fisica", "moral"] = "fisica"


class TenenciaAccionaria(BaseModel):
    """Tenencia accionaria completa."""
    accionistas: list[AccionistaDJ] = Field(default_factory=list)
    hay_extranjeros: bool = False


class MiembroAdministracion(BaseModel):
    """Miembro del consejo de administración o administrador único."""
    nombre: str
    cargo: str | None = None


class RegimenAdministracion(BaseModel):
    """Régimen de administración de la sociedad."""
    tipo: Literal["administrador_unico", "consejo_administracion"] | None = None
    miembros: list[MiembroAdministracion] = Field(default_factory=list)


class FacultadesApoderado(BaseModel):
    """Facultades de un representante / apoderado."""
    administracion: bool = False
    dominio: bool = False
    titulos_credito: bool = False
    apertura_cuentas: bool = False
    delegacion_sustitucion: bool = False
    especiales: str | None = None
    palabras_clave_encontradas: list[str] = Field(default_factory=list)


class ApoderadoDJ(BaseModel):
    """Apoderado / representante legal en el dictamen."""
    nombre: str
    facultades: FacultadesApoderado = Field(default_factory=FacultadesApoderado)
    limitaciones: str | None = None
    regimen_firmas: Literal["individual", "mancomunado"] | None = None
    vigencia: str | None = None
    nacionalidad: Literal["mexicana", "extranjero"] | None = "mexicana"
    cuenta_fm3: bool | None = None
    puede_firmar_contrato: bool | None = None
    puede_designar_web_banking: bool | None = None
    # Datos del poder notarial
    poder_escritura_numero: str | None = None
    poder_fecha: str | None = None
    poder_notario: str | None = None
    poder_notaria: str | None = None
    poder_estado: str | None = None
    poderdante: str | None = None
    tipo_poder_completo: str | None = None


class ConfiabilidadDictamen(BaseModel):
    """Confiabilidad del dictamen jurídico generado."""
    score_global: float = 0.0  # 0-100
    nivel: Literal["ALTA", "MEDIA", "BAJA"] = "BAJA"
    score_ocr: float | None = None        # promedio confiabilidad OCR
    score_reglas: float | None = None      # % reglas cumplidas
    campos_ocr_evaluados: int = 0
    reglas_cumplidas: int = 0
    reglas_totales: int = 0
    usa_llm: bool = False
    detalle: str = ""


class ObservacionesAdicionales(BaseModel):
    """Observaciones adicionales de la sociedad."""
    observaciones: list[str] = Field(default_factory=list)


class ElaboracionRevision(BaseModel):
    """Datos de elaboración y revisión del dictamen."""
    elaboro_fecha: str | None = None
    elaboro_nombre: str | None = None
    reviso_fecha: str | None = None
    reviso_nombre: str | None = None


# ═══════════════════════════════════════════════════════════════════
#  Modelo principal: Dictamen Jurídico DJ-1
# ═══════════════════════════════════════════════════════════════════

class DictamenJuridico(BaseModel):
    """
    Dictamen Jurídico completo (template DJ-1).
    Cada campo corresponde a una sección del formato de Banco PagaTodo.
    """
    # Encabezado
    numero_dictamen: str = "DJ-1"
    fecha: str | None = None

    # Denominación social
    razon_social: str | None = None
    rfc: str | None = None
    denominacion_acta: str | None = None
    denominacion_csf: str | None = None
    cambio_denominacion: bool = False
    cambio_denominacion_detalle: str | None = None

    # Datos corporativos del CSF
    estatus_padron: str | None = None
    giro_mercantil_csf: str | None = None
    domicilio_fiscal: str | None = None
    capital_social: str | None = None
    moneda_capital: str | None = None
    clausula_extranjeros: str | None = None

    # Datos de constitución
    constitucion: DatosEscritura = Field(default_factory=DatosEscritura)

    # Últimos estatutos sociales
    ultimos_estatutos: DatosEscritura = Field(default_factory=DatosEscritura)
    resumen_cambios_estatutos: str | None = None

    # Actividad / giro
    actividad: ActividadGiro = Field(default_factory=ActividadGiro)

    # Tenencia accionaria
    tenencia: TenenciaAccionaria = Field(default_factory=TenenciaAccionaria)

    # Régimen de administración
    administracion: RegimenAdministracion = Field(default_factory=RegimenAdministracion)

    # Apoderados
    apoderados: list[ApoderadoDJ] = Field(default_factory=list)

    # Observaciones
    observaciones: ObservacionesAdicionales = Field(default_factory=ObservacionesAdicionales)

    # Elaboración
    elaboracion: ElaboracionRevision = Field(default_factory=ElaboracionRevision)

    # Confiabilidad
    confiabilidad: ConfiabilidadDictamen = Field(default_factory=ConfiabilidadDictamen)

    # Dictamen final
    dictamen_resultado: Literal[
        "FAVORABLE", "FAVORABLE_CON_CONDICIONES", "NO_FAVORABLE"
    ] | None = None
    fundamento_legal: str | None = None


# ═══════════════════════════════════════════════════════════════════
#  Expediente Legal — datos consolidados de BD
# ═══════════════════════════════════════════════════════════════════

class ExpedienteLegal(BaseModel):
    """Datos consolidados del expediente leídos de la BD compartida."""
    empresa_id: str
    rfc: str
    razon_social: str

    # Documentos extraídos por Dakota (claves: acta_constitutiva, csf, poder, ine, etc.)
    documentos: dict[str, dict] = Field(default_factory=dict)
    tipos_documento: list[str] = Field(default_factory=list)

    # Validación cruzada de Colorado
    validacion_cruzada: dict | None = None

    # Análisis PLD de Arizona
    analisis_pld: dict | None = None
    dictamen_pld: dict | None = None

    # Datos clave extraídos de Colorado resumen_bloques
    datos_clave: dict | None = None


# ═══════════════════════════════════════════════════════════════════
#  Resultado de evaluación de reglas
# ═══════════════════════════════════════════════════════════════════

class ReglaEvaluada(BaseModel):
    """Resultado de evaluar una regla individual."""
    codigo: str
    nombre: str
    cumple: bool
    detalle: str = ""
    severidad: Literal["CRITICA", "MEDIA", "INFORMATIVA"] = "MEDIA"
    fuente_documento: str | None = None


class ResultadoReglas(BaseModel):
    """Consolidación de todas las reglas evaluadas."""
    reglas: list[ReglaEvaluada] = Field(default_factory=list)
    total_criticas_fallidas: int = 0
    total_medias_fallidas: int = 0
    dictamen_sugerido: Literal[
        "FAVORABLE", "FAVORABLE_CON_CONDICIONES", "NO_FAVORABLE"
    ] | None = None
    resumen: str = ""
