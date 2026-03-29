"""
Etapa 4 — Identificación de Propietarios Reales y Beneficiarios Controladores.

Implementa:
1. Cálculo de propiedad indirecta (look-through / perforación de cadena)
2. Cascada CNBV según lineamientos del 28-julio-2017
3. Consolidación de participaciones múltiples
4. Documentación para cumplimiento PLD (DCG Art.115), CFF (Art.32-B) y LFPIORPI

Marcos regulatorios:
- DCG Art. 115 LIC: Propietario Real ≥25%
- CFF Art. 32-B Ter/Quinquies: Beneficiario Controlador >15%
- LFPIORPI Art. 18: Umbral unificado 25%
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from ..models.schemas import (
    EtapaPLD,
    ExpedientePLD,
    PersonaIdentificada,
    SeveridadPLD,
)

logger = logging.getLogger("arizona.etapa4")


# ═══════════════════════════════════════════════════════════════════
#  CONSTANTES REGULATORIAS
# ═══════════════════════════════════════════════════════════════════

# PLD Bancario (DCG Art. 115-bis)
UMBRAL_PROPIETARIO_REAL = 25.0

# Fiscal (CFF Art. 32-B Ter)
UMBRAL_BENEFICIARIO_CONTROLADOR = 15.0

# LFPIORPI 2025 (unificado)
UMBRAL_LFPIORPI = 25.0

# Cotizadas (LMV)
UMBRAL_ACCIONISTA_SIGNIFICATIVO = 10.0

# Máximo nivel de perforación para evitar loops infinitos
MAX_NIVELES_PERFORACION = 10


# ═══════════════════════════════════════════════════════════════════
#  ENUMERACIONES
# ═══════════════════════════════════════════════════════════════════

class CriterioIdentificacion(str, Enum):
    """Criterio utilizado para identificar propietario real."""
    PROPIEDAD_DIRECTA = "PROPIEDAD_DIRECTA"
    PROPIEDAD_INDIRECTA = "PROPIEDAD_INDIRECTA"
    CONTROL_OTROS_MEDIOS = "CONTROL_OTROS_MEDIOS"
    ADMINISTRADOR = "ADMINISTRADOR"
    CONTROLADOR_PM_ADMINISTRADORA = "CONTROLADOR_PM_ADMINISTRADORA"
    NO_IDENTIFICADO = "NO_IDENTIFICADO"


class NivelRiesgo(str, Enum):
    """Nivel de riesgo PLD."""
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    MUY_ALTO = "MUY_ALTO"


# ═══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PropietarioReal:
    """Persona identificada como propietario real."""
    nombre: str
    rfc: str = ""
    curp: str = ""
    tipo_persona: str = "fisica"  # fisica | moral
    
    # Participación
    porcentaje_directo: float = 0.0
    porcentaje_indirecto: float = 0.0
    porcentaje_total: float = 0.0
    
    # Trazabilidad
    cadena_titularidad: list[str] = field(default_factory=list)
    nivel_perforacion: int = 0
    
    # Identificación
    criterio: CriterioIdentificacion = CriterioIdentificacion.PROPIEDAD_DIRECTA
    fuente: str = ""
    
    # Flags
    requiere_documentacion: bool = False
    requiere_perforacion: bool = False
    es_pep: bool = False
    
    # Nacionalidad y domicilio
    nacionalidad: str = ""
    pais_residencia: str = ""
    
    def __post_init__(self):
        self.porcentaje_total = self.porcentaje_directo + self.porcentaje_indirecto


@dataclass
class NodoEstructura:
    """Nodo en el árbol de estructura accionaria."""
    nombre: str
    rfc: str = ""
    tipo_persona: str = "fisica"
    porcentaje: float = 0.0
    hijos: list['NodoEstructura'] = field(default_factory=list)
    nivel: int = 0
    fuente: str = ""


@dataclass
class ResultadoPropietariosReales:
    """Resultado del análisis de propietarios reales."""
    # Propietarios identificados
    propietarios_reales_pld: list[PropietarioReal] = field(default_factory=list)  # ≥25%
    beneficiarios_controladores_cff: list[PropietarioReal] = field(default_factory=list)  # >15%
    todos_propietarios: list[PropietarioReal] = field(default_factory=list)
    
    # Criterio usado
    criterio_identificacion: CriterioIdentificacion = CriterioIdentificacion.NO_IDENTIFICADO
    
    # Cumplimiento
    cumple_pld: bool = False
    cumple_cff: bool = False
    
    # Alertas y documentación
    alertas: list[dict] = field(default_factory=list)
    pm_sin_perforar: list[dict] = field(default_factory=list)
    requiere_documentacion_adicional: bool = False
    requiere_escalamiento: bool = False
    
    # Trazabilidad
    niveles_perforados: int = 0
    total_nodos_analizados: int = 0


@dataclass
class CadenaTitularidad:
    """Cadena de titularidad para LFPIORPI."""
    ruta: list[str] = field(default_factory=list)
    porcentaje_efectivo: float = 0.0
    niveles: int = 0


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def _normalizar_nombre(nombre: str) -> str:
    """Normaliza nombre para comparación."""
    if not nombre:
        return ""
    return " ".join(nombre.upper().split())


def _es_persona_moral(accionista: dict) -> bool:
    """Determina si un accionista es persona moral."""
    # Buscar en ambos campos: tipo_persona (estándar) y tipo (Dakota)
    tipo = (accionista.get("tipo_persona") or accionista.get("tipo") or "").lower()
    if tipo == "moral":
        return True
    if tipo == "fisica":
        return False
    
    nombre = (accionista.get("nombre") or "").upper()
    sufijos_pm = [
        "S.A.", "SA DE CV", "S.A. DE C.V.", "SAPI", "SAB",
        "S. DE R.L.", "S DE R L", "S.C.", "A.C.",
        "FIDEICOMISO", "FONDO", "S.A.S.",
    ]
    return any(s in nombre for s in sufijos_pm)


def _extraer_estructura_accionaria(expediente: ExpedientePLD) -> list[dict]:
    """Extrae estructura accionaria del expediente."""
    # Priorizar reforma sobre acta
    reforma = expediente.documentos.get("reforma_estatutos", {})
    if reforma:
        estructura = reforma.get("estructura_accionaria", [])
        if estructura:
            # Manejar formato Dakota {valor: [...], ...}
            if isinstance(estructura, dict) and "valor" in estructura:
                estructura = estructura.get("valor", [])
            if estructura:
                return estructura
    
    acta = expediente.documentos.get("acta_constitutiva", {})
    estructura = acta.get("estructura_accionaria", [])
    
    # Manejar formato Dakota {valor: [...], ...}
    if isinstance(estructura, dict) and "valor" in estructura:
        estructura = estructura.get("valor", [])
    
    return estructura if isinstance(estructura, list) else []


def _extraer_administradores(expediente: ExpedientePLD) -> list[dict]:
    """Extrae administradores del expediente."""
    acta = expediente.documentos.get("acta_constitutiva", {})
    admins = acta.get("administradores", [])
    
    # Manejar formato Dakota {valor: [...], ...}
    if isinstance(admins, dict) and "valor" in admins:
        admins = admins.get("valor", [])
    
    if not admins:
        # Buscar en consejo de administración
        consejo = acta.get("consejo_administracion", [])
        if isinstance(consejo, dict) and "valor" in consejo:
            consejo = consejo.get("valor", [])
        if consejo:
            return consejo
        
        # Buscar administrador único
        admin_unico = acta.get("administrador_unico", {})
        if isinstance(admin_unico, dict):
            if "valor" in admin_unico:
                admin_unico = admin_unico.get("valor", {})
            if admin_unico.get("nombre"):
                return [admin_unico]
    
    return admins if isinstance(admins, list) else []


# ═══════════════════════════════════════════════════════════════════
#  LOOK-THROUGH / PERFORACIÓN DE CADENA
# ═══════════════════════════════════════════════════════════════════

def calcular_propiedad_indirecta(
    estructura: list[dict],
    estructuras_intermedias: dict[str, list[dict]] | None = None,
    umbral_perforacion: float = UMBRAL_PROPIETARIO_REAL,
) -> list[PropietarioReal]:
    """
    Aplica perforación de cadena hasta llegar a personas físicas.
    
    Ejemplo:
    - Cliente tiene accionista PM-Holding con 60%
    - PM-Holding tiene accionista Juan Pérez (PF) con 80%
    - Propiedad indirecta de Juan = 60% × 80% / 100 = 48%
    
    Args:
        estructura: Lista de accionistas del cliente
        estructuras_intermedias: Mapa RFC_PM -> lista de sus accionistas
        umbral_perforacion: % mínimo para considerar perforación
    
    Returns:
        Lista de PropietarioReal con participación calculada
    """
    propietarios: list[PropietarioReal] = []
    estructuras_intermedias = estructuras_intermedias or {}
    rfcs_visitados: set[str] = set()  # Evitar ciclos
    
    def perforar(
        accionistas: list[dict],
        factor: float = 100.0,
        nivel: int = 0,
        cadena: list[str] | None = None,
    ):
        cadena = cadena or []
        
        if nivel > MAX_NIVELES_PERFORACION:
            logger.warning(f"Max nivel de perforación alcanzado: {MAX_NIVELES_PERFORACION}")
            return
        
        for acc in accionistas:
            nombre = acc.get("nombre", "")
            rfc = acc.get("rfc", "")
            porcentaje = float(acc.get("porcentaje", 0) or 0)
            
            # Calcular porcentaje efectivo en este nivel
            porcentaje_efectivo = porcentaje * factor / 100.0
            
            # Cadena de titularidad
            cadena_actual = cadena + [f"{nombre} ({porcentaje:.1f}%)"]
            
            if _es_persona_moral(acc):
                # Es PM - intentar perforar
                if rfc and rfc in rfcs_visitados:
                    # Ciclo detectado
                    propietarios.append(PropietarioReal(
                        nombre=nombre,
                        rfc=rfc,
                        tipo_persona="moral",
                        porcentaje_directo=porcentaje if nivel == 0 else 0,
                        porcentaje_indirecto=porcentaje_efectivo if nivel > 0 else 0,
                        cadena_titularidad=cadena_actual,
                        nivel_perforacion=nivel,
                        criterio=CriterioIdentificacion.PROPIEDAD_INDIRECTA,
                        requiere_documentacion=True,
                        fuente="estructura_circular_detectada",
                    ))
                    continue
                
                if rfc:
                    rfcs_visitados.add(rfc)
                
                # Buscar estructura de la PM
                if rfc and rfc in estructuras_intermedias:
                    # Tenemos la estructura de esta PM - perforar
                    perforar(
                        estructuras_intermedias[rfc],
                        factor=porcentaje_efectivo,
                        nivel=nivel + 1,
                        cadena=cadena_actual,
                    )
                else:
                    # PM sin estructura conocida
                    propietarios.append(PropietarioReal(
                        nombre=nombre,
                        rfc=rfc,
                        tipo_persona="moral",
                        porcentaje_directo=porcentaje if nivel == 0 else 0,
                        porcentaje_indirecto=porcentaje_efectivo if nivel > 0 else 0,
                        cadena_titularidad=cadena_actual,
                        nivel_perforacion=nivel,
                        criterio=CriterioIdentificacion.PROPIEDAD_INDIRECTA if nivel > 0 else CriterioIdentificacion.PROPIEDAD_DIRECTA,
                        requiere_perforacion=porcentaje_efectivo >= umbral_perforacion,
                        requiere_documentacion=True,
                        fuente="pm_sin_estructura",
                    ))
            else:
                # Es PF - registrar
                propietarios.append(PropietarioReal(
                    nombre=nombre,
                    rfc=rfc,
                    curp=acc.get("curp", ""),
                    tipo_persona="fisica",
                    porcentaje_directo=porcentaje if nivel == 0 else 0,
                    porcentaje_indirecto=porcentaje_efectivo if nivel > 0 else 0,
                    cadena_titularidad=cadena_actual,
                    nivel_perforacion=nivel,
                    criterio=CriterioIdentificacion.PROPIEDAD_INDIRECTA if nivel > 0 else CriterioIdentificacion.PROPIEDAD_DIRECTA,
                    nacionalidad=acc.get("nacionalidad", ""),
                    fuente="estructura_accionaria",
                ))
    
    perforar(estructura)
    
    # Consolidar propietarios que aparecen múltiples veces
    return consolidar_propietarios(propietarios)


def consolidar_propietarios(propietarios: list[PropietarioReal]) -> list[PropietarioReal]:
    """
    Consolida participaciones de la misma persona que aparece
    en múltiples ramas de la estructura.
    """
    consolidado: dict[str, PropietarioReal] = {}
    
    for p in propietarios:
        # Usar RFC o nombre normalizado como clave
        clave = p.rfc if p.rfc else _normalizar_nombre(p.nombre)
        
        if not clave:
            continue
        
        if clave in consolidado:
            # Acumular participaciones
            existente = consolidado[clave]
            existente.porcentaje_directo += p.porcentaje_directo
            existente.porcentaje_indirecto += p.porcentaje_indirecto
            existente.porcentaje_total = existente.porcentaje_directo + existente.porcentaje_indirecto
            
            # Combinar cadenas de titularidad
            for cadena_item in p.cadena_titularidad:
                if cadena_item not in existente.cadena_titularidad:
                    existente.cadena_titularidad.append(cadena_item)
            
            # Mantener flags
            existente.requiere_perforacion = existente.requiere_perforacion or p.requiere_perforacion
            existente.requiere_documentacion = existente.requiere_documentacion or p.requiere_documentacion
        else:
            consolidado[clave] = p
    
    return list(consolidado.values())


# ═══════════════════════════════════════════════════════════════════
#  CASCADA CNBV
# ═══════════════════════════════════════════════════════════════════

def identificar_propietarios_reales_cnbv(
    estructura: list[dict],
    administradores: list[dict],
    estructuras_intermedias: dict[str, list[dict]] | None = None,
    umbral_pld: float = UMBRAL_PROPIETARIO_REAL,
    umbral_fiscal: float = UMBRAL_BENEFICIARIO_CONTROLADOR,
) -> ResultadoPropietariosReales:
    """
    Aplica cascada de identificación según lineamientos CNBV (28-julio-2017):
    
    1. PF con ≥25% de propiedad directa o indirecta
    2. Quien ejerce control por otros medios
    3. Administrador Único o Consejo de Administración
    4. PF designada si administrador es PM
    
    Args:
        estructura: Accionistas del cliente
        administradores: Lista de administradores
        estructuras_intermedias: Estructuras de PM intermedias para look-through
        umbral_pld: Umbral para propietario real (25%)
        umbral_fiscal: Umbral para beneficiario controlador CFF (15%)
    
    Returns:
        ResultadoPropietariosReales con propietarios identificados
    """
    resultado = ResultadoPropietariosReales()
    alertas: list[dict] = []
    
    # ── Paso 1: Calcular propiedad directa e indirecta ──
    todos_propietarios = calcular_propiedad_indirecta(
        estructura,
        estructuras_intermedias,
        umbral_perforacion=umbral_pld,
    )
    
    resultado.todos_propietarios = todos_propietarios
    resultado.niveles_perforados = max((p.nivel_perforacion for p in todos_propietarios), default=0)
    resultado.total_nodos_analizados = len(todos_propietarios)
    
    # ── Paso 2: Filtrar PF con ≥25% (propietarios reales PLD) ──
    propietarios_25 = [
        p for p in todos_propietarios
        if p.tipo_persona == "fisica" and p.porcentaje_total >= umbral_pld
    ]
    
    if propietarios_25:
        resultado.propietarios_reales_pld = propietarios_25
        resultado.criterio_identificacion = CriterioIdentificacion.PROPIEDAD_DIRECTA
        resultado.cumple_pld = True
        
        # También filtrar para CFF (>15%)
        resultado.beneficiarios_controladores_cff = [
            p for p in todos_propietarios
            if p.tipo_persona == "fisica" and p.porcentaje_total >= umbral_fiscal
        ]
        resultado.cumple_cff = True
        
        logger.info(
            f"Propietarios reales identificados por propiedad: "
            f"{len(propietarios_25)} con ≥{umbral_pld}%"
        )
        
        # Verificar PM sin perforar
        pm_sin_perforar = [
            p for p in todos_propietarios
            if p.tipo_persona == "moral" and p.requiere_perforacion
        ]
        if pm_sin_perforar:
            resultado.pm_sin_perforar = [
                {"nombre": p.nombre, "rfc": p.rfc, "porcentaje": p.porcentaje_total}
                for p in pm_sin_perforar
            ]
            resultado.requiere_documentacion_adicional = True
            alertas.append({
                "codigo": "PR001",
                "severidad": "media",
                "mensaje": f"{len(pm_sin_perforar)} PM con >25% requieren perforación adicional",
            })
        
        resultado.alertas = alertas
        return resultado
    
    # ── Paso 3: Buscar control por otros medios ──
    # (Verificar si hay indicadores de control sin propiedad mayoritaria)
    control_detectado = _detectar_control_otros_medios(estructura, administradores)
    
    if control_detectado:
        resultado.propietarios_reales_pld = control_detectado
        resultado.criterio_identificacion = CriterioIdentificacion.CONTROL_OTROS_MEDIOS
        resultado.cumple_pld = True
        resultado.cumple_cff = True
        resultado.beneficiarios_controladores_cff = control_detectado
        
        alertas.append({
            "codigo": "PR002",
            "severidad": "informativa",
            "mensaje": "Propietario real identificado por control de otros medios",
        })
        resultado.alertas = alertas
        return resultado
    
    # ── Paso 4: Usar administradores como fallback ──
    if administradores:
        # Buscar administradores PF
        admin_pf = []
        admin_pm = []
        
        for admin in administradores:
            nombre = admin.get("nombre", "")
            if not nombre:
                continue
            
            if _es_persona_moral(admin):
                admin_pm.append(admin)
            else:
                admin_pf.append(PropietarioReal(
                    nombre=nombre,
                    rfc=admin.get("rfc", ""),
                    tipo_persona="fisica",
                    criterio=CriterioIdentificacion.ADMINISTRADOR,
                    fuente="administrador",
                ))
        
        if admin_pf:
            resultado.propietarios_reales_pld = admin_pf
            resultado.beneficiarios_controladores_cff = admin_pf
            resultado.criterio_identificacion = CriterioIdentificacion.ADMINISTRADOR
            resultado.cumple_pld = True
            resultado.cumple_cff = True
            
            alertas.append({
                "codigo": "PR003",
                "severidad": "informativa",
                "mensaje": f"Propietario real: {len(admin_pf)} administrador(es) PF identificados",
            })
            resultado.alertas = alertas
            return resultado
        
        # ── Paso 5: Si administrador es PM, buscar su representante ──
        if admin_pm:
            pf_designadas = []
            for pm in admin_pm:
                # Buscar representante de la PM administradora
                rfc_pm = pm.get("rfc", "")
                if rfc_pm and estructuras_intermedias and rfc_pm in estructuras_intermedias:
                    estructura_pm = estructuras_intermedias[rfc_pm]
                    # Tomar el accionista mayoritario PF
                    pf_mayoritario = max(
                        (a for a in estructura_pm if not _es_persona_moral(a)),
                        key=lambda x: float(x.get("porcentaje", 0) or 0),
                        default=None
                    )
                    if pf_mayoritario:
                        pf_designadas.append(PropietarioReal(
                            nombre=pf_mayoritario.get("nombre", ""),
                            rfc=pf_mayoritario.get("rfc", ""),
                            tipo_persona="fisica",
                            criterio=CriterioIdentificacion.CONTROLADOR_PM_ADMINISTRADORA,
                            fuente=f"representante_pm:{pm.get('nombre', '')}",
                        ))
            
            if pf_designadas:
                resultado.propietarios_reales_pld = pf_designadas
                resultado.beneficiarios_controladores_cff = pf_designadas
                resultado.criterio_identificacion = CriterioIdentificacion.CONTROLADOR_PM_ADMINISTRADORA
                resultado.cumple_pld = True
                resultado.cumple_cff = True
                
                alertas.append({
                    "codigo": "PR004",
                    "severidad": "informativa",
                    "mensaje": "Propietario real: PF controlador de PM administradora",
                })
                resultado.alertas = alertas
                return resultado
            
            # PM administradoras sin estructura conocida
            alertas.append({
                "codigo": "PR005",
                "severidad": "alta",
                "mensaje": f"{len(admin_pm)} PM administradora(s) sin estructura conocida",
            })
            resultado.requiere_documentacion_adicional = True
    
    # ── Paso 6: No se pudo identificar ──
    resultado.criterio_identificacion = CriterioIdentificacion.NO_IDENTIFICADO
    resultado.cumple_pld = False
    resultado.cumple_cff = False
    resultado.requiere_escalamiento = True
    
    alertas.append({
        "codigo": "PR006",
        "severidad": "critica",
        "mensaje": "No se pudo identificar propietario real mediante ningún criterio",
    })
    
    resultado.alertas = alertas
    return resultado


def _detectar_control_otros_medios(
    estructura: list[dict],
    administradores: list[dict],
) -> list[PropietarioReal]:
    """
    Detecta control por medios distintos a la propiedad accionaria:
    - Capacidad de imponer decisiones en asambleas
    - Nombrar/remover mayoría del consejo
    - Derechos de voto >50% sin propiedad equivalente
    - Dirigir administración y estrategia
    """
    controladores: list[PropietarioReal] = []
    
    # Buscar accionistas con derechos de voto especiales
    for acc in estructura:
        votos = acc.get("derechos_voto", 0) or acc.get("votos", 0)
        porcentaje = float(acc.get("porcentaje", 0) or 0)
        
        if votos and porcentaje > 0:
            ratio_votos = float(votos) / porcentaje if porcentaje else 0
            if ratio_votos > 2.0:  # Votos desproporcionados
                if not _es_persona_moral(acc):
                    controladores.append(PropietarioReal(
                        nombre=acc.get("nombre", ""),
                        rfc=acc.get("rfc", ""),
                        tipo_persona="fisica",
                        porcentaje_directo=porcentaje,
                        criterio=CriterioIdentificacion.CONTROL_OTROS_MEDIOS,
                        fuente="derechos_voto_especiales",
                    ))
    
    # Buscar indicadores de control en metadata
    for acc in estructura:
        es_controlador = acc.get("es_controlador", False) or acc.get("control", False)
        if es_controlador and not _es_persona_moral(acc):
            controladores.append(PropietarioReal(
                nombre=acc.get("nombre", ""),
                rfc=acc.get("rfc", ""),
                tipo_persona="fisica",
                porcentaje_directo=float(acc.get("porcentaje", 0) or 0),
                criterio=CriterioIdentificacion.CONTROL_OTROS_MEDIOS,
                fuente="indicador_control",
            ))
    
    return consolidar_propietarios(controladores) if controladores else []


# ═══════════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL DE ETAPA 4
# ═══════════════════════════════════════════════════════════════════

def ejecutar_etapa4_propietarios_reales(
    expediente: ExpedientePLD,
    estructuras_pm_conocidas: dict[str, list[dict]] | None = None,
) -> ResultadoPropietariosReales:
    """
    Ejecuta la Etapa 4 del análisis PLD: Identificación de propietarios reales.
    
    Args:
        expediente: Expediente PLD con documentos
        estructuras_pm_conocidas: Estructuras de PM intermedias (opcional)
    
    Returns:
        ResultadoPropietariosReales con análisis completo
    """
    logger.info(f"Iniciando Etapa 4 — Propietarios Reales para {expediente.rfc}")
    
    # Extraer estructura accionaria
    estructura = _extraer_estructura_accionaria(expediente)
    
    if not estructura:
        logger.warning(f"Sin estructura accionaria para {expediente.rfc}")
        return ResultadoPropietariosReales(
            criterio_identificacion=CriterioIdentificacion.NO_IDENTIFICADO,
            cumple_pld=False,
            cumple_cff=False,
            requiere_documentacion_adicional=True,
            alertas=[{
                "codigo": "PR007",
                "severidad": "critica",
                "mensaje": "No se encontró estructura accionaria en el expediente",
            }],
        )
    
    # Extraer administradores
    administradores = _extraer_administradores(expediente)
    
    # Ejecutar cascada CNBV
    resultado = identificar_propietarios_reales_cnbv(
        estructura=estructura,
        administradores=administradores,
        estructuras_intermedias=estructuras_pm_conocidas,
    )
    
    # Log resultado
    if resultado.cumple_pld:
        logger.info(
            f"Etapa 4 completada: {len(resultado.propietarios_reales_pld)} "
            f"propietario(s) real(es) identificado(s) por {resultado.criterio_identificacion.value}"
        )
    else:
        logger.warning(f"Etapa 4 incompleta: requiere escalamiento")
    
    return resultado


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE REPORTE
# ═══════════════════════════════════════════════════════════════════

def generar_reporte_propietarios(
    resultado: ResultadoPropietariosReales,
) -> dict[str, Any]:
    """
    Genera reporte estructurado cumpliendo con los tres marcos regulatorios:
    - DCG (25%): propietarios_reales_pld
    - CFF (15%): beneficiarios_controladores
    - LFPIORPI: cadenas_titularidad
    """
    return {
        # Propietarios reales DCG (≥25%)
        "propietarios_reales_pld": [
            {
                "nombre": p.nombre,
                "rfc": p.rfc,
                "curp": p.curp,
                "tipo_persona": p.tipo_persona,
                "porcentaje_directo": round(p.porcentaje_directo, 2),
                "porcentaje_indirecto": round(p.porcentaje_indirecto, 2),
                "porcentaje_total": round(p.porcentaje_total, 2),
                "nacionalidad": p.nacionalidad,
                "pais_residencia": p.pais_residencia,
                "requiere_documentacion": p.requiere_documentacion,
                "es_pep": p.es_pep,
                "criterio": p.criterio.value if hasattr(p.criterio, 'value') else str(p.criterio),
                "fuente": p.fuente,
                "cadena_titularidad": p.cadena_titularidad,
                "nivel_perforacion": p.nivel_perforacion,
            }
            for p in resultado.propietarios_reales_pld
        ],
        
        # Beneficiarios controladores CFF (>15%)
        "beneficiarios_controladores_cff": [
            {
                "nombre": p.nombre,
                "rfc": p.rfc,
                "curp": p.curp,
                "tipo_persona": p.tipo_persona,
                "porcentaje_total": round(p.porcentaje_total, 2),
                "fuente": p.fuente,
            }
            for p in resultado.beneficiarios_controladores_cff
        ],
        
        # Todos los accionistas para referencia
        "todos_propietarios": [
            {
                "nombre": p.nombre,
                "rfc": p.rfc,
                "tipo_persona": p.tipo_persona,
                "porcentaje_total": round(p.porcentaje_total, 2),
            }
            for p in resultado.todos_propietarios
        ],
        
        # Cadenas de titularidad LFPIORPI
        "cadenas_titularidad": [
            {
                "propietario": p.nombre,
                "cadena": p.cadena_titularidad,
                "niveles": p.nivel_perforacion,
            }
            for p in resultado.propietarios_reales_pld
            if p.cadena_titularidad
        ],
        
        # Metadata
        "criterio_identificacion": resultado.criterio_identificacion.value,
        "cumple_pld": resultado.cumple_pld,
        "cumple_cff": resultado.cumple_cff,
        "niveles_perforados": resultado.niveles_perforados,
        "total_nodos_analizados": resultado.total_nodos_analizados,
        
        # Pendientes
        "pm_sin_perforar": resultado.pm_sin_perforar,
        "requiere_documentacion_adicional": resultado.requiere_documentacion_adicional,
        "requiere_escalamiento": resultado.requiere_escalamiento,
        
        # Alertas
        "alertas": resultado.alertas,
    }


def propietarios_a_personas_identificadas(
    resultado: ResultadoPropietariosReales,
) -> list[PersonaIdentificada]:
    """
    Convierte PropietarioReal a PersonaIdentificada para integración con Etapa 1.
    """
    personas = []
    
    for p in resultado.propietarios_reales_pld:
        personas.append(PersonaIdentificada(
            nombre=p.nombre,
            rol="propietario_real",
            fuente=p.fuente or resultado.criterio_identificacion.value,
            tipo_persona=p.tipo_persona,
            porcentaje=p.porcentaje_total,
            requiere_screening=True,
        ))
    
    # Agregar beneficiarios adicionales de CFF que no están en PLD
    rfcs_pld = {p.rfc for p in resultado.propietarios_reales_pld if p.rfc}
    
    for p in resultado.beneficiarios_controladores_cff:
        if p.rfc not in rfcs_pld:
            personas.append(PersonaIdentificada(
                nombre=p.nombre,
                rol="beneficiario_controlador",
                fuente=p.fuente or "cff_15pct",
                tipo_persona=p.tipo_persona,
                porcentaje=p.porcentaje_total,
                requiere_screening=True,
            ))
    
    return personas


def extraer_estructura_para_reporte(expediente: ExpedientePLD) -> dict[str, Any]:
    """
    Extrae la estructura accionaria del expediente en formato para el reporte consolidado.
    
    Incluye:
    - fuente: acta_constitutiva o reforma_estatutos
    - fecha_vigencia: fecha del documento fuente
    - capital_social: monto y moneda (si disponible)
    - accionistas: lista completa con porcentajes
    - propietarios_reales: ≥25% (DCG Art. 115)
    - beneficiarios_controladores: >15% (CFF Art. 32-B Ter)
    - alertas: problemas detectados
    """
    resultado: dict[str, Any] = {}
    
    # 1. Determinar fuente (reforma tiene prioridad)
    reforma = expediente.documentos.get("reforma_estatutos", {})
    acta = expediente.documentos.get("acta_constitutiva", {})
    
    estructura = []
    fuente = "N/D"
    fecha_vigencia = None
    
    # Intentar obtener de reforma
    if reforma:
        est_reforma = reforma.get("estructura_accionaria", [])
        if isinstance(est_reforma, dict) and "valor" in est_reforma:
            est_reforma = est_reforma.get("valor", [])
        if est_reforma:
            estructura = est_reforma
            fuente = "reforma_estatutos"
            fecha_vigencia = reforma.get("fecha_asamblea") or reforma.get("fecha_inscripcion_rpc")
    
    # Fallback a acta constitutiva
    if not estructura and acta:
        est_acta = acta.get("estructura_accionaria", [])
        if isinstance(est_acta, dict) and "valor" in est_acta:
            est_acta = est_acta.get("valor", [])
        if est_acta:
            estructura = est_acta
            fuente = "acta_constitutiva"
            fecha_vigencia = acta.get("fecha_constitucion")
    
    resultado["fuente"] = fuente
    resultado["fecha_vigencia"] = fecha_vigencia
    
    # 2. Extraer capital social
    capital = {}
    if acta:
        cap_social = acta.get("capital_social", {})
        if isinstance(cap_social, dict):
            # Si tiene estructura {valor: X, ...}
            if "valor" in cap_social:
                valor = cap_social.get("valor")
                # valor puede ser un número o un diccionario
                if isinstance(valor, (int, float)):
                    capital = {"monto": valor, "moneda": "MXN"}
                elif isinstance(valor, dict):
                    capital = {
                        "monto": valor.get("monto") or valor.get("cantidad"),
                        "moneda": valor.get("moneda", "MXN"),
                    }
            else:
                capital = {
                    "monto": cap_social.get("monto") or cap_social.get("cantidad"),
                    "moneda": cap_social.get("moneda", "MXN"),
                }
        elif isinstance(cap_social, (int, float)):
            capital = {"monto": cap_social, "moneda": "MXN"}
    resultado["capital_social"] = capital
    
    # 3. Normalizar accionistas
    accionistas_normalizados = []
    for acc in estructura:
        if isinstance(acc, dict):
            accionistas_normalizados.append({
                "nombre": acc.get("nombre") or acc.get("nombre_completo") or "",
                "rfc": acc.get("rfc") or "",
                "curp": acc.get("curp") or "",
                "nacionalidad": acc.get("nacionalidad") or "",
                "porcentaje": acc.get("porcentaje") or acc.get("porcentaje_directo") or 0,
                "tipo_persona": acc.get("tipo_persona") or _inferir_tipo_persona_nombre(acc.get("nombre", "")),
            })
    resultado["accionistas"] = accionistas_normalizados
    
    # 4. Identificar propietarios reales (≥25%)
    propietarios_reales = []
    for acc in accionistas_normalizados:
        try:
            pct = float(acc.get("porcentaje") or 0)
        except (ValueError, TypeError):
            pct = 0
        if pct >= UMBRAL_PROPIETARIO_REAL:
            propietarios_reales.append({
                "nombre": acc.get("nombre"),
                "rfc": acc.get("rfc"),
                "porcentaje_efectivo": pct,
                "tipo_participacion": "directa",
            })
    resultado["propietarios_reales"] = propietarios_reales
    
    # 5. Identificar beneficiarios controladores (>15%)
    beneficiarios = []
    for acc in accionistas_normalizados:
        try:
            pct = float(acc.get("porcentaje") or 0)
        except (ValueError, TypeError):
            pct = 0
        if pct > UMBRAL_BENEFICIARIO_CONTROLADOR:
            beneficiarios.append({
                "nombre": acc.get("nombre"),
                "rfc": acc.get("rfc"),
                "porcentaje_efectivo": pct,
            })
    resultado["beneficiarios_controladores"] = beneficiarios
    
    # 6. Generar alertas
    alertas = []
    
    # Verificar suma de porcentajes
    suma = sum(float(acc.get("porcentaje") or 0) for acc in accionistas_normalizados)
    if accionistas_normalizados and not (99.0 <= suma <= 101.0):
        alertas.append({
            "codigo": "EA001",
            "severidad": "media",
            "mensaje": f"Suma de porcentajes no cuadra: {suma:.2f}% (esperado ~100%)",
        })
    
    # Verificar si hay accionistas Persona Moral
    for acc in accionistas_normalizados:
        tipo = acc.get("tipo_persona", "").lower()
        try:
            pct = float(acc.get("porcentaje") or 0)
        except (ValueError, TypeError):
            pct = 0
        if tipo == "moral":
            alertas.append({
                "codigo": "EA004",
                "severidad": "critica",
                "mensaje": (
                    f"Accionista Persona Moral detectado: {acc.get('nombre')} ({pct:.2f}%). "
                    "Requiere perforación de cadena (look-through) hasta identificar "
                    "personas físicas beneficiarias. DCG Art. 115 / CFF Art. 32-B Ter."
                ),
            })
            if pct >= UMBRAL_PROPIETARIO_REAL:
                alertas.append({
                    "codigo": "EA002",
                    "severidad": "alta",
                    "mensaje": f"PM {acc.get('nombre')} ({pct:.2f}%) requiere perforación de cadena",
                })
    
    # Verificar si no hay propietarios reales
    if not propietarios_reales and accionistas_normalizados:
        alertas.append({
            "codigo": "EA003",
            "severidad": "media",
            "mensaje": "No se identificaron propietarios reales (≥25%). Participación fragmentada.",
        })
    
    resultado["alertas"] = alertas
    
    return resultado


def _inferir_tipo_persona_nombre(nombre: str) -> str:
    """Infiere tipo de persona desde el nombre."""
    sufijos_pm = [
        "S.A.", "SA DE CV", "S.A. DE C.V.", "SAPI", "SAB",
        "S. DE R.L.", "S DE R L", "S.C.", "A.C.",
        "FIDEICOMISO", "FONDO", "S.A.S.",
    ]
    nombre_upper = nombre.upper()
    return "moral" if any(s in nombre_upper for s in sufijos_pm) else "fisica"
