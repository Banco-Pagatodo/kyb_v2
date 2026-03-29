"""
Modelos Pydantic para estructura accionaria completa.

Implementa los modelos definidos en SPEC_ESTRUCTURA_ACCIONARIA.md
para cumplir con DCG Art. 115 LIC, CFF y LFPIORPI 2025.
"""

from typing import Optional, Literal, List
from pydantic import BaseModel, Field, model_validator
from datetime import date


class DomicilioCompleto(BaseModel):
    """Domicilio completo según DCG Art. 115."""
    calle: str = Field(default="", description="Nombre de la calle")
    numero_exterior: str = Field(default="", description="Número exterior")
    numero_interior: Optional[str] = Field(default=None, description="Número interior")
    colonia: str = Field(default="", description="Colonia o fraccionamiento")
    alcaldia_municipio: str = Field(default="", description="Alcaldía o Municipio")
    ciudad: Optional[str] = Field(default=None, description="Ciudad (si aplica)")
    entidad_federativa: str = Field(default="", description="Estado de la República")
    codigo_postal: str = Field(default="", description="Código postal (5 dígitos)")
    pais: str = Field(default="México", description="País")


class AccionistaCompleto(BaseModel):
    """
    Modelo completo de accionista para PLD bancario mexicano.
    
    Incluye todos los campos requeridos por:
    - DCG Art. 115 LIC (Propietario Real)
    - CFF Art. 32-B (Beneficiario Controlador)
    - LFPIORPI 2025 (cadena de titularidad)
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # IDENTIFICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    
    nombre_completo: str = Field(
        default="",
        description="PF: nombre(s) + ap. paterno + ap. materno"
    )
    denominacion_social: Optional[str] = Field(
        default=None,
        description="PM: razón social completa incluyendo tipo societario"
    )
    tipo_persona: Literal["fisica", "moral"] = Field(
        default="fisica",
        description="Tipo de persona: física o moral"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # IDENTIFICADORES FISCALES
    # ═══════════════════════════════════════════════════════════════════════════
    
    rfc: str = Field(
        default="",
        description="RFC: 12 chars para PM, 13 chars para PF"
    )
    curp: Optional[str] = Field(
        default=None,
        description="CURP: 18 caracteres (solo PF mexicanas)"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATOS PERSONALES/CORPORATIVOS
    # ═══════════════════════════════════════════════════════════════════════════
    
    nacionalidad: str = Field(
        default="Mexicana",
        description="Nacionalidad del accionista"
    )
    fecha_nacimiento: Optional[str] = Field(
        default=None,
        description="Solo PF, formato YYYY-MM-DD"
    )
    fecha_constitucion: Optional[str] = Field(
        default=None,
        description="Solo PM, formato YYYY-MM-DD"
    )
    genero: Optional[Literal["M", "F"]] = Field(
        default=None,
        description="Género (solo PF)"
    )
    estado_civil: Optional[str] = Field(
        default=None,
        description="Estado civil (solo PF)"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DOMICILIO
    # ═══════════════════════════════════════════════════════════════════════════
    
    domicilio: Optional[DomicilioCompleto] = Field(
        default=None,
        description="Domicilio completo del accionista"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PARTICIPACIÓN ACCIONARIA
    # ═══════════════════════════════════════════════════════════════════════════
    
    numero_acciones: Optional[int] = Field(
        default=None,
        ge=0,
        description="Número de acciones (S.A., S.A. de C.V.)"
    )
    numero_partes_sociales: Optional[int] = Field(
        default=None,
        ge=0,
        description="Número de partes sociales (S. de R.L.)"
    )
    serie: Optional[str] = Field(
        default=None,
        description="Serie de acciones (A, B, etc.)"
    )
    clase: Optional[str] = Field(
        default=None,
        description="Clase de acciones (ordinaria, preferente, etc.)"
    )
    valor_nominal: Optional[float] = Field(
        default=None,
        ge=0,
        description="Valor nominal por acción/parte social"
    )
    porcentaje_directo: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Porcentaje de participación directa"
    )
    porcentaje_indirecto: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Porcentaje de participación indirecta (look-through)"
    )
    porcentaje_total: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Porcentaje total = directo + indirecto"
    )
    monto_exhibiciones: Optional[float] = Field(
        default=None,
        ge=0,
        description="Monto exhibido del capital"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # METADATOS Y VALIDACIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    
    fuente: str = Field(
        default="acta_constitutiva",
        description="Documento fuente: acta_constitutiva | reforma_estatutos"
    )
    fecha_documento: Optional[str] = Field(
        default=None,
        description="Fecha del documento fuente"
    )
    confiabilidad: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Score de confiabilidad de extracción (0.0 - 1.0)"
    )
    requiere_verificacion: bool = Field(
        default=False,
        description="Requiere verificación manual"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FLAGS PLD
    # ═══════════════════════════════════════════════════════════════════════════
    
    es_propietario_real: bool = Field(
        default=False,
        description="Es Propietario Real (≥25% según DCG)"
    )
    es_beneficiario_controlador: bool = Field(
        default=False,
        description="Es Beneficiario Controlador (≥15% según CFF)"
    )
    requiere_perforacion: bool = Field(
        default=False,
        description="PM con >25% que requiere look-through"
    )
    nivel_cadena: int = Field(
        default=0,
        ge=0,
        description="Nivel en cadena de propiedad (0=directo)"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # VALIDACIONES RFC
    # ═══════════════════════════════════════════════════════════════════════════
    
    rfc_valido: bool = Field(
        default=False,
        description="RFC validado con formato correcto"
    )
    rfc_generico: bool = Field(
        default=False,
        description="RFC es genérico (extranjero, público, etc.)"
    )
    
    @model_validator(mode='after')
    def calcular_porcentaje_total(self):
        """Calcula porcentaje total si no está definido."""
        if self.porcentaje_total == 0 and (self.porcentaje_directo or self.porcentaje_indirecto):
            self.porcentaje_total = self.porcentaje_directo + self.porcentaje_indirecto
        return self
    
    @model_validator(mode='after')
    def detectar_propietario_real(self):
        """Detecta si es propietario real o beneficiario controlador."""
        # DCG Art. 115: ≥25%
        if self.porcentaje_total >= 25.0:
            self.es_propietario_real = True
        
        # CFF Art. 32-B: >15%
        if self.porcentaje_total > 15.0:
            self.es_beneficiario_controlador = True
        
        # PM con >25% requiere perforación
        if self.tipo_persona == "moral" and self.porcentaje_total > 25.0:
            self.requiere_perforacion = True
        
        return self


class Administrador(BaseModel):
    """Modelo para administrador o consejero."""
    nombre_completo: str = Field(default="", description="Nombre completo")
    cargo: str = Field(
        default="",
        description="Cargo: presidente, secretario, tesorero, vocal, etc."
    )
    tipo_persona: Literal["fisica", "moral"] = Field(
        default="fisica",
        description="Tipo de persona"
    )
    rfc: str = Field(default="", description="RFC")
    fecha_nombramiento: Optional[str] = Field(default=None, description="Fecha de nombramiento")
    vigencia: Optional[str] = Field(default=None, description="Vigencia del cargo")


class Comisario(BaseModel):
    """Modelo para comisario de la sociedad."""
    nombre_completo: str = Field(default="", description="Nombre completo")
    tipo: Literal["propietario", "suplente"] = Field(
        default="propietario",
        description="Tipo de comisario"
    )
    rfc: str = Field(default="", description="RFC")


class EntidadCompleta(BaseModel):
    """
    Modelo completo de la entidad (persona moral cliente).
    
    Extraído del Acta Constitutiva y Reformas de Estatutos.
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # IDENTIFICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    
    denominacion_social: str = Field(
        default="",
        description="Razón social completa"
    )
    tipo_societario: str = Field(
        default="",
        description="S.A. de C.V., S. de R.L., etc."
    )
    objeto_social: str = Field(
        default="",
        description="Objeto social de la empresa"
    )
    domicilio_social: Optional[DomicilioCompleto] = Field(
        default=None,
        description="Domicilio social"
    )
    duracion: str = Field(
        default="",
        description="Duración: '99 años', 'indefinida'"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CAPITAL SOCIAL
    # ═══════════════════════════════════════════════════════════════════════════
    
    capital_social_total: float = Field(
        default=0.0,
        ge=0,
        description="Capital social total"
    )
    capital_fijo: Optional[float] = Field(
        default=None,
        ge=0,
        description="Capital fijo (mínimo)"
    )
    capital_variable: Optional[float] = Field(
        default=None,
        ge=0,
        description="Capital variable"
    )
    moneda: str = Field(
        default="MXN",
        description="Moneda del capital"
    )
    total_acciones: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total de acciones emitidas"
    )
    valor_nominal_accion: Optional[float] = Field(
        default=None,
        ge=0,
        description="Valor nominal por acción"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATOS CONSTITUTIVOS
    # ═══════════════════════════════════════════════════════════════════════════
    
    fecha_constitucion: Optional[str] = Field(
        default=None,
        description="Fecha de constitución"
    )
    numero_escritura: str = Field(
        default="",
        description="Número de escritura pública"
    )
    notario: str = Field(
        default="",
        description="Nombre del notario/corredor"
    )
    numero_notaria: Optional[int] = Field(
        default=None,
        description="Número de notaría"
    )
    plaza_notarial: str = Field(
        default="",
        description="Plaza donde radica la notaría"
    )
    fecha_protocolizacion: Optional[str] = Field(
        default=None,
        description="Fecha de protocolización"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # REGISTRO
    # ═══════════════════════════════════════════════════════════════════════════
    
    folio_mercantil: Optional[str] = Field(
        default=None,
        description="Folio Mercantil Electrónico"
    )
    fecha_inscripcion_rpc: Optional[str] = Field(
        default=None,
        description="Fecha de inscripción en RPC"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ADMINISTRACIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    
    tipo_administracion: Literal["administrador_unico", "consejo_administracion", ""] = Field(
        default="",
        description="Tipo de administración"
    )
    administradores: List[Administrador] = Field(
        default_factory=list,
        description="Lista de administradores"
    )
    comisarios: List[Comisario] = Field(
        default_factory=list,
        description="Lista de comisarios"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ESTRUCTURA ACCIONARIA
    # ═══════════════════════════════════════════════════════════════════════════
    
    estructura_accionaria: List[AccionistaCompleto] = Field(
        default_factory=list,
        description="Lista de accionistas"
    )


class ReformaEstatutos(BaseModel):
    """
    Modelo para Reforma de Estatutos.
    
    Registra modificaciones a la estructura societaria.
    """
    
    # Identificación
    tipo_asamblea: Literal["ordinaria", "extraordinaria", ""] = Field(
        default="",
        description="Tipo de asamblea"
    )
    fecha_asamblea: Optional[str] = Field(
        default=None,
        description="Fecha de celebración de la asamblea"
    )
    
    # Modificaciones
    modificaciones: List[str] = Field(
        default_factory=list,
        description="Lista de tipos de modificación: capital_social, ingreso_socios, etc."
    )
    
    # Nueva estructura accionaria (post-modificación)
    estructura_accionaria_nueva: List[AccionistaCompleto] = Field(
        default_factory=list,
        description="Nueva distribución accionaria"
    )
    
    # Accionistas entrantes/salientes
    accionistas_entrantes: List[AccionistaCompleto] = Field(
        default_factory=list,
        description="Nuevos accionistas"
    )
    accionistas_salientes: List[str] = Field(
        default_factory=list,
        description="Nombres de accionistas que salen"
    )
    
    # Datos notariales
    numero_escritura: str = Field(default="", description="Número de escritura")
    notario: str = Field(default="", description="Nombre del notario")
    numero_notaria: Optional[int] = Field(default=None, description="Número de notaría")
    plaza_notarial: str = Field(default="", description="Plaza notarial")
    fecha_protocolizacion: Optional[str] = Field(default=None, description="Fecha de protocolización")
    
    # Inscripción registral
    folio_mercantil: Optional[str] = Field(default=None, description="Folio mercantil")
    fecha_inscripcion_rpc: Optional[str] = Field(default=None, description="Fecha inscripción RPC")
    inscrita: bool = Field(default=False, description="¿Reforma inscrita en RPC?")


class PropietarioReal(BaseModel):
    """
    Modelo para Propietario Real / Beneficiario Controlador.
    
    Resultado del análisis look-through según DCG Art. 115 y CFF.
    """
    nombre: str = Field(default="", description="Nombre completo")
    rfc: str = Field(default="", description="RFC")
    curp: Optional[str] = Field(default=None, description="CURP")
    nacionalidad: str = Field(default="Mexicana", description="Nacionalidad")
    
    # Porcentajes
    porcentaje_directo: float = Field(default=0.0, ge=0, le=100)
    porcentaje_indirecto: float = Field(default=0.0, ge=0, le=100)
    porcentaje_total: float = Field(default=0.0, ge=0, le=100)
    
    # Cadena de propiedad
    nivel_cadena: int = Field(default=0, ge=0, description="Nivel en cadena")
    cadena_titularidad: List[str] = Field(
        default_factory=list,
        description="Cadena de titularidad desde la entidad"
    )
    
    # Criterio de identificación
    criterio: Literal[
        "PROPIEDAD_25PCT",
        "PROPIEDAD_15PCT",
        "CONTROL_OTROS_MEDIOS",
        "ADMINISTRADOR",
        "CONTROLADOR_PM_ADMINISTRADORA",
        "DESIGNADO",
    ] = Field(default="PROPIEDAD_25PCT", description="Criterio de identificación")
    
    # Clasificación
    es_propietario_real_pld: bool = Field(default=False, description="≥25% según DCG")
    es_beneficiario_controlador_cff: bool = Field(default=False, description=">15% según CFF")
    
    # Metadatos
    fecha_identificacion: Optional[str] = Field(default=None)
    documentacion_soporte: List[str] = Field(default_factory=list)


class ResultadoEstructuraAccionaria(BaseModel):
    """
    Resultado completo del análisis de estructura accionaria.
    
    Incluye:
    - Estructura vigente
    - Propietarios reales identificados
    - Alertas y banderas rojas
    - Métricas de confiabilidad
    """
    
    # Estructura vigente
    accionistas: List[AccionistaCompleto] = Field(
        default_factory=list,
        description="Lista de accionistas vigentes"
    )
    
    # Propietarios reales
    propietarios_reales: List[PropietarioReal] = Field(
        default_factory=list,
        description="PF identificadas como propietarios reales"
    )
    
    # Alertas
    alertas_rfc: List[str] = Field(default_factory=list)
    alertas_estructura: List[str] = Field(default_factory=list)
    alertas_pld: List[str] = Field(default_factory=list)
    banderas_rojas: List[str] = Field(default_factory=list)
    
    # Métricas
    confiabilidad: float = Field(default=0.0, ge=0, le=1)
    status: str = Field(default="pendiente")
    requiere_revision_manual: bool = Field(default=False)
    
    # Cumplimiento regulatorio
    cumple_dcg: bool = Field(default=False, description="Cumple DCG Art. 115")
    cumple_cff: bool = Field(default=False, description="Cumple CFF Art. 32-B")
    documentacion_completa: bool = Field(default=False)
    
    # Fuentes
    fuente_acta: Optional[str] = Field(default=None)
    fuente_reforma: Optional[str] = Field(default=None)
    fecha_analisis: Optional[str] = Field(default=None)
