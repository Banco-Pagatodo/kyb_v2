"""
Modelos Pydantic para el agente de validación cruzada.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Enumeraciones ────────────────────────────────────────────────

class Severidad(str, Enum):
    """Nivel de severidad de un hallazgo."""
    CRITICA = "CRITICA"
    MEDIA = "MEDIA"
    INFORMATIVA = "INFORMATIVA"


class Dictamen(str, Enum):
    """Resultado final de la validación cruzada."""
    APROBADO = "APROBADO"
    APROBADO_CON_OBSERVACIONES = "APROBADO_CON_OBSERVACIONES"
    RECHAZADO = "RECHAZADO"


# ── Modelos de datos ─────────────────────────────────────────────

class Hallazgo(BaseModel):
    """Un hallazgo individual de una validación."""
    codigo: str = Field(description="Código de la validación, e.g. V1.1")
    nombre: str = Field(description="Nombre corto de la validación")
    bloque: int = Field(description="Número del bloque (1-9)")
    bloque_nombre: str = Field(description="Nombre del bloque")
    pasa: bool | None = Field(description="True=pasa, False=falla, None=N/A")
    severidad: Severidad
    mensaje: str = Field(description="Descripción del resultado")
    detalles: dict[str, Any] = Field(default_factory=dict)


class PersonaClave(BaseModel):
    """Persona relevante extraída del expediente."""
    nombre: str = Field(description="Nombre completo")
    rol: str = Field(description="Rol: accionista, apoderado, representante_legal, consejero")
    fuente: str = Field(default="", description="Documento de origen: ine, poder, acta_constitutiva, reforma")
    tipo_persona: str = Field(default="fisica", description="fisica o moral")
    porcentaje: float | None = Field(default=None, description="% accionario (solo accionistas)")
    facultades: str | None = Field(default=None, description="Tipo de poder/facultades (solo apoderados)")


class DomicilioClave(BaseModel):
    """Domicilio validado de la persona moral."""
    calle: str = Field(default="", description="Nombre de la calle")
    numero_exterior: str = Field(default="", description="Número exterior")
    numero_interior: str = Field(default="", description="Número interior")
    colonia: str = Field(default="", description="Colonia")
    codigo_postal: str = Field(default="", description="Código postal")
    municipio: str = Field(default="", description="Municipio o delegación")
    estado: str = Field(default="", description="Entidad federativa")
    fuente: str = Field(default="", description="Documento de origen: csf, comprobante_domicilio")


class DatosClave(BaseModel):
    """Datos clave de la persona moral extraídos del expediente."""
    razon_social: str = Field(description="Razón social / denominación de la PM")
    rfc: str = Field(default="", description="RFC de la PM")
    apoderados: list[PersonaClave] = Field(default_factory=list, description="Apoderados legales")
    representante_legal: PersonaClave | None = Field(default=None, description="Representante legal principal")
    accionistas: list[PersonaClave] = Field(default_factory=list, description="Accionistas / socios")
    consejo_administracion: list[PersonaClave] = Field(default_factory=list, description="Miembros del consejo de administración")
    poder_cuenta_bancaria: bool | None = Field(
        default=None,
        description="True si el poder incluye facultad expresa para abrir/operar cuentas bancarias",
    )
    # ── Campos adicionales para PLD (Arizona) ──
    giro_mercantil: str = Field(default="", description="Giro mercantil / actividad económica (del CSF)")
    fecha_constitucion: str = Field(default="", description="Fecha de constitución (del acta)")
    numero_serie_fiel: str = Field(default="", description="Número de serie del certificado FIEL")
    domicilio: DomicilioClave | None = Field(default=None, description="Domicilio fiscal validado")


class ExpedienteEmpresa(BaseModel):
    """Datos completos de una empresa cargados de la BD."""
    empresa_id: str
    rfc: str
    razon_social: str
    documentos: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="doc_type → datos_extraidos (el más reciente si hay duplicados)",
    )
    doc_types_presentes: list[str] = Field(default_factory=list)


class ComparacionCampo(BaseModel):
    """Resultado de la comparación de un campo entre fuente manual y OCR."""
    campo: str = Field(description="Nombre del campo comparado")
    valor_manual: str = Field(default="", description="Valor del formulario manual")
    valor_ocr: str = Field(default="", description="Valor extraído por OCR")
    coincide: bool | None = Field(description="True=coincide, False=discrepa, None=no evaluable")
    similitud: float | None = Field(default=None, description="Score de similitud 0.0-1.0")
    severidad: Severidad = Field(default=Severidad.INFORMATIVA)


class ReporteValidacion(BaseModel):
    """Reporte completo de validación cruzada para una empresa."""
    empresa_id: str
    rfc: str
    razon_social: str
    fecha_analisis: datetime
    documentos_presentes: list[str]
    hallazgos: list[Hallazgo] = Field(default_factory=list)
    dictamen: Dictamen
    total_criticos: int = 0
    total_medios: int = 0
    total_informativos: int = 0
    total_pasan: int = 0
    recomendaciones: list[str] = Field(default_factory=list)
    datos_clave: DatosClave | None = Field(
        default=None,
        description="Datos clave de la persona moral: razón social, apoderados, representante legal, accionistas",
    )
    comparacion_fuentes: list[ComparacionCampo] = Field(
        default_factory=list,
        description="Comparación campo a campo entre formulario manual y OCR (Bloque 11)",
    )


class ResumenGlobal(BaseModel):
    """Resumen de validación de todas las empresas."""
    fecha_analisis: datetime
    total_empresas: int
    reportes: list[ReporteValidacion]
    tabla_dictamenes: list[dict[str, Any]] = Field(default_factory=list)
    hallazgos_frecuentes: list[dict[str, Any]] = Field(default_factory=list)
    recomendaciones_globales: list[str] = Field(default_factory=list)


class ValidacionCruzadaDB(BaseModel):
    """Registro persistido en la tabla validaciones_cruzadas."""
    id: str
    empresa_id: str
    rfc: str
    razon_social: str
    dictamen: Dictamen
    total_pasan: int
    total_criticos: int
    total_medios: int
    total_informativos: int
    hallazgos: list[dict[str, Any]]
    recomendaciones: list[str]
    documentos_presentes: list[str]
    portales_ejecutados: bool
    modulos_portales: list[str] | None
    reporte_texto: str | None = None
    resumen_bloques: dict[str, Any] | None = None
    created_at: datetime
