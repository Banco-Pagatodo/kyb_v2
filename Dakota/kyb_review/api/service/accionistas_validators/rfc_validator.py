"""
Validador de RFC para PLD bancario mexicano.

Implementa validación de RFC según especificaciones SAT/CNBV:
- RFC Persona Moral: 12 caracteres
- RFC Persona Física: 13 caracteres  
- RFCs genéricos para extranjeros y fideicomisos
- Validación de dígito verificador (Módulo 11)

Referencia: DCG Art. 115 LIC, CFF Art. 32-B Ter–Quinquies
"""

import re
from typing import Tuple, Optional, List
from dataclasses import dataclass
from enum import Enum


class TipoRFC(Enum):
    """Clasificación del tipo de RFC."""
    PERSONA_MORAL = "moral"
    PERSONA_FISICA = "fisica"
    GENERICO = "generico"
    INVALIDO = "invalido"


@dataclass
class ResultadoValidacionRFC:
    """Resultado de la validación de RFC."""
    rfc: str
    es_valido: bool
    tipo: TipoRFC
    tipo_persona: str  # "fisica", "moral", "generico"
    mensaje: str
    es_generico: bool
    descripcion_generico: Optional[str] = None
    formato_correcto: bool = False
    digito_verificador_valido: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES - Patrones RFC según SAT
# ═══════════════════════════════════════════════════════════════════════════════

# RFC Persona Moral: 3 letras + 6 dígitos (fecha AAMMDD) + 3 homoclave
RFC_PM_PATTERN = r'^[A-ZÑ&]{3}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'

# RFC Persona Física: 4 letras + 6 dígitos (fecha AAMMDD) + 3 homoclave
RFC_PF_PATTERN = r'^[A-ZÑ&]{4}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'

# RFCs genéricos reconocidos por SAT y CNBV
RFCS_GENERICOS = {
    # Extranjeros
    "EXTF900101NI1": "Persona física extranjera sin RFC mexicano",
    "EXTM900101NI1": "Persona física extranjera masculino sin RFC mexicano",
    "EXT990101NI1": "Persona moral extranjera sin RFC mexicano",
    "XEXX010101000": "Persona física residente en extranjero sin RFC",
    "EXT9901018A0": "Persona moral extranjera (variante)",
    
    # Ventas al público en general
    "XAXX010101000": "Público en general / Venta mostrador",
    "XGXX010101000": "Público en general (variante)",
    
    # Fideicomisos y vehículos especiales
    "FID850101AAA": "Fideicomiso genérico",
    "000000000000": "RFC no aplica (12 ceros)",
    "0000000000000": "RFC no aplica (13 ceros)",
    
    # Gobierno y paraestatal
    "GDF850101AAA": "Gobierno del Distrito Federal",
    "SAT970701NN3": "Servicio de Administración Tributaria",
}

# Caracteres válidos para cálculo de dígito verificador
CARACTERES_RFC = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
VALORES_RFC = {c: i for i, c in enumerate(CARACTERES_RFC)}

# Sufijos corporativos para detección automática de PM
SUFIJOS_PERSONA_MORAL = [
    "S.A.", "S.A. DE C.V.", "S.A.B.", "S.A.B. DE C.V.",
    "S.A.P.I.", "S.A.P.I. DE C.V.", "S.A.S.",
    "S. DE R.L.", "S. DE R.L. DE C.V.", "S.R.L.",
    "S. EN C.", "S. EN C.S.", "S. EN N.C.",
    "S.C.", "S.C. DE R.L.", "S.C.S.",
    "A.C.", "I.A.P.", "A.B.P.",
    "FIDEICOMISO", "FONDO",
]


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE VALIDACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

def normalizar_rfc(rfc: str) -> str:
    """
    Normaliza RFC a mayúsculas sin espacios.
    
    Args:
        rfc: RFC en cualquier formato
        
    Returns:
        RFC normalizado (mayúsculas, sin espacios)
    """
    if not rfc:
        return ""
    return rfc.upper().strip().replace(" ", "").replace("-", "")


def calcular_digito_verificador(rfc_sin_digito: str) -> str:
    """
    Calcula el dígito verificador de un RFC usando Módulo 11.
    
    El algoritmo SAT asigna peso 13-2 a cada posición y aplica módulo 11.
    
    Args:
        rfc_sin_digito: RFC de 11 o 12 caracteres (sin dígito verificador)
        
    Returns:
        Dígito verificador calculado (0-9 o A)
    """
    # Padding para PM (12 chars sin dígito = 11 chars)
    if len(rfc_sin_digito) == 11:
        rfc_sin_digito = " " + rfc_sin_digito
    
    if len(rfc_sin_digito) != 12:
        return ""
    
    # Calcular suma ponderada
    suma = 0
    for i, char in enumerate(rfc_sin_digito):
        peso = 13 - i
        if char == " ":
            valor = 0
        elif char in VALORES_RFC:
            valor = VALORES_RFC[char]
        else:
            return ""  # Caracter inválido
        suma += valor * peso
    
    # Calcular módulo
    residuo = suma % 11
    
    # Convertir a dígito verificador
    if residuo == 0:
        return "0"
    else:
        digito = 11 - residuo
        if digito == 10:
            return "A"
        return str(digito)


def validar_digito_verificador(rfc: str) -> bool:
    """
    Valida que el dígito verificador del RFC sea correcto.
    
    Args:
        rfc: RFC completo (12 o 13 caracteres)
        
    Returns:
        True si el dígito verificador es correcto
    """
    rfc = normalizar_rfc(rfc)
    
    if len(rfc) not in (12, 13):
        return False
    
    rfc_sin_digito = rfc[:-1]
    digito_esperado = calcular_digito_verificador(rfc_sin_digito)
    digito_actual = rfc[-1]
    
    return digito_esperado == digito_actual


def es_rfc_generico(rfc: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica si un RFC es uno de los genéricos reconocidos.
    
    Args:
        rfc: RFC a verificar
        
    Returns:
        Tupla (es_generico, descripcion)
    """
    rfc = normalizar_rfc(rfc)
    
    if rfc in RFCS_GENERICOS:
        return True, RFCS_GENERICOS[rfc]
    
    # Verificar patrones de RFCs genéricos
    if rfc.startswith("XAXX") or rfc.startswith("XEXX") or rfc.startswith("XGXX"):
        return True, "RFC genérico para público en general o extranjero"
    
    if rfc.startswith("EXT") and len(rfc) >= 12:
        return True, "RFC genérico para extranjero"
    
    if rfc.startswith("FID") and len(rfc) == 12:
        return True, "RFC genérico para fideicomiso"
    
    # RFCs de solo ceros
    if rfc in ("000000000000", "0000000000000"):
        return True, "RFC no aplica"
    
    return False, None


def validar_rfc(rfc: str, validar_checksum: bool = True) -> ResultadoValidacionRFC:
    """
    Valida formato y estructura de un RFC mexicano.
    
    Implementa validación completa según especificaciones SAT:
    1. Verifica longitud (12 PM, 13 PF)
    2. Verifica patrón de caracteres
    3. Verifica fecha válida
    4. Opcionalmente valida dígito verificador
    
    Args:
        rfc: RFC a validar
        validar_checksum: Si True, valida el dígito verificador
        
    Returns:
        ResultadoValidacionRFC con todos los detalles
    """
    rfc_original = rfc
    rfc = normalizar_rfc(rfc)
    
    # Verificar RFC vacío
    if not rfc:
        return ResultadoValidacionRFC(
            rfc=rfc_original,
            es_valido=False,
            tipo=TipoRFC.INVALIDO,
            tipo_persona="invalido",
            mensaje="RFC vacío o nulo",
            es_generico=False,
            formato_correcto=False,
        )
    
    # Verificar si es RFC genérico
    es_generico, desc_generico = es_rfc_generico(rfc)
    if es_generico:
        # Los genéricos son válidos pero con tipo especial
        return ResultadoValidacionRFC(
            rfc=rfc,
            es_valido=True,
            tipo=TipoRFC.GENERICO,
            tipo_persona="generico",
            mensaje=f"RFC genérico válido: {desc_generico}",
            es_generico=True,
            descripcion_generico=desc_generico,
            formato_correcto=True,
        )
    
    # Verificar longitud
    if len(rfc) == 12:
        # Potencial persona moral
        if re.match(RFC_PM_PATTERN, rfc):
            # Validar dígito verificador si se solicita
            digito_valido = None
            if validar_checksum:
                digito_valido = validar_digito_verificador(rfc)
            
            if validar_checksum and not digito_valido:
                return ResultadoValidacionRFC(
                    rfc=rfc,
                    es_valido=False,
                    tipo=TipoRFC.PERSONA_MORAL,
                    tipo_persona="moral",
                    mensaje="RFC de persona moral con dígito verificador inválido",
                    es_generico=False,
                    formato_correcto=True,
                    digito_verificador_valido=False,
                )
            
            return ResultadoValidacionRFC(
                rfc=rfc,
                es_valido=True,
                tipo=TipoRFC.PERSONA_MORAL,
                tipo_persona="moral",
                mensaje="RFC de persona moral válido",
                es_generico=False,
                formato_correcto=True,
                digito_verificador_valido=digito_valido,
            )
        else:
            return ResultadoValidacionRFC(
                rfc=rfc,
                es_valido=False,
                tipo=TipoRFC.INVALIDO,
                tipo_persona="invalido",
                mensaje="RFC de 12 caracteres con formato inválido para persona moral",
                es_generico=False,
                formato_correcto=False,
            )
    
    elif len(rfc) == 13:
        # Potencial persona física
        if re.match(RFC_PF_PATTERN, rfc):
            # Validar dígito verificador si se solicita
            digito_valido = None
            if validar_checksum:
                digito_valido = validar_digito_verificador(rfc)
            
            if validar_checksum and not digito_valido:
                return ResultadoValidacionRFC(
                    rfc=rfc,
                    es_valido=False,
                    tipo=TipoRFC.PERSONA_FISICA,
                    tipo_persona="fisica",
                    mensaje="RFC de persona física con dígito verificador inválido",
                    es_generico=False,
                    formato_correcto=True,
                    digito_verificador_valido=False,
                )
            
            return ResultadoValidacionRFC(
                rfc=rfc,
                es_valido=True,
                tipo=TipoRFC.PERSONA_FISICA,
                tipo_persona="fisica",
                mensaje="RFC de persona física válido",
                es_generico=False,
                formato_correcto=True,
                digito_verificador_valido=digito_valido,
            )
        else:
            return ResultadoValidacionRFC(
                rfc=rfc,
                es_valido=False,
                tipo=TipoRFC.INVALIDO,
                tipo_persona="invalido",
                mensaje="RFC de 13 caracteres con formato inválido para persona física",
                es_generico=False,
                formato_correcto=False,
            )
    
    else:
        return ResultadoValidacionRFC(
            rfc=rfc,
            es_valido=False,
            tipo=TipoRFC.INVALIDO,
            tipo_persona="invalido",
            mensaje=f"Longitud de RFC inválida: {len(rfc)} caracteres (esperado 12 o 13)",
            es_generico=False,
            formato_correcto=False,
        )


def inferir_tipo_persona_por_rfc(rfc: str) -> str:
    """
    Infiere el tipo de persona basándose únicamente en el RFC.
    
    Args:
        rfc: RFC a analizar
        
    Returns:
        "fisica", "moral", "generico" o "desconocido"
    """
    resultado = validar_rfc(rfc, validar_checksum=False)
    
    if resultado.tipo == TipoRFC.PERSONA_FISICA:
        return "fisica"
    elif resultado.tipo == TipoRFC.PERSONA_MORAL:
        return "moral"
    elif resultado.tipo == TipoRFC.GENERICO:
        return "generico"
    else:
        return "desconocido"


def detectar_tipo_persona(
    nombre: str,
    rfc: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Detecta si es persona física o moral usando RFC y nombre.
    
    Prioridad de detección:
    1. RFC (si disponible y válido)
    2. Sufijo corporativo en nombre (S.A., S. de R.L., etc.)
    3. Indicadores textuales (FIDEICOMISO, FONDO, etc.)
    4. Default: persona física
    
    Args:
        nombre: Nombre o denominación
        rfc: RFC (opcional)
        
    Returns:
        Tupla (tipo_persona, fuente_deteccion)
    """
    # 1. Intentar por RFC si disponible
    if rfc:
        rfc_norm = normalizar_rfc(rfc)
        if rfc_norm:
            resultado = validar_rfc(rfc_norm, validar_checksum=False)
            if resultado.tipo == TipoRFC.PERSONA_MORAL:
                return "moral", "rfc"
            elif resultado.tipo == TipoRFC.PERSONA_FISICA:
                return "fisica", "rfc"
            elif resultado.tipo == TipoRFC.GENERICO:
                # Para genéricos, depender del nombre
                pass
    
    # 2. Detectar por sufijo corporativo
    nombre_upper = nombre.upper().strip() if nombre else ""
    
    for sufijo in SUFIJOS_PERSONA_MORAL:
        if sufijo in nombre_upper:
            return "moral", "sufijo_corporativo"
    
    # 3. Detectar por indicadores textuales
    indicadores_moral = ["FIDEICOMISO", "FONDO", "SOCIEDAD", "ASOCIACIÓN", "ASOCIACION"]
    for indicador in indicadores_moral:
        if indicador in nombre_upper:
            return "moral", "indicador_textual"
    
    # 4. Default: persona física
    return "fisica", "default"


def validar_consistencia_rfc_tipo(
    rfc: str,
    tipo_declarado: str,
) -> Tuple[bool, str]:
    """
    Valida que el RFC sea consistente con el tipo de persona declarado.
    
    Según DCG Art. 115, el RFC debe corresponder con el tipo de persona.
    
    Args:
        rfc: RFC a validar
        tipo_declarado: Tipo declarado ("fisica" o "moral")
        
    Returns:
        Tupla (es_consistente, mensaje)
    """
    if not rfc:
        return True, "Sin RFC para validar"
    
    resultado = validar_rfc(rfc, validar_checksum=False)
    
    if resultado.tipo == TipoRFC.GENERICO:
        return True, "RFC genérico - sin validación de consistencia"
    
    if resultado.tipo == TipoRFC.INVALIDO:
        return False, resultado.mensaje
    
    tipo_rfc = resultado.tipo_persona
    tipo_declarado_norm = tipo_declarado.lower().strip()
    
    if tipo_rfc == tipo_declarado_norm:
        return True, "RFC consistente con tipo declarado"
    
    return False, (
        f"Inconsistencia: RFC indica '{tipo_rfc}' ({len(rfc)} chars) "
        f"pero se declaró como '{tipo_declarado_norm}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE BATCH PARA ESTRUCTURA ACCIONARIA
# ═══════════════════════════════════════════════════════════════════════════════

def validar_rfcs_estructura(
    accionistas: List[dict],
    validar_checksum: bool = False,
) -> List[dict]:
    """
    Valida y enriquece los RFCs de una estructura accionaria.
    
    Por cada accionista:
    1. Valida formato de RFC
    2. Detecta tipo de persona (física/moral)
    3. Verifica consistencia RFC vs tipo declarado
    4. Genera alertas si hay problemas
    
    Args:
        accionistas: Lista de accionistas con campo 'rfc'
        validar_checksum: Si True, valida dígito verificador
        
    Returns:
        Lista de accionistas enriquecida con validaciones
    """
    resultado = []
    
    for acc in accionistas:
        acc_copy = acc.copy()
        rfc = acc.get("rfc", "")
        nombre = acc.get("nombre", "")
        tipo_declarado = acc.get("tipo", "")
        
        # Normalizar RFC
        rfc_norm = normalizar_rfc(rfc) if rfc else None
        if rfc_norm:
            acc_copy["rfc"] = rfc_norm
        
        # Validar RFC
        if rfc_norm:
            resultado_rfc = validar_rfc(rfc_norm, validar_checksum)
            acc_copy["_rfc_valido"] = resultado_rfc.es_valido
            acc_copy["_rfc_tipo"] = resultado_rfc.tipo_persona
            acc_copy["_rfc_mensaje"] = resultado_rfc.mensaje
            acc_copy["_rfc_es_generico"] = resultado_rfc.es_generico
            
            if resultado_rfc.es_generico:
                acc_copy["_rfc_descripcion_generico"] = resultado_rfc.descripcion_generico
            
            # Detectar tipo de persona basado en RFC
            if resultado_rfc.tipo in (TipoRFC.PERSONA_FISICA, TipoRFC.PERSONA_MORAL):
                acc_copy["_tipo_por_rfc"] = resultado_rfc.tipo_persona
        
        # Detectar tipo de persona (RFC + nombre)
        tipo_detectado, fuente = detectar_tipo_persona(nombre, rfc_norm)
        acc_copy["_tipo_detectado"] = tipo_detectado
        acc_copy["_tipo_fuente"] = fuente
        
        # Si no hay tipo declarado, usar el detectado
        if not tipo_declarado:
            acc_copy["tipo"] = tipo_detectado
        
        # Verificar consistencia si hay tipo declarado
        if tipo_declarado and rfc_norm:
            consistente, msg = validar_consistencia_rfc_tipo(rfc_norm, tipo_declarado)
            acc_copy["_rfc_consistente"] = consistente
            if not consistente:
                acc_copy["_alerta_rfc"] = msg
        
        resultado.append(acc_copy)
    
    return resultado


def generar_alertas_rfc(accionistas: List[dict]) -> List[str]:
    """
    Genera lista de alertas relacionadas con RFC.
    
    Args:
        accionistas: Lista de accionistas ya validados
        
    Returns:
        Lista de alertas/advertencias
    """
    alertas = []
    
    for acc in accionistas:
        nombre = acc.get("nombre", "Desconocido")
        
        # RFC inválido
        if acc.get("rfc") and not acc.get("_rfc_valido", True):
            alertas.append(
                f"RFC inválido para '{nombre}': {acc.get('_rfc_mensaje', 'formato incorrecto')}"
            )
        
        # Inconsistencia RFC vs tipo
        if not acc.get("_rfc_consistente", True):
            alertas.append(acc.get("_alerta_rfc", ""))
        
        # RFC genérico
        if acc.get("_rfc_es_generico"):
            desc = acc.get("_rfc_descripcion_generico", "RFC genérico")
            alertas.append(
                f"RFC genérico para '{nombre}': {desc}"
            )
        
        # Persona moral sin RFC
        if acc.get("tipo") == "moral" and not acc.get("rfc"):
            alertas.append(
                f"Persona moral '{nombre}' sin RFC - requiere documentación"
            )
    
    return [a for a in alertas if a]  # Filtrar vacíos
