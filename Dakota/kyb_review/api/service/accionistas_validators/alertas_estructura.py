"""
Generador de alertas para estructura accionaria.

Implementa detección de alertas según SPEC_ESTRUCTURA_ACCIONARIA.md:
- Alertas estructurales (multicapa, shell companies, etc.)
- Alertas documentales (tachaduras, sin inscripción, etc.)
- Alertas PLD (PEP, perforación requerida, etc.)
- Banderas rojas (prestanombres, circulares, alto riesgo)

Referencia: DCG Art. 115, GAFI/FATF Rec. 10, 24, 25
"""

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, date


class SeveridadAlerta(Enum):
    """Severidad de las alertas generadas."""
    INFO = "info"
    ADVERTENCIA = "warning"
    ERROR = "error"
    CRITICA = "critical"


class TipoAlerta(Enum):
    """Clasificación de tipos de alerta."""
    ESTRUCTURAL = "estructural"
    DOCUMENTAL = "documental"
    PLD = "pld"
    BANDERA_ROJA = "bandera_roja"


@dataclass
class Alerta:
    """Modelo de alerta generada."""
    codigo: str
    tipo: TipoAlerta
    severidad: SeveridadAlerta
    mensaje: str
    entidad: str  # Nombre del accionista/entidad afectado
    detalle: Optional[str] = None
    accion_requerida: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES - Jurisdicciones de alto riesgo
# ═══════════════════════════════════════════════════════════════════════════════

JURISDICCIONES_ALTO_RIESGO = {
    # Lista GAFI/FATF actualizaciones 2024-2025
    "IRAN": "Lista negra GAFI",
    "COREA DEL NORTE": "Lista negra GAFI",
    "MYANMAR": "Lista gris GAFI",
    "SIRIA": "Sanciones internacionales",
    # Paraísos fiscales UE
    "ISLAS VIRGENES BRITANICAS": "Paraíso fiscal",
    "ISLAS CAIMAN": "Paraíso fiscal",
    "PANAMA": "Alto riesgo fiscal",
    "BELICE": "Paraíso fiscal",
    "BAHAMAS": "Paraíso fiscal",
    "BERMUDA": "Paraíso fiscal",
    "JERSEY": "Paraíso fiscal",
    "GUERNSEY": "Paraíso fiscal",
    "ISLA DE MAN": "Paraíso fiscal",
    "SEYCHELLES": "Paraíso fiscal",
    "MAURICIO": "Paraíso fiscal",
    "ANTIGUA Y BARBUDA": "Alto riesgo",
    "SAN KITTS": "Alto riesgo",
    "NEVIS": "Alto riesgo",
    # Centroamérica alto riesgo
    "NICARAGUA": "Deficiencias AML",
    "HONDURAS": "Alto riesgo narco",
    "GUATEMALA": "Alto riesgo",
}

# Umbrales PLD
UMBRAL_PROPIETARIO_REAL = 25.0
UMBRAL_BENEFICIARIO_CONTROLADOR = 15.0
UMBRAL_ACCIONISTA_SIGNIFICATIVO = 10.0

# Límites de estructura
MAX_NIVELES_CADENA = 3
MAX_CAMBIOS_12_MESES = 3
ANTIGUEDAD_ACTA_ALERTA_ANOS = 5


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTAS ESTRUCTURALES
# ═══════════════════════════════════════════════════════════════════════════════

def detectar_estructura_multicapa(
    accionistas: List[Dict[str, Any]],
    nivel_maximo: int = MAX_NIVELES_CADENA,
) -> List[Alerta]:
    """
    Detecta estructuras con múltiples capas de PM.
    
    Según GAFI, estructuras >3 niveles sin propósito claro son sospechosas.
    """
    alertas = []
    
    # Contar PM accionistas
    pm_accionistas = [
        a for a in accionistas 
        if a.get("tipo", "").lower() == "moral" or a.get("tipo_persona", "").lower() == "moral"
    ]
    
    if len(pm_accionistas) >= 2:
        # Verificar si alguna PM tiene >25% (requeriría perforación)
        pm_significativas = [
            pm for pm in pm_accionistas
            if (pm.get("porcentaje", 0) or pm.get("porcentaje_directo", 0) or 0) > UMBRAL_PROPIETARIO_REAL
        ]
        
        if pm_significativas:
            for pm in pm_significativas:
                nombre = pm.get("nombre", pm.get("denominacion_social", "PM Desconocida"))
                pct = pm.get("porcentaje", pm.get("porcentaje_directo", 0)) or 0
                alertas.append(Alerta(
                    codigo="EST001",
                    tipo=TipoAlerta.ESTRUCTURAL,
                    severidad=SeveridadAlerta.ADVERTENCIA,
                    mensaje=f"Estructura multicapa detectada: PM '{nombre}' con {pct:.1f}%",
                    entidad=nombre,
                    detalle="Múltiples PM en estructura accionaria requieren documentación adicional",
                    accion_requerida="Solicitar Acta Constitutiva de la PM accionista para perforación",
                ))
    
    return alertas


def detectar_shell_company(
    accionistas: List[Dict[str, Any]],
    fecha_constitucion_cliente: Optional[str] = None,
) -> List[Alerta]:
    """
    Detecta posibles shell companies (PM recién constituidas sin operaciones).
    
    Indicadores:
    - PM accionista constituida menos de 12 meses antes
    - Sin actividad declarada
    - Capital mínimo
    """
    alertas = []
    
    if not fecha_constitucion_cliente:
        return alertas
    
    try:
        fecha_cliente = datetime.strptime(fecha_constitucion_cliente[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return alertas
    
    for acc in accionistas:
        if acc.get("tipo", "").lower() != "moral" and acc.get("tipo_persona", "").lower() != "moral":
            continue
        
        fecha_pm = acc.get("fecha_constitucion")
        if not fecha_pm:
            continue
        
        try:
            fecha_pm_dt = datetime.strptime(fecha_pm[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        
        # Si la PM se constituyó menos de 6 meses antes del cliente
        diferencia = (fecha_cliente - fecha_pm_dt).days
        if 0 < diferencia < 180:
            nombre = acc.get("nombre", acc.get("denominacion_social", "PM Desconocida"))
            alertas.append(Alerta(
                codigo="EST002",
                tipo=TipoAlerta.ESTRUCTURAL,
                severidad=SeveridadAlerta.ADVERTENCIA,
                mensaje=f"Posible shell company: '{nombre}' constituida {diferencia} días antes del cliente",
                entidad=nombre,
                detalle="PM accionista constituida recientemente antes del cliente",
                accion_requerida="Verificar operaciones reales de la PM, estados financieros",
            ))
    
    return alertas


def detectar_estructura_circular(
    accionistas: List[Dict[str, Any]],
    denominacion_cliente: str = "",
) -> List[Alerta]:
    """
    Detecta posible estructura circular (A posee B, B posee A).
    
    Requiere información de la estructura de PM accionistas.
    """
    alertas = []
    
    # Verificar si el cliente aparece como accionista de alguna PM accionista
    # (Esto requeriría perforación previa)
    for acc in accionistas:
        accionistas_pm = acc.get("estructura_accionaria", [])
        if accionistas_pm:
            for sub_acc in accionistas_pm:
                nombre_sub = (sub_acc.get("nombre", "") or sub_acc.get("denominacion_social", "")).upper()
                if denominacion_cliente.upper() in nombre_sub or nombre_sub in denominacion_cliente.upper():
                    nombre_pm = acc.get("nombre", acc.get("denominacion_social", "PM"))
                    alertas.append(Alerta(
                        codigo="EST003",
                        tipo=TipoAlerta.BANDERA_ROJA,
                        severidad=SeveridadAlerta.CRITICA,
                        mensaje=f"Estructura circular detectada: Cliente ↔ '{nombre_pm}'",
                        entidad=nombre_pm,
                        detalle="El cliente aparece en la estructura accionaria de su propio accionista",
                        accion_requerida="Escalamiento inmediato a Oficial de Cumplimiento",
                    ))
    
    return alertas


def detectar_cambios_frecuentes(
    reformas: List[Dict[str, Any]],
    meses: int = 12,
    limite: int = MAX_CAMBIOS_12_MESES,
) -> List[Alerta]:
    """
    Detecta cambios frecuentes en estructura accionaria.
    """
    alertas = []
    
    if len(reformas) <= limite:
        return alertas
    
    # Filtrar reformas de los últimos N meses
    ahora = datetime.now()
    reformas_recientes = []
    
    for reforma in reformas:
        fecha = reforma.get("fecha_asamblea") or reforma.get("fecha_protocolizacion")
        if not fecha:
            continue
        try:
            fecha_dt = datetime.strptime(fecha[:10], "%Y-%m-%d")
            if (ahora - fecha_dt).days <= meses * 30:
                reformas_recientes.append(reforma)
        except (ValueError, TypeError):
            continue
    
    if len(reformas_recientes) > limite:
        alertas.append(Alerta(
            codigo="EST004",
            tipo=TipoAlerta.ESTRUCTURAL,
            severidad=SeveridadAlerta.ADVERTENCIA,
            mensaje=f"Cambios frecuentes: {len(reformas_recientes)} reformas en últimos {meses} meses",
            entidad="Estructura accionaria",
            detalle=f"Se detectaron {len(reformas_recientes)} modificaciones (límite: {limite})",
            accion_requerida="Justificar cambios frecuentes con documentación soporte",
        ))
    
    return alertas


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTAS DOCUMENTALES
# ═══════════════════════════════════════════════════════════════════════════════

def detectar_sin_inscripcion_rpc(
    data: Dict[str, Any],
    tipo_documento: str = "acta",
) -> List[Alerta]:
    """
    Detecta documentos sin inscripción en Registro Público de Comercio.
    """
    alertas = []
    
    folio = data.get("folio_mercantil") or data.get("fme")
    inscrita = data.get("inscrita", True)  # Default a True si no hay campo
    
    if not folio and not inscrita:
        alertas.append(Alerta(
            codigo="DOC001",
            tipo=TipoAlerta.DOCUMENTAL,
            severidad=SeveridadAlerta.ADVERTENCIA,
            mensaje=f"Documento sin inscripción en RPC: {tipo_documento}",
            entidad=tipo_documento,
            detalle="No se encontró Folio Mercantil Electrónico en el documento",
            accion_requerida="Solicitar Boleta de Inscripción o documento con sello del RPC",
        ))
    
    return alertas


def detectar_acta_antigua(
    fecha_constitucion: Optional[str],
    reformas: List[Dict[str, Any]] = None,
    anos_limite: int = ANTIGUEDAD_ACTA_ALERTA_ANOS,
) -> List[Alerta]:
    """
    Detecta actas constitutivas muy antiguas sin reformas posteriores.
    """
    alertas = []
    reformas = reformas or []
    
    if not fecha_constitucion:
        return alertas
    
    try:
        fecha_const = datetime.strptime(fecha_constitucion[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return alertas
    
    antiguedad_anos = (datetime.now() - fecha_const).days / 365
    
    if antiguedad_anos > anos_limite and len(reformas) == 0:
        alertas.append(Alerta(
            codigo="DOC002",
            tipo=TipoAlerta.DOCUMENTAL,
            severidad=SeveridadAlerta.INFO,
            mensaje=f"Acta Constitutiva de {antiguedad_anos:.0f} años sin reformas registradas",
            entidad="Acta Constitutiva",
            detalle="Documento antiguo - verificar vigencia de información",
            accion_requerida="Confirmar que la estructura accionaria sigue vigente",
        ))
    
    return alertas


def detectar_discrepancia_denominacion(
    denominacion_acta: str,
    denominacion_csf: str,
) -> List[Alerta]:
    """
    Detecta discrepancias entre denominación en Acta y CSF.
    """
    alertas = []
    
    if not denominacion_acta or not denominacion_csf:
        return alertas
    
    # Normalizar para comparación
    def normalizar(s):
        import re
        s = s.upper().strip()
        s = re.sub(r'\s+', ' ', s)
        s = s.replace(".", "").replace(",", "")
        return s
    
    acta_norm = normalizar(denominacion_acta)
    csf_norm = normalizar(denominacion_csf)
    
    if acta_norm != csf_norm:
        # Verificar si es diferencia menor (con/sin tipo societario)
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, acta_norm, csf_norm).ratio()
        
        if ratio < 0.95:
            alertas.append(Alerta(
                codigo="DOC003",
                tipo=TipoAlerta.DOCUMENTAL,
                severidad=SeveridadAlerta.ERROR if ratio < 0.80 else SeveridadAlerta.ADVERTENCIA,
                mensaje="Discrepancia en denominación social entre Acta y CSF",
                entidad="Denominación social",
                detalle=f"Acta: '{denominacion_acta}' vs CSF: '{denominacion_csf}'",
                accion_requerida="Verificar denominación correcta y actualizar si es necesario",
            ))
    
    return alertas


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTAS PLD
# ═══════════════════════════════════════════════════════════════════════════════

def detectar_requiere_perforacion(accionistas: List[Dict[str, Any]]) -> List[Alerta]:
    """
    Detecta PM accionistas que requieren perforación de cadena.
    
    Según DCG Art. 115, PM con >25% requiere identificación de sus propietarios.
    """
    alertas = []
    
    for acc in accionistas:
        tipo = (acc.get("tipo", "") or acc.get("tipo_persona", "")).lower()
        if tipo != "moral":
            continue
        
        porcentaje = acc.get("porcentaje", 0) or acc.get("porcentaje_directo", 0) or 0
        
        if porcentaje > UMBRAL_PROPIETARIO_REAL:
            nombre = acc.get("nombre", acc.get("denominacion_social", "PM Desconocida"))
            alertas.append(Alerta(
                codigo="PLD001",
                tipo=TipoAlerta.PLD,
                severidad=SeveridadAlerta.ADVERTENCIA,
                mensaje=f"Persona moral '{nombre}' con {porcentaje:.1f}% requiere perforación",
                entidad=nombre,
                detalle=f"PM supera umbral de {UMBRAL_PROPIETARIO_REAL}% - requiere identificación de propietarios reales",
                accion_requerida="Solicitar Acta Constitutiva de la PM y realizar look-through",
            ))
    
    return alertas


def detectar_jurisdiccion_alto_riesgo(accionistas: List[Dict[str, Any]]) -> List[Alerta]:
    """
    Detecta accionistas en jurisdicciones de alto riesgo.
    """
    alertas = []
    
    for acc in accionistas:
        nacionalidad = (acc.get("nacionalidad", "") or "").upper()
        pais_domicilio = (acc.get("domicilio", {}) or {}).get("pais", "").upper() if isinstance(acc.get("domicilio"), dict) else ""
        
        for jurisdiccion, razon in JURISDICCIONES_ALTO_RIESGO.items():
            if jurisdiccion in nacionalidad or jurisdiccion in pais_domicilio:
                nombre = acc.get("nombre", acc.get("denominacion_social", "Accionista"))
                alertas.append(Alerta(
                    codigo="PLD002",
                    tipo=TipoAlerta.BANDERA_ROJA,
                    severidad=SeveridadAlerta.CRITICA,
                    mensaje=f"Accionista '{nombre}' en jurisdicción de alto riesgo: {jurisdiccion}",
                    entidad=nombre,
                    detalle=f"Jurisdicción: {jurisdiccion} - {razon}",
                    accion_requerida="Aplicar debida diligencia reforzada (EDD)",
                ))
    
    return alertas


def detectar_documentacion_incompleta(accionistas: List[Dict[str, Any]]) -> List[Alerta]:
    """
    Detecta accionistas con documentación incompleta.
    """
    alertas = []
    
    for acc in accionistas:
        nombre = acc.get("nombre", acc.get("denominacion_social", "Accionista"))
        tipo = (acc.get("tipo", "") or acc.get("tipo_persona", "")).lower()
        porcentaje = acc.get("porcentaje", 0) or acc.get("porcentaje_directo", 0) or 0
        
        # Solo alertar para accionistas significativos
        if porcentaje < UMBRAL_ACCIONISTA_SIGNIFICATIVO:
            continue
        
        campos_faltantes = []
        
        # RFC
        if not acc.get("rfc"):
            campos_faltantes.append("RFC")
        
        # Datos según tipo
        if tipo == "fisica":
            if not acc.get("curp"):
                campos_faltantes.append("CURP")
        else:
            if not acc.get("fecha_constitucion"):
                campos_faltantes.append("Fecha de constitución")
        
        # Domicilio
        if not acc.get("domicilio"):
            campos_faltantes.append("Domicilio")
        
        if campos_faltantes:
            alertas.append(Alerta(
                codigo="PLD003",
                tipo=TipoAlerta.PLD,
                severidad=SeveridadAlerta.ADVERTENCIA,
                mensaje=f"Documentación incompleta para '{nombre}' ({porcentaje:.1f}%)",
                entidad=nombre,
                detalle=f"Campos faltantes: {', '.join(campos_faltantes)}",
                accion_requerida=f"Solicitar: {', '.join(campos_faltantes)}",
            ))
    
    return alertas


# ═══════════════════════════════════════════════════════════════════════════════
# BANDERAS ROJAS
# ═══════════════════════════════════════════════════════════════════════════════

def detectar_prestanombre_posible(
    accionistas: List[Dict[str, Any]],
    capital_social: float = 0,
) -> List[Alerta]:
    """
    Detecta posibles prestanombres.
    
    Indicadores:
    - PF con participación muy alta sin RFC
    - PF joven con participación significativa
    - Múltiples PF con exactamente mismo porcentaje
    """
    alertas = []
    
    # Detectar PF con alta participación sin RFC
    for acc in accionistas:
        tipo = (acc.get("tipo", "") or acc.get("tipo_persona", "")).lower()
        if tipo != "fisica":
            continue
        
        porcentaje = acc.get("porcentaje", 0) or acc.get("porcentaje_directo", 0) or 0
        rfc = acc.get("rfc", "")
        
        if porcentaje >= 25 and not rfc:
            nombre = acc.get("nombre", "PF Desconocida")
            alertas.append(Alerta(
                codigo="BRD001",
                tipo=TipoAlerta.BANDERA_ROJA,
                severidad=SeveridadAlerta.ADVERTENCIA,
                mensaje=f"Posible prestanombre: '{nombre}' ({porcentaje:.1f}%) sin RFC",
                entidad=nombre,
                detalle="Persona física con participación significativa sin identificación fiscal",
                accion_requerida="Solicitar RFC y verificar capacidad económica",
            ))
    
    # Detectar distribución sospechosa (todos igual)
    porcentajes = [
        acc.get("porcentaje", 0) or acc.get("porcentaje_directo", 0) or 0
        for acc in accionistas
    ]
    
    if len(porcentajes) >= 3:
        porcentajes_unicos = set(round(p, 2) for p in porcentajes if p > 0)
        if len(porcentajes_unicos) == 1 and list(porcentajes_unicos)[0] < 25:
            # Todos tienen exactamente el mismo porcentaje y es <25%
            alertas.append(Alerta(
                codigo="BRD002",
                tipo=TipoAlerta.BANDERA_ROJA,
                severidad=SeveridadAlerta.ADVERTENCIA,
                mensaje=f"Distribución sospechosa: {len(porcentajes)} accionistas con {list(porcentajes_unicos)[0]:.1f}% cada uno",
                entidad="Estructura accionaria",
                detalle="Distribución igualitaria diseñada para evitar umbral de 25%",
                accion_requerida="Verificar relación entre accionistas y justificación de estructura",
            ))
    
    return alertas


def detectar_capital_inconsistente(
    capital_social: float,
    actividad_economica: str = "",
) -> List[Alerta]:
    """
    Detecta capital social inconsistente con actividad económica.
    """
    alertas = []
    
    if not capital_social or not actividad_economica:
        return alertas
    
    actividad_upper = actividad_economica.upper()
    
    # Actividades que típicamente requieren alto capital
    actividades_alto_capital = [
        "INMOBILIARIA", "CONSTRUCCION", "MANUFACTURA", "INDUSTRIAL",
        "FINANCIERA", "SEGUROS", "AUTOMOTRIZ", "MINERIA",
    ]
    
    for actividad in actividades_alto_capital:
        if actividad in actividad_upper:
            # Para estas actividades, capital < 500,000 es sospechoso
            if capital_social < 500000:
                alertas.append(Alerta(
                    codigo="BRD003",
                    tipo=TipoAlerta.BANDERA_ROJA,
                    severidad=SeveridadAlerta.ADVERTENCIA,
                    mensaje=f"Capital de ${capital_social:,.2f} bajo para actividad: {actividad_economica}",
                    entidad="Capital social",
                    detalle="Capital aparentemente insuficiente para la actividad declarada",
                    accion_requerida="Verificar fuente de financiamiento operativo",
                ))
            break
    
    return alertas


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL - Generar todas las alertas
# ═══════════════════════════════════════════════════════════════════════════════

def generar_todas_alertas(
    accionistas: List[Dict[str, Any]],
    data_acta: Dict[str, Any] = None,
    reformas: List[Dict[str, Any]] = None,
    denominacion_csf: str = "",
) -> Dict[str, List[Alerta]]:
    """
    Genera todas las alertas para una estructura accionaria.
    
    Args:
        accionistas: Lista de accionistas
        data_acta: Datos del Acta Constitutiva
        reformas: Lista de Reformas de Estatutos
        denominacion_csf: Denominación según CSF (para cruce)
        
    Returns:
        Diccionario con alertas categorizadas por tipo
    """
    data_acta = data_acta or {}
    reformas = reformas or []
    
    todas_alertas = []
    
    # Alertas estructurales
    todas_alertas.extend(detectar_estructura_multicapa(accionistas))
    todas_alertas.extend(detectar_shell_company(
        accionistas, 
        data_acta.get("fecha_constitucion")
    ))
    todas_alertas.extend(detectar_estructura_circular(
        accionistas,
        data_acta.get("denominacion_social", "")
    ))
    todas_alertas.extend(detectar_cambios_frecuentes(reformas))
    
    # Alertas documentales
    todas_alertas.extend(detectar_sin_inscripcion_rpc(data_acta, "acta_constitutiva"))
    for reforma in reformas:
        todas_alertas.extend(detectar_sin_inscripcion_rpc(reforma, "reforma_estatutos"))
    todas_alertas.extend(detectar_acta_antigua(
        data_acta.get("fecha_constitucion"),
        reformas
    ))
    todas_alertas.extend(detectar_discrepancia_denominacion(
        data_acta.get("denominacion_social", ""),
        denominacion_csf
    ))
    
    # Alertas PLD
    todas_alertas.extend(detectar_requiere_perforacion(accionistas))
    todas_alertas.extend(detectar_jurisdiccion_alto_riesgo(accionistas))
    todas_alertas.extend(detectar_documentacion_incompleta(accionistas))
    
    # Banderas rojas
    todas_alertas.extend(detectar_prestanombre_posible(
        accionistas,
        data_acta.get("capital_social_total", 0)
    ))
    todas_alertas.extend(detectar_capital_inconsistente(
        data_acta.get("capital_social_total", 0),
        data_acta.get("objeto_social", "")
    ))
    
    # Categorizar por tipo
    resultado = {
        "estructurales": [],
        "documentales": [],
        "pld": [],
        "banderas_rojas": [],
    }
    
    for alerta in todas_alertas:
        if alerta.tipo == TipoAlerta.ESTRUCTURAL:
            resultado["estructurales"].append(alerta)
        elif alerta.tipo == TipoAlerta.DOCUMENTAL:
            resultado["documentales"].append(alerta)
        elif alerta.tipo == TipoAlerta.PLD:
            resultado["pld"].append(alerta)
        elif alerta.tipo == TipoAlerta.BANDERA_ROJA:
            resultado["banderas_rojas"].append(alerta)
    
    return resultado


def alertas_a_lista_strings(
    alertas_dict: Dict[str, List[Alerta]]
) -> Dict[str, List[str]]:
    """
    Convierte alertas a listas de strings para serialización.
    """
    return {
        categoria: [
            f"[{a.codigo}] {a.mensaje}" for a in alertas
        ]
        for categoria, alertas in alertas_dict.items()
    }
