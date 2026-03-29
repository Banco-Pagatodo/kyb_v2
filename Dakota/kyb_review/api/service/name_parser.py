# api/service/name_parser.py
"""
Módulo para parsear y separar nombres mexicanos en sus componentes.
Maneja casos especiales como apellidos compuestos, partículas nobiliarias, etc.
"""

import re
from typing import Dict, Optional
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES - PARTÍCULAS Y APELLIDOS ESPECIALES
# ═══════════════════════════════════════════════════════════════════════════════

# Partículas que forman parte de apellidos compuestos
PARTICULAS_APELLIDO = {
    "de", "del", "de la", "de los", "de las",
    "la", "las", "los", "el",
    "van", "von", "da", "do", "dos", "di",
    "san", "santa", "santo"
}

# Apellidos compuestos comunes en México
APELLIDOS_COMPUESTOS = {
    "de la cruz", "de la rosa", "de la torre", "de la garza",
    "de la fuente", "de la o", "de la paz", "de la vega",
    "de leon", "de los santos", "de los reyes", "de los angeles",
    "del rio", "del valle", "del toro", "del angel", "del moral",
    "san juan", "san martin", "santa cruz", "santa maria",
    "san miguel", "san pedro", "san jose",
    "la torre", "la cruz", "la rosa", "la fuente",
    "mc donald", "mac donald", "o brien", "o connor",
}

# Palabras que indican segundo nombre vs apellido
NOMBRES_COMUNES_MEXICANOS = {
    # Nombres masculinos comunes
    "jose", "juan", "luis", "carlos", "miguel", "angel", "jesus", "francisco",
    "antonio", "pedro", "manuel", "rafael", "jorge", "fernando", "david",
    "alejandro", "eduardo", "ricardo", "enrique", "arturo", "roberto", "oscar",
    "sergio", "alberto", "mario", "victor", "guillermo", "pablo", "raul",
    "daniel", "alfonso", "javier", "marco", "hector", "andres", "gabriel",
    # Nombres femeninos comunes
    "maria", "guadalupe", "ana", "patricia", "laura", "rosa", "carmen",
    "elena", "martha", "leticia", "veronica", "claudia", "silvia", "adriana",
    "sandra", "alicia", "elizabeth", "teresa", "monica", "gabriela", "lucia",
    "beatriz", "rocio", "susana", "margarita", "yolanda", "irma", "gloria",
    "cristina", "julia", "norma", "isabel", "luz", "esperanza", "dolores",
}


# ═══════════════════════════════════════════════════════════════════════════════
# ESTRUCTURA DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedName:
    """Nombre parseado en sus componentes."""
    primer_nombre: str
    segundo_nombre: Optional[str]
    primer_apellido: str
    segundo_apellido: Optional[str]
    nombre_completo_original: str
    confianza: float  # 0.0 - 1.0
    
    def to_dict(self) -> Dict[str, any]:
        """Convierte a diccionario para JSON."""
        return {
            "primer_nombre": self.primer_nombre,
            "segundo_nombre": self.segundo_nombre,
            "primer_apellido": self.primer_apellido,
            "segundo_apellido": self.segundo_apellido,
            "nombre_completo": self.nombre_completo_original,
            "confianza_parsing": self.confianza
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TÍTULOS PROFESIONALES A REMOVER
# ═══════════════════════════════════════════════════════════════════════════════

TITULOS_PROFESIONALES = {
    "lic", "lic.", "licenciado", "licenciada",
    "ing", "ing.", "ingeniero", "ingeniera",
    "dr", "dr.", "doctor", "doctora", "dra", "dra.",
    "mtro", "mtro.", "maestro", "maestra", "mtra", "mtra.",
    "c", "c.", "ciudadano", "ciudadana",
    "sr", "sr.", "señor", "sra", "sra.", "señora",
    "prof", "prof.", "profesor", "profesora",
    "arq", "arq.", "arquitecto", "arquitecta",
    "cp", "c.p.", "contador", "contadora",
    "abog", "abog.", "abogado", "abogada",
}


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def remover_titulos(nombre: str) -> str:
    """
    Remueve títulos profesionales del inicio del nombre.
    
    Args:
        nombre: Nombre que puede contener títulos
    
    Returns:
        Nombre sin títulos
    """
    if not nombre:
        return ""
    
    palabras = nombre.split()
    while palabras and palabras[0].lower().rstrip(".") in TITULOS_PROFESIONALES:
        palabras.pop(0)
    
    return " ".join(palabras)


def normalizar_nombre(nombre: str) -> str:
    """
    Normaliza un nombre: quita espacios extra, títulos y capitaliza correctamente.
    
    Args:
        nombre: Nombre a normalizar
    
    Returns:
        Nombre normalizado
    """
    if not nombre:
        return ""
    
    # Quitar espacios extra
    nombre = " ".join(nombre.split())
    
    # Remover títulos profesionales
    nombre = remover_titulos(nombre)
    
    if not nombre:
        return ""
    
    # Capitalizar cada palabra excepto partículas
    palabras = nombre.lower().split()
    resultado = []
    
    for i, palabra in enumerate(palabras):
        # Primera palabra siempre capitalizada
        if i == 0:
            resultado.append(palabra.capitalize())
        # Partículas en minúscula (excepto al inicio)
        elif palabra in {"de", "del", "la", "las", "los", "el", "y"}:
            resultado.append(palabra)
        else:
            resultado.append(palabra.capitalize())
    
    return " ".join(resultado)


def es_nombre_comun(palabra: str) -> bool:
    """Verifica si una palabra es un nombre común mexicano."""
    return palabra.lower() in NOMBRES_COMUNES_MEXICANOS


def es_particula(palabra: str) -> bool:
    """Verifica si una palabra es una partícula de apellido."""
    return palabra.lower() in PARTICULAS_APELLIDO


def detectar_apellido_compuesto(palabras: list, indice: int) -> Optional[int]:
    """
    Detecta si hay un apellido compuesto comenzando en el índice dado.
    
    Args:
        palabras: Lista de palabras del nombre
        indice: Índice donde comenzar a buscar
    
    Returns:
        Número de palabras del apellido compuesto, o None si no hay
    """
    if indice >= len(palabras):
        return None
    
    # Verificar combinaciones de 2 y 3 palabras
    for longitud in [3, 2]:
        if indice + longitud <= len(palabras):
            posible_compuesto = " ".join(palabras[indice:indice + longitud]).lower()
            if posible_compuesto in APELLIDOS_COMPUESTOS:
                return longitud
    
    # Verificar patrón "de/del/de la + palabra"
    if indice + 1 < len(palabras):
        primera = palabras[indice].lower()
        if primera in {"de", "del"}:
            return 2
        if primera == "de" and indice + 2 < len(palabras):
            segunda = palabras[indice + 1].lower()
            if segunda in {"la", "los", "las", "el"}:
                return 3
    
    return None


def parse_nombre_mexicano(nombre_completo: str) -> ParsedName:
    """
    Parsea un nombre mexicano completo en sus componentes.
    
    Formato típico mexicano: Nombre(s) Apellido_Paterno Apellido_Materno
    
    Args:
        nombre_completo: Nombre completo a parsear
    
    Returns:
        ParsedName con los componentes separados
    
    Examples:
        "Juan Carlos García López" -> 
            primer_nombre="Juan", segundo_nombre="Carlos",
            primer_apellido="García", segundo_apellido="López"
        
        "María de la Cruz Hernández" ->
            primer_nombre="María", segundo_nombre=None,
            primer_apellido="de la Cruz", segundo_apellido="Hernández"
    """
    if not nombre_completo or not nombre_completo.strip():
        return ParsedName(
            primer_nombre="",
            segundo_nombre=None,
            primer_apellido="",
            segundo_apellido=None,
            nombre_completo_original=nombre_completo or "",
            confianza=0.0
        )
    
    # Normalizar y separar en palabras
    nombre_normalizado = normalizar_nombre(nombre_completo)
    palabras = nombre_normalizado.split()
    
    # Casos especiales por número de palabras
    if len(palabras) == 1:
        # Solo una palabra - asumir que es nombre
        return ParsedName(
            primer_nombre=palabras[0],
            segundo_nombre=None,
            primer_apellido="",
            segundo_apellido=None,
            nombre_completo_original=nombre_completo,
            confianza=0.3
        )
    
    if len(palabras) == 2:
        # Dos palabras: Nombre Apellido
        return ParsedName(
            primer_nombre=palabras[0],
            segundo_nombre=None,
            primer_apellido=palabras[1],
            segundo_apellido=None,
            nombre_completo_original=nombre_completo,
            confianza=0.7
        )
    
    if len(palabras) == 3:
        # Tres palabras: varias posibilidades
        # Caso 1: Nombre Nombre Apellido (ej: Jose Luis Garcia)
        # Caso 2: Nombre Apellido Apellido (ej: Juan Garcia Lopez)
        
        # Si la segunda palabra es nombre común, es segundo nombre
        if es_nombre_comun(palabras[1]):
            return ParsedName(
                primer_nombre=palabras[0],
                segundo_nombre=palabras[1],
                primer_apellido=palabras[2],
                segundo_apellido=None,
                nombre_completo_original=nombre_completo,
                confianza=0.8
            )
        else:
            # Asumir Nombre Apellido Apellido
            return ParsedName(
                primer_nombre=palabras[0],
                segundo_nombre=None,
                primer_apellido=palabras[1],
                segundo_apellido=palabras[2],
                nombre_completo_original=nombre_completo,
                confianza=0.85
            )
    
    # 4 o más palabras - caso más complejo
    # Estrategia: identificar dónde empiezan los apellidos
    
    primer_nombre = palabras[0]
    segundo_nombre = None
    primer_apellido = ""
    segundo_apellido = None
    indice_apellidos = 1
    
    # Verificar si la segunda palabra es un segundo nombre
    if es_nombre_comun(palabras[1]):
        segundo_nombre = palabras[1]
        indice_apellidos = 2
    
    # Verificar apellidos compuestos
    if indice_apellidos < len(palabras):
        longitud_compuesto = detectar_apellido_compuesto(palabras, indice_apellidos)
        
        if longitud_compuesto:
            primer_apellido = " ".join(palabras[indice_apellidos:indice_apellidos + longitud_compuesto])
            indice_segundo_apellido = indice_apellidos + longitud_compuesto
        else:
            primer_apellido = palabras[indice_apellidos]
            indice_segundo_apellido = indice_apellidos + 1
        
        # Segundo apellido
        if indice_segundo_apellido < len(palabras):
            longitud_compuesto_2 = detectar_apellido_compuesto(palabras, indice_segundo_apellido)
            
            if longitud_compuesto_2:
                segundo_apellido = " ".join(palabras[indice_segundo_apellido:indice_segundo_apellido + longitud_compuesto_2])
            else:
                # Tomar solo la siguiente palabra como segundo apellido
                segundo_apellido = palabras[indice_segundo_apellido]
    
    # Calcular confianza basada en la estructura
    confianza = 0.9
    if not segundo_apellido:
        confianza -= 0.1
    if len(palabras) > 5:
        confianza -= 0.1  # Nombres muy largos son más difíciles de parsear
    
    return ParsedName(
        primer_nombre=primer_nombre,
        segundo_nombre=segundo_nombre,
        primer_apellido=primer_apellido,
        segundo_apellido=segundo_apellido,
        nombre_completo_original=nombre_completo,
        confianza=max(0.5, confianza)
    )


def separar_nombres_en_datos(datos: Dict[str, any], campos_nombre: list) -> Dict[str, any]:
    """
    Procesa un diccionario de datos y separa los campos de nombre especificados.
    
    Args:
        datos: Diccionario con los datos extraídos
        campos_nombre: Lista de nombres de campos que contienen nombres completos
    
    Returns:
        Diccionario actualizado con nombres separados
    
    Example:
        datos = {"nombre_apoderado": "Juan Carlos García López"}
        campos = ["nombre_apoderado"]
        resultado = separar_nombres_en_datos(datos, campos)
        # resultado["nombre_apoderado_parsed"] = {
        #     "primer_nombre": "Juan",
        #     "segundo_nombre": "Carlos",
        #     "primer_apellido": "García",
        #     "segundo_apellido": "López",
        #     ...
        # }
    """
    resultado = datos.copy()
    
    for campo in campos_nombre:
        valor = datos.get(campo)
        
        if not valor:
            continue
        
        # Manejar si es dict con "valor"
        if isinstance(valor, dict):
            nombre_str = valor.get("valor", "")
        else:
            nombre_str = str(valor)
        
        if nombre_str:
            parsed = parse_nombre_mexicano(nombre_str)
            resultado[f"{campo}_parsed"] = parsed.to_dict()
    
    return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CONVENIENCIA
# ═══════════════════════════════════════════════════════════════════════════════

def get_campos_nombre_por_documento(doc_type: str) -> list:
    """
    Retorna los campos de nombre relevantes para cada tipo de documento.
    
    Args:
        doc_type: Tipo de documento (ine, acta_constitutiva, poder_notarial, etc.)
    
    Returns:
        Lista de nombres de campos que contienen nombres de personas
    """
    campos_por_documento = {
        # INE
        "ine": ["nombre", "nombre_completo"],
        "ine_reverso": ["nombre", "nombre_completo"],
        
        # Acta Constitutiva (doc_type puede ser "acta_constitutiva" o "acta")
        "acta_constitutiva": ["nombre_notario", "representante_legal", "socios", 
                              "primer_nombre_fedatario", "segundo_nombre_fedatario",
                              "apellido_paterno_fedatario", "apellido_materno_fedatario"],
        "acta": ["nombre_notario", "representante_legal", "socios",
                 "primer_nombre_fedatario", "segundo_nombre_fedatario",
                 "apellido_paterno_fedatario", "apellido_materno_fedatario"],
        
        # Poder Notarial (doc_type puede ser "poder_notarial" o "poder")
        "poder_notarial": ["nombre_apoderado", "nombre_poderdante", "nombre_notario"],
        "poder": ["nombre_apoderado", "nombre_poderdante", "nombre_notario"],
        
        # Reforma de Estatutos (doc_type puede ser "reforma_estatutos" o "reforma")
        "reforma_estatutos": ["nombre_notario", "representante_legal"],
        "reforma": ["nombre_notario", "representante_legal"],
        
        # CSF
        "csf": ["nombre_contribuyente", "razon_social", "denominacion_razon_social"],
        
        # FIEL
        "fiel": ["nombre_titular", "nombre_contribuyente", "nombre", "denominacion_razon_social"],
        
        # Estado de Cuenta
        "estado_cuenta": ["nombre_titular", "titular", "nombre_cliente", "nombre"],
        
        # Comprobante de Domicilio
        "domicilio": ["nombre_titular", "titular", "nombre", "nombre_cliente"],
    }
    
    return campos_por_documento.get(doc_type, [])


def procesar_nombres_documento(datos: Dict[str, any], doc_type: str) -> Dict[str, any]:
    """
    Procesa automáticamente todos los campos de nombre de un documento.
    
    Args:
        datos: Datos extraídos del documento (puede tener estructura con "valor")
        doc_type: Tipo de documento
    
    Returns:
        Diccionario con nombres parseados (solo los campos procesados)
        Ej: {"nombre_apoderado": {"primer_nombre": "Juan", ...}}
    """
    campos = get_campos_nombre_por_documento(doc_type)
    resultado = {}
    
    for campo in campos:
        valor = datos.get(campo)
        
        if not valor:
            continue
        
        # Manejar si es dict con "valor" (estructura del validation_wrapper)
        if isinstance(valor, dict):
            nombre_str = valor.get("valor", "")
        else:
            nombre_str = str(valor)
        
        # Solo procesar si parece un nombre (no vacío, no es número, etc.)
        if nombre_str and not nombre_str.upper() in ["N/A", "PENDIENTE", ""]:
            # Verificar que no sea solo números o caracteres especiales
            if any(c.isalpha() for c in nombre_str):
                parsed = parse_nombre_mexicano(nombre_str)
                resultado[campo] = parsed.to_dict()
    
    return resultado
