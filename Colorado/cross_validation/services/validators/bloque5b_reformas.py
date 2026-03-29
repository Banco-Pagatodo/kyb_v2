"""
BLOQUE 5B: VALIDACIÓN DE REFORMAS Y ESTRUCTURA ACCIONARIA AVANZADA
V5.5 — Cruce cronológico de reformas (estructura vigente)
V5.6 — Consistencia RFC vs tipo persona
V5.7 — Cross-reference accionistas Acta vs Reforma
V5.8 — Validación de inscripción RPC
V5.9 — Alertas estructura PLD
V5.10 — Estructura accionaria vigente consolidada

Implementa Fases 3-4 del pipeline de estructura accionaria según
SPEC_ESTRUCTURA_ACCIONARIA.md (DCG Art.115-bis, CFF Art.32-B, LFPIORPI).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Literal

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor, get_valor_str, normalizar_texto
from .base import h, obtener_datos, obtener_reforma


_B = 5
_BN = "ESTRUCTURA SOCIETARIA (REFORMAS)"

# ═══════════════════════════════════════════════════════════════════
#  CONSTANTES Y PATRONES
# ═══════════════════════════════════════════════════════════════════

# Umbrales regulatorios
UMBRAL_PROPIETARIO_REAL = 25.0  # DCG Art. 115-bis: >25%
UMBRAL_BENEFICIARIO_CONTROLADOR = 15.0  # CFF Art. 32-B Ter: >15%
UMBRAL_ALERTA_PARTICIPACION = 10.0  # Umbral para requerir RFC

# Patrones RFC
RFC_PM_PATTERN = r'^[A-ZÑ&]{3}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'
RFC_PF_PATTERN = r'^[A-ZÑ&]{4}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'

RFCS_GENERICOS = {
    "EXTF900101NI1": "Persona física extranjera",
    "EXT990101NI1": "Persona moral extranjera",
    "XAXX010101000": "Público en general",
    "XEXX010101000": "Residente extranjero sin RFC",
}

# Sufijos corporativos
SUFIJOS_PERSONA_MORAL = [
    "S.A. DE C.V.", "S.A.DE C.V.", "SA DE CV", "SADECV",
    "S.A.P.I. DE C.V.", "SAPI DE CV", "SAPIDECV",
    "S.A.B. DE C.V.", "SAB DE CV", "SABDECV",
    "S. DE R.L.", "S DE R L", "SDERLR", "S.DE R.L.",
    "S. DE R.L. DE C.V.", "S DE RL DE CV", "SDERLDECV",
    "S.A.", "S.A", "S.C.", "A.C.",
    "S.N.C.", "S. EN N.C.", "S. EN C.S.",
    "S.A.S.", "SAS",
    "FIDEICOMISO", "FONDO",
]

# Jurisdicciones de alto riesgo (GAFI)
JURISDICCIONES_ALTO_RIESGO = [
    "IRAN", "COREA DEL NORTE", "MYANMAR", "SIRIA",
    "AFGANISTAN", "YEMEN", "LIBIA", "SOMALIA",
    # Paraísos fiscales de vigilancia
    "ISLAS CAIMAN", "ISLAS VIRGENES BRITANICAS", "PANAMA",
    "BAHAMAS", "BERMUDAS", "JERSEY", "GUERNSEY", "ISLA DE MAN",
]


# ═══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EstructuraVigente:
    """Resultado del cruce cronológico de reformas."""
    accionistas: list[dict]
    fuente_final: str  # "acta_constitutiva" | "reforma_estatutos"
    fecha_vigencia: str | None
    reformas_aplicadas: int = 0
    reformas_no_inscritas: int = 0
    alertas: list[dict] = field(default_factory=list)


@dataclass
class AlertaEstructura:
    """Alerta generada durante validación de estructura."""
    codigo: str
    tipo: str  # "pld", "documental", "estructural"
    severidad: str  # "critica", "media", "informativa"
    mensaje: str
    accionista: str | None = None
    detalles: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE VALIDACIÓN RFC
# ═══════════════════════════════════════════════════════════════════

def _validar_formato_rfc(rfc: str) -> tuple[bool, str]:
    """
    Valida formato de RFC y determina tipo de persona.
    
    Returns:
        (valido, tipo): tipo puede ser "moral", "fisica", "generico", "invalido"
    """
    if not rfc:
        return False, "invalido"
    
    rfc = rfc.upper().strip().replace("-", "").replace(" ", "")
    
    if rfc in RFCS_GENERICOS:
        return True, "generico"
    
    if len(rfc) == 12 and re.match(RFC_PM_PATTERN, rfc):
        return True, "moral"
    
    if len(rfc) == 13 and re.match(RFC_PF_PATTERN, rfc):
        return True, "fisica"
    
    return False, "invalido"


def _detectar_tipo_persona_por_nombre(nombre: str) -> str:
    """Detecta si es PM o PF por el nombre."""
    if not nombre:
        return "desconocido"
    
    nombre_upper = nombre.upper()
    
    for sufijo in SUFIJOS_PERSONA_MORAL:
        if sufijo in nombre_upper:
            return "moral"
    
    return "fisica"  # Default


def _inferir_tipo_persona(accionista: dict) -> tuple[str, str]:
    """
    Infiere tipo de persona con fuente de inferencia.
    
    Returns:
        (tipo_persona, fuente): fuente indica cómo se determinó
    """
    tipo_declarado = accionista.get("tipo_persona", "")
    rfc = accionista.get("rfc", "")
    nombre = accionista.get("nombre", "")
    
    # Prioridad 1: RFC
    if rfc:
        valido, tipo_rfc = _validar_formato_rfc(rfc)
        if valido and tipo_rfc in ("moral", "fisica"):
            return tipo_rfc, "rfc"
    
    # Prioridad 2: Tipo declarado
    if tipo_declarado and tipo_declarado.lower() in ("moral", "fisica"):
        return tipo_declarado.lower(), "declarado"
    
    # Prioridad 3: Nombre
    tipo_nombre = _detectar_tipo_persona_por_nombre(nombre)
    if tipo_nombre != "desconocido":
        return tipo_nombre, "nombre"
    
    return "fisica", "default"


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE CRUCE CRONOLÓGICO
# ═══════════════════════════════════════════════════════════════════

def _ordenar_reformas_cronologicamente(reformas: list[dict]) -> list[dict]:
    """
    Ordena reformas por fecha de inscripción RPC (o fecha asamblea si no hay).
    """
    def obtener_fecha_orden(ref: dict) -> datetime:
        """Extrae fecha de ordenamiento."""
        # Priorizar fecha de inscripción RPC
        fecha_rpc = get_valor_str(ref, "fecha_inscripcion_rpc")
        if fecha_rpc:
            try:
                return datetime.strptime(fecha_rpc[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        
        # Fallback: fecha de asamblea / otorgamiento
        for campo in ["fecha_asamblea", "fecha_otorgamiento", "fecha_protocolizacion"]:
            fecha = get_valor_str(ref, campo)
            if fecha:
                try:
                    return datetime.strptime(fecha[:10], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
        
        return datetime.min
    
    return sorted(reformas, key=obtener_fecha_orden)


def _aplicar_modificaciones(
    base: list[dict],
    entrantes: list[dict],
    salientes: list[str],
) -> list[dict]:
    """
    Aplica modificaciones de una reforma a la estructura base.
    """
    resultado = [acc for acc in base if normalizar_texto(acc.get("nombre", "")) 
                 not in {normalizar_texto(s) for s in salientes}]
    resultado.extend(entrantes)
    return resultado


def determinar_estructura_vigente(
    acta_constitutiva: dict,
    reformas: list[dict],
) -> EstructuraVigente:
    """
    Determina la estructura accionaria vigente aplicando
    todas las reformas en orden cronológico.
    
    REGLA: La última Reforma inscrita en RPC prevalece.
    """
    alertas: list[dict] = []
    estructura_base = get_valor(acta_constitutiva, "estructura_accionaria")
    
    if not isinstance(estructura_base, list):
        estructura_base = []
    
    if not reformas:
        return EstructuraVigente(
            accionistas=estructura_base,
            fuente_final="acta_constitutiva",
            fecha_vigencia=acta_constitutiva.get("fecha_constitucion"),
            reformas_aplicadas=0,
        )
    
    # Ordenar reformas
    reformas_ordenadas = _ordenar_reformas_cronologicamente(reformas)
    reformas_aplicadas = 0
    reformas_no_inscritas = 0
    fecha_vigencia = None
    fuente_final = "acta_constitutiva"
    
    for reforma in reformas_ordenadas:
        inscrita = get_valor(reforma, "inscrita") or False
        folio = get_valor_str(reforma, "folio_mercantil")
        
        if not inscrita and not folio:
            # Reforma no inscrita
            reformas_no_inscritas += 1
            alertas.append({
                "codigo": "REF001",
                "mensaje": "Reforma no inscrita en RPC",
                "fecha": get_valor_str(reforma, "fecha_asamblea"),
                "severidad": "media",
            })
            continue
        
        # Aplicar modificaciones
        est_raw = get_valor(reforma, "estructura_accionaria")
        if isinstance(est_raw, list):
            estructura_base = est_raw
            reformas_aplicadas += 1
            fecha_vigencia = (get_valor_str(reforma, "fecha_inscripcion_rpc") or 
                              get_valor_str(reforma, "fecha_asamblea"))
            fuente_final = "reforma_estatutos"
        elif get_valor(reforma, "accionistas_entrantes") or get_valor(reforma, "accionistas_salientes"):
            estructura_base = _aplicar_modificaciones(
                estructura_base,
                get_valor(reforma, "accionistas_entrantes") or [],
                get_valor(reforma, "accionistas_salientes") or [],
            )
            reformas_aplicadas += 1
            fecha_vigencia = (get_valor_str(reforma, "fecha_inscripcion_rpc") or 
                              get_valor_str(reforma, "fecha_asamblea"))
            fuente_final = "reforma_estatutos"
    
    return EstructuraVigente(
        accionistas=estructura_base,
        fuente_final=fuente_final,
        fecha_vigencia=fecha_vigencia,
        reformas_aplicadas=reformas_aplicadas,
        reformas_no_inscritas=reformas_no_inscritas,
        alertas=alertas,
    )


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE ALERTAS PLD
# ═══════════════════════════════════════════════════════════════════

def _detectar_estructura_multicapa(accionistas: list[dict]) -> list[AlertaEstructura]:
    """Detecta PM con participación >25% que requiere perforación."""
    alertas = []
    
    pm_relevantes = []
    for acc in accionistas:
        tipo, _ = _inferir_tipo_persona(acc)
        porcentaje = float(acc.get("porcentaje", 0) or 0)
        
        if tipo == "moral" and porcentaje > UMBRAL_PROPIETARIO_REAL:
            pm_relevantes.append(acc)
    
    if len(pm_relevantes) >= 2:
        alertas.append(AlertaEstructura(
            codigo="EST001",
            tipo="pld",
            severidad="media",
            mensaje=f"Estructura multicapa detectada: {len(pm_relevantes)} PM con >25%",
            detalles={"pm_list": [p.get("nombre") for p in pm_relevantes]},
        ))
    
    for pm in pm_relevantes:
        alertas.append(AlertaEstructura(
            codigo="EST002",
            tipo="pld",
            severidad="media",
            mensaje="PM con >25% requiere perforación de estructura",
            accionista=pm.get("nombre"),
            detalles={"porcentaje": pm.get("porcentaje"), "rfc": pm.get("rfc")},
        ))
    
    return alertas


def _detectar_shell_company(accionistas: list[dict], fecha_base: str | None) -> list[AlertaEstructura]:
    """Detecta PM constituidas recientemente (<2 años)."""
    alertas = []
    
    if not fecha_base:
        return alertas
    
    try:
        fecha_ref = datetime.strptime(str(fecha_base)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        fecha_ref = datetime.now()
    
    for acc in accionistas:
        tipo, _ = _inferir_tipo_persona(acc)
        if tipo != "moral":
            continue
        
        fecha_const = acc.get("fecha_constitucion", "")
        if not fecha_const:
            continue
        
        try:
            fecha_pm = datetime.strptime(str(fecha_const)[:10], "%Y-%m-%d")
            antiguedad_dias = (fecha_ref - fecha_pm).days
            
            if antiguedad_dias < 730:  # < 2 años
                alertas.append(AlertaEstructura(
                    codigo="EST003",
                    tipo="pld",
                    severidad="media",
                    mensaje=f"PM accionista constituida recientemente ({antiguedad_dias} días)",
                    accionista=acc.get("nombre"),
                    detalles={"fecha_constitucion": fecha_const, "antiguedad_dias": antiguedad_dias},
                ))
        except (ValueError, TypeError):
            continue
    
    return alertas


def _detectar_jurisdiccion_riesgo(accionistas: list[dict]) -> list[AlertaEstructura]:
    """Detecta accionistas de jurisdicciones de alto riesgo."""
    alertas = []
    
    for acc in accionistas:
        nacionalidad = (acc.get("nacionalidad", "") or "").upper()
        pais = (acc.get("pais", "") or "").upper()
        
        for jurisdiccion in JURISDICCIONES_ALTO_RIESGO:
            if jurisdiccion in nacionalidad or jurisdiccion in pais:
                alertas.append(AlertaEstructura(
                    codigo="EST004",
                    tipo="pld",
                    severidad="critica",
                    mensaje=f"Accionista de jurisdicción de alto riesgo: {jurisdiccion}",
                    accionista=acc.get("nombre"),
                    detalles={"nacionalidad": nacionalidad, "pais": pais},
                ))
                break
    
    return alertas


def _detectar_documentacion_incompleta(accionistas: list[dict]) -> list[AlertaEstructura]:
    """Detecta accionistas >10% sin RFC."""
    alertas = []
    
    for acc in accionistas:
        porcentaje = float(acc.get("porcentaje", 0) or 0)
        rfc = acc.get("rfc", "")
        
        if porcentaje >= UMBRAL_ALERTA_PARTICIPACION and not rfc:
            alertas.append(AlertaEstructura(
                codigo="EST005",
                tipo="documental",
                severidad="media",
                mensaje=f"Accionista con {porcentaje}% sin RFC",
                accionista=acc.get("nombre"),
                detalles={"porcentaje": porcentaje},
            ))
    
    return alertas


def _detectar_rfc_inconsistente(accionistas: list[dict]) -> list[AlertaEstructura]:
    """Detecta inconsistencias entre RFC y tipo declarado."""
    alertas = []
    
    for acc in accionistas:
        rfc = acc.get("rfc", "")
        tipo_declarado = (acc.get("tipo_persona", "") or "").lower()
        
        if not rfc or not tipo_declarado:
            continue
        
        valido, tipo_rfc = _validar_formato_rfc(rfc)
        
        if not valido:
            alertas.append(AlertaEstructura(
                codigo="RFC001",
                tipo="documental",
                severidad="critica",
                mensaje=f"RFC inválido: {rfc}",
                accionista=acc.get("nombre"),
                detalles={"rfc": rfc},
            ))
        elif tipo_rfc != "generico" and tipo_rfc != tipo_declarado:
            alertas.append(AlertaEstructura(
                codigo="RFC002",
                tipo="documental",
                severidad="critica",
                mensaje=f"RFC {tipo_rfc} pero declarado como {tipo_declarado}",
                accionista=acc.get("nombre"),
                detalles={"rfc": rfc, "tipo_rfc": tipo_rfc, "tipo_declarado": tipo_declarado},
            ))
    
    return alertas


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE CROSS-REFERENCE
# ═══════════════════════════════════════════════════════════════════

def _normalizar_nombre_accionista(nombre: str) -> str:
    """Normaliza nombre para comparación fuzzy."""
    if not nombre:
        return ""
    
    nombre = normalizar_texto(nombre)
    
    # Remover sufijos corporativos solo al final del nombre
    for sufijo in SUFIJOS_PERSONA_MORAL:
        # Normalizar sufijo para comparación
        sufijo_norm = sufijo.replace(".", "").replace(" ", "").upper()
        if nombre.upper().endswith(sufijo_norm):
            nombre = nombre[:-len(sufijo_norm)]
            break
        # También verificar con espacios
        sufijo_con_espacios = sufijo.upper()
        if nombre.upper().endswith(sufijo_con_espacios):
            nombre = nombre[:-len(sufijo_con_espacios)]
            break
    
    return nombre.strip()


def _cross_reference_accionistas(
    accionistas_acta: list[dict],
    accionistas_reforma: list[dict],
) -> dict[str, Any]:
    """
    Cross-reference entre accionistas de acta constitutiva y reforma.
    
    Returns:
        dict con:
        - permanecen: Accionistas en ambos documentos
        - nuevos: Accionistas solo en reforma
        - salieron: Accionistas solo en acta
        - discrepancias: Cambios en porcentaje/acciones
    """
    nombres_acta = {}
    for acc in accionistas_acta:
        nombre_norm = _normalizar_nombre_accionista(acc.get("nombre", ""))
        if nombre_norm:
            nombres_acta[nombre_norm] = acc
    
    nombres_reforma = {}
    for acc in accionistas_reforma:
        nombre_norm = _normalizar_nombre_accionista(acc.get("nombre", ""))
        if nombre_norm:
            nombres_reforma[nombre_norm] = acc
    
    permanecen = []
    discrepancias = []
    
    for nombre, acc_acta in nombres_acta.items():
        if nombre in nombres_reforma:
            acc_ref = nombres_reforma[nombre]
            permanecen.append(nombre)
            
            # Verificar cambios en porcentaje
            pct_acta = float(acc_acta.get("porcentaje", 0) or 0)
            pct_ref = float(acc_ref.get("porcentaje", 0) or 0)
            
            if abs(pct_acta - pct_ref) > 0.01:
                discrepancias.append({
                    "nombre": nombre,
                    "porcentaje_acta": pct_acta,
                    "porcentaje_reforma": pct_ref,
                    "cambio": pct_ref - pct_acta,
                })
    
    nuevos = [n for n in nombres_reforma if n not in nombres_acta]
    salieron = [n for n in nombres_acta if n not in nombres_reforma]
    
    return {
        "permanecen": permanecen,
        "nuevos": nuevos,
        "salieron": salieron,
        "discrepancias": discrepancias,
        "total_acta": len(nombres_acta),
        "total_reforma": len(nombres_reforma),
    }


# ═══════════════════════════════════════════════════════════════════
#  VALIDACIONES (FUNCIONES PRINCIPALES)
# ═══════════════════════════════════════════════════════════════════

def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """Ejecuta todas las validaciones del bloque 5B."""
    resultado = []
    resultado.append(_v5_5_cruce_cronologico(exp))
    resultado.append(_v5_6_consistencia_rfc(exp))
    resultado.append(_v5_7_cross_reference(exp))
    resultado.append(_v5_8_inscripcion_rpc(exp))
    resultado.append(_v5_9_alertas_pld(exp))
    resultado.append(_v5_10_estructura_vigente(exp))
    return resultado


def _v5_5_cruce_cronologico(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.5 — Cruce cronológico de reformas."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    if not acta:
        return h("V5.5", "Cruce cronológico", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay Acta Constitutiva para analizar cronología")
    
    # Obtener todas las reformas si hay múltiples
    reformas = []
    if reforma:
        reformas.append(reforma)
    
    # Buscar reformas adicionales
    for doc_type, datos in exp.documentos.items():
        if "reforma" in doc_type.lower() and doc_type not in ("reforma", "reforma_estatutos"):
            reformas.append(datos)
    
    if not reformas:
        return h("V5.5", "Cruce cronológico", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 "Sin reformas — estructura vigente es la del Acta Constitutiva",
                 estructura_fuente="acta_constitutiva")
    
    estructura = determinar_estructura_vigente(acta, reformas)
    
    alertas_msg = []
    if estructura.reformas_no_inscritas > 0:
        alertas_msg.append(f"{estructura.reformas_no_inscritas} reforma(s) sin inscripción RPC")
    
    msg_parts = [
        f"Reformas aplicadas: {estructura.reformas_aplicadas}",
        f"Fuente vigente: {estructura.fuente_final}",
    ]
    if estructura.fecha_vigencia:
        msg_parts.append(f"Vigente desde: {estructura.fecha_vigencia}")
    if alertas_msg:
        msg_parts.append(" | ".join(alertas_msg))
    
    pasa = estructura.reformas_no_inscritas == 0
    
    return h("V5.5", "Cruce cronológico", _B, _BN, pasa,
             Severidad.MEDIA if not pasa else Severidad.INFORMATIVA,
             " | ".join(msg_parts),
             reformas_aplicadas=estructura.reformas_aplicadas,
             reformas_no_inscritas=estructura.reformas_no_inscritas,
             fuente_final=estructura.fuente_final,
             fecha_vigencia=estructura.fecha_vigencia,
             alertas=estructura.alertas)


def _v5_6_consistencia_rfc(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.6 — Consistencia RFC vs tipo persona."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    doc = reforma if reforma else acta
    if not doc:
        return h("V5.6", "Consistencia RFC", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay documento con estructura accionaria")
    
    estructura = get_valor(doc, "estructura_accionaria")
    if not isinstance(estructura, list) or not estructura:
        return h("V5.6", "Consistencia RFC", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay estructura accionaria para validar RFC")
    
    alertas = _detectar_rfc_inconsistente(estructura)
    
    if not alertas:
        return h("V5.6", "Consistencia RFC", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"RFCs consistentes en {len(estructura)} accionistas")
    
    criticas = [a for a in alertas if a.severidad == "critica"]
    
    return h("V5.6", "Consistencia RFC", _B, _BN, False,
             Severidad.CRITICA if criticas else Severidad.MEDIA,
             f"{len(alertas)} inconsistencia(s) de RFC detectada(s)",
             alertas=[{
                 "codigo": a.codigo,
                 "mensaje": a.mensaje,
                 "accionista": a.accionista,
                 "detalles": a.detalles,
             } for a in alertas])


def _v5_7_cross_reference(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.7 — Cross-reference accionistas Acta vs Reforma."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    if not acta or not reforma:
        return h("V5.7", "Cross-reference accionistas", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "Requiere Acta y Reforma para cross-reference")
    
    est_acta = get_valor(acta, "estructura_accionaria")
    est_reforma = get_valor(reforma, "estructura_accionaria")
    
    if not isinstance(est_acta, list) or not isinstance(est_reforma, list):
        return h("V5.7", "Cross-reference accionistas", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "Estructura accionaria incompleta en documentos")
    
    resultado = _cross_reference_accionistas(est_acta, est_reforma)
    
    msg_parts = [
        f"Acta: {resultado['total_acta']} socios",
        f"Reforma: {resultado['total_reforma']} socios",
    ]
    
    if resultado["permanecen"]:
        msg_parts.append(f"Permanecen: {len(resultado['permanecen'])}")
    if resultado["nuevos"]:
        msg_parts.append(f"Nuevos: {', '.join(resultado['nuevos'][:3])}")
    if resultado["salieron"]:
        msg_parts.append(f"Salieron: {', '.join(resultado['salieron'][:3])}")
    if resultado["discrepancias"]:
        msg_parts.append(f"Cambios porcentaje: {len(resultado['discrepancias'])}")
    
    return h("V5.7", "Cross-reference accionistas", _B, _BN, True,
             Severidad.INFORMATIVA,
             " | ".join(msg_parts),
             **resultado)


def _v5_8_inscripcion_rpc(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.8 — Validación de inscripción RPC."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    if not acta:
        return h("V5.8", "Inscripción RPC", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay Acta Constitutiva para verificar RPC")
    
    # Verificar acta
    folio_acta = get_valor_str(acta, "folio_mercantil")
    fecha_rpc_acta = get_valor_str(acta, "fecha_inscripcion_rpc")
    
    # Verificar reforma
    folio_reforma = get_valor_str(reforma, "folio_mercantil") if reforma else ""
    fecha_rpc_reforma = get_valor_str(reforma, "fecha_inscripcion_rpc") if reforma else ""
    
    problemas = []
    
    if not folio_acta:
        problemas.append("Acta sin folio mercantil")
    
    if reforma and not folio_reforma and not fecha_rpc_reforma:
        problemas.append("Reforma sin inscripción RPC")
    
    if not problemas:
        msg_parts = []
        if folio_acta:
            msg_parts.append(f"Acta: {folio_acta}")
        if folio_reforma:
            msg_parts.append(f"Reforma: {folio_reforma}")
        
        return h("V5.8", "Inscripción RPC", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"Inscripción RPC verificada: {' | '.join(msg_parts)}",
                 folio_acta=folio_acta, folio_reforma=folio_reforma)
    
    return h("V5.8", "Inscripción RPC", _B, _BN, False,
             Severidad.MEDIA,
             f"Problemas de inscripción: {'; '.join(problemas)}",
             folio_acta=folio_acta, folio_reforma=folio_reforma,
             problemas=problemas)


def _v5_9_alertas_pld(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.9 — Alertas estructura PLD."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    doc = reforma if reforma else acta
    if not doc:
        return h("V5.9", "Alertas PLD", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay documento con estructura para alertas PLD")
    
    estructura = get_valor(doc, "estructura_accionaria")
    if not isinstance(estructura, list) or not estructura:
        return h("V5.9", "Alertas PLD", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay estructura accionaria para detectar alertas PLD")
    
    fecha_base = get_valor_str(doc, "fecha_constitucion") or get_valor_str(doc, "fecha_asamblea")
    
    # Recolectar todas las alertas
    todas_alertas: list[AlertaEstructura] = []
    todas_alertas.extend(_detectar_estructura_multicapa(estructura))
    todas_alertas.extend(_detectar_shell_company(estructura, fecha_base))
    todas_alertas.extend(_detectar_jurisdiccion_riesgo(estructura))
    todas_alertas.extend(_detectar_documentacion_incompleta(estructura))
    
    if not todas_alertas:
        return h("V5.9", "Alertas PLD", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"Sin alertas PLD en {len(estructura)} accionistas")
    
    criticas = [a for a in todas_alertas if a.severidad == "critica"]
    medias = [a for a in todas_alertas if a.severidad == "media"]
    
    severidad = Severidad.CRITICA if criticas else Severidad.MEDIA
    pasa = len(criticas) == 0
    
    return h("V5.9", "Alertas PLD", _B, _BN, pasa,
             severidad,
             f"{len(todas_alertas)} alerta(s) PLD: {len(criticas)} críticas, {len(medias)} medias",
             alertas=[{
                 "codigo": a.codigo,
                 "tipo": a.tipo,
                 "severidad": a.severidad,
                 "mensaje": a.mensaje,
                 "accionista": a.accionista,
                 "detalles": a.detalles,
             } for a in todas_alertas],
             total_criticas=len(criticas),
             total_medias=len(medias))


def _v5_10_estructura_vigente(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.10 — Estructura accionaria vigente consolidada."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)
    
    # Obtener todas las reformas
    reformas = []
    if reforma:
        reformas.append(reforma)
    for doc_type, datos in exp.documentos.items():
        if "reforma" in doc_type.lower() and doc_type not in ("reforma", "reforma_estatutos"):
            reformas.append(datos)
    
    if not acta:
        return h("V5.10", "Estructura vigente", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay Acta Constitutiva para determinar estructura vigente")
    
    estructura = determinar_estructura_vigente(acta, reformas)
    
    if not estructura.accionistas:
        return h("V5.10", "Estructura vigente", _B, _BN, False,
                 Severidad.MEDIA,
                 "No se pudo determinar estructura vigente")
    
    # Calcular resumen
    n_pf = sum(1 for a in estructura.accionistas 
               if _inferir_tipo_persona(a)[0] == "fisica")
    n_pm = len(estructura.accionistas) - n_pf
    
    # Identificar >25%
    mayores_25 = [a for a in estructura.accionistas 
                  if float(a.get("porcentaje", 0) or 0) > UMBRAL_PROPIETARIO_REAL]
    
    msg = f"{len(estructura.accionistas)} accionistas ({n_pf} PF, {n_pm} PM)"
    if mayores_25:
        msg += f" | {len(mayores_25)} con >25%"
    
    return h("V5.10", "Estructura vigente", _B, _BN, True,
             Severidad.INFORMATIVA,
             msg,
             accionistas=estructura.accionistas,
             total_accionistas=len(estructura.accionistas),
             total_pf=n_pf,
             total_pm=n_pm,
             mayores_25_pct=[a.get("nombre") for a in mayores_25],
             fuente=estructura.fuente_final,
             fecha_vigencia=estructura.fecha_vigencia)
