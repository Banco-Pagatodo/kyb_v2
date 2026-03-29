"""
Validador robusto para estructura accionaria.

Este módulo proporciona funciones para:
1. Validar que un string sea realmente un nombre de persona (no basura/texto legal)
2. Deduplicar accionistas con similitud fuzzy
3. Filtrar entradas basura
4. Calcular confiabilidad de la estructura extraída

Resuelve los problemas de:
- Entradas como "Certificados Provisionales Que Amparen Sus Respectivas"
- Duplicados como "Rusell Herrera Palomo" vs "Russell Herrera Palomo"
- Fragmentos de texto legal parseados como nombres de personas
"""

import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES - Palabras y frases que NUNCA aparecen en nombres de personas
# ═══════════════════════════════════════════════════════════════════════════════

PALABRAS_PROHIBIDAS_EXACTAS = {
    # Legal / Notarial
    'certificados', 'provisionales', 'comparecientes', 'importe', 'acciones',
    'capital', 'sociedad', 'serie', 'escritura', 'notario', 'protocolo',
    'folio', 'mercantil', 'testimonio', 'clausula', 'articulo', 'estatutos',
    'asamblea', 'registro', 'domicilio', 'objeto', 'denominacion', 'duracion',
    'constitucion', 'constitutiva', 'accionista', 'accionistas',
    # Administrativo / Institucional
    'secretaria', 'economia', 'hacienda', 'tributaria', 'fiscal', 'federal',
    'nacional', 'publica', 'publico', 'gobierno', 'republica', 'mexicana',
    'mexicano', 'instituto', 'comision', 'direccion', 'general',
    # Números en texto (largos - indican montos, no nombres)
    'novecientos', 'ochocientos', 'setecientos', 'seiscientos', 'quinientos',
    'cuatrocientos', 'trescientos', 'doscientos', 'ciento', 'cien',
    'noventa', 'ochenta', 'setenta', 'sesenta', 'cincuenta', 'cuarenta', 'treinta',
    # Moneda / Valores
    'moneda', 'pesos', 'dolares', 'valor', 'nominal', 'importe', 'cantidad',
    'monto', 'total', 'suma', 'parcial',
    # Documentos
    'testimonio', 'copia', 'original', 'certificado', 'constancia',
    # Tipos de sociedad
    'anonima', 'responsabilidad', 'limitada', 'variable', 'civil',
    'mercantil', 'cooperativa', 'fideicomiso',
    # Verbos / Acciones legales
    'suscribe', 'aporta', 'exhibe', 'representa', 'declara', 'manifiesta',
    'comparece', 'otorga', 'constituye',
}

# Frases completas que indican que NO es un nombre
FRASES_PROHIBIDAS = [
    'certificados provisionales',
    'comparecientes que',
    'importe mencionado',
    'capital social',
    'sociedad anonima',
    'acciones nominativas',
    'acciones serie',
    'serie a',
    'serie b',
    'moneda nacional',
    'pesos mexicanos',
    'clausula primera',
    'articulo primero',
    'registro publico',
    'secretaria de economia',
    'secretaria de hacienda',
    'que amparen',
    'sus respectivas',
    'el importe',
    'la cantidad',
    'por un monto',
    'con valor',
    'valor nominal',
    'de capital',
    'en efectivo',
    'del capital',
    'los comparecientes',
    'las partes',
]


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE VALIDACIÓN DE NOMBRES
# ═══════════════════════════════════════════════════════════════════════════════

def normalizar_texto(texto: str) -> str:
    """
    Normaliza texto removiendo acentos y caracteres especiales.
    """
    if not texto:
        return ""
    
    reemplazos = {
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'Ñ': 'N', 'ñ': 'n', 'Ü': 'U', 'ü': 'u',
    }
    for acentuada, normal in reemplazos.items():
        texto = texto.replace(acentuada, normal)
    
    return texto


def es_nombre_persona_valido(nombre: str) -> bool:
    """
    Validación estricta de si un string es un nombre de persona válido.
    
    Aplica múltiples reglas para filtrar basura:
    1. Longitud y estructura mínima
    2. No contiene palabras prohibidas (legales, institucionales, números)
    3. No empieza con artículos sueltos
    4. No termina con preposiciones/artículos
    5. Al menos 2 palabras significativas (≥3 chars, no artículos)
    6. No tiene demasiados números
    
    Args:
        nombre: String a validar
        
    Returns:
        True si parece nombre de persona, False si es basura/frase legal
    """
    if not nombre or len(nombre) < 8:
        return False
    
    nombre_lower = normalizar_texto(nombre.lower().strip())
    nombre_norm = ' '.join(nombre_lower.split())
    palabras = nombre_norm.split()
    
    # Regla 1: Entre 2 y 6 palabras (nombres mexicanos típicos)
    if not (2 <= len(palabras) <= 6):
        return False
    
    # Regla 2: No contiene frases prohibidas completas
    for frase in FRASES_PROHIBIDAS:
        if frase in nombre_norm:
            return False
    
    # Regla 3: Ninguna palabra es prohibida
    for palabra in palabras:
        # Coincidencia exacta
        if palabra in PALABRAS_PROHIBIDAS_EXACTAS:
            return False
        # Para palabras largas, verificar coincidencia parcial
        if len(palabra) >= 7:
            for prohibida in PALABRAS_PROHIBIDAS_EXACTAS:
                if len(prohibida) >= 7 and (prohibida in palabra or palabra in prohibida):
                    return False
    
    # Regla 4: No empieza con artículos/preposiciones sueltas
    palabras_inicio_invalidas = {
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
        'del', 'al', 'que', 'quien', 'quienes', 'cual', 'cuales',
        'por', 'para', 'con', 'sin', 'sobre', 'bajo', 'ante',
        'y', 'o', 'ni', 'pero', 'sino', 'aunque', 'porque',
    }
    if palabras[0] in palabras_inicio_invalidas:
        return False
    
    # Regla 5: No termina con preposiciones/artículos/conjunciones
    palabras_fin_invalidas = {
        'de', 'del', 'en', 'a', 'al', 'la', 'el', 'los', 'las',
        'y', 'o', 'e', 'u', 'ni', 'por', 'para', 'con', 'sin',
        'que', 'quien', 'cual', 'sus', 'su', 'bis', 'etc',
    }
    if palabras[-1] in palabras_fin_invalidas:
        return False
    
    # Regla 6: Al menos 2 palabras "significativas" (≥3 chars y no artículos)
    palabras_funcion = {
        'de', 'del', 'la', 'el', 'los', 'las', 'y', 'en',
        'a', 'al', 'o', 'e', 'u', 'su', 'sus', 'por', 'con',
    }
    palabras_significativas = [
        p for p in palabras 
        if len(p) >= 3 and p not in palabras_funcion
    ]
    if len(palabras_significativas) < 2:
        return False
    
    # Regla 7: No tiene demasiados números (máximo 2 dígitos, ej: "Juan Carlos 2do")
    if len(re.findall(r'\d', nombre)) > 2:
        return False
    
    # Regla 8: Al menos una palabra parece nombre propio (empieza con mayúscula en original)
    # Esta regla es flexible porque el OCR puede distorsionar mayúsculas
    nombre_orig = nombre.strip()
    tiene_mayuscula = any(p[0].isupper() for p in nombre_orig.split() if p)
    if not tiene_mayuscula and not nombre_orig.isupper():
        # Si no está todo en mayúsculas y no tiene ninguna mayúscula inicial, sospechoso
        return False
    
    return True


def es_nombre_similar(nombre1: str, nombre2: str, umbral: float = 0.80) -> bool:
    """
    Verifica si dos nombres son similares usando múltiples criterios.
    
    Args:
        nombre1: Primer nombre
        nombre2: Segundo nombre
        umbral: Umbral de similitud (0.0 a 1.0)
        
    Returns:
        True si son similares, False si no
    """
    n1 = normalizar_texto(nombre1.upper().strip())
    n2 = normalizar_texto(nombre2.upper().strip())
    
    n1 = ' '.join(n1.split())
    n2 = ' '.join(n2.split())
    
    # Similitud exacta
    if n1 == n2:
        return True
    
    # Similitud fuzzy (SequenceMatcher)
    ratio = SequenceMatcher(None, n1, n2).ratio()
    if ratio >= umbral:
        return True
    
    # Similitud por palabras compartidas
    palabras1 = set(n1.split())
    palabras2 = set(n2.split())
    # Remover palabras muy cortas
    palabras1 = {p for p in palabras1 if len(p) > 2}
    palabras2 = {p for p in palabras2 if len(p) > 2}
    
    if palabras1 and palabras2:
        comunes = palabras1 & palabras2
        # Si comparten al menos 2 palabras significativas y una es subconjunto
        if len(comunes) >= 2:
            if palabras1.issubset(palabras2) or palabras2.issubset(palabras1):
                return True
            # O si comparten más del 60% de palabras
            max_palabras = max(len(palabras1), len(palabras2))
            if len(comunes) / max_palabras >= 0.6:
                return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE DEDUPLICACIÓN Y FILTRADO
# ═══════════════════════════════════════════════════════════════════════════════

def filtrar_entradas_basura(accionistas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filtra entradas que claramente no son accionistas válidos.
    
    Args:
        accionistas: Lista de diccionarios con datos de accionistas
        
    Returns:
        Lista filtrada sin entradas basura
    """
    if not accionistas:
        return []
    
    resultado = []
    for acc in accionistas:
        nombre = acc.get('nombre', '')
        if es_nombre_persona_valido(nombre):
            resultado.append(acc)
    
    return resultado


def deduplicar_accionistas(
    accionistas: List[Dict[str, Any]], 
    umbral: float = 0.80
) -> List[Dict[str, Any]]:
    """
    Deduplica lista de accionistas usando similitud fuzzy.
    Fusiona entradas duplicadas priorizando la que tiene más datos.
    
    Args:
        accionistas: Lista de diccionarios con datos de accionistas
        umbral: Umbral de similitud para considerar duplicados (0.0 a 1.0)
        
    Returns:
        Lista deduplicada con datos fusionados
    """
    if not accionistas:
        return []
    
    resultado = []
    indices_procesados = set()
    
    for i, acc1 in enumerate(accionistas):
        if i in indices_procesados:
            continue
        
        nombre1 = acc1.get('nombre', '')
        mejor_entrada = acc1.copy()
        indices_procesados.add(i)
        
        # Buscar duplicados en el resto de la lista
        for j, acc2 in enumerate(accionistas):
            if j <= i or j in indices_procesados:
                continue
            
            nombre2 = acc2.get('nombre', '')
            
            if es_nombre_similar(nombre1, nombre2, umbral):
                # Es duplicado - fusionar datos
                indices_procesados.add(j)
                
                # Determinar cuál tiene más datos
                tiene_datos_1 = (
                    mejor_entrada.get('acciones') is not None or 
                    mejor_entrada.get('porcentaje') is not None
                )
                tiene_datos_2 = (
                    acc2.get('acciones') is not None or 
                    acc2.get('porcentaje') is not None
                )
                
                if tiene_datos_2 and not tiene_datos_1:
                    # acc2 tiene datos y mejor_entrada no - reemplazar
                    mejor_entrada = acc2.copy()
                elif tiene_datos_1 and tiene_datos_2:
                    # Ambos tienen datos - fusionar campo por campo
                    if acc2.get('acciones') and not mejor_entrada.get('acciones'):
                        mejor_entrada['acciones'] = acc2['acciones']
                    if acc2.get('porcentaje') and not mejor_entrada.get('porcentaje'):
                        mejor_entrada['porcentaje'] = acc2['porcentaje']
                    if acc2.get('serie') and not mejor_entrada.get('serie'):
                        mejor_entrada['serie'] = acc2['serie']
                    # Tomar la mayor confiabilidad
                    conf1 = mejor_entrada.get('_confiabilidad', 0)
                    conf2 = acc2.get('_confiabilidad', 0)
                    mejor_entrada['_confiabilidad'] = max(conf1, conf2)
                
                # Usar el nombre más largo (más completo)
                if len(acc2.get('nombre', '')) > len(mejor_entrada.get('nombre', '')):
                    mejor_entrada['nombre'] = acc2['nombre']
                
                # Marcar como fusionado
                mejor_entrada['_fusionado'] = True
        
        resultado.append(mejor_entrada)
    
    return resultado


def limpiar_y_deduplicar(
    accionistas: List[Dict[str, Any]], 
    umbral_similitud: float = 0.80
) -> List[Dict[str, Any]]:
    """
    Pipeline completo de limpieza: filtra basura y deduplica.
    
    Args:
        accionistas: Lista de diccionarios con datos de accionistas
        umbral_similitud: Umbral para deduplicación fuzzy
        
    Returns:
        Lista limpia y deduplicada
    """
    # Paso 1: Filtrar basura
    filtrados = filtrar_entradas_basura(accionistas)
    
    # Paso 2: Deduplicar
    deduplicados = deduplicar_accionistas(filtrados, umbral_similitud)
    
    return deduplicados


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CÁLCULO DE CONFIABILIDAD
# ═══════════════════════════════════════════════════════════════════════════════

def calcular_confiabilidad_estructura(
    accionistas: List[Dict[str, Any]],
    total_acciones: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calcula score de confiabilidad basado en completitud y consistencia de datos.
    
    Escala de confiabilidad:
    - 95-100%: Todos los accionistas con datos, sumas correctas
    - 70-94%: Todos con datos pero sumas no cuadran
    - 40-69%: Algunos con datos, otros sin
    - 20-39%: Solo nombres, sin datos numéricos
    - 0-19%: Sin datos o todos basura
    
    Args:
        accionistas: Lista de accionistas extraídos
        total_acciones: Total de acciones declarado (opcional)
        
    Returns:
        Diccionario con score, nivel, y métricas de validación
    """
    if not accionistas:
        return {
            'score': 0,
            'nivel': 'sin_datos',
            'requiere_revision': True,
            'mensaje': 'No se encontraron accionistas',
        }
    
    total = len(accionistas)
    con_acciones = sum(1 for a in accionistas if a.get('acciones') is not None)
    con_porcentaje = sum(1 for a in accionistas if a.get('porcentaje') is not None)
    con_algun_dato = sum(
        1 for a in accionistas 
        if a.get('acciones') is not None or a.get('porcentaje') is not None
    )
    
    # Calcular sumas
    suma_acciones = sum(a.get('acciones', 0) or 0 for a in accionistas)
    suma_porcentaje = sum(a.get('porcentaje', 0) or 0 for a in accionistas)
    
    # Validar sumas
    acciones_validas = False
    if total_acciones and total_acciones > 0:
        acciones_validas = suma_acciones == total_acciones
    elif suma_acciones > 0:
        # Si no hay total declarado, asumir que la suma es el total
        acciones_validas = True
    
    porcentaje_valido = False
    if con_porcentaje == total and total > 0:
        # Solo validar si TODOS tienen porcentaje
        porcentaje_valido = abs(suma_porcentaje - 100) <= 1.5  # Tolerancia de 1.5%
    
    # Calcular score base
    if con_algun_dato == total and total > 0:
        # Todos tienen algún dato
        if acciones_validas or porcentaje_valido:
            score = 95
            nivel = 'alta'
        else:
            score = 75
            nivel = 'media'
    elif con_algun_dato > 0:
        # Algunos tienen datos
        ratio = con_algun_dato / total
        score = int(40 + (ratio * 30))  # 40-70
        nivel = 'parcial'
    else:
        # Solo nombres, sin datos
        score = 25
        nivel = 'solo_nombres'
    
    # Penalizaciones
    if suma_porcentaje > 0 and abs(suma_porcentaje - 100) > 5:
        score -= 10  # Penalización por suma incorrecta
    
    if total_acciones and suma_acciones > 0 and suma_acciones != total_acciones:
        score -= 10  # Penalización por acciones no cuadran
    
    # Ajustar score a rango válido
    score = max(0, min(100, score))
    
    # Determinar si requiere revisión
    requiere_revision = score < 70 or not (acciones_validas or porcentaje_valido)
    
    return {
        'score': score,
        'nivel': nivel,
        'requiere_revision': requiere_revision,
        'total_accionistas': total,
        'con_acciones': con_acciones,
        'con_porcentaje': con_porcentaje,
        'suma_acciones': suma_acciones,
        'suma_porcentaje': round(suma_porcentaje, 2),
        'acciones_validas': acciones_validas,
        'porcentaje_valido': porcentaje_valido,
        'total_acciones_esperado': total_acciones,
    }


def generar_alertas_estructura(
    accionistas: List[Dict[str, Any]],
    metricas: Dict[str, Any]
) -> List[str]:
    """
    Genera lista de alertas/advertencias basadas en las métricas.
    
    Args:
        accionistas: Lista de accionistas
        metricas: Resultado de calcular_confiabilidad_estructura
        
    Returns:
        Lista de strings con alertas
    """
    alertas = []
    
    # Alerta por suma de porcentajes
    if metricas.get('con_porcentaje', 0) > 0:
        suma = metricas.get('suma_porcentaje', 0)
        if abs(suma - 100) > 1.5:
            alertas.append(
                f"Suma de porcentajes: {suma}% (debería ser 100%)"
            )
    
    # Alerta por suma de acciones
    total_esperado = metricas.get('total_acciones_esperado')
    suma_acc = metricas.get('suma_acciones', 0)
    if total_esperado and suma_acc > 0 and suma_acc != total_esperado:
        alertas.append(
            f"Suma de acciones ({suma_acc}) no coincide con total declarado ({total_esperado})"
        )
    
    # Alerta por accionistas sin datos
    total = metricas.get('total_accionistas', 0)
    con_datos = metricas.get('con_acciones', 0)
    sin_datos = total - con_datos
    if sin_datos > 0:
        alertas.append(
            f"{sin_datos} accionista(s) sin datos de acciones/porcentaje"
        )
    
    # Alerta por personas morales con >25%
    for acc in accionistas:
        if acc.get('tipo') == 'moral':
            pct = acc.get('porcentaje', 0) or 0
            if pct > 25:
                alertas.append(
                    f"Persona moral '{acc.get('nombre')}' con {pct}% (>25%) - requiere perforación"
                )
    
    return alertas
