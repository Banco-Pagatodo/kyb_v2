"""
Modelos Pydantic para el módulo de Compliance MER PLD/FT v7.0.

Define esquemas para la solicitud de evaluación de riesgo,
el resultado detallado por factor, y la clasificación final.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enumeraciones ────────────────────────────────────────────────

class GradoRiesgo(str, Enum):
    """Grado de riesgo MER resultante."""
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class TipoPersona(str, Enum):
    PF = "PF"
    PFAE = "PFAE"
    PM = "PM"


class ResultadoLista(str, Enum):
    SI = "SI"
    NO = "NO"


class TipoPEP(str, Enum):
    NACIONAL = "NACIONAL"
    EXTRANJERA = "EXTRANJERA"
    NO = "NO"


# ── Solicitud de evaluación MER ──────────────────────────────────

class SolicitudMER(BaseModel):
    """Datos requeridos para calcular el grado de riesgo MER."""

    nombre_razon_social: str = Field(
        description="Nombre o razón social de la Persona Moral",
    )
    pais_constitucion: str = Field(
        default="México",
        description="País de constitución de la PM",
    )
    fecha_constitucion: Optional[str] = Field(
        default=None,
        description="Fecha de constitución (YYYY-MM-DD o DD/MM/YYYY)",
    )
    actividad_economica: Optional[str] = Field(
        default=None,
        description="Actividad económica / giro (nombre o código CNBV)",
    )
    entidad_federativa: Optional[str] = Field(
        default=None,
        description="Entidad federativa del domicilio",
    )
    alcaldia: Optional[str] = Field(
        default=None,
        description="Alcaldía (solo si entidad es Ciudad de México / CDMX)",
    )
    producto: Optional[str] = Field(
        default=None,
        description=(
            "Producto o cuenta a contratar: "
            "ya_ganaste, basica_nomina, adquirencia, fundadores, util, corporativa"
        ),
    )

    # Transaccionales
    monto_recibido: Optional[float] = Field(
        default=None,
        description="Monto estimado mensual de recursos a recibir (MXN)",
    )
    monto_enviado: Optional[float] = Field(
        default=None,
        description="Monto estimado mensual de recursos a enviar (MXN)",
    )
    ops_recibidas: Optional[int] = Field(
        default=None,
        description="Número estimado de operaciones mensuales recibidas",
    )
    ops_enviadas: Optional[int] = Field(
        default=None,
        description="Número estimado de operaciones mensuales enviadas",
    )
    origen_recursos: Optional[str] = Field(
        default=None,
        description="Origen principal de los recursos",
    )
    destino_recursos: Optional[str] = Field(
        default=None,
        description="Destino principal de los recursos",
    )

    # Listas
    coincidencia_lpb: bool = Field(
        default=False,
        description="¿Aparece en Lista de Personas Bloqueadas?",
    )
    coincidencia_listas_negativas: bool = Field(
        default=False,
        description="¿Aparece en Listas / Noticias negativas?",
    )
    pep: TipoPEP = Field(
        default=TipoPEP.NO,
        description="¿Algún representante/accionista/beneficiario es PEP?",
    )


# ── Resultado por factor ─────────────────────────────────────────

class FactorRiesgo(BaseModel):
    """Resultado de un factor individual del modelo MER."""
    numero: int = Field(description="Número de factor (1-15)")
    nombre: str = Field(description="Nombre del factor")
    dato_cliente: str = Field(description="Dato usado del cliente")
    valor_riesgo: float = Field(description="Valor de riesgo asignado")
    peso: float = Field(description="Peso del factor (0-1)")
    puntaje: float = Field(description="Puntaje = valor × peso × 100")
    dato_asumido: bool = Field(default=False, description="True si el dato fue asumido por falta de información")
    nota: str = Field(default="", description="Nota explicativa del factor (asumido, resuelto por LLM, etc.)")


# ── Resultado completo ───────────────────────────────────────────

class ResultadoMER(BaseModel):
    """Resultado completo del cálculo MER para una Persona Moral."""

    empresa: str = Field(description="Nombre / razón social")
    tipo_persona: TipoPersona = Field(default=TipoPersona.PM)
    factores: list[FactorRiesgo] = Field(description="Desglose por factor")
    puntaje_total: float = Field(description="Suma de todos los puntajes")
    grado_riesgo: GradoRiesgo = Field(description="Clasificación final")
    observaciones: list[str] = Field(
        default_factory=list,
        description="Alertas y observaciones relevantes",
    )
    recomendaciones: list[str] = Field(
        default_factory=list,
        description="Recomendaciones de debida diligencia",
    )
    contexto_mer: list[str] = Field(
        default_factory=list,
        description="Fragmentos del manual MER consultados (RAG)",
    )
    alertas: list[str] = Field(
        default_factory=list,
        description="Alertas estructurales (SAPI, datos asumidos, etc.)",
    )
    calculo_completo: bool = Field(
        default=True,
        description="False si hay factores pendientes de resolución LLM",
    )
