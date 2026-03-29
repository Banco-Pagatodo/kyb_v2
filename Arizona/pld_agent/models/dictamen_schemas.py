"""
Modelos Pydantic para el Dictamen PLD/FT — Banco PagaTodo.

Estructura de 6 páginas/secciones que mapea al formato fijo bancario:
  1. Datos generales de la PM + screening PM + actividad económica
  2. Domicilio + estructura accionaria vigente
  3. Propietarios reales / beneficiarios controladores
  4. Representantes legales + administración
  5. Organigrama + personas relacionadas
  6. Perfil transaccional + conclusiones PLD/FT
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
#  Sub-modelos de screening (reutilizados en varias secciones)
# ═══════════════════════════════════════════════════════════════════

class ScreeningSeccion(BaseModel):
    """Resultado de screening de una sección (PM, accionistas, etc.)."""
    coincidencia_listas: bool = False
    datos_lista: str | None = None
    confirma_coincidencia: bool = False
    justificacion_descarte: str | None = None
    fuentes_negativas: bool = False
    detalle_fuentes: str | None = None


# ═══════════════════════════════════════════════════════════════════
#  Entidades tabulares
# ═══════════════════════════════════════════════════════════════════

class AccionistaDictamen(BaseModel):
    """Fila de la tabla de estructura accionaria."""
    numero: int
    nombre_razon_social: str
    porcentaje_accionario: str
    rfc_curp: str | None = None
    tipo_persona: str = "PF"
    coincidencia_listas: str = "NO"
    screening_detalle: dict[str, Any] | None = None


class PropietarioRealDictamen(BaseModel):
    """Fila de la tabla de propietarios reales."""
    numero: int
    nombre: str
    tipo_control: str
    rfc_curp: str | None = None
    coincidencia_listas: str = "NO"
    screening_detalle: dict[str, Any] | None = None


class RepresentanteLegalDictamen(BaseModel):
    """Fila de la tabla de representantes legales."""
    numero: int
    nombre: str
    rfc_curp: str | None = None
    coincidencia_listas: str = "NO"


class AdministradorDictamen(BaseModel):
    """Fila de la tabla de administración."""
    numero: int
    nombre: str
    puesto: str = ""
    rfc_curp: str | None = None
    coincidencia_listas: str = "NO"


class PersonaOrganigrama(BaseModel):
    """Fila de la tabla de organigrama."""
    numero: int
    nombre: str
    rfc_curp: str | None = None
    coincidencia_listas: str = "NO"


class PersonaRelacionada(BaseModel):
    """Fila de la tabla de personas relacionadas."""
    numero: int
    nombre_razon_social: str
    rfc_curp: str | None = None
    relacion: str = ""
    coincidencia_listas: str = "NO"


# ═══════════════════════════════════════════════════════════════════
#  Modelo principal: DictamenPLDFT
# ═══════════════════════════════════════════════════════════════════

class DictamenPLDFT(BaseModel):
    """Dictamen PLD/FT completo — mapeo 1:1 al formato bancario de 6 páginas."""

    dictamen_id: str = Field(description="DICT-PLD-[RFC]-[YYYYMMDD]-[SEQ]")
    version: str = "1.0"
    fecha_elaboracion: date
    tipo_producto: str = "Cuenta corporativa"
    grado_riesgo_inicial: str = "bajo"

    # ── Página 1: Datos PM ───────────────────────────────────────
    persona_moral: dict[str, Any] = Field(default_factory=dict)
    screening_persona_moral: ScreeningSeccion = Field(default_factory=ScreeningSeccion)
    actividad_economica: str = ""
    congruencia_info_docs: bool = True
    actividades_no_declaradas: bool = False
    detalle_act_no_declaradas: str | None = None
    actividades_mayor_riesgo: bool = False
    detalle_act_mayor_riesgo: str | None = None

    # ── Página 2: Domicilio + Estructura accionaria ──────────────
    domicilio: str = ""
    concuerda_domicilio_docs: bool = True
    concuerda_domicilio_actividad: bool = True
    observaciones_domicilio: str = "Sin observaciones"
    vinculo_otra_pm: bool = False
    detalle_vinculo_pm: str | None = None
    vinculos_paises_sancionados: bool = False
    detalle_paises_sancionados: str | None = None

    estructura_accionaria: list[AccionistaDictamen] = Field(default_factory=list)
    screening_accionistas: ScreeningSeccion = Field(default_factory=ScreeningSeccion)

    # ── Página 3: Propietarios reales ────────────────────────────
    propietarios_reales: list[PropietarioRealDictamen] = Field(default_factory=list)
    screening_propietarios: ScreeningSeccion = Field(default_factory=ScreeningSeccion)
    vinculos_otras_pm_propietarios: bool = False
    detalle_vinculos_pm_propietarios: str | None = None
    senales_alerta_propietarios: str = "Sin señales de alerta"

    # ── Página 4: Representantes + Administración ────────────────
    representantes_legales: list[RepresentanteLegalDictamen] = Field(default_factory=list)
    screening_representantes: ScreeningSeccion = Field(default_factory=ScreeningSeccion)
    administracion: list[AdministradorDictamen] = Field(default_factory=list)
    screening_administracion: ScreeningSeccion = Field(default_factory=ScreeningSeccion)

    # ── Página 5: Organigrama + Personas relacionadas ────────────
    senales_alerta_admin: str | None = "Sin señales de alerta"
    organigrama: list[PersonaOrganigrama] = Field(default_factory=list)
    screening_organigrama: ScreeningSeccion = Field(default_factory=ScreeningSeccion)
    personas_relacionadas: list[PersonaRelacionada] = Field(default_factory=list)
    screening_relacionadas: ScreeningSeccion = Field(default_factory=ScreeningSeccion)

    # ── Página 6: Perfil transaccional + Conclusiones ────────────
    senales_alerta_relacionadas: str | None = "Sin señales de alerta"
    uso_cuenta: str = ""
    congruencia_perfil_actividad: bool = True
    observaciones_perfil: str | None = None

    # Datos transaccionales del estado de cuenta (BUG-09)
    perfil_transaccional: dict[str, Any] = Field(default_factory=dict)

    # Vigencia de documentos (BUG-11)
    vigencia_documentos: list[dict[str, Any]] = Field(default_factory=list)

    # Detalle del poder notarial (BUG-14)
    detalle_poder_notarial: dict[str, Any] = Field(default_factory=dict)

    conclusiones: dict[str, Any] = Field(default_factory=dict)

    elaboro: dict[str, str] = Field(default_factory=lambda: {
        "nombre": "Agente Arizona v2.3",
        "firma": "Dictamen generado automáticamente por Agente Arizona — Pipeline PLD/FT",
    })

    metadata: dict[str, Any] = Field(default_factory=dict)
