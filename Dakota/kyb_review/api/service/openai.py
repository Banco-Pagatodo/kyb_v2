import json
import logging

import re
from textwrap import dedent

from langchain_openai import AzureChatOpenAI
from langchain_openai import AzureOpenAIEmbeddings

from os import getenv
from dotenv import load_dotenv

from .resilience import (
    get_circuit_breaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    retry_with_backoff,
    OpenAIRetryConfig,
    parse_json_safe
)

# Validadores especializados para estructura accionaria
from .accionistas_validators.accionistas_validator import (
    es_nombre_persona_valido,
    limpiar_y_deduplicar,
    filtrar_entradas_basura,
    deduplicar_accionistas,
    calcular_confiabilidad_estructura,
    generar_alertas_estructura,
)

# Validador de RFC según especificación PLD
from .accionistas_validators.rfc_validator import (
    validar_rfc,
    normalizar_rfc,
    detectar_tipo_persona,
    validar_rfcs_estructura,
    generar_alertas_rfc,
)

# Alertas estructurales PLD
from .accionistas_validators.alertas_estructura import (
    generar_todas_alertas,
    alertas_a_lista_strings,
    detectar_requiere_perforacion,
    UMBRAL_PROPIETARIO_REAL,
)

import unicodedata as _unicodedata

def _strip_accents(s: str) -> str:
    """Normaliza un string removiendo acentos para comparación insensible a diacríticos."""
    if not s:
        return ""
    s = _unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not _unicodedata.combining(c))

logger = logging.getLogger(__name__)

# Circuit breaker para Azure OpenAI
_openai_cb_config = CircuitBreakerConfig(
    failure_threshold=5,      # 5 fallos consecutivos
    success_threshold=2,      # 2 éxitos para recuperar
    timeout_seconds=60.0      # 1 minuto en estado OPEN
)
openai_circuit_breaker = get_circuit_breaker("azure_openai", _openai_cb_config)

# Load environment variables - usar ruta absoluta basada en __file__
from pathlib import Path
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path)


def invoke_llm_safe(llm: AzureChatOpenAI, prompt: str, operation_name: str = "LLM call") -> str:
    """
    Invoca el LLM con retry y circuit breaker.
    
    Args:
        llm: Instancia de AzureChatOpenAI
        prompt: Prompt a enviar
        operation_name: Nombre para logging
    
    Returns:
        Respuesta del LLM como string
    
    Raises:
        CircuitBreakerOpen: Si el servicio no está disponible
        Exception: Si todos los reintentos fallan
    """
    if not openai_circuit_breaker.can_execute():
        logger.error(f"OpenAI circuit breaker OPEN - skipping {operation_name}")
        raise CircuitBreakerOpen("azure_openai")
    
    def do_invoke():
        response = llm.invoke(prompt)
        return response.content.strip() if response and response.content else ""
    
    try:
        result = retry_with_backoff(
            do_invoke,
            config=OpenAIRetryConfig(),
            circuit_breaker=openai_circuit_breaker,
            operation_name=operation_name
        )
        return result
    except CircuitBreakerOpen:
        raise
    except Exception as e:
        logger.error(f"{operation_name} failed: {type(e).__name__}: {e}")
        raise


def parse_llm_json_response(response: str, fallback: dict = None) -> dict:
    """
    Parsea la respuesta JSON del LLM de forma segura.
    
    Args:
        response: Respuesta del LLM
        fallback: Valor por defecto si falla el parsing
    
    Returns:
        Dict parseado
    """
    return parse_json_safe(response, fallback or {})


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES HELPER DE VALIDACIÓN Y MEJORA
# ═══════════════════════════════════════════════════════════════════════════════

def _fix_campos_no_encontrados_generic(data: dict, campos_a_verificar: list) -> dict:
    """
    Corrige inconsistencias en campos_no_encontrados para cualquier tipo de documento.
    Si un campo tiene "Pendiente", "N/A" o está vacío, debe estar en la lista.
    """
    result = data.copy()
    
    if "campos_no_encontrados" not in result:
        result["campos_no_encontrados"] = []
    
    for campo in campos_a_verificar:
        valor = str(result.get(campo, "")).lower().strip()
        
        es_pendiente_o_vacio = (
            not valor or
            valor in ["", "n/a", "null", "none"] or
            "pendiente" in valor or
            "no encontrado" in valor or
            "no disponible" in valor
        )
        
        if es_pendiente_o_vacio:
            if campo not in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].append(campo)
        else:
            if campo in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].remove(campo)
    
    return result


def _find_page_and_paragraph(text_ocr: str, valor: str, pos: int) -> dict:
    """
    Encuentra la página y el párrafo donde se ubicó el valor.
    El texto tiene marcadores [[[PÁGINA:N]]] que delimitan las páginas.
    
    Args:
        text_ocr: Texto OCR completo con marcadores de página
        valor: El valor encontrado
        pos: Posición donde se encontró el valor
    
    Returns:
        dict con página y párrafo
    """
    # Encontrar la página basándose en los marcadores [[[PÁGINA:N]]]
    pagina = 1
    pagina_matches = list(re.finditer(r'\[\[\[PÁGINA:(\d+)\]\]\]', text_ocr))
    
    for match in pagina_matches:
        if match.start() <= pos:
            pagina = int(match.group(1))
        else:
            break
    
    # Extraer el párrafo/línea donde está el valor
    # Buscar desde el inicio de la línea hasta el fin de la línea
    inicio_linea = text_ocr.rfind('\n', 0, pos)
    if inicio_linea == -1:
        inicio_linea = 0
    else:
        inicio_linea += 1  # Saltar el \n
    
    fin_linea = text_ocr.find('\n', pos)
    if fin_linea == -1:
        fin_linea = len(text_ocr)
    
    # Extraer la línea y limpiarla
    linea = text_ocr[inicio_linea:fin_linea].strip()
    
    # Si la línea es muy corta, expandir el contexto
    if len(linea) < 20:
        # Tomar un contexto más amplio
        inicio = max(0, pos - 80)
        fin = min(len(text_ocr), pos + len(valor) + 80)
        linea = text_ocr[inicio:fin].strip()
    
    # Limpiar y normalizar el párrafo
    linea = re.sub(r'\[\[\[PÁGINA:\d+\]\]\]', '', linea)  # Remover marcadores de página
    linea = re.sub(r'\s+', ' ', linea).strip()  # Normalizar espacios
    linea = linea[:200]  # Limitar longitud
    
    return {
        "pagina": pagina,
        "parrafo": linea if linea else None
    }


def _buscar_valor_en_texto(valor: str, text_ocr: str, campo: str = "") -> int:
    """
    Busca un valor en el texto OCR usando múltiples estrategias.
    Retorna la posición donde se encontró, o -1 si no se encontró.
    
    Estrategias (en orden de prioridad):
    1. Búsqueda específica por tipo de campo (PRIMERO para campos conocidos)
    2. Búsqueda exacta (case insensitive)
    3. Búsqueda de números sin formato (27883 vs 27,883)
    4. Búsqueda de números escritos en palabras
    5. Búsqueda de fechas en diferentes formatos
    6. Búsqueda de nombres/apellidos individuales
    """
    valor_str = str(valor).strip()
    text_lower = text_ocr.lower()
    valor_lower = valor_str.lower()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 0. BÚSQUEDA ESPECÍFICA POR CAMPO - TIENE PRIORIDAD
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CAMPOS DE ESTADO DE CUENTA BANCARIO
    # ─────────────────────────────────────────────────────────────────────────────
    
    # Para periodo del estado de cuenta (puede venir como "01/08/2025 - 31/08/2025")
    if campo == "periodo":
        # Diccionario de meses abreviados y completos
        meses_map = {
            '01': r'ene(?:ro)?', '02': r'feb(?:rero)?', '03': r'mar(?:zo)?',
            '04': r'abr(?:il)?', '05': r'may(?:o)?', '06': r'jun(?:io)?',
            '07': r'jul(?:io)?', '08': r'ago(?:sto)?', '09': r'sep(?:tiembre)?',
            '10': r'oct(?:ubre)?', '11': r'nov(?:iembre)?', '12': r'dic(?:iembre)?'
        }
        # Extraer fechas del periodo
        periodo_match = re.match(r'(\d{1,2})/(\d{2})/(\d{4})\s*[-–]\s*(\d{1,2})/(\d{2})/(\d{4})', valor_str)
        if periodo_match:
            dia1, mes1, anio1, dia2, mes2, anio2 = periodo_match.groups()
            # Buscar variaciones: "Del 1-AGO-25 al 31-AGO-25" o "PERIODO: 01/AGO/2025 - 31/AGO/2025"
            mes1_patron = meses_map.get(mes1, mes1)
            mes2_patron = meses_map.get(mes2, mes2)
            anio1_short = anio1[-2:]
            anio2_short = anio2[-2:]
            
            patrones_periodo = [
                rf'(?:del|periodo)[:\s]*{int(dia1)}[-/]{mes1_patron}[-/](?:{anio1}|{anio1_short})',
                rf'(?:del|periodo)[:\s]*{int(dia1)}.*?{mes1_patron}.*?(?:{anio1}|{anio1_short})',
                rf'{int(dia1)}[-/]{mes1_patron}[-/](?:{anio1}|{anio1_short}).*?{int(dia2)}[-/]{mes2_patron}',
                rf'periodo.*?{mes1_patron}.*?{anio1}',
            ]
            for patron in patrones_periodo:
                match = re.search(patron, text_lower, re.IGNORECASE)
                if match:
                    return match.start()
    
    # Para saldos y montos (saldo_inicial, saldo_final, total_depositos, total_retiros)
    if campo in ["saldo_inicial", "saldo_final", "total_depositos", "total_retiros"]:
        # Limpiar el valor: "160000.00" -> 160000.00
        try:
            monto = float(valor_str.replace(",", ""))
            # Crear variaciones del formato del monto
            monto_int = int(monto)
            monto_str_sin_decimales = str(monto_int)
            monto_str_con_comas = f"{monto_int:,}".replace(",", "[,.]?")
            monto_str_decimal = f"{monto:.2f}".replace(".", r"[.,]")
            
            # Buscar contexto según el campo
            contexto_map = {
                "saldo_inicial": r'saldo\s+inicial|saldo\s+anterior|saldo\s+al\s+inicio',
                "saldo_final": r'saldo\s+final|saldo\s+al\s+cierre|saldo\s+actual',
                "total_depositos": r'(?:total\s+)?dep[oó]sitos|abonos|entradas',
                "total_retiros": r'(?:total\s+)?retiros|cargos|salidas'
            }
            contexto = contexto_map.get(campo, campo.replace("_", r"\s*"))
            
            # Buscar monto cerca del contexto
            patrones_monto = [
                rf'{contexto}[:\s$]*[\$]?\s*{monto_str_con_comas}',
                rf'{monto_str_con_comas}[.\d]*\s*.*?{contexto}',
                rf'\b{monto_str_sin_decimales}[.,]\d{{2}}\b',
                rf'\$?\s*{monto_str_con_comas}[.,]?\d*',
            ]
            for patron in patrones_monto:
                match = re.search(patron, text_lower, re.IGNORECASE)
                if match:
                    return match.start()
        except ValueError:
            pass
    
    # Para numero_escritura_poliza, buscar específicamente cerca de "ESCRITURA"
    if campo == "numero_escritura_poliza" and valor_str.isdigit():
        # Buscar patrón "ESCRITURA (PÚBLICA) NÚMERO X" o "INSTRUMENTO NÚMERO X"
        patrones_escritura = [
            rf'escritura\s+(?:p[úu]blica\s+)?n[úu]mero\s*[^\d]*{valor_str}\b',
            rf'instrumento\s+(?:n[úu]mero|no\.?)\s*[^\d]*{valor_str}\b',
            rf'p[óo]liza\s+(?:n[úu]mero|no\.?)\s*[^\d]*{valor_str}\b',
            rf'instrumento\s+no\.?\s*{valor_str}\b',
        ]
        for patron in patrones_escritura:
            match = re.search(patron, text_lower, re.IGNORECASE)
            if match:
                return match.start()
    
    # Para numero_notaria, buscar específicamente en página 1 el patrón de notaría
    if campo == "numero_notaria" and valor_str.isdigit():
        # Encontrar la primera página
        pagina2_pos = text_lower.find('[[[página:2]]]')
        if pagina2_pos == -1:
            pagina2_pos = len(text_lower)
        texto_p1 = text_lower[:pagina2_pos]
        
        # Diccionario de números en palabras (1-20)
        numeros_palabras = {
            '1': 'uno|una|primer[ao]?', '2': 'dos|segund[ao]', '3': 'tres|tercer[ao]?',
            '4': 'cuatro|cuart[ao]', '5': 'cinco|quint[ao]', '6': 'seis|sext[ao]',
            '7': 'siete|s[eé]ptim[ao]', '8': 'ocho|octav[ao]', '9': 'nueve|noven[ao]',
            '10': 'diez|d[eé]cim[ao]', '11': 'once|und[eé]cim[ao]', '12': 'doce|duod[eé]cim[ao]',
            '13': 'trece', '14': 'catorce', '15': 'quince',
            '16': 'diecis[eé]is', '17': 'diecisiete', '18': 'dieciocho',
            '19': 'diecinueve', '20': 'veinte'
        }
        
        num_palabra = numeros_palabras.get(valor_str, valor_str)
        
        # Primero buscar "titular de la notaría" que es más específico
        patron_titular = rf'titular\s+de\s+la\s+notar[íi]a\s+p[úu]blica\s+n[úu]mero\s*(?:{valor_str}|{num_palabra})\b'
        match = re.search(patron_titular, texto_p1, re.IGNORECASE)
        if match:
            return match.start()
        
        # Luego buscar "notaría pública número X"
        patron_notaria = rf'notar[íi]a\s+(?:p[úu]blica\s+)?(?:n[úu]mero|no\.?)\s*(?:\(?\s*)?(?:{valor_str}|{num_palabra})\b'
        match = re.search(patron_notaria, texto_p1, re.IGNORECASE)
        if match:
            return match.start()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. BÚSQUEDA EXACTA
    # ═══════════════════════════════════════════════════════════════════════════
    pos = text_lower.find(valor_lower)
    if pos >= 0:
        return pos
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. PARA NÚMEROS - buscar sin formato y con formato
    # ═══════════════════════════════════════════════════════════════════════════
    if valor_str.isdigit():
        # Buscar el número con posibles separadores (27883 vs 27,883)
        patron_numero = r'\b' + re.escape(valor_str[0])
        for char in valor_str[1:]:
            patron_numero += r'[,.\s]?' + re.escape(char)
        patron_numero += r'\b'
        match = re.search(patron_numero, text_lower)
        if match:
            return match.start()
        
        # 2.1. Buscar número escrito en palabras - MEJORADO
        # Para escrituras y notarías, el número suele estar en palabras
        numero = int(valor_str)
        palabras_clave = _numero_a_palabras_busqueda(numero)
        
        # Buscar patrón "ESCRITURA NUMERO" + palabras del número para escrituras
        if campo == "numero_escritura_poliza":
            # Primero buscar contexto de escritura
            escritura_pos = re.search(r'escritura\s+(?:p[úu]blica\s+)?n[úu]mero', text_lower)
            if escritura_pos:
                # Buscar el número en palabras cerca de ahí
                contexto_fin = min(len(text_lower), escritura_pos.end() + 200)
                contexto = text_lower[escritura_pos.start():contexto_fin]
                for palabra in palabras_clave:
                    if palabra.lower() in contexto:
                        return escritura_pos.start()
        
        # Buscar palabras clave genéricas del número
        for palabra_clave in palabras_clave:
            pos = text_lower.find(palabra_clave.lower())
            if pos >= 0:
                return pos
    
    # 3. Para fechas dd/mm/aaaa, buscar variaciones
    fecha_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', valor_str)
    if fecha_match:
        dia, mes, anio = fecha_match.groups()
        meses_nombres = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 
                 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        mes_idx = int(mes) - 1
        
        # Diccionario de días en palabras
        dias_palabras = {
            '1': 'primer[o]?|uno|un', '2': 'dos|segundo', '3': 'tres|tercer[o]?',
            '4': 'cuatro', '5': 'cinco', '6': 'seis', '7': 'siete',
            '8': 'ocho', '9': 'nueve', '10': 'diez', '11': 'once',
            '12': 'doce', '13': 'trece', '14': 'catorce', '15': 'quince',
            '16': 'diecis[eé]is', '17': 'diecisiete', '18': 'dieciocho',
            '19': 'diecinueve', '20': 'veinte', '21': 'veintiuno|veinti[uú]n',
            '22': 'veintid[oó]s', '23': 'veintitr[eé]s', '24': 'veinticuatro',
            '25': 'veinticinco', '26': 'veintis[eé]is', '27': 'veintisiete',
            '28': 'veintiocho', '29': 'veintinueve', '30': 'treinta',
            '31': 'treinta y uno|treinta y un'
        }
        dia_palabra = dias_palabras.get(dia.lstrip('0'), dia)
        
        # Diccionario de años en palabras (2000-2030)
        anios_palabras = {
            '2000': 'dos mil', '2001': 'dos mil uno', '2002': 'dos mil dos',
            '2003': 'dos mil tres', '2004': 'dos mil cuatro', '2005': 'dos mil cinco',
            '2006': 'dos mil seis', '2007': 'dos mil siete', '2008': 'dos mil ocho',
            '2009': 'dos mil nueve', '2010': 'dos mil diez', '2011': 'dos mil once',
            '2012': 'dos mil doce', '2013': 'dos mil trece', '2014': 'dos mil catorce',
            '2015': 'dos mil quince', '2016': 'dos mil diecis[eé]is',
            '2017': 'dos mil diecisiete', '2018': 'dos mil dieciocho',
            '2019': 'dos mil diecinueve', '2020': 'dos mil veinte',
            '2021': 'dos mil veintiuno', '2022': 'dos mil veintid[oó]s',
            '2023': 'dos mil veintitr[eé]s', '2024': 'dos mil veinticuatro',
            '2025': 'dos mil veinticinco', '2026': 'dos mil veintis[eé]is',
            '2027': 'dos mil veintisiete', '2028': 'dos mil veintiocho',
            '2029': 'dos mil veintinueve', '2030': 'dos mil treinta'
        }
        anio_palabra = anios_palabras.get(anio, anio)
        
        # Para fecha_constitucion, buscar en TODO el documento, no solo página 1
        texto_busqueda = text_lower
        
        # Buscar patrón "X días del mes de MES" o "los X días del... MES"
        if 0 <= mes_idx < 12:
            # Patrón principal: "trece días del mes de abril del año dos mil once"
            patron_fecha = rf'(?:\(?{int(dia)}\)?|{dia_palabra})\s*d[íi]as?\s+del\s+mes\s+de\s+{meses_nombres[mes_idx]}.*?(?:{anio}|{anio_palabra})'
            match = re.search(patron_fecha, texto_busqueda, re.DOTALL | re.IGNORECASE)
            if match:
                return match.start()
            
            # Patrón simplificado: "trece días del... abril"
            patron_fecha_simple = rf'(?:\(?{int(dia)}\)?|{dia_palabra})\s*d[íi]as?\s+del.*?{meses_nombres[mes_idx]}'
            match = re.search(patron_fecha_simple, texto_busqueda, re.DOTALL | re.IGNORECASE)
            if match:
                return match.start()
            
            # Buscar "X de MES de YYYY" (con número o palabra)
            patron_fecha2 = rf'(?:\(?{int(dia)}\)?|{dia_palabra})\s+de\s+{meses_nombres[mes_idx]}\s+de[l]?\s+(?:a[ñn]o\s+)?(?:{anio}|{anio_palabra})'
            match = re.search(patron_fecha2, texto_busqueda, re.IGNORECASE)
            if match:
                return match.start()
            
            # Buscar solo "mes... año" (más flexible)
            patron_mes_anio = rf'{meses_nombres[mes_idx]}.*?(?:{anio}|{anio_palabra})'
            match = re.search(patron_mes_anio, texto_busqueda, re.DOTALL | re.IGNORECASE)
            if match:
                return match.start()
        
        # Buscar el año con contexto de mes
        pos_anio = texto_busqueda.find(anio)
        if pos_anio >= 0:
            contexto_inicio = max(0, pos_anio - 100)
            contexto = texto_busqueda[contexto_inicio:pos_anio + 50]
            if 0 <= mes_idx < 12 and meses_nombres[mes_idx] in contexto:
                return pos_anio
    
    # 4. Para nombres completos, buscar apellidos o primeras palabras
    palabras = valor_str.split()
    if len(palabras) >= 2:
        for palabra in palabras:
            if len(palabra) > 3:
                pos = text_lower.find(palabra.lower())
                if pos >= 0:
                    return pos
    
    # 5. Búsqueda específica por tipo de campo
    if campo == "clausula_extranjeros":
        if "exclus" in valor_lower:
            patrones = [
                r'exclusi[oó]n.*extranjero',
                r'no\s+admitir[áa]n.*extranjero',
                r'cláusula.*exclusi[oó]n',
                r'cláusula.*extranjer[ií]a',
                r'ninguna persona extranjera',
                r'persona extranjera.*no podr[áa]',
                r'extranjera.*podr[áa] tener participaci[oó]n',
                r'sociedad es mexicana',
                r'capital.*nacional',
                r'no admitir[áa]n.*como socios.*extranjero'
            ]
        else:
            patrones = [
                r'admisi[oó]n.*extranjero',
                r'podr[áa]n.*participar.*extranjero',
                r'permitir.*extranjero',
                r'extranjeros.*podr[áa]n'
            ]
        
        for patron in patrones:
            match = re.search(patron, text_lower)
            if match:
                return match.start()
    
    if campo == "folio_mercantil":
        # Buscar "FOLIO MERCANTIL" cerca del valor
        patrones = [
            rf'folio\s+mercantil\s+electr[óo]nico[^\d]*{re.escape(valor_str)}',
            rf'folio\s+mercantil[^\d\n]*\n?\s*{re.escape(valor_str)}',
            rf'{re.escape(valor_str)}.*?folio',
        ]
        for patron in patrones:
            match = re.search(patron, text_lower)
            if match:
                return match.start()
    
    # 6. Búsqueda parcial (primeros N caracteres)
    if len(valor_str) > 5:
        pos = text_lower.find(valor_lower[:10])
        if pos >= 0:
            return pos
    
    return -1


def _numero_a_palabras_busqueda(numero: int) -> list:
    """
    Genera palabras clave para buscar un número escrito en texto.
    Retorna lista de términos de búsqueda que podrían aparecer.
    Para números de escrituras notariales mexicanas.
    
    Ej: 57542 -> ["cincuenta y siete mil", "quinientos cuarenta y dos", "cincuenta", "siete mil"]
    """
    palabras = []
    
    # Diccionarios para conversión
    unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve']
    decenas = ['', 'diez', 'veinte', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa']
    especiales = {
        11: 'once', 12: 'doce', 13: 'trece', 14: 'catorce', 15: 'quince',
        16: 'dieciseis', 17: 'diecisiete', 18: 'dieciocho', 19: 'diecinueve',
        21: 'veintiuno', 22: 'veintidos', 23: 'veintitres', 24: 'veinticuatro',
        25: 'veinticinco', 26: 'veintiseis', 27: 'veintisiete', 28: 'veintiocho', 29: 'veintinueve'
    }
    centenas = ['', 'cien', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos',
                'seiscientos', 'setecientos', 'ochocientos', 'novecientos']
    
    # Extraer partes del número
    if numero >= 100000:
        # Número muy grande (>= 100,000), no convertir a palabras
        # Solo devolver el número como string y "mil"
        palabras.append(str(numero))
        palabras.append("mil")
        return palabras
    
    if numero >= 10000:
        decenas_miles = numero // 10000
        miles = (numero % 10000) // 1000
        centenas_val = (numero % 1000) // 100
        decenas_val = (numero % 100) // 10
        unidades_val = numero % 10
        
        # Generar palabras clave principales
        if decenas_miles > 0:
            palabras.append(decenas[decenas_miles])  # "cincuenta"
        if miles > 0:
            palabras.append(unidades[miles])  # "siete"
        palabras.append("mil")  # siempre para números > 1000
        
        # Centenas
        if centenas_val > 0:
            palabras.append(centenas[centenas_val])  # "quinientos"
        
        # Decenas y unidades
        resto = numero % 100
        if resto in especiales:
            palabras.append(especiales[resto])
        else:
            if decenas_val > 0:
                palabras.append(decenas[decenas_val])  # "cuarenta"
            if unidades_val > 0:
                palabras.append(unidades[unidades_val])  # "dos"
        
        # Combinación parcial distintiva (ej: "siete mil quinientos")
        if decenas_miles > 0 and miles > 0:
            palabras.append(f"{decenas[decenas_miles]} y {unidades[miles]} mil")
        elif decenas_miles > 0:
            palabras.append(f"{decenas[decenas_miles]} mil")
        elif miles > 0:
            palabras.append(f"{unidades[miles]} mil")
    
    elif numero >= 1000:
        miles = numero // 1000
        centenas_val = (numero % 1000) // 100
        resto = numero % 100
        
        if miles > 1:
            palabras.append(unidades[miles])
        palabras.append("mil")
        
        if centenas_val > 0:
            palabras.append(centenas[centenas_val])
        
        if resto in especiales:
            palabras.append(especiales[resto])
        else:
            decenas_val = resto // 10
            unidades_val = resto % 10
            if decenas_val > 0:
                palabras.append(decenas[decenas_val])
            if unidades_val > 0:
                palabras.append(unidades[unidades_val])
    
    elif numero >= 100:
        centenas_val = numero // 100
        resto = numero % 100
        palabras.append(centenas[centenas_val])
        
        if resto in especiales:
            palabras.append(especiales[resto])
        else:
            decenas_val = resto // 10
            unidades_val = resto % 10
            if decenas_val > 0:
                palabras.append(decenas[decenas_val])
            if unidades_val > 0:
                palabras.append(unidades[unidades_val])
    
    else:
        if numero in especiales:
            palabras.append(especiales[numero])
        else:
            decenas_val = numero // 10
            unidades_val = numero % 10
            if decenas_val > 0:
                palabras.append(decenas[decenas_val])
            if unidades_val > 0:
                palabras.append(unidades[unidades_val])
    
    # Filtrar palabras vacías
    palabras = [p for p in palabras if p]
    
    return palabras


def _add_extraction_evidence_generic(data: dict, text_ocr: str, campos_a_buscar: list) -> dict:
    """
    Agrega evidencia de dónde se extrajo cada campo (genérico para todos los documentos).
    Incluye página y párrafo donde se encontró cada campo.
    También calcula un score de confiabilidad por campo basado en la evidencia.
    """
    result = data.copy()
    evidencia = {}
    confiabilidad_campos = {}
    
    for campo in campos_a_buscar:
        valor = result.get(campo)
        if not valor or "pendiente" in str(valor).lower() or str(valor).upper() == "N/A":
            evidencia[campo] = {
                "encontrado": False,
                "pagina": None,
                "parrafo": None
            }
            confiabilidad_campos[campo] = 0.0
            continue
        
        # Buscar el valor en el texto usando múltiples estrategias
        valor_str = str(valor)
        pos = _buscar_valor_en_texto(valor_str, text_ocr, campo)
        
        if pos >= 0:
            # Encontrar página y párrafo
            ubicacion = _find_page_and_paragraph(text_ocr, valor_str, pos)
            evidencia[campo] = {
                "encontrado": True,
                "pagina": ubicacion["pagina"],
                "parrafo": ubicacion["parrafo"]
            }
            # Alta confianza: el valor fue encontrado literalmente en el texto
            confiabilidad_campos[campo] = 1.0
        else:
            # Intentar encontrar contexto aproximado basado en palabras clave del campo
            parrafo_aproximado, pagina_aproximada = _buscar_contexto_aproximado(campo, valor_str, text_ocr)
            evidencia[campo] = {
                "encontrado": False,
                "pagina": pagina_aproximada,
                "parrafo": parrafo_aproximado,
                "nota": "Valor extraído por LLM, contexto aproximado"
            }
            # Confianza media: el LLM extrajo algo pero no se encontró literalmente
            # (podría ser normalizado, corregido, etc.)
            confiabilidad_campos[campo] = 0.7 if parrafo_aproximado else 0.5
    
    result["_evidencia_extraccion"] = evidencia
    result["_confiabilidad_campos"] = confiabilidad_campos
    
    # Calcular confiabilidad promedio
    if confiabilidad_campos:
        result["_confiabilidad_promedio"] = round(
            sum(confiabilidad_campos.values()) / len(confiabilidad_campos), 2
        )
    
    return result


def _buscar_contexto_aproximado(campo: str, valor: str, text_ocr: str) -> tuple:
    """
    Busca un contexto aproximado para un campo cuando el valor exacto no se encuentra.
    Utiliza palabras clave asociadas al campo para localizar la sección relevante.
    
    Returns:
        tuple: (parrafo_aproximado, pagina_aproximada)
    """
    # Mapeo de campos a palabras clave de búsqueda
    palabras_clave = {
        # Campos de dirección/domicilio
        "calle": ["calle", "avenida", "av.", "blvd", "boulevard", "calzada", "circuito"],
        "numero_exterior": ["no.", "num.", "número", "ext.", "exterior", "#"],
        "numero_interior": ["int.", "interior", "depto", "departamento", "piso", "local"],
        "colonia": ["colonia", "col.", "fracc", "fraccionamiento"],
        "codigo_postal": ["c.p.", "cp", "código postal", "codigo postal"],
        "alcaldia": ["alcaldía", "alcaldia", "delegación", "delegacion", "municipio"],
        "ciudad": ["ciudad", "localidad", "población", "poblacion"],
        "entidad_federativa": ["estado", "entidad"],
        "estado": ["estado", "edo.", "entidad federativa"],
        # Campos de documentos notariales
        "numero_escritura": ["escritura", "instrumento", "número", "volumen"],
        "fecha_otorgamiento": ["otorgamiento", "otorgada", "otorgado"],
        "fecha_expedicion": ["expedición", "expedicion", "fecha"],
        "nombre_notario": ["notario", "lic.", "licenciado", "titular"],
        "numero_notaria": ["notaría", "notaria", "número"],
        "estado_notaria": ["estado", "entidad"],
        "folio_mercantil": ["folio", "mercantil", "registro", "comercio"],
        # Campos de empresa
        "rfc": ["rfc", "registro federal"],
        "razon_social": ["razón social", "razon social", "denominación", "denominacion"],
        "giro_mercantil": ["giro", "actividad", "objeto social"],
        # Campos bancarios
        "banco": ["banco", "institución", "bancaria"],
        "clabe": ["clabe", "interbancaria"],
        "numero_cuenta": ["cuenta", "número de cuenta"],
        "titular": ["titular", "nombre", "cliente"],
        "periodo": ["período", "periodo", "fecha", "del", "al"],
        # Campos de identificación
        "curp": ["curp"],
        "clave_elector": ["clave", "elector", "credencial"],
        "vigencia": ["vigencia", "vence", "válido hasta"],
        "fecha_de_nacimiento": ["nacimiento", "fecha de nacimiento", "nació"],
        # Campos de FIEL
        "numero_serie_certificado": ["serie", "certificado", "número"],
        "vigencia_desde": ["vigencia", "válido desde", "inicio"],
        "vigencia_hasta": ["vigencia", "válido hasta", "vence", "fin"],
    }
    
    # Obtener palabras clave para el campo
    keywords = palabras_clave.get(campo, [campo.replace("_", " ")])
    
    text_lower = text_ocr.lower()
    mejor_pos = -1
    
    # Buscar la primera ocurrencia de cualquier palabra clave
    for keyword in keywords:
        pos = text_lower.find(keyword.lower())
        if pos >= 0 and (mejor_pos == -1 or pos < mejor_pos):
            mejor_pos = pos
    
    if mejor_pos >= 0:
        # Encontrar página
        pagina = 1
        pagina_matches = list(re.finditer(r'\[\[\[PÁGINA:(\d+)\]\]\]', text_ocr))
        for match in pagina_matches:
            if match.start() <= mejor_pos:
                pagina = int(match.group(1))
            else:
                break
        
        # Extraer párrafo alrededor de la posición encontrada
        inicio = max(0, mejor_pos - 50)
        fin = min(len(text_ocr), mejor_pos + 150)
        parrafo = text_ocr[inicio:fin].strip()
        
        # Limpiar
        parrafo = re.sub(r'\[\[\[PÁGINA:\d+\]\]\]', '', parrafo)
        parrafo = re.sub(r'\s+', ' ', parrafo).strip()
        parrafo = parrafo[:200]
        
        return (parrafo if parrafo else None, pagina)
    
    return (None, None)


def init_openai_llm() -> AzureChatOpenAI:
    load_dotenv(dotenv_path=_env_path)
    return AzureChatOpenAI(
        azure_endpoint =    getenv("AZURE_OPENAI_ENDPOINT"),
        deployment_name =   getenv("AZURE_DEPLOYMENT_NAME"),
        api_version =       getenv("AZURE_OPENAI_API_VERSION"),
        api_key =           getenv("AZURE_OPENAI_API_KEY"),
    )

def build_llm():
    AZURE_OPENAI_ENDPOINT =         getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_DEPLOYMENT_NAME =         getenv("AZURE_DEPLOYMENT_NAME")
    AZURE_OPENAI_API_VERSION =      getenv("AZURE_OPENAI_API_VERSION")
    AZURE_OPENAI_API_KEY =          getenv("AZURE_OPENAI_API_KEY")

    missing = [k for k, v in [
        ("AZURE_OPENAI_ENDPOINT",    AZURE_OPENAI_ENDPOINT),
        ("AZURE_OPENAI_API_KEY",     AZURE_OPENAI_API_KEY),
        ("AZURE_OPENAI_API_VERSION", AZURE_OPENAI_API_VERSION),
        ("AZURE_DEPLOYMENT_NAME",    AZURE_DEPLOYMENT_NAME),
    ] if not v]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    return AzureChatOpenAI(
        azure_deployment =  AZURE_DEPLOYMENT_NAME,
        api_key =           AZURE_OPENAI_API_KEY,
        api_version =       AZURE_OPENAI_API_VERSION,
        azure_endpoint =    AZURE_OPENAI_ENDPOINT,
        temperature =       0
    )


def get_embedding_function():
    AZURE_OPENAI_ENDPOINT =         getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION =      getenv("AZURE_OPENAI_API_VERSION")
    AZURE_OPENAI_API_KEY =          getenv("AZURE_OPENAI_API_KEY")
    AZURE_EMBEDDING_DEPLOYMENT =    getenv("AZURE_EMBEDDING_DEPLOYMENT")
    
    missing = [k for k, v in [
        ("AZURE_OPENAI_ENDPOINT", AZURE_OPENAI_ENDPOINT),
        ("AZURE_OPENAI_API_KEY", AZURE_OPENAI_API_KEY),
        ("AZURE_OPENAI_API_VERSION", AZURE_OPENAI_API_VERSION),
        ("AZURE_EMBEDDING_DEPLOYMENT", AZURE_EMBEDDING_DEPLOYMENT),
    ] if not v]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    return AzureOpenAIEmbeddings(
        azure_deployment=AZURE_EMBEDDING_DEPLOYMENT,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )
    pass

def extract_poder_fields(text_ocr: str, llm) -> dict:
    """
    Extrae campos de un Poder Notarial mexicano.
    
    CAMPOS CRÍTICOS:
    - numero_escritura: Número de la escritura pública del poder
    - fecha_otorgamiento: Fecha en que se otorgó el poder (en el acta)
    - fecha_expedicion: Fecha de expedición del testimonio (nota al calce)
    - nombre_apoderado: Nombre completo del apoderado designado
    - nombre_poderdante: Quien otorga el poder (persona física o moral)
    - tipo_poder: General, especial, para pleitos y cobranzas, actos de administración, etc.
    - facultades: Descripción de las facultades otorgadas al apoderado
    - numero_notaria: Número de la notaría pública
    - estado_notaria: Estado donde se ubica la notaría
    - nombre_notario: Nombre completo del notario público
    """
    if not text_ocr.strip():
        return {"error": "Texto vacío"}

    MAX_CHUNK = 200000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)] or [""]

    json_template = """
    {
      "numero_escritura": "",
      "fecha_otorgamiento": "",
      "fecha_expedicion": "",
      "nombre_apoderado": "",
      "nombre_poderdante": "",
      "tipo_poder": "",
      "facultades": "",
      "numero_notaria": "",
      "estado_notaria": "",
      "nombre_notario": "",
      "campos_no_encontrados": []
    }
    """

    extracted_data = {k: [] if isinstance(v, list) else "" for k, v in json.loads(json_template).items()}

    for idx, chunk in enumerate(chunks, start=1):
        prompt = dedent(f"""
        Eres un analista experto en poderes notariales mexicanos.
        
        Extrae SOLO los campos de la plantilla. No inventes datos.
        Si un campo no aparece explícitamente, deja vacío y agrégalo a "campos_no_encontrados".

        CAMPOS A EXTRAER:
        
        1. "numero_escritura": Número de escritura pública o póliza del poder.
           - Buscar "ESCRITURA PÚBLICA NÚMERO X" o "PÓLIZA NÚMERO X"
           - Solo el número, sin texto adicional
        
        2. "fecha_otorgamiento": Fecha en que se OTORGÓ el poder (dentro del acta).
           - Buscar "a los X días del mes de Y del año Z"
           - Formato: dd/mm/aaaa
           - Convertir fechas en palabras a números
        
        3. "fecha_expedicion": Fecha de EXPEDICIÓN del testimonio (nota al calce, al final).
           - Buscar después de "SE EXPIDE" o "EXPIDO ESTE" o en la nota final
           - Formato: dd/mm/aaaa
           - Si no hay nota al calce, dejar vacío
        
        4. "nombre_apoderado": Nombre COMPLETO del apoderado designado.
           - Buscar después de "SE CONFIERE PODER A", "DESIGNA COMO APODERADO A"
           - Nombre y apellidos completos
        
        5. "nombre_poderdante": Quien OTORGA el poder (la entidad o persona que da el poder).
           - Si es una empresa: buscar la RAZÓN SOCIAL completa (ej: "XXX, S.A. DE C.V.")
           - Buscar después de "EN REPRESENTACIÓN DE", "A NOMBRE DE", "POR CUENTA DE"
           - También puede aparecer como "LA SOCIEDAD" seguido de la razón social
           - En actas de consejo, el poderdante es la empresa cuyo consejo se reunió
           - NO confundir con el apoderado (quien RECIBE el poder)
        
        6. "tipo_poder": Clasificación del poder otorgado.
           - Valores comunes: "GENERAL PARA PLEITOS Y COBRANZAS", "GENERAL PARA ACTOS DE ADMINISTRACIÓN", 
             "GENERAL PARA ACTOS DE DOMINIO", "ESPECIAL", "GENERAL AMPLIO"
           - Buscar después de "PODER" o "CONFIERE"
        
        7. "facultades": Descripción COMPLETA de las facultades otorgadas.
           - Incluir TODAS las facultades mencionadas, sin omitir ni resumir
           - Es CRÍTICO incluir menciones a: cuentas bancarias, instituciones de crédito,
             actos de administración, actos de dominio, operaciones bancarias, etc.
           - Ej: "Celebrar contratos, abrir cuentas bancarias, representar en juicios,
             operar cuentas en instituciones de crédito..."
           - Máximo 1000 caracteres
        
        8. "numero_notaria": Número de la notaría pública.
           - Buscar "NOTARÍA PÚBLICA NÚMERO X" o "NOTARIO NÚMERO X"
        
        9. "estado_notaria": Estado donde se ubica la notaría.
           - Buscar "NOTARÍA DE/EN [ESTADO]" o "NOTARIO DEL ESTADO DE [ESTADO]"
        
        10. "nombre_notario": Nombre completo del notario público.
            - Buscar "LICENCIADO X, NOTARIO" o "NOTARIO PÚBLICO X"

        JSON esperado:
        {json_template}

        Texto (fragmento {idx}/{len(chunks)}):
        {chunk}
        """)

        resp = llm.invoke(prompt).content.strip()
        resp = re.sub(r"^```(?:json)?|```$", "", resp).strip()
        match = re.search(r"\{.*\}", resp, re.S)

        try:
            partial_data = json.loads(match.group(0)) if match else {}
        except:
            partial_data = {}

        for key in extracted_data.keys():
            if isinstance(extracted_data[key], list):
                if partial_data.get(key):
                    for item in partial_data[key]:
                        if item not in extracted_data[key]:
                            extracted_data[key].append(item)
            else:
                if not extracted_data[key] and partial_data.get(key):
                    extracted_data[key] = partial_data[key]

    # Post-procesamiento y validación
    extracted_data = _validate_and_correct_poder_fields(extracted_data, text_ocr)
    
    # Agregar evidencia de extracción (página y párrafo)
    campos_a_buscar = [
        "numero_escritura", "fecha_otorgamiento", "fecha_expedicion",
        "nombre_apoderado", "nombre_poderdante", "tipo_poder",
        "facultades", "numero_notaria", "estado_notaria", "nombre_notario"
    ]
    extracted_data = _add_extraction_evidence_generic(extracted_data, text_ocr, campos_a_buscar)

    return extracted_data


def _validate_and_correct_poder_fields(data: dict, text_ocr: str) -> dict:
    """
    Post-procesamiento para campos de Poder Notarial.
    Similar a _validate_and_correct_acta_fields pero para poderes.
    """
    result = data.copy()
    text_lower = text_ocr.lower()
    
    # Meses para conversión
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    # Días en palabras
    dias_palabras = {
        'uno': '01', 'primero': '01', 'primer': '01', 'dos': '02',
        'tres': '03', 'cuatro': '04', 'cinco': '05', 'seis': '06',
        'siete': '07', 'ocho': '08', 'nueve': '09', 'diez': '10',
        'once': '11', 'doce': '12', 'trece': '13', 'catorce': '14', 'quince': '15',
        'dieciseis': '16', 'dieciséis': '16', 'diecisiete': '17', 'dieciocho': '18',
        'diecinueve': '19', 'veinte': '20', 'veintiuno': '21', 'veintidos': '22',
        'veintidós': '22', 'veintitres': '23', 'veintitrés': '23', 'veinticuatro': '24',
        'veinticinco': '25', 'veintiseis': '26', 'veintiséis': '26', 'veintisiete': '27',
        'veintiocho': '28', 'veintinueve': '29', 'treinta': '30', 'treinta y uno': '31'
    }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. NÚMERO DE ESCRITURA - Limpiar y validar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("numero_escritura"):
        num = re.sub(r'[^\d]', '', str(result["numero_escritura"]))
        if num:
            result["numero_escritura"] = num
    else:
        # Buscar con regex
        patterns = [
            r'ESCRITURA\s+P[ÚU]BLICA\s+N[ÚU]MERO\s+(\d{1,6})',
            r'ESCRITURA\s+N[ÚU]MERO\s+(\d{1,6})',
            r'P[ÓO]LIZA\s+N[ÚU]MERO\s+(\d{1,6})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_escritura"] = match.group(1)
                break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. FECHA DE EXPEDICIÓN - Buscar en nota al calce
    # ═══════════════════════════════════════════════════════════════════════════
    fecha_exp_actual = str(result.get("fecha_expedicion", "")).lower()
    necesita_buscar_fecha = (
        not result.get("fecha_expedicion") or
        "pendiente" in fecha_exp_actual or
        fecha_exp_actual in ["n/a", "", "null", "none"]
    )
    
    if necesita_buscar_fecha:
        # Buscar en los últimos 15000 caracteres
        texto_final = text_ocr[-15000:] if len(text_ocr) > 15000 else text_ocr
        
        expedicion_patterns_palabras = [
            r'EXPIDO\s+(?:ESTE|EL\s+PRESENTE).*?A\s+LOS\s+(\w+)\s+DIAS?\s+DEL\s+MES\s+DE\s+(\w+)\s+DEL?\s+A[ÑN]O',
            r'SE\s+EXPIDE.*?A\s+LOS\s+(\w+)\s+D[ÍI]AS?\s+DEL\s+MES\s+DE\s+(\w+)\s+DEL?\s+A[ÑN]O',
            r'EXPIDO.*?A\s+LOS\s+(\w+)\s+DIAS?\s+DEL\s+MES\s+DE\s+(\w+)',
        ]
        
        for pattern_palabras in expedicion_patterns_palabras:
            match_palabras = re.search(pattern_palabras, texto_final, re.IGNORECASE | re.DOTALL)
            if match_palabras:
                dia_palabra = match_palabras.group(1).lower()
                mes_texto = match_palabras.group(2).lower()
                
                dia = dias_palabras.get(dia_palabra, None)
                if not dia and dia_palabra.isdigit():
                    dia = dia_palabra.zfill(2)
                
                if dia and mes_texto in meses:
                    texto_despues = texto_final[match_palabras.end():match_palabras.end()+500]
                    anio_match = re.search(r'\b(19\d{2}|20\d{2})\b', texto_despues)
                    
                    if anio_match:
                        anio = anio_match.group(1)
                        result["fecha_expedicion"] = f"{dia}/{meses[mes_texto]}/{anio}"
                        break
        
        # Si no encontramos con palabras, buscar con números
        if not result.get("fecha_expedicion") or "pendiente" in str(result.get("fecha_expedicion", "")).lower():
            expedicion_patterns_numeros = [
                r'(?:GUADALAJARA|CIUDAD\s+DE\s+M[ÉE]XICO|MONTERREY)[,\s]+(?:\w+)[,\s]+A\s+(\d{1,2})\s+\w+\s+DE\s+(\w+)\s+DE[L]?\s+(\d{4})',
            ]
            for pattern in expedicion_patterns_numeros:
                match = re.search(pattern, texto_final, re.IGNORECASE)
                if match:
                    dia = match.group(1).zfill(2)
                    mes_texto = match.group(2).lower()
                    anio = match.group(3)
                    if mes_texto in meses:
                        result["fecha_expedicion"] = f"{dia}/{meses[mes_texto]}/{anio}"
                        break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. TIPO DE PODER - Normalizar
    # ═══════════════════════════════════════════════════════════════════════════
    tipo_poder = str(result.get("tipo_poder", "")).upper()
    if not tipo_poder or tipo_poder in ["", "N/A"]:
        # Buscar tipo de poder en el texto
        tipo_patterns = [
            (r'PODER\s+GENERAL\s+(?:AMPLIO|AMPLÍSIMO)', "PODER GENERAL AMPLIO"),
            (r'PODER\s+GENERAL\s+PARA\s+PLEITOS\s+Y\s+COBRANZAS', "PODER GENERAL PARA PLEITOS Y COBRANZAS"),
            (r'PODER\s+GENERAL\s+PARA\s+ACTOS\s+DE\s+ADMINISTRACI[ÓO]N', "PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN"),
            (r'PODER\s+GENERAL\s+PARA\s+ACTOS\s+DE\s+DOMINIO', "PODER GENERAL PARA ACTOS DE DOMINIO"),
            (r'PODER\s+ESPECIAL', "PODER ESPECIAL"),
        ]
        for pattern, tipo in tipo_patterns:
            if re.search(pattern, text_ocr, re.IGNORECASE):
                result["tipo_poder"] = tipo
                break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. NOMBRE APODERADO - Buscar si está vacío
    # ═══════════════════════════════════════════════════════════════════════════
    if not result.get("nombre_apoderado") or str(result.get("nombre_apoderado", "")).strip() == "":
        # Buscar patrones comunes para el apoderado
        apoderado_patterns = [
            # "FORMALIZA: SR. NOMBRE APELLIDO APELLIDO" (encabezado)
            r'FORMALIZA[:\s]+(?:SR\.?|SRA\.?|C\.?|LIC\.?|ING\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,4})',
            # "SE CONFIERE PODER A NOMBRE"
            r'(?:se\s+)?confiere\s+(?:el\s+)?poder\s+a\s+(?:favor\s+de\s+)?(?:SR\.?|SRA\.?|C\.?|LIC\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,4})',
            # "DESIGNA COMO APODERADO A NOMBRE"
            r'designa\s+(?:como\s+)?apoderado\s+a\s+(?:SR\.?|SRA\.?|C\.?|LIC\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,4})',
            # "OTORGA PODER A NOMBRE"
            r'otorga\s+(?:el\s+)?poder\s+a\s+(?:favor\s+de\s+)?(?:SR\.?|SRA\.?|C\.?|LIC\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,4})',
            # "A FAVOR DE SR. NOMBRE"
            r'a\s+favor\s+de[l]?\s+(?:SR\.?|SRA\.?|C\.?|LIC\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,4})',
        ]
        
        for pattern in apoderado_patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                nombre = match.group(1).strip()
                # Capitalizar correctamente
                nombre = nombre.title()
                if len(nombre.split()) >= 2:  # Al menos nombre y apellido
                    result["nombre_apoderado"] = nombre
                    break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. NOMBRE PODERDANTE - Buscar razón social si está vacío
    # ═══════════════════════════════════════════════════════════════════════════
    if not result.get("nombre_poderdante") or str(result.get("nombre_poderdante", "")).strip() == "":
        # Buscar razón social de la empresa que otorga el poder
        razon_patterns = [
            # "denominada XXX, S.A. DE C.V." o similar
            r'(?:denominada|denominaci[óo]n)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+(?:S\.?A\.?(?:\s+DE\s+C\.?V\.?)?|S\.?\s*DE\s*R\.?\s*L\.?|S\.?C\.?))',
            # "la sociedad XXX, S.A."
            r'(?:la\s+sociedad|sociedad\s+mercantil)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+(?:S\.?A\.?(?:\s+DE\s+C\.?V\.?)?|S\.?\s*DE\s*R\.?\s*L\.?))',
            # "EN REPRESENTACIÓN DE XXX"
            r'en\s+representaci[óo]n\s+de\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+(?:S\.?A\.?|S\.?C\.?))',
            # "a nombre de XXX"
            r'a\s+nombre\s+de\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+(?:S\.?A\.?|S\.?C\.?))',
        ]
        
        for pattern in razon_patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                razon = match.group(1).strip()
                # Limpiar y normalizar
                razon = re.sub(r'\s+', ' ', razon).strip(' ,.')
                if len(razon) > 5:
                    result["nombre_poderdante"] = razon.upper()
                    break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. CAMPOS NO ENCONTRADOS - Actualizar lista
    # ═══════════════════════════════════════════════════════════════════════════
    campos_obligatorios = [
        "numero_escritura", "fecha_otorgamiento", "nombre_apoderado",
        "nombre_poderdante", "tipo_poder", "numero_notaria", "nombre_notario"
    ]
    
    if "campos_no_encontrados" not in result:
        result["campos_no_encontrados"] = []
    
    for campo in campos_obligatorios:
        valor = str(result.get(campo, "")).lower().strip()
        es_vacio = not valor or valor in ["", "n/a", "null", "none", "pendiente"]
        
        if es_vacio:
            if campo not in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].append(campo)
        else:
            if campo in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].remove(campo)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LIMPIEZA FINAL - Limpiar nombres (después de todos los fallbacks)
    # ═══════════════════════════════════════════════════════════════════════════
    for campo_nombre in ["nombre_apoderado", "nombre_poderdante", "nombre_notario"]:
        if result.get(campo_nombre):
            nombre = str(result[campo_nombre])
            # Quitar saltos de línea - primero reales, luego literales
            nombre = nombre.split('\n')[0].strip()
            nombre = nombre.split('\\n')[0].strip()
            # Quitar texto tipo "Esc", "ESC:", "LIBRO", etc. al final
            nombre = re.sub(r'\s*(?:ESC|Esc|LIBRO|Libro|FECHA|Fecha|ESCRITURA)[:\s].*$', '', nombre, flags=re.IGNORECASE)
            nombre = re.sub(r'\s*Esc\s*$', '', nombre, flags=re.IGNORECASE)
            # Quitar números sueltos al final
            nombre = re.sub(r'\s+\d+.*$', '', nombre)
            result[campo_nombre] = nombre.strip()
    
    return result

def extract_ine_reverso(text_ocr: str, llm: AzureChatOpenAI):
    if not text_ocr.strip():
        return {"error": "Texto vacío"}
    MAX_CHUNK = 200000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)]
    
    #Plantilla JSON
    json_template = """
    {
      "primer_nombre": "",
      "segundo_nombre": "",
      "primer_apellido": "",
      "segundo_apellido": "",
      "fecha_de_nacimiento": "",
      "curp": "",
      "vigencia_de_ine": ""
    }
    """
    
    #Diccionario para acumular resultados
    extracted_data = {k: "" for k in json.loads(json_template)}
    
    for idx, chunk in enumerate(chunks, start=1):
        prompt = dedent(f"""
        Eres un asistente experto en documentos legales mexicanos. 
        Tu tarea: EXTRAER valores exactos del texto y normalizarlos según estas reglas:

        REGLAS:
        - Si el valor NO aparece explícitamente, deja el campo vacío (solamente aplica para segundo_nombre_fedatario).
        - No inventes valores.
        - Para 'vigencia':
            * Son la misma fecha.
            * Convierte cualquier fecha a formato dd/mm/aaaa.
            * Convierte fechas escritas en palabras a numéricas.
        - Si dice "DISTRITO FEDERAL", interpreta como "Ciudad de México".
        - Si no hay segundo nombre, usa "N/A".
        - Responde SOLO con un JSON válido, sin texto adicional.

        JSON esperado:
        {json_template}

        Texto (fragmento {idx}/{len(chunks)}):
        {chunk}
        """)

        resp = llm.invoke(prompt).content.strip()
        resp = re.sub(r"^```(?:json)?|```$", "", resp).strip()
        match = re.search(r"\{.*\}", resp, re.S)
        
        try:
            partial_data = json.loads(match.group(0)) if match else {}
        except:
            partial_data = {}

    #Fusionamos: si un campo sigue vacío y en este chunk aparece, lo tomamos
        for key in extracted_data.keys():
            if not extracted_data[key] and partial_data.get(key):
                extracted_data[key] = partial_data[key]

    # Agregar evidencia de extracción (página y párrafo) para INE Reverso
    campos_ine = [
        "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
        "fecha_de_nacimiento", "curp", "vigencia_de_ine"
    ]
    extracted_data = _add_extraction_evidence_generic(extracted_data, text_ocr, campos_ine)

    return extracted_data


def _validate_and_correct_acta_fields(extracted_data: dict, text_ocr: str, llm=None) -> dict:
    """
    Post-procesa y valida los campos extraídos del Acta Constitutiva.
    Aplica reglas de negocio y extracción con regex como fallback.
    Si se proporciona llm, puede hacer re-extracción de estructura accionaria.
    """
    import re
    
    result = extracted_data.copy()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. FOLIO MERCANTIL ELECTRÓNICO (FME) - SIEMPRE buscar y validar
    # ═══════════════════════════════════════════════════════════════════════════
    # El FME puede tener varios formatos:
    # - N-2019050847 o M-2019050847 (letra + guión + números)
    # - 28308 (solo número, en boletas más antiguas)
    # - NO confundir con NCI (solo números largos: 201900148937)
    
    fme_encontrado = None
    
    # Estrategia 1: Buscar patrones específicos en orden de prioridad
    folio_patterns = [
        # Formato donde el número está en la línea siguiente después de "No."
        # Ej: "FOLIO MERCANTIL ELECTRONICO No.\n28308 * 2"
        r'FOLIO\s+MERCANTIL\s+ELECTR[ÓO]NICO\s+No\.?\s*\n\s*(\d{4,})',
        # Formato más común: "FOLIO MERCANTIL ELECTRONICO No. 28308" (mismo línea)
        r'FOLIO\s+MERCANTIL\s+ELECTR[ÓO]NICO\s+(?:No\.?|N[ÚU]MERO)?\s*([NM]?-?\d{4,})',
        # Formato con N- o M- prefijo
        r'FOLIO\s+MERCANTIL\s+ELECTR[ÓO]NICO[^\d\n]*([NM]-\d{7,})',
        # Formato genérico en boletas donde el número está después de MERCANTIL
        r'FOLIO\s+MERCANTIL[^\d]*?(\d{4,})\s*(?:\*\s*\d)?',
        # FME abreviado
        r'\bFME[:\s]+([NM]?-?\d{4,})',
        r'\bFME\b[^\d]*(\d{4,})',
    ]
    
    for pattern in folio_patterns:
        match = re.search(pattern, text_ocr, re.IGNORECASE | re.DOTALL)
        if match:
            fme_encontrado = match.group(1).strip()
            # Limpiar: remover asterisco y número de versión si quedó
            fme_encontrado = re.sub(r'\s*\*.*$', '', fme_encontrado).strip()
            # Normalizar: si tiene formato N-xxx o M-xxx, mantenerlo en mayúsculas
            if re.match(r'^[NM]-', fme_encontrado, re.IGNORECASE):
                fme_encontrado = fme_encontrado.upper()
            # Restaurar prefijo N-/M- si fue perdido por el regex (captura solo dígitos)
            elif re.match(r'^\d+$', fme_encontrado):
                prefix_match = re.search(
                    r'([NM])-' + re.escape(fme_encontrado),
                    text_ocr, re.IGNORECASE
                )
                if prefix_match:
                    fme_encontrado = f"{prefix_match.group(1).upper()}-{fme_encontrado}"
            break
    
    # Estrategia 2: Buscar en sección de Boleta de Inscripción específicamente
    if not fme_encontrado:
        # Buscar la sección de boleta y luego el número
        boleta_match = re.search(
            r'Boleta\s+de\s+Inscripci[óo]n.*?FOLIO\s+MERCANTIL[^\d\n]*\n?\s*(\d{4,})',
            text_ocr, re.IGNORECASE | re.DOTALL
        )
        if boleta_match:
            fme_encontrado = boleta_match.group(1).strip()
    
    # Restaurar prefijo N-/M- si fue perdido (aplica también a Estrategia 2)
    if fme_encontrado and re.match(r'^\d+$', fme_encontrado):
        prefix_match = re.search(
            r'([NM])-' + re.escape(fme_encontrado),
            text_ocr, re.IGNORECASE
        )
        if prefix_match:
            fme_encontrado = f"{prefix_match.group(1).upper()}-{fme_encontrado}"
    
    # Si encontramos un FME válido, usarlo (independiente de lo que dijo el LLM)
    if fme_encontrado:
        result["folio_mercantil"] = fme_encontrado
        if "folio_mercantil" in result.get("campos_no_encontrados", []):
            result["campos_no_encontrados"].remove("folio_mercantil")
    # Si el LLM extrajo "Pendiente" pero podría haber FME no detectado
    elif "pendiente" in str(result.get("folio_mercantil", "")).lower():
        # Verificar que realmente no hay folio - buscar "Pendiente de Inscripción" literal
        if not re.search(r'pendiente\s+de\s+inscripci[oó]n', text_ocr, re.IGNORECASE):
            # Último intento: buscar cualquier número de 4-7 dígitos después de "FOLIO MERCANTIL"
            ultimo_match = re.search(r'FOLIO\s+MERCANTIL[^\d]*(\d{4,7})\b', text_ocr, re.IGNORECASE)
            if ultimo_match:
                result["folio_mercantil"] = ultimo_match.group(1)
                if "folio_mercantil" in result.get("campos_no_encontrados", []):
                    result["campos_no_encontrados"].remove("folio_mercantil")
    
    # Restauración global: si el folio final es puramente numérico,
    # intentar restaurar prefijo N-/M- desde el texto OCR original
    folio_final = str(result.get("folio_mercantil", "")).strip()
    if folio_final and re.match(r'^\d+$', folio_final):
        prefix_check = re.search(
            r'([NM])-' + re.escape(folio_final),
            text_ocr, re.IGNORECASE
        )
        if prefix_check:
            result["folio_mercantil"] = f"{prefix_check.group(1).upper()}-{folio_final}"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. FECHA EXPEDICIÓN - SIEMPRE buscar en NOTA AL CALCE
    # ═══════════════════════════════════════════════════════════════════════════
    # La fecha de expedición está al FINAL del documento, en la NOTA AL CALCE
    # Formato típico: "GUADALAJARA, JALISCO, A 04 CUATRO DE JUNIO DE 2019"
    
    fecha_exp_actual = str(result.get("fecha_expedicion", "")).lower()
    necesita_buscar_fecha = (
        not result.get("fecha_expedicion") or
        result.get("fecha_expedicion") == result.get("fecha_constitucion") or
        "pendiente" in fecha_exp_actual or
        fecha_exp_actual in ["n/a", "", "null", "none"]
    )
    
    if necesita_buscar_fecha:
        meses = {
            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
            'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
        }
        
        # Días en palabras
        dias_palabras = {
            'uno': '01', 'primero': '01', 'primer': '01', 'dos': '02', 'segundo': '02',
            'tres': '03', 'tercero': '03', 'cuatro': '04', 'cuarto': '04',
            'cinco': '05', 'quinto': '05', 'seis': '06', 'sexto': '06',
            'siete': '07', 'septimo': '07', 'séptimo': '07', 'ocho': '08', 'octavo': '08',
            'nueve': '09', 'noveno': '09', 'diez': '10', 'décimo': '10', 'decimo': '10',
            'once': '11', 'doce': '12', 'trece': '13', 'catorce': '14', 'quince': '15',
            'dieciseis': '16', 'dieciséis': '16', 'diecisiete': '17', 'dieciocho': '18',
            'diecinueve': '19', 'veinte': '20', 'veintiuno': '21', 'veintidos': '22',
            'veintidós': '22', 'veintitres': '23', 'veintitrés': '23', 'veinticuatro': '24',
            'veinticinco': '25', 'veintiseis': '26', 'veintiséis': '26', 'veintisiete': '27',
            'veintiocho': '28', 'veintinueve': '29', 'treinta': '30', 'treintaiuno': '31',
            'treinta y uno': '31'
        }
        
        # Buscar en la NOTA AL CALCE (última parte del documento)
        # Patrones para fecha de expedición del testimonio
        expedicion_patterns = [
            # "GUADALAJARA, JALISCO, A 04 CUATRO DE JUNIO DE 2019"
            r'(?:GUADALAJARA|CIUDAD\s+DE\s+M[ÉE]XICO|MONTERREY|CDMX)[,\s]+(?:JALISCO|D\.?F\.?|N\.?L\.?|NUEVO\s+LE[ÓO]N)[,\s]+A\s+(\d{1,2})\s+\w+\s+DE\s+(\w+)\s+DE[L]?\s+(\d{4})',
            # "--- GUADALAJARA, JALISCO, A 04 CUATRO DE JUNIO DE 2019 DOS MIL DIECINUEVE"
            r'---\s*(?:GUADALAJARA|CIUDAD)[,\s]+\w+[,\s]+A\s+(\d{1,2})\s+\w+\s+DE\s+(\w+)\s+DE[L]?\s+(\d{4})',
            # Buscar después de "SE SACO DE SU MATRIZ" o "CERTIFICO"
            r'(?:SE\s+SAC[ÓO]|CERTIFICO).*?A\s+(\d{1,2})\s+\w+\s+DE\s+(\w+)\s+DE[L]?\s+(\d{4})',
        ]
        
        # Patrones especiales para fecha de expedición con día en palabras
        # Incluye variantes: "EXPIDO ESTE", "SE EXPIDE", "EXPIDO EL PRESENTE"
        expedicion_patterns_palabras = [
            # "EXPIDO ESTE...A LOS VEINTE DIAS DEL MES DE FEBRERO DEL AÑO DOS MIL QUINCE"
            r'EXPIDO\s+(?:ESTE|EL\s+PRESENTE).*?A\s+LOS\s+(\w+)\s+DIAS?\s+DEL\s+MES\s+DE\s+(\w+)\s+DEL?\s+A[ÑN]O',
            # "SE EXPIDE A FAVOR DE...A LOS DIECIOCHO DÍAS DEL MES DE ABRIL DEL AÑO"
            r'SE\s+EXPIDE.*?A\s+LOS\s+(\w+)\s+D[ÍI]AS?\s+DEL\s+MES\s+DE\s+(\w+)\s+DEL?\s+A[ÑN]O',
            # "EXPIDO...A LOS X DIAS DEL MES DE Y"
            r'EXPIDO.*?A\s+LOS\s+(\w+)\s+DIAS?\s+DEL\s+MES\s+DE\s+(\w+)',
        ]
        
        # Buscar en los últimos 20000 caracteres (donde está la nota al calce)
        texto_final = text_ocr[-20000:] if len(text_ocr) > 20000 else text_ocr
        
        fechas_encontradas = []
        
        # Primero buscar patrones con día en palabras (EXPIDO ESTE, SE EXPIDE, etc.)
        for pattern_palabras in expedicion_patterns_palabras:
            match_palabras = re.search(pattern_palabras, texto_final, re.IGNORECASE | re.DOTALL)
            if match_palabras:
                dia_palabra = match_palabras.group(1).lower()
                mes_texto = match_palabras.group(2).lower()
                
                # Convertir día en palabras a número
                dia = dias_palabras.get(dia_palabra, None)
                if not dia and dia_palabra.isdigit():
                    dia = dia_palabra.zfill(2)
                
                if dia and mes_texto in meses:
                    # Buscar el año después del patrón (puede ser "DOS MIL QUINCE" o "2015")
                    # Expandir búsqueda a 500 caracteres porque el OCR puede tener errores
                    texto_despues = texto_final[match_palabras.end():match_palabras.end()+500]
                    # Buscar año en números (4 dígitos que empiecen con 19 o 20)
                    anio_match = re.search(r'\b(19\d{2}|20\d{2})\b', texto_despues)
                    
                    if anio_match:
                        anio = anio_match.group(1)
                    else:
                        # Si no encontramos año explícito, usar el año de fecha_constitucion
                        fecha_const = result.get("fecha_constitucion", "")
                        if fecha_const and "/" in str(fecha_const):
                            anio = str(fecha_const).split("/")[-1]
                        else:
                            anio = None
                    
                    if anio:
                        fecha_str = f"{dia}/{meses[mes_texto]}/{anio}"
                        if fecha_str != result.get("fecha_constitucion"):
                            fechas_encontradas.append(fecha_str)
                            break  # Si encontramos una fecha válida, salir del bucle
        
        # Luego buscar patrones con día en números
        for pattern in expedicion_patterns:
            matches = list(re.finditer(pattern, texto_final, re.IGNORECASE | re.DOTALL))
            for match in matches:
                dia = match.group(1).zfill(2)
                mes_texto = match.group(2).lower()
                anio = match.group(3)
                
                if mes_texto in meses:
                    fecha_str = f"{dia}/{meses[mes_texto]}/{anio}"
                    # No agregar si es igual a fecha_constitucion
                    if fecha_str != result.get("fecha_constitucion"):
                        fechas_encontradas.append(fecha_str)
        
        # Usar la primera fecha encontrada que no sea la de constitución
        if fechas_encontradas:
            result["fecha_expedicion"] = fechas_encontradas[0]
            if "fecha_expedicion" in result.get("campos_no_encontrados", []):
                result["campos_no_encontrados"].remove("fecha_expedicion")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. CLÁUSULA DE EXTRANJEROS - Validar que sea EXCLUSIÓN o ADMISIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    clausula = result.get("clausula_extranjeros", "")
    
    # Si está vacío o tiene valores incorrectos, buscar en texto
    if not clausula or clausula in ["N/A", ""] or isinstance(clausula, list):
        # Buscar cláusula de exclusión
        exclusion_patterns = [
            r'CLÁUSULA\s+DE\s+EXCLUSIÓN\s+DE\s+EXTRANJEROS',
            r'NO\s+admitirá\s+directa,?\s+ni\s+indirectamente.*?inversionistas\s+extranjeros',
            r'inversión\s+extranjera\s+no\s+podrá\s+participar',
            r'EXCLUSIÓN\s+DE\s+EXTRANJEROS',
        ]
        
        admision_patterns = [
            r'CLÁUSULA\s+DE\s+ADMISIÓN\s+DE\s+EXTRANJEROS',
            r'podrán\s+participar\s+inversionistas\s+extranjeros',
            r'ADMISIÓN\s+DE\s+EXTRANJEROS',
        ]
        
        for pattern in exclusion_patterns:
            if re.search(pattern, text_ocr, re.IGNORECASE):
                result["clausula_extranjeros"] = "EXCLUSIÓN DE EXTRANJEROS"
                break
        else:
            for pattern in admision_patterns:
                if re.search(pattern, text_ocr, re.IGNORECASE):
                    result["clausula_extranjeros"] = "ADMISIÓN DE EXTRANJEROS"
                    break
    
    # Normalizar respuesta
    if isinstance(result.get("clausula_extranjeros"), list):
        result["clausula_extranjeros"] = "EXCLUSIÓN DE EXTRANJEROS" if any(
            "exclu" in str(x).lower() for x in result["clausula_extranjeros"]
        ) else "NO ESPECIFICADA"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. NÚMERO DE ESCRITURA - Limpiar y validar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("numero_escritura_poliza"):
        # Extraer solo dígitos
        num = re.sub(r'[^\d]', '', str(result["numero_escritura_poliza"]))
        if num:
            result["numero_escritura_poliza"] = num
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. NÚMERO DE NOTARÍA - Limpiar y validar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("numero_notaria"):
        num = re.sub(r'[^\d]', '', str(result["numero_notaria"]))
        if num:
            result["numero_notaria"] = num
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 6. Eliminar campo 'extranjeras' si existe (campo legacy incorrecto)
    # ═══════════════════════════════════════════════════════════════════════════
    if "extranjeras" in result:
        del result["extranjeras"]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 7. REGEX FALLBACK - Buscar campos faltantes con patrones
    # ═══════════════════════════════════════════════════════════════════════════
    result = _regex_fallback_extraction(result, text_ocr)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 8. CORREGIR INCONSISTENCIA campos_no_encontrados
    # ═══════════════════════════════════════════════════════════════════════════
    result = _fix_campos_no_encontrados(result)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 9. VALIDAR ESTRUCTURA ACCIONARIA (con fallback regex)
    # ═══════════════════════════════════════════════════════════════════════════
    result = _validate_estructura_accionaria(result, text_ocr)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 9.5 BACKUP ROBUSTO: Si la suma de porcentajes es < 98%, intentar rescatar
    # ═══════════════════════════════════════════════════════════════════════════
    estructura = result.get("estructura_accionaria", [])
    if isinstance(estructura, list) and len(estructura) > 0:
        # Calcular suma actual de porcentajes
        porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
        total_porcentaje = sum(porcentajes) if porcentajes else 0
        
        if total_porcentaje < 98:
            logger.warning(f"[ACTA] Suma porcentajes={total_porcentaje:.2f}% < 98% - Activando BACKUP ROBUSTO")
            
            # 1. Intentar extraer accionistas adicionales con regex backup
            accionistas_backup = _extract_accionistas_regex_backup(text_ocr, estructura)
            
            if accionistas_backup:
                logger.info(f"[ACTA] Backup encontró {len(accionistas_backup)} accionista(s) adicional(es)")
                estructura.extend(accionistas_backup)
                result["_backup_regex_aplicado"] = True
                result["_accionistas_backup"] = len(accionistas_backup)
            
            # 2. Si aún < 98% y tenemos LLM, re-extraer con prompt especializado
            porcentajes_post = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
            total_post = sum(porcentajes_post) if porcentajes_post else 0
            
            if total_post < 98 and llm is not None:
                logger.warning(f"[ACTA] Aún {total_post:.2f}% < 98% - Intentando re-extracción LLM")
                accionistas_llm = _reextract_estructura_accionaria(text_ocr, llm)
                
                if accionistas_llm:
                    # Fusionar con los existentes (sin duplicar, pero enriqueciendo si faltan datos)
                    nombres_existentes = {_strip_accents(a.get("nombre", "").upper().strip()) for a in estructura}
                    for acc_nuevo in accionistas_llm:
                        nombre_nuevo = _strip_accents(acc_nuevo.get("nombre", "").upper().strip())
                        if not nombre_nuevo or not es_nombre_persona_valido(acc_nuevo.get("nombre", "")):
                            continue
                        if nombre_nuevo not in nombres_existentes:
                            estructura.append(acc_nuevo)
                            nombres_existentes.add(nombre_nuevo)
                            logger.info(f"[ACTA] LLM re-extracción agregó: {nombre_nuevo}")
                        elif acc_nuevo.get("acciones") is not None:
                            # Enriquecer existente si le faltan datos numéricos
                            for acc_ex in estructura:
                                if _strip_accents(acc_ex.get("nombre", "").upper().strip()) == nombre_nuevo:
                                    if acc_ex.get("acciones") is None:
                                        acc_ex["acciones"] = acc_nuevo["acciones"]
                                        acc_ex["porcentaje"] = acc_nuevo.get("porcentaje")
                                        acc_ex["_enriquecido_por"] = "reextraccion_llm"
                                        logger.info(f"[ACTA] LLM re-extracción enriqueció: {nombre_nuevo}")
                                    break
                    
                    result["_reextraccion_llm_aplicada"] = True
            
            # 2.5. Si aún <98%, usar búsqueda multi-sección (comparecientes + texto libre)
            porcentajes_post2 = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
            total_post2 = sum(porcentajes_post2) if porcentajes_post2 else 0
            
            if total_post2 < 98:
                logger.info("[ACTA] Intentando búsqueda multi-sección (comparecientes + texto libre)")
                total_acciones_doc = None
                try:
                    total_acciones_doc = int(str(result.get("total_acciones", "0")).replace(",", "").replace(".", ""))
                except (ValueError, TypeError):
                    pass
                
                socios_multi, tipo_extraccion = _extract_accionistas_multiseccion(text_ocr, total_acciones_doc)
                
                if socios_multi:
                    nombres_existentes_ms = {_strip_accents(" ".join(a.get("nombre", "").upper().split())) for a in estructura}
                    for sm in socios_multi:
                        nombre_sm = _strip_accents(" ".join(sm.get("nombre", "").upper().split()))
                        if not nombre_sm or not es_nombre_persona_valido(sm.get("nombre", "")):
                            continue
                        if nombre_sm not in nombres_existentes_ms:
                            estructura.append(sm)
                            nombres_existentes_ms.add(nombre_sm)
                            logger.info(f"[ACTA] Multi-sección agregó: {sm.get('nombre')}")
                        elif sm.get("acciones") is not None:
                            # Enriquecer existente si le faltan datos numéricos
                            for acc_ex in estructura:
                                if _strip_accents(" ".join(acc_ex.get("nombre", "").upper().split())) == nombre_sm:
                                    if acc_ex.get("acciones") is None:
                                        acc_ex["acciones"] = sm["acciones"]
                                        acc_ex["porcentaje"] = sm.get("porcentaje")
                                        acc_ex["_enriquecido_por"] = "multiseccion_backup"
                                        logger.info(f"[ACTA] Multi-sección enriqueció: {nombre_sm}")
                                    break
                    
                    result["_multiseccion_aplicada"] = True
                    result["_tipo_extraccion_multiseccion"] = tipo_extraccion
                    
                    # Si tipo es "estructura_implicita", actualizar status
                    if tipo_extraccion == "estructura_implicita":
                        result["_estructura_accionaria_status"] = "Estructura_Implicita"
                        result["_nota_estructura"] = (
                            "Los socios se identificaron como comparecientes pero el documento "
                            "no especifica distribución individual de acciones. "
                            "Puede ser una S de RL donde los porcentajes están en otra cláusula."
                        )
            
            # 3. Deduplicar por nombre similar (ordenar por longitud de nombre, más largo primero)
            estructura_ordenada = sorted(estructura, key=lambda x: len(x.get("nombre", "")), reverse=True)
            nombres_vistos = set()
            estructura_dedup = []
            
            for acc in estructura_ordenada:
                nombre = acc.get("nombre", "").upper().strip()
                # Normalizar removiendo espacios extra, caracteres especiales Y acentos
                nombre_norm = _strip_accents(" ".join(nombre.split()))
                
                # Solo mantener nombres de longitud razonable (>= 12 caracteres)
                if len(nombre_norm) < 12:
                    continue
                    
                # Verificar si es duplicado o subconjunto de otro nombre
                es_duplicado = False
                for nombre_visto in nombres_vistos:
                    if nombre_norm in nombre_visto or nombre_visto in nombre_norm:
                        es_duplicado = True
                        # Si el duplicado tiene datos mejores, enriquecer al que ya se vio
                        if acc.get("porcentaje") is not None:
                            for acc_visto in estructura_dedup:
                                n_v = _strip_accents(" ".join(acc_visto.get("nombre", "").upper().split()))
                                if n_v == nombre_visto and acc_visto.get("porcentaje") is None:
                                    acc_visto["porcentaje"] = acc.get("porcentaje")
                                    acc_visto["acciones"] = acc.get("acciones", acc_visto.get("acciones"))
                                    logger.info(f"[ACTA] Dedup enriqueció: {nombre_visto}")
                                    break
                        break
                
                if not es_duplicado and nombre_norm:
                    nombres_vistos.add(nombre_norm)
                    estructura_dedup.append(acc)
            
            if len(estructura_dedup) != len(estructura):
                logger.info(f"[ACTA] Deduplicación: {len(estructura)} → {len(estructura_dedup)} socios")
                estructura = estructura_dedup
            
            # 4. Recalcular suma y confiabilidad final
            porcentajes_final = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
            total_final = sum(porcentajes_final) if porcentajes_final else 0
            
            result["_suma_porcentajes"] = round(total_final, 2)
            result["_porcentajes_validos"] = abs(total_final - 100.0) <= 2.0
            
            # Recalcular confiabilidad
            if result.get("_porcentajes_validos"):
                result["_estructura_confiabilidad"] = 1.0
                result["_estructura_accionaria_status"] = "Verificada"
            elif total_final >= 95:
                result["_estructura_confiabilidad"] = 0.9
                result["_estructura_accionaria_status"] = "Verificada"
            elif total_final >= 80:
                result["_estructura_confiabilidad"] = 0.7
                result["_estructura_accionaria_status"] = "Parcial"
            
            result["estructura_accionaria"] = estructura
            logger.info(f"[ACTA] BACKUP ROBUSTO completado: {len(estructura)} socios, {total_final:.2f}%")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 10. AGREGAR EVIDENCIA DE EXTRACCIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    result = _add_extraction_evidence(result, text_ocr)
    
    return result


def _extract_tabla_accionistas_estructurada(texto: str) -> list:
    """
    Extrae accionistas de tablas estructuradas en Actas Constitutivas.
    Busca secciones con encabezados ACCIONISTA/ACCIONES/VALOR/IMPORTE o similares
    y extrae los datos fila por fila.
    
    Maneja formatos:
    1. NOMBRE / ACCIONES / VALOR (linealizado OCR)
    2. NOMBRE / ACCIONES / IMPORTE / RFC / CURP (con datos fiscales intermedios)
    3. NOMBRE + ACCIONES en misma línea
    
    Retorna lista de dict con: nombre, acciones, valor (si disponible)
    """
    socios = []
    texto_upper = texto.upper()
    
    # Buscar la sección que contiene la tabla de accionistas
    # Patrones de inicio de tabla
    patron_inicio_tabla = r'(?:ACCIONISTAS?\s*(?:ACCIONES?|PARTES)\s*(?:VALOR|IMPORTE)?|' \
                         r'SUSCR[IÍ]BENSE?\s+(?:LAS?\s+)?ACCIONES?\s+(?:DE\s+)?(?:LA\s+)?(?:SIGUIENTE|ASÍ)|' \
                         r'CAPITAL\s+(?:SOCIAL\s+)?(?:QUEDA\s+)?(?:SUSCRITO|REPRESENTADO)\s+(?:COMO\s+)?(?:SIGUE|ASÍ)|' \
                         r'(?:QUEDA\s+)?SUSCRITO\s+Y\s*\n?\s*PAGADO\s+(?:DE\s+)?LA\s+SIGUIENTE\s+MANERA|' \
                         r'REPRESENTADO\s+DE\s+LA\s+SIGUIENTE\s+MANERA)'
    
    match_inicio = re.search(patron_inicio_tabla, texto_upper)
    if not match_inicio:
        return []
    
    # Tomar texto desde el inicio de la tabla hasta "TOTAL" o "SEGUNDO" o similar
    inicio = match_inicio.end()
    # Buscar fin de tabla
    patron_fin = r'(?:\bTOTAL\b|\bSEGUNDO\b|\bSEGUNDA\b|\bTERCER[OA]?\b|\bNOMBRAMIENTO\b|---\s*SEGUND|---\s*TERCER|\n---\s*[A-Z]{4,})'
    match_fin = re.search(patron_fin, texto_upper[inicio:])
    
    if match_fin:
        seccion_tabla = texto_upper[inicio:inicio + match_fin.start()]
    else:
        # Tomar hasta 3000 caracteres si no encontramos fin
        seccion_tabla = texto_upper[inicio:inicio + 3000]
    
    # Líneas a ignorar (encabezados, RFC, CURP, etc.)
    patrones_ignorar = [
        r'^ACCIONISTAS?$', r'^ACCIONES?$', r'^VALOR$', r'^IMPORTE$', r'^SERIE$',
        r'^IM$',  # Fragmento de IMPORTE
        r'^REGISTRO\s+FEDERAL', r'^RFC', r'^CURP', r'^\$', r'^MONEDA',
        r'^[A-Z]{4}\d{6}', r'^\d{6}[A-Z]',  # Patrones de RFC/CURP
        r'^COTEJADO', r'^NACIONAL', r'^PESOS'
    ]
    
    def es_linea_ignorable(linea: str) -> bool:
        linea = linea.strip()
        for patron in patrones_ignorar:
            if re.match(patron, linea):
                return True
        return len(linea) < 3
    
    def es_nombre_valido_tabla(linea: str) -> bool:
        """Verifica si la línea parece un nombre de persona"""
        linea = linea.strip()
        # Debe tener al menos 2 palabras y empezar con letra
        if not re.match(r'^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,}$', linea):
            return False
        # No debe ser RFC/CURP ni contener números
        if re.search(r'\d', linea):
            return False
        # Debe tener al menos 2 palabras de más de 2 letras
        palabras = [p for p in linea.split() if len(p) > 2]
        return len(palabras) >= 2
    
    lineas = seccion_tabla.split('\n')
    i = 0
    while i < len(lineas):
        linea = lineas[i].strip()
        
        # Saltar líneas ignorables
        if es_linea_ignorable(linea):
            i += 1
            continue
        
        # Verificar si la línea parece un nombre de persona
        if es_nombre_valido_tabla(linea):
            nombre_candidato = linea
            encontrado = False
            
            # Buscar acciones en las siguientes líneas, manejando nombres multi-línea
            # El OCR puede partir un nombre en 2 líneas:
            #   "MARTHA GONZÁLEZ"   <- línea 1
            #   "GARCÍA       100"  <- línea 2 (apellido + acciones)
            for j in range(i + 1, min(i + 10, len(lineas))):
                linea_sig = lineas[j].strip()
                
                # ¿Es un número puro? (acciones)
                # IMPORTANTE: verificar ANTES de es_linea_ignorable() porque
                # números cortos como "5" o "45" (len < 3) serían filtrados.
                if re.match(r'^\d{1,6}$', linea_sig):
                    acciones = int(linea_sig)
                    socios.append({
                        "nombre": nombre_candidato.title(),
                        "acciones": acciones,
                        "_patron": "tabla_ocr_busqueda"
                    })
                    i = j + 1
                    encontrado = True
                    break
                
                # Saltar líneas ignorables (RFC, CURP, $valores, etc.)
                if es_linea_ignorable(linea_sig):
                    continue
                
                # ¿Es fragmento de nombre (1-3 palabras uppercase) seguido de número?
                # Maneja OCR multi-línea: "GARCÍA           100"
                match_frag_num = re.match(
                    r'^([A-ZÁÉÍÓÚÑ]{2,25}(?:\s+[A-ZÁÉÍÓÚÑ]{2,25}){0,2})\s{2,}(\d{1,6})(?:\s|$)',
                    linea_sig
                )
                if match_frag_num:
                    fragmento = match_frag_num.group(1).strip()
                    acciones = int(match_frag_num.group(2))
                    nombre_completo = nombre_candidato + " " + fragmento
                    socios.append({
                        "nombre": nombre_completo.title(),
                        "acciones": acciones,
                        "_patron": "tabla_ocr_multilinea_fusionado"
                    })
                    i = j + 1
                    encontrado = True
                    break
                
                # ¿Es fragmento de nombre + número pegado? "GARCÍA100"
                match_frag_pegado = re.match(
                    r'^([A-ZÁÉÍÓÚÑ]{2,25}(?:\s+[A-ZÁÉÍÓÚÑ]{2,25}){0,1})(\d{1,6})$',
                    linea_sig
                )
                if match_frag_pegado:
                    fragmento = match_frag_pegado.group(1).strip()
                    acciones = int(match_frag_pegado.group(2))
                    nombre_completo = nombre_candidato + " " + fragmento
                    socios.append({
                        "nombre": nombre_completo.title(),
                        "acciones": acciones,
                        "_patron": "tabla_ocr_multilinea_pegado"
                    })
                    i = j + 1
                    encontrado = True
                    break
                
                # ¿Es solo continuación de nombre? (1-2 palabras uppercase sin números)
                # Ejemplo: nombre_candidato="MARTHA GONZÁLEZ", linea_sig="GARCÍA"
                if re.match(r'^[A-ZÁÉÍÓÚÑ]{2,25}(?:\s+[A-ZÁÉÍÓÚÑ]{2,25})?$', linea_sig):
                    palabras = linea_sig.split()
                    if len(palabras) <= 2:
                        nombre_candidato = nombre_candidato + " " + linea_sig.strip()
                        continue  # Seguir buscando acciones
                
                # Si encontramos otro nombre completo (3+ palabras), no hay acciones
                if es_nombre_valido_tabla(linea_sig):
                    break
            
            if not encontrado:
                i += 1
            continue
        
        # Formato alternativo: NOMBRE + número pegado o en misma línea
        match_nombre_num = re.match(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,45})(\d{1,6})$', linea)
        if match_nombre_num:
            nombre = match_nombre_num.group(1).strip()
            if es_nombre_valido_tabla(nombre):
                acciones = int(match_nombre_num.group(2))
                socios.append({
                    "nombre": nombre.title(),
                    "acciones": acciones,
                    "_patron": "tabla_ocr_nombre_num_pegado"
                })
            i += 1
            continue
        
        # Formato con espacios múltiples: "NOMBRE    45    $45,000.00"
        match_espacios = re.match(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,45})\s{2,}(\d{1,6})(?:\s|$)', linea)
        if match_espacios:
            nombre = match_espacios.group(1).strip()
            if es_nombre_valido_tabla(nombre):
                acciones = int(match_espacios.group(2))
                socios.append({
                    "nombre": nombre.title(),
                    "acciones": acciones,
                    "_patron": "tabla_ocr_espacios"
                })
            i += 1
            continue
        
        i += 1
    
    return socios


def _extract_accionistas_multiseccion(text_ocr: str, total_acciones: int = None) -> tuple:
    """
    Búsqueda multi-sección: identifica socios en TODAS las secciones del documento.
    
    Implementa 3 pasos:
    PASO 1: Identifica TODAS las personas mencionadas en secciones relevantes
    PASO 2: Para cada persona, busca en ±5 líneas información de acciones/porcentajes
    PASO 3: Asocia información aunque no esté en formato tabla
    
    Busca en:
    1. Tablas de distribución de capital (más confiable)
    2. Sección de COMPARECIENTES (donde se presenta cada socio)
    3. Cláusulas de CAPITAL SOCIAL
    4. Sección de SUSCRIPCIÓN Y PAGO DE ACCIONES
    5. Texto libre con keywords: "suscribe", "titular de", "le corresponden",
       "aporta", "acciones representativas", "partes sociales"
    
    Returns:
        (lista_accionistas, tipo_extraccion)
        tipo_extraccion: "tabla", "clausula", "comparecientes", "texto_libre",
                         "estructura_implicita", "no_encontrada"
    """
    import unicodedata
    
    def _norm(nombre: str) -> str:
        if not nombre:
            return ""
        nombre = unicodedata.normalize('NFKD', nombre)
        nombre = ''.join(c for c in nombre if not unicodedata.combining(c))
        return ' '.join(nombre.upper().split())
    
    def _es_nombre_persona(nombre: str) -> bool:
        """Verifica si un string parece nombre de persona (no notario, no frase legal).
        
        Validaciones robustas:
        1. Longitud y estructura mínima
        2. Sin palabras prohibidas (legales, institucionales, números en texto)
        3. No empieza con artículos
        4. No termina con preposiciones/artículos
        5. Al menos 2 palabras "significativas" (≥3 chars, no artículos)
        """
        if not nombre or len(nombre) < 10 or nombre.count(' ') < 1:
            return False
        if len(re.findall(r'\d', nombre)) > 2:
            return False
        
        nombre_up = nombre.upper()
        palabras = nombre_up.split()
        
        # --- Palabras prohibidas (substring match) ---
        prohibidas = [
            # Institucional / Notarial
            'NOTARIO', 'ESCRITURA', 'CAPITAL', 'SOCIEDAD', 'ASAMBLEA',
            'ARTICULO', 'CLAUSULA', 'ESTATUTO', 'FOLIO', 'REGISTRO',
            'NACIONAL', 'PUBLICO', 'PUBLICA', 'NUMERO', 'TESTIMONIO',
            'ACCIONISTAS', 'ACCIONES', 'VALOR', 'SERIE', 'PORCENTAJE',
            'MONEDA', 'PESOS', 'TOTAL', 'CORREDOR', 'LICENCIADO',
            'FEDATARIO', 'SECRETARIO', 'JUEZ', 'TRIBUNAL',
            # Legal / Administrativo
            'LEY', 'FEDERAL', 'PROCEDIMIENTO', 'ADMINISTRATIV',
            'DECRETO', 'REGLAMENTO', 'FRACCION', 'DISPOSICION',
            'LEGISLACION', 'CODIGO', 'MERCANTIL', 'COMERCIO',
            'CONSTITUTIVA', 'OBJETO', 'DENOMINACION', 'DURACION',
            'PROPORCION', 'REALIZACION', 'OBLIGACION',
            # Números en texto (bloquea "NOVENTA Y CINCO", "NOVECIENTOS...", etc.)
            'NOVENTA', 'OCHENTA', 'SETENTA', 'SESENTA', 'CINCUENTA',
            'CUARENTA', 'TREINTA', 'NOVECIENTOS', 'OCHOCIENTOS',
            'SETECIENTOS', 'SEISCIENTOS', 'QUINIENTOS', 'CUATROCIENTOS',
            'TRESCIENTOS', 'DOSCIENTOS', 'CIENTO',
        ]
        if any(p in nombre_up for p in prohibidas):
            return False
        
        # --- Rechazar si empieza con artículos ---
        if palabras[0] in ('LA', 'EL', 'LOS', 'LAS', 'DEL', 'AL', 'UNA', 'UN'):
            return False
        
        # --- Rechazar si termina con preposiciones/artículos/conjunciones ---
        if palabras[-1] in ('DE', 'DEL', 'EN', 'A', 'AL', 'LA', 'EL', 'LOS', 'LAS',
                            'SUS', 'SU', 'Y', 'O', 'POR', 'CON', 'QUE', 'BIS'):
            return False
        
        # --- Al menos 2 palabras "significativas" (≥3 chars y no artículos/preposiciones) ---
        palabras_funcion = {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y', 'EN',
                            'A', 'AL', 'O', 'E', 'SU', 'SUS', 'POR', 'CON'}
        palabras_sig = [p for p in palabras if len(p) >= 3 and p not in palabras_funcion]
        if len(palabras_sig) < 2:
            return False
        
        return True
    
    def _limpiar_nombre(nombre: str) -> str:
        nombre = re.sub(r'\s+', ' ', nombre.strip())
        # Remover prefijos de tratamiento (El Señor, La Señora, C., Lic., etc.)
        nombre = re.sub(
            r'^(?:EL\s+|LA\s+)?(?:SR\.?\s*|SRA\.?\s*|C\.?\s+|LIC\.?\s*|ING\.?\s*|'
            r'DR\.?\s*|MTRO\.?\s*|CIUDADANO\s+|SE[ÑN]OR\s+|SE[ÑN]ORA?\s+)',
            '', nombre, flags=re.IGNORECASE
        )
        # Remover sufijos (quienes, de nacionalidad, con domicilio, etc.)
        nombre = re.sub(
            r'\s+(?:QUIEN|QUIENES|POR\s+SU|QUE\s+SE|Y\s+EL|Y\s+LA|DE\s+NACIONALIDAD|'
            r'MEXICANO|MEXICANA|CON\s+DOMICILIO|CASADO|CASADA|SOLTERO|SOLTERA|'
            r'MAYOR\s+DE|CON\s+CREDENCIAL|CON\s+RFC|IDENTIFICÁNDOSE|IDENTIFICANDOSE|'
            r'SE\s+IDENTIFICA|ORIGINARI[OA]).*$',
            '', nombre, flags=re.IGNORECASE
        )
        return nombre.strip()
    
    texto_upper = text_ocr.upper()
    lineas = text_ocr.split('\n')
    lineas_upper = texto_upper.split('\n')
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PASO 1: Identificar TODAS las personas en secciones relevantes
    # ═══════════════════════════════════════════════════════════════════════════
    
    personas = {}  # nombre_norm -> {nombre_original, seccion, linea_idx}
    
    # --- 1A. COMPARECIENTES ---
    patron_comp_inicio = re.compile(
        r'(?:COMPARECE[N]?\s|COMPARECIENTES|ANTE\s+MI[,\s]+(?:EL\s+)?(?:NOTARIO|SUSCRITO).*?COMPARECE[N]?|'
        r'ANTE\s+MI\s+FE\s+COMPARECE[N]?)',
        re.IGNORECASE
    )
    for m in patron_comp_inicio.finditer(texto_upper):
        inicio_idx = m.start()
        # Buscar fin de sección comparecientes
        texto_despues = texto_upper[inicio_idx:inicio_idx + 8000]
        fin_match = re.search(
            r'(?:DECLARA[N]?\s*[:\-]|ANTECEDENTES|ESTATUTOS\s+SOCIALES|CLÁUSULAS?\s+PRIMERA)',
            texto_despues
        )
        seccion = texto_despues[:fin_match.start() if fin_match else 5000]
        
        # Extraer nombres de personas con varios patrones
        patrones_persona = [
            r'(?:EL\s+)?(?:SE[ÑN]OR|SR\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)(?:\s*,|\s+CON\s|\s+DE\s+NACIONALIDAD|\s+MEXICANO|\s+QUIEN)',
            r'(?:LA\s+)?(?:SE[ÑN]ORA|SRA\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)(?:\s*,|\s+CON\s|\s+DE\s+NACIONALIDAD|\s+MEXICANA|\s+QUIEN)',
            r'(?:EL\s+)?(?:C\.?\s+|CIUDADANO\s+)([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)(?:\s*,|\s+CON\s|\s+DE\s+NACIONALIDAD)',
            # Nombres entre separadores en listas de comparecientes
            r'(?:^|\n)\s*(?:[-•\d]+[.)]\s*)?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{10,55}?)(?:\s*,\s*(?:MEXICANO|MEXICANA|MAYOR|CON\s+DOMICILIO))',
        ]
        
        for patron in patrones_persona:
            for match_p in re.finditer(patron, seccion, re.IGNORECASE | re.MULTILINE):
                nombre_raw = _limpiar_nombre(match_p.group(1))
                nombre_norm = _norm(nombre_raw)
                if _es_nombre_persona(nombre_norm):
                    # Encontrar la línea correspondiente en el documento original
                    pos_abs = inicio_idx + match_p.start()
                    linea_aprox = text_ocr[:pos_abs].count('\n')
                    if nombre_norm not in personas:
                        personas[nombre_norm] = {
                            'nombre_original': nombre_raw.title() if nombre_raw.isupper() else nombre_raw,
                            'seccion': 'comparecientes',
                            'linea_idx': linea_aprox,
                        }
    
    # --- 1B. SECCIÓN CAPITAL SOCIAL / SUSCRIPCIÓN Y PAGO ---
    patron_capital = re.compile(
        r'(?:CAPITAL\s+SOCIAL|SUSCRIPCI[ÓO]N\s+Y\s+PAGO|DISTRIBUCI[ÓO]N\s+(?:DE[L]?\s+)?(?:CAPITAL|ACCIONES)|'
        r'APORTACIONES?\s+(?:DE\s+)?(?:LOS?\s+)?SOCIOS)',
        re.IGNORECASE
    )
    for m in patron_capital.finditer(texto_upper):
        inicio_idx = m.start()
        seccion = texto_upper[max(0, inicio_idx - 200):inicio_idx + 8000]
        
        # Buscar nombres con contexto de acciones
        patrones_cap = [
            r'(?:EL\s+)?(?:SE[ÑN]OR|C\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(?:SUSCRIBE|APORTA|EXHIBE)',
            r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(?:SUSCRIBE|APORTA|ES\s+TITULAR)',
        ]
        for patron in patrones_cap:
            for match_p in re.finditer(patron, seccion, re.IGNORECASE):
                nombre_raw = _limpiar_nombre(match_p.group(1))
                nombre_norm = _norm(nombre_raw)
                if _es_nombre_persona(nombre_norm):
                    pos_abs = max(0, inicio_idx - 200) + match_p.start()
                    linea_aprox = text_ocr[:pos_abs].count('\n')
                    if nombre_norm not in personas:
                        personas[nombre_norm] = {
                            'nombre_original': nombre_raw.title(),
                            'seccion': 'capital_social',
                            'linea_idx': linea_aprox,
                        }
    
    # --- 1C. TEXTO LIBRE - Patrones directos con datos de acciones ---
    patrones_texto_libre = [
        # "NOMBRE suscribe N acciones"
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(?:QUIEN\s+)?SUSCRIBE\s+(\d{1,6})\s*'
         r'(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)', 'suscribe', 'acciones'),
        # "NOMBRE es titular de N partes sociales"
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(?:ES\s+)?TITULAR\s+DE\s+(\d{1,6})\s*'
         r'(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)', 'titular', 'acciones'),
        # "correspondiéndole a NOMBRE N acciones"
        (r'CORRESPONDI[ÉE]NDOLE\s+A\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(\d{1,6})\s*'
         r'(?:\([^)]*\))?\s*(?:ACCIONES|PARTES)', 'correspondiente', 'acciones'),
        # "NOMBRE aporta N acciones" (directo)
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+APORTA\s+(\d{1,6})\s*'
         r'(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)', 'aporta', 'acciones'),
        # "NOMBRE aporta... correspondiente a / importe de N acciones" (con monto intermedio)
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+APORTA.{0,250}?'
         r'(?:CORRESPONDIENTES?\s+A|IMPORTE\s+DE|EQUIVALENTES?\s+A)\s+'
         r'(\d{1,6})\s*(?:\([^)]*\))?\s*ACCIONES', 'aporta_correspondiente', 'acciones'),
        # "le corresponden N acciones" (buscar nombre antes)
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s+(?:A\s+QUIEN\s+)?LE\s+CORRESPONDE[N]?\s+(\d{1,6})\s*'
         r'(?:\([^)]*\))?\s*(?:ACCIONES|PARTES)', 'le_corresponden', 'acciones'),
        # "NOMBRE, representativas del N%"
        (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55}?)\s*,?\s*(?:REPRESENTATIVAS?\s+DEL?|EQUIVALENTES?\s+AL?|'
         r'QUE\s+REPRESENTAN?)\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*%', 'representativas', 'porcentaje'),
        # "el X% del capital ... representado por NOMBRE"
        (r'(\d{1,3}(?:[.,]\d{1,2})?)\s*%\s*(?:DEL\s+)?(?:CAPITAL\s+)?(?:SOCIAL\s+)?'
         r'(?:REPRESENTADO\s+POR|CORRESPONDIENTE\s+A|PERTENECIENTE\s+A)\s+'
         r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,55})', 'pct_representado', 'porcentaje_inv'),
    ]
    
    accionistas_directos = {}  # nombre_norm -> datos
    
    for patron, tipo, dato_tipo in patrones_texto_libre:
        for match_tl in re.finditer(patron, texto_upper, re.IGNORECASE | re.DOTALL):
            if dato_tipo == 'porcentaje_inv':
                porcentaje = float(match_tl.group(1).replace(',', '.'))
                nombre_raw = _limpiar_nombre(match_tl.group(2))
                nombre_norm = _norm(nombre_raw)
                if _es_nombre_persona(nombre_norm) and 0 < porcentaje <= 100:
                    if nombre_norm not in accionistas_directos:
                        accionistas_directos[nombre_norm] = {
                            'nombre': nombre_raw.title(),
                            'acciones': None,
                            'porcentaje': porcentaje,
                            '_patron': f'texto_libre_{tipo}',
                            '_confiabilidad': 0.85,
                        }
            elif dato_tipo == 'porcentaje':
                nombre_raw = _limpiar_nombre(match_tl.group(1))
                porcentaje = float(match_tl.group(2).replace(',', '.'))
                nombre_norm = _norm(nombre_raw)
                if _es_nombre_persona(nombre_norm) and 0 < porcentaje <= 100:
                    if nombre_norm not in accionistas_directos:
                        accionistas_directos[nombre_norm] = {
                            'nombre': nombre_raw.title(),
                            'acciones': None,
                            'porcentaje': porcentaje,
                            '_patron': f'texto_libre_{tipo}',
                            '_confiabilidad': 0.85,
                        }
            else:  # acciones
                nombre_raw = _limpiar_nombre(match_tl.group(1))
                acciones = int(match_tl.group(2))
                nombre_norm = _norm(nombre_raw)
                if _es_nombre_persona(nombre_norm):
                    if nombre_norm not in accionistas_directos:
                        accionistas_directos[nombre_norm] = {
                            'nombre': nombre_raw.title(),
                            'acciones': acciones,
                            'porcentaje': None,
                            '_patron': f'texto_libre_{tipo}',
                            '_confiabilidad': 0.90,
                        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PASO 2: Para cada persona de COMPARECIENTES, buscar ±5 líneas
    # ═══════════════════════════════════════════════════════════════════════════
    
    accionistas_proximidad = {}
    
    for nombre_norm, datos_persona in personas.items():
        # Si ya lo encontramos con datos directos, priorizar eso
        if nombre_norm in accionistas_directos and accionistas_directos[nombre_norm].get('acciones'):
            continue
        
        linea_idx = datos_persona['linea_idx']
        nombre_orig = datos_persona['nombre_original']
        
        # Buscar en ±5 líneas alrededor de donde aparece el nombre
        rango_inicio = max(0, linea_idx - 5)
        rango_fin = min(len(lineas_upper), linea_idx + 6)
        contexto = '\n'.join(lineas_upper[rango_inicio:rango_fin])
        
        acciones_encontradas = None
        porcentaje_encontrado = None
        
        # Buscar número + "acciones"/"partes sociales" en contexto próximo
        # CUIDADO: excluir contextos de "total" o "dividido en" (capital global)
        m_acc = re.search(
            r'(?:SUSCRIBE|APORTA|EXHIBE|TITULAR\s+DE|LE\s+CORRESPONDE[N]?)\s+'
            r'(\d{1,6})\s*(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)',
            contexto
        )
        if m_acc:
            acciones_encontradas = int(m_acc.group(1))
        
        # Buscar genérico N acciones, pero excluir "dividido en N" y "total de N"
        if not acciones_encontradas:
            for m_acc2 in re.finditer(
                r'(\d{1,6})\s*(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)',
                contexto
            ):
                num = int(m_acc2.group(1))
                # Verificar que no sea el total de acciones del documento
                if total_acciones and num == total_acciones:
                    continue  # Es el total, no acciones individuales
                # Verificar que NO esté precedido por "dividido en", "total de", etc.
                pre = contexto[:m_acc2.start()].rstrip()
                if re.search(r'(?:DIVIDIDO\s+EN|TOTAL\s+DE|CAPITAL\s+DE)\s*$', pre):
                    continue  # Contexto de capital global
                acciones_encontradas = num
                break
        
        # Buscar "titular de N"
        m_tit = re.search(r'TITULAR\s+DE\s+(\d{1,6})', contexto)
        if m_tit and not acciones_encontradas:
            acciones_encontradas = int(m_tit.group(1))
        
        # Buscar porcentaje
        m_pct = re.search(r'(\d{1,3}(?:[.,]\d{1,2})?)\s*%', contexto)
        if m_pct:
            pct = float(m_pct.group(1).replace(',', '.'))
            if 0 < pct <= 100:
                porcentaje_encontrado = pct
        
        # También buscar en TODA la sección de capital social / suscripción
        # usando los apellidos del compareciente como clave de búsqueda
        if not acciones_encontradas:
            palabras_nombre = nombre_norm.split()
            if len(palabras_nombre) >= 2:
                # Usar apellidos para una búsqueda más robusta
                apellido_patron = r'\s+'.join(re.escape(p) for p in palabras_nombre[-2:])
                # Buscar: "APELLIDOS ... suscribe/aporta ... correspondiente a / importe de N acciones"
                patron_global_corr = (
                    apellido_patron + r'.{0,300}?'
                    r'(?:SUSCRIBE|APORTA|EXHIBE|TITULAR).{0,200}?'
                    r'(?:CORRESPONDIENTES?\s+A|IMPORTE\s+DE|EQUIVALENTES?\s+A)\s+'
                    r'(\d{1,6})\s*(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)'
                )
                m_global_corr = re.search(patron_global_corr, texto_upper, re.DOTALL)
                if m_global_corr:
                    num = int(m_global_corr.group(1))
                    if not (total_acciones and num == total_acciones):
                        acciones_encontradas = num
                
                # Buscar: "APELLIDOS ... suscribe/aporta ... N acciones" (directo, sin monto intermedio)
                if not acciones_encontradas:
                    patron_global = (
                        apellido_patron + r'.{0,100}?'
                        r'(?:SUSCRIBE|APORTA|EXHIBE|TITULAR)\s+'
                        r'(\d{1,6})\s*(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)'
                    )
                    m_global = re.search(patron_global, texto_upper, re.DOTALL)
                    if m_global:
                        acciones_encontradas = int(m_global.group(1))
                    
                # Buscar patrón inverso: "N acciones... suscritas por APELLIDOS"
                if not acciones_encontradas:
                    patron_inv = (
                        r'(\d{1,6})\s*(?:\([^)]*\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)'
                        r'.{0,100}?' + apellido_patron
                    )
                    m_inv = re.search(patron_inv, texto_upper, re.DOTALL)
                    if m_inv:
                        num = int(m_inv.group(1))
                        # Verificar que no sea total
                        if not (total_acciones and num == total_acciones):
                            acciones_encontradas = num
        
        if acciones_encontradas or porcentaje_encontrado:
            accionistas_proximidad[nombre_norm] = {
                'nombre': nombre_orig,
                'acciones': acciones_encontradas,
                'porcentaje': porcentaje_encontrado,
                '_patron': 'proximidad_' + datos_persona['seccion'],
                '_confiabilidad': 0.75 if acciones_encontradas else 0.60,
                '_seccion': datos_persona['seccion'],
            }
        else:
            # MODIFICADO: NO generar entradas 'solo_compareciente' aquí.
            # Las entradas sin datos de acciones generan basura y falsos positivos.
            # Solo registramos como compareciente si ya hay evidencia de datos reales
            # en accionistas_directos o si otros patrones encontraron datos.
            # Las entradas sin datos se agregarán solo al final si hay contexto válido.
            pass
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PASO 3: Consolidar resultados con deduplicación inteligente
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _es_mismo_nombre(n1: str, n2: str) -> bool:
        """Verifica si dos nombres normalizados refieren a la misma persona."""
        if n1 == n2:
            return True
        p1 = set(n1.split())
        p2 = set(n2.split())
        # Si comparten al menos 2 palabras significativas (>2 chars) y una es subconjunto
        p1_sig = {w for w in p1 if len(w) > 2}
        p2_sig = {w for w in p2 if len(w) > 2}
        comunes = p1_sig & p2_sig
        if len(comunes) >= 2 and (p1_sig.issubset(p2_sig) or p2_sig.issubset(p1_sig)):
            return True
        return False
    
    def _buscar_duplicado(nombre_norm: str, diccionario: dict) -> str | None:
        """Busca si nombre_norm ya existe como variante en el diccionario."""
        for clave in diccionario:
            if _es_mismo_nombre(nombre_norm, clave):
                return clave
        return None
    
    resultado = {}
    
    # Prioridad 1: accionistas encontrados directamente con texto libre
    for nombre_norm, datos in accionistas_directos.items():
        dup = _buscar_duplicado(nombre_norm, resultado)
        if dup:
            # Fusionar: priorizar el que tiene datos más completos
            if resultado[dup].get('acciones') is None and datos.get('acciones') is not None:
                resultado[dup].update(datos)
        else:
            resultado[nombre_norm] = datos
    
    # Prioridad 2: accionistas encontrados por proximidad
    for nombre_norm, datos in accionistas_proximidad.items():
        dup = _buscar_duplicado(nombre_norm, resultado)
        if dup:
            if resultado[dup].get('acciones') is None and datos.get('acciones') is not None:
                resultado[dup]['acciones'] = datos['acciones']
                resultado[dup]['porcentaje'] = datos.get('porcentaje')
                resultado[dup]['_confiabilidad'] = max(
                    resultado[dup].get('_confiabilidad', 0),
                    datos.get('_confiabilidad', 0)
                )
        else:
            resultado[nombre_norm] = datos
    
    # Construir lista final
    socios_result = []
    for nombre_norm, datos in resultado.items():
        es_moral = any(s in nombre_norm for s in [
            'S.A.', 'SAPI', 'S.C.', 'A.C.', 'S DE RL', 'LLC', 'FIDEICOMISO'
        ])
        
        socio = {
            'nombre': datos.get('nombre', nombre_norm.title()),
            'tipo': 'moral' if es_moral else 'fisica',
            'acciones': datos.get('acciones'),
            'porcentaje': datos.get('porcentaje'),
            'serie': 'A',
            'es_fundador': True,
            '_extraido_por': 'multiseccion',
            '_confiabilidad': datos.get('_confiabilidad', 0.5),
            '_patron_usado': datos.get('_patron', 'desconocido'),
            '_seccion_origen': datos.get('_seccion', 'texto_libre'),
        }
        
        if datos.get('acciones') is None and datos.get('porcentaje') is None:
            socio['_requiere_verificacion'] = True
            socio['_nota'] = datos.get('_nota',
                'Socio identificado sin datos de acciones confirmados')
        
        socios_result.append(socio)
    
    # Calcular porcentajes si tenemos total_acciones
    if total_acciones and total_acciones > 0:
        for socio in socios_result:
            if socio.get('acciones') and not socio.get('porcentaje'):
                socio['porcentaje'] = round(
                    (socio['acciones'] / total_acciones) * 100, 2
                )
    
    # Determinar tipo de extracción
    socios_con_datos = [
        s for s in socios_result
        if s.get('acciones') is not None or s.get('porcentaje') is not None
    ]
    
    if not socios_result:
        tipo = 'no_encontrada'
    elif len(socios_con_datos) == len(socios_result) and socios_con_datos:
        tipo = 'texto_libre'
    elif len(socios_con_datos) > 0:
        tipo = 'parcial'
    else:
        tipo = 'estructura_implicita'
    
    # ═══════════════════════════════════════════════════════════════════════════
    # NUEVO: Aplicar validadores de calidad antes de retornar
    # Si NO hay socios con datos reales, NO incluir comparecientes sin datos
    # Esto evita generar basura cuando no hay distribución en el documento
    # ═══════════════════════════════════════════════════════════════════════════
    
    if socios_result:
        # Filtrar entradas basura
        socios_limpios = filtrar_entradas_basura(socios_result)
        
        # Si no hay socios con datos reales, retornar vacío
        # (evita entradas "solo_compareciente" basura)
        socios_con_datos_limpios = [
            s for s in socios_limpios
            if s.get('acciones') is not None or s.get('porcentaje') is not None
        ]
        
        if not socios_con_datos_limpios:
            # No hay evidencia de distribución - retornar vacío
            return [], 'no_encontrada'
        
        # Deduplicar
        socios_dedup = deduplicar_accionistas(socios_limpios, umbral=0.80)
        
        # Recalcular tipo basado en datos limpios
        socios_con_datos_final = [
            s for s in socios_dedup
            if s.get('acciones') is not None or s.get('porcentaje') is not None
        ]
        
        if len(socios_con_datos_final) == len(socios_dedup):
            tipo = 'texto_libre'
        elif len(socios_con_datos_final) > 0:
            tipo = 'parcial'
        else:
            tipo = 'no_encontrada'
        
        return socios_dedup, tipo
    
    return socios_result, tipo


def _extract_socios_fundadores_fallback(text_ocr: str, total_acciones: int = None) -> list:
    """
    Fallback con regex para extraer socios fundadores cuando el LLM falla.
    Busca patrones comunes en Actas Constitutivas mexicanas.
    
    IMPORTANTE: Esta función NO asume distribución igualitaria.
    Si no puede extraer las acciones específicas, marca como requiere_verificacion.
    """
    socios = []
    texto = text_ocr.upper()
    socios_con_acciones = {}  # nombre -> {acciones, porcentaje}
    nombres_sin_acciones = set()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PRIMERO: INTENTAR EXTRAER DE TABLA ESTRUCTURADA (MAYOR CONFIABILIDAD)
    # ═══════════════════════════════════════════════════════════════════════════
    
    socios_tabla = _extract_tabla_accionistas_estructurada(text_ocr)
    if socios_tabla:
        # Si encontramos socios en tabla, usarlos como base con alta confiabilidad
        for socio_t in socios_tabla:
            nombre = socio_t.get("nombre", "").upper()
            if nombre and len(nombre) > 8:
                socios_con_acciones[nombre] = {
                    "acciones": socio_t.get("acciones"),
                    "porcentaje": None,
                    "_confiabilidad": 0.98,
                    "_patron": socio_t.get("_patron", "tabla_estructurada")
                }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCIÓN PARA CONVERTIR NÚMEROS EN TEXTO A VALORES NUMÉRICOS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def texto_a_numero(texto: str) -> int | None:
        """Convierte números escritos en texto a valores numéricos."""
        texto = texto.upper().strip()
        
        # Diccionario de números básicos
        unidades = {
            'UNO': 1, 'UNA': 1, 'DOS': 2, 'TRES': 3, 'CUATRO': 4, 'CINCO': 5,
            'SEIS': 6, 'SIETE': 7, 'OCHO': 8, 'NUEVE': 9, 'DIEZ': 10,
            'ONCE': 11, 'DOCE': 12, 'TRECE': 13, 'CATORCE': 14, 'QUINCE': 15,
            'DIECISEIS': 16, 'DIECISÉIS': 16, 'DIECISIETE': 17, 'DIECIOCHO': 18, 'DIECINUEVE': 19,
            'VEINTE': 20, 'VEINTIUNO': 21, 'VEINTIUNA': 21, 'VEINTIDOS': 22, 'VEINTIDÓS': 22,
            'VEINTITRES': 23, 'VEINTITRÉS': 23, 'VEINTICUATRO': 24, 'VEINTICINCO': 25,
            'VEINTISEIS': 26, 'VEINTISÉIS': 26, 'VEINTISIETE': 27, 'VEINTIOCHO': 28, 'VEINTINUEVE': 29,
            'TREINTA': 30, 'CUARENTA': 40, 'CINCUENTA': 50, 'SESENTA': 60,
            'SETENTA': 70, 'OCHENTA': 80, 'NOVENTA': 90, 'CIEN': 100, 'CIENTO': 100,
            'DOSCIENTOS': 200, 'DOSCIENTAS': 200, 'TRESCIENTOS': 300, 'TRESCIENTAS': 300,
            'CUATROCIENTOS': 400, 'CUATROCIENTAS': 400, 'QUINIENTOS': 500, 'QUINIENTAS': 500,
            'SEISCIENTOS': 600, 'SEISCIENTAS': 600, 'SETECIENTOS': 700, 'SETECIENTAS': 700,
            'OCHOCIENTOS': 800, 'OCHOCIENTAS': 800, 'NOVECIENTOS': 900, 'NOVECIENTAS': 900,
            'MIL': 1000,
        }
        
        # Caso simple: número exacto
        if texto in unidades:
            return unidades[texto]
        
        # Caso compuesto: "TREINTA Y CINCO", "CIENTO VEINTE", etc.
        partes = re.split(r'\s+Y\s+|\s+', texto)
        total = 0
        acumulado = 0
        
        for parte in partes:
            if parte in unidades:
                valor = unidades[parte]
                if valor == 1000:  # MIL - multiplicador
                    acumulado = max(1, acumulado) * valor
                elif valor >= 100:  # CIENTO, DOSCIENTOS, etc.
                    acumulado += valor
                else:
                    acumulado += valor
            elif parte == 'Y':
                continue
        
        total = acumulado if acumulado > 0 else None
        return total
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PATRONES PARA EXTRAER SOCIOS CON ACCIONES EXPLÍCITAS (ALTA CONFIABILIDAD)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Patrón 1: "NOMBRE suscribe/aporta N acciones" - flexible con indentación y viñetas
    patron_suscribe = r'(?:^|\n)\s*[-•*]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,60})\s+(?:QUIEN\s+)?(?:SUSCRIBE|APORTA|EXHIBE)\s+(\d{1,6})\s*(?:\([^)]+\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)'
    
    # Patrón 2: "N acciones a NOMBRE" o "N acciones suscritas por NOMBRE"
    patron_acciones_a = r'(\d{1,6})\s*(?:\([^)]+\))?\s*(?:ACCIONES|PARTES\s+SOCIALES)\s+(?:A|SUSCRITAS?\s+POR|PARA)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})'
    
    # Patrón 3: "NOMBRE con N acciones" - requiere explícitamente "CON" y contexto de acciones
    patron_nombre_con = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})\s+CON\s+(\d{1,6})\s*(?:\([^)]+\))?\s*(?:ACCIONES|PARTES)'
    
    # Patrón 4: "NOMBRE, representativas del N%" - flexible con indentación
    patron_porcentaje = r'(?:^|\n)\s*[-•*]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})\s*,\s*(?:ACCIONES\s+)?(?:REPRESENTATIVAS?\s+DEL?|EQUIVALENTES?\s+AL?|QUE\s+REPRESENTAN?)\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*%'
    
    # Patrón 5: "NOMBRE, propietario de N acciones"
    patron_propietario = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})\s*,?\s*(?:PROPIETARIO|TITULAR|TENEDOR)\s+DE\s+(\d{1,6})\s*(?:\([^)]+\))?\s*(?:ACCIONES|PARTES)'
    
    # Patrón 6: Tabla estilo "Socio | Acciones | Porcentaje"
    patron_tabla = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})\s+(\d{1,6})\s+(?:ACCIONES?\s+)?(\d{1,3}(?:[.,]\d{1,2})?)\s*%'
    
    # Patrón 7: "NOMBRE suscribe N acciones representativas del X%"
    patron_completo = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{8,60})\s+(?:SUSCRIBE|APORTA)\s+(\d{1,6})\s*(?:\([^)]+\))?\s*(?:ACCIONES|PARTES)[^.]{0,50}?(\d{1,3}(?:[.,]\d{1,2})?)\s*%'
    
    # Patrón 8: Tabla OCR linearizada "NOMBRE\nNúmero\n$valor" 
    # Busca: NOMBRE_COMPLETO (en mayúsculas) seguido de un número (acciones) y valor monetario
    # Este formato es común cuando el OCR lineariza tablas de accionistas
    # IMPORTANTE: Usar ' ' (espacio) en vez de \s en la clase del nombre para NO cruzar líneas
    patron_tabla_ocr = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{10,50})\s*\n\s*(?:([A-ZÁÉÍÓÚÑ]{2,25}(?:\s+[A-ZÁÉÍÓÚÑ]{2,25})?)\s*\n\s*)?(\d{1,6})\s*\n\s*\$[\d,\.]+(?:\s+MONEDA)?'
    
    # Patrón 9: Tabla con columnas NOMBRE | ACCIONES | $VALOR en misma línea o contextual
    # Para formato: "ARTURO PONS AGUIRRE    45    $45,000.00"
    patron_tabla_linea = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{10,45})\s{2,}(\d{1,6})\s{2,}\$[\d,\.]+(?:\.\d{2})?'
    
    # Patrón 10: Texto narrativo "El señor [NOMBRE] aporta N acciones" (directo)
    patron_narrativo_aporta = r'(?:EL\s+)?(?:SE[ÑN]OR|SE[ÑN]ORA?|CIUDADANO|C\.)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,50}?)\s+APORTA\s+(\d{1,6})\s*(?:\([^)]+\))?\s*ACCIONES?'
    
    # Patrón 11: "NOMBRE aporta $X... correspondiente a / importe de Y acciones" (con monto intermedio)
    patron_narrativo_monto = r'(?:EL\s+)?(?:SE[ÑN]ORA?|SE[ÑN]OR|LA\s+SE[ÑN]ORA?|CIUDADANO|C\.)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,50}?)\s+APORTA.{0,250}?(?:CORRESPONDIENTES?\s+A|IMPORTE\s+DE|EQUIVALENTES?\s+A)\s+(\d{1,6})\s*(?:\([^)]+\))?\s*ACCIONES?'
    
    # Patrón 12: Texto narrativo con números en texto "El señor NOMBRE aporta... importe de CINCUENTA acciones"
    # Captura el nombre y el número escrito en texto (CINCUENTA, CIEN, DOSCIENTAS, etc.)
    patron_narrativo_texto = r'(?:EL\s+)?(?:SE[ÑN]OR|SE[ÑN]ORA?|CIUDADANO|C\.)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,50}?)\s+APORTA[^.]{0,200}?IMPORTE\s+DE\s+([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s]{2,40}?)\s+ACCIONES?'
    
    def normalizar_nombre(nombre: str) -> str:
        """Normaliza y limpia un nombre extraído."""
        nombre = re.sub(r'\s+', ' ', nombre.strip())
        # Eliminar prefijos comunes al inicio
        nombre = re.sub(r'^(?:EL\s+)?(?:SR\.?|SRA\.?|C\.?|LIC\.?|ING\.?|DR\.?|MTRO\.?)\s+', '', nombre, flags=re.IGNORECASE)
        # Eliminar palabras sueltas al final que no son parte del nombre
        nombre = re.sub(r'\s+(?:QUIEN|QUIENES|DECLARA|POR|QUE|Y)\s*$', '', nombre, flags=re.IGNORECASE)
        # Eliminar texto después de "SERIE" si aparece (para "APORTA 300 ACCIONES SERIE A")
        nombre = re.sub(r'\s+SERIE\s+[A-Z].*$', '', nombre, flags=re.IGNORECASE)
        return nombre.strip()
    
    def es_nombre_valido(nombre: str) -> bool:
        """Verifica si un string parece ser un nombre válido de persona.
        
        Validaciones robustas para evitar falsos positivos de frases legales,
        encabezados de tabla, números en texto, etc.
        """
        if len(nombre) < 10:
            return False
        if nombre.count(' ') < 1:  # Al menos nombre y apellido
            return False
        # Rechazar si tiene muchos números o caracteres especiales
        if len(re.findall(r'\d', nombre)) > 2:
            return False
        
        nombre_up = nombre.upper()
        palabras = nombre_up.split()
        
        # Rechazar frases que no son nombres (substring match)
        frases_rechazar = [
            'CAPITAL SOCIAL', 'ACCIONES NOMINATIVAS', 'SOCIEDAD ANONIMA', 
            'ASAMBLEA', 'ESTATUTOS', 'CLAUSULA', 'ARTICULO', 'NOTARIO',
            'ESCRITURA', 'TESTIMONIO', 'FOLIO', 'REGISTRO',
            'ACCIONISTAS', 'ACCIONES', 'VALOR', 'SERIE', 'PORCENTAJE',
            'MONEDA NACIONAL', 'PESOS', 'TOTAL',
            # Legal / Administrativo
            'LEY', 'FEDERAL', 'PROCEDIMIENTO', 'ADMINISTRATIV',
            'DECRETO', 'REGLAMENTO', 'CODIGO', 'MERCANTIL',
            'PROPORCION', 'REALIZACION', 'OBLIGACION',
            # Números en texto
            'NOVENTA', 'OCHENTA', 'SETENTA', 'SESENTA', 'CINCUENTA',
            'CUARENTA', 'TREINTA', 'NOVECIENTOS', 'OCHOCIENTOS',
            'SETECIENTOS', 'SEISCIENTOS', 'QUINIENTOS', 'CUATROCIENTOS',
            'TRESCIENTOS', 'DOSCIENTOS', 'CIENTO',
        ]
        if any(frase in nombre_up for frase in frases_rechazar):
            return False
        # Rechazar si empieza con palabras de encabezado de tabla o artículos
        if nombre_up.strip().startswith(('ACCIONISTA', 'NOMBRE', 'RAZON SOCIAL',
                                         'LA ', 'EL ', 'LOS ', 'LAS ')):
            return False
        # Rechazar si termina con preposiciones/artículos
        if palabras[-1] in ('DE', 'DEL', 'EN', 'A', 'AL', 'LA', 'EL', 'SUS',
                            'SU', 'Y', 'O', 'POR', 'CON', 'QUE', 'BIS'):
            return False
        # Al menos 2 palabras significativas
        palabras_funcion = {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y', 'EN',
                            'A', 'AL', 'O', 'E', 'SU', 'SUS', 'POR', 'CON'}
        palabras_sig = [p for p in palabras if len(p) >= 3 and p not in palabras_funcion]
        if len(palabras_sig) < 2:
            return False
        return True
    
    # Buscar con patrón completo primero (nombre + acciones + porcentaje)
    matches_completo = re.findall(patron_completo, texto, re.IGNORECASE | re.MULTILINE)
    for nombre, acciones, porcentaje in matches_completo:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio):
            try:
                porc = float(porcentaje.replace(',', '.'))
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": porc,
                    "_confiabilidad": 1.0,
                    "_patron": "completo"
                }
            except ValueError:
                pass
    
    # Buscar con patrón tabla
    matches_tabla = re.findall(patron_tabla, texto, re.IGNORECASE | re.MULTILINE)
    for nombre, acciones, porcentaje in matches_tabla:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                porc = float(porcentaje.replace(',', '.'))
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": porc,
                    "_confiabilidad": 0.95,
                    "_patron": "tabla"
                }
            except ValueError:
                pass
    
    # Buscar con patrones de suscripción (solo acciones)
    for patron, nombre_patron in [(patron_suscribe, "suscribe"), (patron_propietario, "propietario"), (patron_nombre_con, "nombre_con")]:
        matches = re.findall(patron, texto, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            nombre, acciones = match[0], match[1]
            nombre_limpio = normalizar_nombre(nombre)
            if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
                try:
                    socios_con_acciones[nombre_limpio] = {
                        "acciones": int(acciones),
                        "porcentaje": None,
                        "_confiabilidad": 0.9,
                        "_patron": nombre_patron
                    }
                except ValueError:
                    pass
    
    # Buscar con patrón inverso (N acciones a NOMBRE)
    matches_inverso = re.findall(patron_acciones_a, texto, re.IGNORECASE | re.MULTILINE)
    for acciones, nombre in matches_inverso:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": None,
                    "_confiabilidad": 0.85,
                    "_patron": "inverso"
                }
            except ValueError:
                pass
    
    # Buscar con patrón de porcentaje (solo porcentaje)
    matches_porcentaje = re.findall(patron_porcentaje, texto, re.IGNORECASE | re.MULTILINE)
    for nombre, porcentaje in matches_porcentaje:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                porc = float(porcentaje.replace(',', '.'))
                if 0 < porc <= 100:  # Validar rango
                    socios_con_acciones[nombre_limpio] = {
                        "acciones": None,
                        "porcentaje": porc,
                        "_confiabilidad": 0.85,
                        "_patron": "porcentaje"
                    }
            except ValueError:
                pass
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PATRONES PARA TABLAS OCR LINEARIZADAS (FORMATO ESPECIAL)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Buscar con patrón de tabla OCR linearizada (NOMBRE\n[CONTINUACIÓN]\n#acciones\n$valor)
    matches_tabla_ocr = re.findall(patron_tabla_ocr, texto, re.IGNORECASE | re.MULTILINE)
    for match in matches_tabla_ocr:
        nombre_base = match[0].strip()
        nombre_continuacion = match[1].strip() if match[1] else ""
        acciones = match[2]
        nombre_completo = (nombre_base + " " + nombre_continuacion).strip() if nombre_continuacion else nombre_base
        nombre_limpio = normalizar_nombre(nombre_completo)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": None,
                    "_confiabilidad": 0.95,
                    "_patron": "tabla_ocr_multilinea"
                }
            except ValueError:
                pass
    
    # Buscar con patrón de tabla en línea (NOMBRE  #acciones  $valor)
    matches_tabla_linea = re.findall(patron_tabla_linea, texto, re.IGNORECASE | re.MULTILINE)
    for nombre, acciones in matches_tabla_linea:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": None,
                    "_confiabilidad": 0.95,
                    "_patron": "tabla_ocr_linea"
                }
            except ValueError:
                pass
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PATRONES NARRATIVOS (TEXTO CORRIDO - CLÁUSULAS TRANSITORIAS)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Buscar con patrón narrativo "El señor NOMBRE aporta... importe de N acciones"
    matches_narrativo = re.findall(patron_narrativo_aporta, texto, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    for nombre, acciones in matches_narrativo:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": None,
                    "_confiabilidad": 0.92,
                    "_patron": "narrativo_aporta"
                }
            except ValueError:
                pass
    
    # Buscar con patrón narrativo alternativo "NOMBRE aporta $X... Y acciones"
    matches_narrativo_monto = re.findall(patron_narrativo_monto, texto, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    for nombre, acciones in matches_narrativo_monto:
        nombre_limpio = normalizar_nombre(nombre)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
            try:
                socios_con_acciones[nombre_limpio] = {
                    "acciones": int(acciones),
                    "porcentaje": None,
                    "_confiabilidad": 0.92,
                    "_patron": "narrativo_monto"
                }
            except ValueError:
                pass
    
    # Buscar con patrón narrativo con NÚMEROS EN TEXTO (CINCUENTA, CIEN, etc.)
    matches_narrativo_texto = re.findall(patron_narrativo_texto, texto, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    for nombre, acciones_texto in matches_narrativo_texto:
        nombre_limpio = normalizar_nombre(nombre)
        # Convertir texto a número (CINCUENTA -> 50)
        acciones_num = texto_a_numero(acciones_texto)
        if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones and acciones_num:
            socios_con_acciones[nombre_limpio] = {
                "acciones": acciones_num,
                "porcentaje": None,
                "_confiabilidad": 0.90,
                "_patron": "narrativo_texto"
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PATRONES PARA EXTRAER NOMBRES SIN ACCIONES (BAJA CONFIABILIDAD)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Patrón: "los señores X y Y" o "los señores X, Y y Z"
    patron_senores = r'(?:LOS\s+SE[ÑN]ORES?|COMPARECEN|CONSTITUYEN|FUNDADORES?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s+(?:Y|,)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,\s*CON|,\s*RESPECTIVAMENTE|,\s*QUIENES|\s+CON\s+ARREGLO)'
    
    # Patrón: "que realizan los señores X y Y"
    patron_realizan = r'QUE\s+REALIZAN\s+LOS\s+SE[ÑN]ORES?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s+Y\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,|\s+CON)'
    
    # Patrón: "otorgan los CC. X y Y"
    patron_otorgan = r'(?:OTORGAN|COMPARECEN)\s+(?:LOS\s+)?(?:CC\.?|CIUDADANOS?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s+Y\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,|\s+QUIENES)'
    
    for patron in [patron_realizan, patron_senores, patron_otorgan]:
        match = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        if match:
            for nombre in match.groups():
                if nombre:
                    nombre_limpio = normalizar_nombre(nombre)
                    if es_nombre_valido(nombre_limpio) and nombre_limpio not in socios_con_acciones:
                        nombres_sin_acciones.add(nombre_limpio)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # BÚSQUEDA MULTI-SECCIÓN: comparecientes + cláusulas capital + texto libre
    # Si los patrones regex anteriores no encontraron socios con acciones,
    # usar búsqueda multi-sección como fuente adicional
    # ═══════════════════════════════════════════════════════════════════════════
    
    if not socios_con_acciones:
        socios_multi, tipo_ext = _extract_accionistas_multiseccion(text_ocr, total_acciones)
        for sm in socios_multi:
            nombre_sm = ' '.join(sm.get("nombre", "").upper().split())
            if nombre_sm and len(nombre_sm) > 8:
                if nombre_sm not in socios_con_acciones:
                    if sm.get("acciones") is not None or sm.get("porcentaje") is not None:
                        socios_con_acciones[nombre_sm] = {
                            "acciones": sm.get("acciones"),
                            "porcentaje": sm.get("porcentaje"),
                            "_confiabilidad": sm.get("_confiabilidad", 0.5),
                            "_patron": sm.get("_patron_usado", "multiseccion")
                        }
                    else:
                        nombres_sin_acciones.add(nombre_sm)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONSTRUIR LISTA FINAL DE SOCIOS CON DEDUPLICACIÓN POR NOMBRE
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Deduplicar basándose en nombres similares (usar nombre normalizado como clave)
    # NO deduplicar por acciones - múltiples socios pueden tener el mismo número de acciones
    socios_finales = {}  # nombre_normalizado -> datos
    
    def normalizar_clave(nombre: str) -> str:
        """Crea una clave normalizada para deduplicación (sin acentos)."""
        # Remover caracteres especiales y espacios extras
        clave = re.sub(r'[^A-ZÁÉÍÓÚÑ\s]', '', nombre.upper())
        clave = re.sub(r'\s+', ' ', clave).strip()
        # Normalizar acentos
        clave = _strip_accents(clave)
        # Tomar solo palabras que empiezan con mayúscula (nombres propios)
        palabras = [p for p in clave.split() if len(p) > 2]
        return ' '.join(palabras)
    
    def es_nombre_duplicado(nombre_nuevo: str, nombres_existentes: dict) -> str | None:
        """Verifica si un nombre es duplicado de otro (uno es prefijo del otro).
        Retorna la clave existente si es duplicado, None si es nuevo."""
        clave_nueva = normalizar_clave(nombre_nuevo)
        palabras_nuevas = set(clave_nueva.split())
        
        for clave_existente in nombres_existentes.keys():
            palabras_existentes = set(clave_existente.split())
            
            # Si comparten al menos 3 palabras y una es subconjunto de la otra
            palabras_comunes = palabras_nuevas & palabras_existentes
            if len(palabras_comunes) >= 3:
                # Es duplicado si una es prefijo/subconjunto de la otra
                if palabras_nuevas.issubset(palabras_existentes) or palabras_existentes.issubset(palabras_nuevas):
                    return clave_existente
        return None
    
    for nombre, datos in socios_con_acciones.items():
        clave = normalizar_clave(nombre)
        if clave and len(clave) > 8:
            # Verificar si es duplicado de un nombre existente
            clave_existente = es_nombre_duplicado(nombre, socios_finales)
            
            if clave_existente:
                # Es duplicado - FUSIONAR datos, priorizando el más completo
                datos_existentes = socios_finales[clave_existente]
                # Usar el nombre más largo (más completo)
                nombre_final = nombre if len(nombre) > len(datos_existentes["nombre"]) else datos_existentes["nombre"]
                # Fusionar datos: priorizar el que tiene acciones definidas
                acciones_final = datos.get("acciones") if datos.get("acciones") is not None else datos_existentes.get("acciones")
                porcentaje_final = datos.get("porcentaje") if datos.get("porcentaje") is not None else datos_existentes.get("porcentaje")
                confiabilidad_final = max(datos.get("_confiabilidad", 0), datos_existentes.get("_confiabilidad", 0))
                patron_final = datos.get("_patron") if datos.get("acciones") is not None else datos_existentes.get("_patron", "fusionado")
                
                del socios_finales[clave_existente]
                socios_finales[clave] = {
                    "nombre": nombre_final,
                    "acciones": acciones_final,
                    "porcentaje": porcentaje_final,
                    "_confiabilidad": confiabilidad_final,
                    "_patron": patron_final
                }
            elif clave in socios_finales:
                # Clave exacta ya existe - FUSIONAR datos
                datos_existentes = socios_finales[clave]
                acciones_final = datos.get("acciones") if datos.get("acciones") is not None else datos_existentes.get("acciones")
                porcentaje_final = datos.get("porcentaje") if datos.get("porcentaje") is not None else datos_existentes.get("porcentaje")
                confiabilidad_final = max(datos.get("_confiabilidad", 0), datos_existentes.get("_confiabilidad", 0))
                socios_finales[clave] = {
                    "nombre": nombre if len(nombre) > len(datos_existentes["nombre"]) else datos_existentes["nombre"],
                    "acciones": acciones_final,
                    "porcentaje": porcentaje_final,
                    "_confiabilidad": confiabilidad_final,
                    "_patron": datos.get("_patron", datos_existentes.get("_patron", "fusionado"))
                }
            else:
                socios_finales[clave] = {"nombre": nombre, **datos}
    
    # Agregar socios deduplicados
    for clave, datos in socios_finales.items():
        socio = {
            "nombre": datos["nombre"],
            "tipo": "fisica",
            "rfc": None,
            "acciones": datos.get("acciones"),
            "porcentaje": datos.get("porcentaje"),
            "serie": "A",
            "es_fundador": True,
            "_extraido_por": "regex_fallback",
            "_confiabilidad": datos.get("_confiabilidad", 0.8),
            "_patron_usado": datos.get("_patron", "desconocido"),
            "_requiere_verificacion": False
        }
        socios.append(socio)
    
    # Agregar socios sin acciones conocidas (IMPORTANTE: NO asumimos distribución)
    for nombre in nombres_sin_acciones:
        socios.append({
            "nombre": nombre,
            "tipo": "fisica",
            "rfc": None,
            "acciones": None,  # NO asumimos distribución igualitaria
            "porcentaje": None,  # NO asumimos distribución igualitaria
            "serie": "A",
            "es_fundador": True,
            "_extraido_por": "regex_fallback",
            "_confiabilidad": 0.3,  # Baja confiabilidad - solo nombre encontrado
            "_patron_usado": "solo_nombre",
            "_requiere_verificacion": True  # REQUIERE verificación manual
        })
    
    # Calcular porcentajes SOLO para socios con acciones conocidas
    if total_acciones and total_acciones > 0:
        for socio in socios:
            if socio.get("acciones") and not socio.get("porcentaje"):
                socio["porcentaje"] = round((socio["acciones"] / total_acciones) * 100, 2)
    
    # Validar suma de porcentajes si todos los socios tienen porcentaje
    todos_tienen_porcentaje = all(s.get("porcentaje") is not None for s in socios)
    if todos_tienen_porcentaje and socios:
        suma = sum(s.get("porcentaje", 0) for s in socios)
        if abs(suma - 100) > 0.5:
            # Marcar todos como requiere verificación si no suman 100%
            for socio in socios:
                socio["_requiere_verificacion"] = True
                socio["_advertencia"] = f"Suma de porcentajes: {suma}% (debería ser 100%)"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # NUEVO: Aplicar validadores de calidad antes de retornar
    # Filtra basura y deduplica usando el módulo validators/accionistas_validator
    # ═══════════════════════════════════════════════════════════════════════════
    
    if socios:
        # Paso 1: Filtrar entradas basura (frases legales, etc.)
        socios_filtrados = filtrar_entradas_basura(socios)
        
        # Paso 2: Deduplicar entradas similares (fusiona datos)
        socios_deduplicados = deduplicar_accionistas(socios_filtrados, umbral=0.80)
        
        # Log si hubo cambios significativos
        if len(socios) != len(socios_deduplicados):
            logger.info(
                f"Validador accionistas: {len(socios)} → {len(socios_deduplicados)} "
                f"(filtradas {len(socios) - len(socios_filtrados)}, "
                f"deduplicadas {len(socios_filtrados) - len(socios_deduplicados)})"
            )
        
        return socios_deduplicados
    
    return socios


def _validate_estructura_accionaria(data: dict, text_ocr: str = "") -> dict:
    """
    Valida y normaliza la estructura accionaria extraída.
    - Asegura que los porcentajes sumen ~100% (o marca como requiere verificación)
    - Normaliza tipos de persona (fisica/moral)
    - Calcula porcentajes faltantes SOLO si hay suficiente información confiable
    - USA FALLBACK si la lista está vacía O si socios no tienen acciones
    - NUNCA asume distribución igualitaria - marca para verificación manual
    """
    result = data.copy()
    estructura = result.get("estructura_accionaria", [])
    
    # Obtener total de acciones para cálculos
    total_acciones = None
    try:
        total_acciones = int(str(result.get("total_acciones", "0")).replace(",", "").replace(".", ""))
    except:
        pass
    
    # FALLBACK CASO 1: Si no hay estructura accionaria
    if (not estructura or not isinstance(estructura, list) or len(estructura) == 0) and text_ocr:
        estructura = _extract_socios_fundadores_fallback(text_ocr, total_acciones)
        if estructura:
            result["_estructura_extraida_por_fallback"] = True
    
    # FALLBACK CASO 2: Si hay socios pero NINGUNO tiene acciones, intentar enriquecer
    elif estructura and isinstance(estructura, list) and len(estructura) > 0 and text_ocr:
        # Verificar si algún socio tiene acciones
        socios_con_acciones = [s for s in estructura if isinstance(s, dict) and s.get("acciones") is not None]
        
        if len(socios_con_acciones) < len(estructura):
            # Hay socios sin acciones - ejecutar fallback para enriquecer los que faltan
            socios_fallback = _extract_socios_fundadores_fallback(text_ocr, total_acciones)
            
            if socios_fallback:
                # Crear mapa de nombres a datos del fallback
                fallback_por_nombre = {}
                for sf in socios_fallback:
                    nombre_orig = sf.get("nombre", "").upper().strip()
                    fallback_por_nombre[nombre_orig] = sf
                    # Crear versiones normalizadas (sin acentos y sin caracteres especiales)
                    nombre_norm = _strip_accents("".join(c for c in nombre_orig if c.isalpha() or c.isspace()))
                    nombre_norm = " ".join(nombre_norm.split())
                    fallback_por_nombre[nombre_norm] = sf
                
                # Enriquecer socios existentes con datos del fallback
                for socio in estructura:
                    if isinstance(socio, dict) and socio.get("acciones") is None:
                        nombre = socio.get("nombre", "").upper().strip()
                        nombre_norm = _strip_accents("".join(c for c in nombre if c.isalpha() or c.isspace()))
                        nombre_norm = " ".join(nombre_norm.split())
                        
                        # Buscar coincidencia exacta
                        datos_fb = fallback_por_nombre.get(nombre) or fallback_por_nombre.get(nombre_norm)
                        
                        # Si no hay coincidencia exacta, fuzzy matching por palabras
                        if not datos_fb:
                            palabras_socio = set(nombre_norm.split())
                            if len(palabras_socio) >= 2:
                                mejor_match = None
                                mejor_overlap = 0
                                for fb_nombre, fb_datos in fallback_por_nombre.items():
                                    palabras_fb = set(fb_nombre.split())
                                    overlap = len(palabras_socio & palabras_fb)
                                    if overlap >= 2 and overlap > mejor_overlap:
                                        mejor_overlap = overlap
                                        mejor_match = fb_datos
                                datos_fb = mejor_match
                        
                        if datos_fb and datos_fb.get("acciones") is not None:
                            socio["acciones"] = datos_fb["acciones"]
                            socio["porcentaje"] = datos_fb.get("porcentaje")
                            socio["_enriquecido_por_fallback"] = True
                            socio["_confiabilidad"] = datos_fb.get("_confiabilidad", 0.8)
                
                result["_estructura_enriquecida_por_fallback"] = True
    
    if not estructura or not isinstance(estructura, list):
        result["_estructura_accionaria_status"] = "no_encontrada"
        result["_estructura_confiabilidad"] = 0.0
        return result
    
    # Filtrar elementos que no son diccionarios
    estructura = [a for a in estructura if isinstance(a, dict)]
    
    # Normalizar cada accionista
    for accionista in estructura:
        # Normalizar nombre a mayúsculas
        if accionista.get("nombre"):
            accionista["nombre"] = str(accionista["nombre"]).upper().strip()
        
        # Normalizar tipo
        tipo = str(accionista.get("tipo", "")).lower().strip()
        nombre = accionista.get("nombre", "").upper()
        
        # Auto-detectar tipo basado en nombre si no está definido
        if tipo not in ("fisica", "moral"):
            patrones_moral = ["S.A.", "S.A. DE C.V.", "S. DE R.L.", "S.C.", "A.C.", 
                           "S.A.P.I.", "SOCIEDAD", "FIDEICOMISO", "FONDO"]
            es_moral = any(patron in nombre for patron in patrones_moral)
            accionista["tipo"] = "moral" if es_moral else "fisica"
        else:
            accionista["tipo"] = tipo
        
        # Manejar porcentaje - puede ser None (válido)
        porcentaje = accionista.get("porcentaje")
        if porcentaje is not None:
            try:
                accionista["porcentaje"] = float(porcentaje)
            except (ValueError, TypeError):
                accionista["porcentaje"] = None
                accionista["_requiere_verificacion"] = True
        
        # Manejar acciones - puede ser None (válido)
        acciones = accionista.get("acciones")
        if acciones is not None:
            try:
                accionista["acciones"] = int(acciones)
            except (ValueError, TypeError):
                accionista["acciones"] = None
                accionista["_requiere_verificacion"] = True
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FILTRADO DE BASURA Y DEDUPLICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════
    len_antes_filtrado = len(estructura)
    estructura = limpiar_y_deduplicar(estructura, umbral_similitud=0.80)
    len_despues_filtrado = len(estructura)
    
    if len_antes_filtrado != len_despues_filtrado:
        result["_entradas_filtradas"] = len_antes_filtrado - len_despues_filtrado
        logger.info(f"[VALIDATE_ESTRUCTURA] Filtrado: {len_antes_filtrado} -> {len_despues_filtrado} accionistas")
    
    # Si después del filtrado no queda nada, retornar sin estructura
    if not estructura:
        result["_estructura_accionaria_status"] = "no_encontrada"
        result["_estructura_confiabilidad"] = 0.0
        return result
    
    # ═══════════════════════════════════════════════════════════════════════════
    # VALIDACIÓN DE RFC Y DETECCIÓN DE TIPO DE PERSONA
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        estructura = validar_rfcs_estructura(estructura, validar_checksum=False)
        alertas_rfc = generar_alertas_rfc(estructura)
        if alertas_rfc:
            result["_alertas_rfc"] = alertas_rfc
            logger.info(f"[VALIDATE_ESTRUCTURA] Alertas RFC: {len(alertas_rfc)}")
    except Exception as e:
        logger.warning(f"[VALIDATE_ESTRUCTURA] Error validando RFCs: {e}")
    
    # Calcular porcentajes SOLO para accionistas con acciones conocidas
    total_acciones = result.get("total_acciones")
    if total_acciones:
        try:
            total_acciones = int(str(total_acciones).replace(",", "").replace(".", ""))
        except (ValueError, TypeError):
            total_acciones = None
    
    # Si no hay total_acciones pero todos los socios tienen acciones, usar la suma
    if not total_acciones:
        acciones_todos = [acc.get("acciones") for acc in estructura if acc.get("acciones") is not None]
        if acciones_todos and len(acciones_todos) == len(estructura):
            total_acciones = sum(acciones_todos)
            result["_total_acciones_calculado"] = total_acciones
    
    # Calcular porcentajes
    if total_acciones and total_acciones > 0:
        for acc in estructura:
            if acc.get("acciones") and acc.get("porcentaje") is None:
                acc["porcentaje"] = round((acc["acciones"] / total_acciones) * 100, 2)
                acc["_porcentaje_calculado"] = True
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ANÁLISIS DE CALIDAD DE LA ESTRUCTURA ACCIONARIA
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Contar accionistas con datos completos vs incompletos
    accionistas_completos = 0
    accionistas_incompletos = 0
    accionistas_requieren_verificacion = 0
    
    for acc in estructura:
        tiene_acciones = acc.get("acciones") is not None
        tiene_porcentaje = acc.get("porcentaje") is not None
        requiere_verificacion = acc.get("_requiere_verificacion", False)
        
        # Contar si tiene datos numéricos (independiente de si requiere verificación)
        if tiene_acciones or tiene_porcentaje:
            accionistas_completos += 1
        else:
            accionistas_incompletos += 1
        
        # Contar además si requiere verificación (flags separadas)
        if requiere_verificacion:
            accionistas_requieren_verificacion += 1
    
    # Verificar suma de porcentajes (solo para los que tienen porcentaje)
    porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
    total_porcentaje = sum(porcentajes)
    
    result["_suma_porcentajes"] = round(total_porcentaje, 2) if porcentajes else None
    result["_porcentajes_validos"] = abs(total_porcentaje - 100.0) <= 0.5 if porcentajes else False
    
    # Verificar suma de acciones
    acciones_lista = [a.get("acciones", 0) for a in estructura if a.get("acciones") is not None]
    suma_acciones = sum(acciones_lista)
    if total_acciones and acciones_lista:
        result["_suma_acciones"] = suma_acciones
        result["_acciones_validas"] = suma_acciones == total_acciones
    
    # Calcular confiabilidad general
    if len(estructura) == 0:
        confiabilidad = 0.0
    elif accionistas_completos == len(estructura) and result.get("_porcentajes_validos"):
        confiabilidad = 1.0
    elif accionistas_completos == len(estructura):
        confiabilidad = 0.8  # Todos tienen datos pero no suman 100%
    elif accionistas_completos > 0:
        confiabilidad = 0.5 * (accionistas_completos / len(estructura))
    else:
        confiabilidad = 0.2  # Solo nombres, sin datos numéricos
    
    # Solo reducir confiabilidad por verificación si los datos NO suman correctamente
    # Si los datos validan matemáticamente, confiar aunque vengan de fallback
    if accionistas_requieren_verificacion > 0 and not result.get("_porcentajes_validos"):
        confiabilidad *= 0.5
    
    result["_estructura_confiabilidad"] = round(confiabilidad, 2)
    
    # Determinar estado de la estructura (Title Case para consistencia)
    if confiabilidad >= 0.9:
        status = "Verificada"
    elif confiabilidad >= 0.6:
        status = "Parcial"
    elif confiabilidad >= 0.3:
        status = "Requiere_Verificacion"
    elif accionistas_incompletos == len(estructura) and len(estructura) > 0:
        # TODOS los socios son solo nombres sin datos numéricos
        # → Estructura implícita (socios como comparecientes sin distribución)
        status = "Estructura_Implicita"
        confiabilidad = 0.25
        result["_estructura_confiabilidad"] = confiabilidad
        result["_nota_estructura"] = (
            "Los socios se identificaron como comparecientes pero el documento "
            "no especifica distribución individual de acciones por accionista. "
            "Se requiere verificar en el Registro de Accionistas."
        )
    else:
        status = "No_Confiable"
    
    result["_estructura_accionaria_status"] = status
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALERTAS Y ADVERTENCIAS
    # ═══════════════════════════════════════════════════════════════════════════
    
    alertas_accionarias = []
    
    # Detectar personas morales con >25% (requieren perforación)
    for acc in estructura:
        if acc.get("tipo") == "moral" and (acc.get("porcentaje") or 0) > 25:
            alertas_accionarias.append(
                f"Persona moral '{acc.get('nombre')}' posee {acc.get('porcentaje')}% (>25%) - requiere perforación"
            )
    
    # Alertar si los porcentajes no suman 100%
    if porcentajes and not result.get("_porcentajes_validos"):
        alertas_accionarias.append(
            f"Suma de porcentajes: {result['_suma_porcentajes']}% (debería ser 100%)"
        )
    
    # Alertar si hay accionistas sin datos numéricos
    if accionistas_incompletos > 0:
        alertas_accionarias.append(
            f"{accionistas_incompletos} accionista(s) sin datos de acciones/porcentaje - REQUIERE VERIFICACIÓN MANUAL"
        )
    
    # Alertar si hay discrepancia en suma de acciones
    if total_acciones and acciones_lista and not result.get("_acciones_validas"):
        alertas_accionarias.append(
            f"Suma de acciones ({suma_acciones}) no coincide con total declarado ({total_acciones})"
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALERTAS PLD (Propietarios Reales y Beneficiarios Controladores)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Detectar accionistas que podrían ser propietarios reales (PF ≥25%)
    propietarios_reales_pf = []
    beneficiarios_controladores_pf = []
    
    for acc in estructura:
        porcentaje = acc.get("porcentaje") or 0
        tipo = acc.get("tipo", "fisica")
        nombre = acc.get("nombre", "Desconocido")
        
        if tipo == "fisica":
            # DCG Art. 115: ≥25% = Propietario Real
            if porcentaje >= 25.0:
                propietarios_reales_pf.append({
                    "nombre": nombre,
                    "porcentaje": porcentaje,
                    "criterio": "PROPIEDAD_25PCT"
                })
            # CFF Art. 32-B: >15% = Beneficiario Controlador
            elif porcentaje > 15.0:
                beneficiarios_controladores_pf.append({
                    "nombre": nombre,
                    "porcentaje": porcentaje,
                    "criterio": "PROPIEDAD_15PCT"
                })
    
    if propietarios_reales_pf:
        result["_propietarios_reales"] = propietarios_reales_pf
    if beneficiarios_controladores_pf:
        result["_beneficiarios_controladores"] = beneficiarios_controladores_pf
    
    if alertas_accionarias:
        result["_alertas_accionarias"] = alertas_accionarias
    
    # Salida enriquecida: incluye RFC y flags de validación
    result["estructura_accionaria"] = [
        {
            "nombre": acc.get("nombre"),
            "tipo": acc.get("tipo"),
            "porcentaje": acc.get("porcentaje"),
            "rfc": acc.get("rfc"),
            "_rfc_valido": acc.get("_rfc_valido"),
            "_rfc_tipo": acc.get("_rfc_tipo"),
            "_tipo_detectado": acc.get("_tipo_detectado"),
        }
        for acc in estructura
    ]
    return result


def _regex_fallback_extraction(data: dict, text_ocr: str) -> dict:
    """
    MEJORA 3: Regex fallback para campos no extraídos por LLM.
    Busca patrones específicos en el texto cuando el LLM falla.
    """
    result = data.copy()
    
    # Meses para conversión
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    # --- NÚMERO DE ESCRITURA ---
    if not result.get("numero_escritura_poliza") or result.get("numero_escritura_poliza") in ["", "N/A"]:
        patterns = [
            r'ESCRITURA\s+P[ÚU]BLICA\s+N[ÚU]MERO\s+(\d{1,6})',
            r'ESCRITURA\s+N[ÚU]MERO\s+(\d{1,6})',
            r'P[ÓO]LIZA\s+N[ÚU]MERO\s+(\d{1,6})',
            r'INSTRUMENTO\s+N[ÚU]MERO\s+(\d{1,6})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_escritura_poliza"] = match.group(1)
                break
    
    # --- NÚMERO DE NOTARÍA ---
    if not result.get("numero_notaria") or result.get("numero_notaria") in ["", "N/A"]:
        patterns = [
            r'NOTAR[ÍI]A\s+(?:P[ÚU]BLICA\s+)?(?:N[ÚU]MERO|NO\.?|#)\s*(\d{1,4})',
            r'NOTARIO\s+P[ÚU]BLICO\s+(?:N[ÚU]MERO|NO\.?|#)\s*(\d{1,4})',
            r'NOTARIO\s+(\d{1,4})\s+DEL',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_notaria"] = match.group(1)
                break
    
    # --- FECHA CONSTITUCIÓN ---
    if not result.get("fecha_constitucion") or result.get("fecha_constitucion") in ["", "N/A"]:
        # Buscar en primera parte del documento
        texto_inicio = text_ocr[:15000] if len(text_ocr) > 15000 else text_ocr
        patterns = [
            r'(?:a\s+los?\s+)?(\d{1,2})\s+(?:\w+\s+)?d[íi]as?\s+del\s+mes\s+de\s+(\w+)\s+del?\s+(?:a[ñn]o\s+)?(?:de\s+)?(\d{4})',
            r'(\d{1,2})\s+de\s+(\w+)\s+de[l]?\s+(\d{4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, texto_inicio, re.IGNORECASE)
            if match:
                dia = match.group(1).zfill(2)
                mes_texto = match.group(2).lower()
                anio = match.group(3)
                if mes_texto in meses:
                    result["fecha_constitucion"] = f"{dia}/{meses[mes_texto]}/{anio}"
                    break
    
    # --- ESTADO DE NOTARÍA ---
    if not result.get("estado_notaria") or result.get("estado_notaria") in ["", "N/A"]:
        estados_pattern = r'(?:NOTAR[ÍI]A|NOTARIO).*?(?:EN|DE|DEL?\s+ESTADO\s+DE)\s+(JALISCO|NUEVO\s+LE[ÓO]N|CIUDAD\s+DE\s+M[ÉE]XICO|QUINTANA\s+ROO|CHIAPAS|CHIHUAHUA|COAHUILA|GUANAJUATO|PUEBLA|VERACRUZ|SONORA|TAMAULIPAS|M[ÉE]XICO|OAXACA|MICHOAC[ÁA]N|GUERRERO|YUCAT[ÁA]N|BAJA\s+CALIFORNIA(?:\s+SUR)?|SINALOA|TABASCO|MORELOS|HIDALGO|QUER[ÉE]TARO|AGUASCALIENTES|NAYARIT|TLAXCALA|CAMPECHE|COLIMA|ZACATECAS|SAN\s+LUIS\s+POTOS[ÍI]|DURANGO)'
        match = re.search(estados_pattern, text_ocr, re.IGNORECASE)
        if match:
            result["estado_notaria"] = match.group(1).title()
    
    # --- NOMBRE NOTARIO ---
    if not result.get("nombre_notario") or result.get("nombre_notario") in ["", "N/A"]:
        patterns = [
            r'(?:LICENCIADO|LIC\.?|NOTARIO)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){2,4})\s*,?\s*(?:NOTARIO|TITULAR)',
            r'NOTARIO\s+P[ÚU]BLICO.*?(?:ES|SOY)\s+(?:EL\s+)?(?:LICENCIADO|LIC\.?)?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){2,4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                nombre = match.group(1).strip()
                # Capitalizar correctamente
                result["nombre_notario"] = nombre.title()
                break

    # --- CAPITAL SOCIAL ---
    # Trigger when the LLM missed the value (empty, zero, or "N/A").
    # Reads the amount directly from the OCR text so it is immune to LLM confusion
    # caused by "capital variable ilimitada" language.
    cs_current = result.get("capital_social")
    cs_missing = (
        not cs_current
        or cs_current in ["", "N/A"]
        or (isinstance(cs_current, (int, float)) and cs_current == 0)
        or str(cs_current).strip() in ["0", "0.0", "0.00"]
    )
    if cs_missing and text_ocr:
        cs_patterns = [
            # "capital [social] mínimo fijo de ($2,500,000.00)"  ← Almirante-style
            r'capital\s+(?:social\s+)?m[ií]nimo\s+fijo\s+de\s+\(\s*\$?\s*([\d,]+\.?\d*)\)',
            # "capital social de ($2,500,000.00)"
            r'capital\s+social\s+de\s+\(\s*\$?\s*([\d,]+\.?\d*)\)',
            # generic: any $X,XXX,XXX.XX in the CAPITAL SOCIAL section (first 500 chars)
            r'capital\s+social[^\n]{0,300}\$\s*([\d,]+\.?\d*)',
        ]
        for pattern in cs_patterns:
            m = re.search(pattern, text_ocr, re.IGNORECASE | re.DOTALL)
            if m:
                try:
                    cs_val = float(m.group(1).replace(",", ""))
                    if cs_val > 0:
                        result["capital_social"] = cs_val
                        logger.info(
                            "[capital_social] Extraído por regex OCR: %s (patrón: %s)",
                            cs_val, pattern[:40],
                        )
                        break
                except ValueError:
                    pass

    return result


def _fix_campos_no_encontrados(data: dict) -> dict:
    """
    MEJORA 2: Corrige inconsistencias en campos_no_encontrados.
    Si un campo tiene "Pendiente" o está vacío, debe estar en la lista.
    """
    result = data.copy()
    
    campos_a_verificar = [
        "numero_escritura_poliza",
        "fecha_constitucion", 
        "fecha_expedicion",
        "estado_notaria",
        "numero_notaria",
        "folio_mercantil",
        "nombre_notario"
    ]
    
    if "campos_no_encontrados" not in result:
        result["campos_no_encontrados"] = []
    
    for campo in campos_a_verificar:
        valor = str(result.get(campo, "")).lower().strip()
        
        es_pendiente_o_vacio = (
            not valor or
            valor in ["", "n/a", "null", "none"] or
            "pendiente" in valor or
            "no encontrado" in valor or
            "no disponible" in valor
        )
        
        if es_pendiente_o_vacio:
            if campo not in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].append(campo)
        else:
            # Si tiene valor válido, quitarlo de la lista
            if campo in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].remove(campo)
    
    return result


def _add_extraction_evidence(data: dict, text_ocr: str) -> dict:
    """
    MEJORA 1: Agrega evidencia de dónde se extrajo cada campo.
    Busca el valor extraído en el texto y guarda página y párrafo.
    
    NOTA: Esta función es para campos de Actas/Poderes que NO se procesan
    con _add_extraction_evidence_generic. Usa el mismo sistema mejorado.
    """
    result = data.copy()
    evidencia = {}
    confiabilidad_campos = {}
    
    campos_a_buscar = [
        "numero_escritura_poliza",
        "fecha_constitucion", 
        "fecha_expedicion",
        "estado_notaria",
        "numero_notaria",
        "folio_mercantil",
        "nombre_notario",
        "clausula_extranjeros"
    ]
    
    for campo in campos_a_buscar:
        valor = result.get(campo)
        if not valor or "pendiente" in str(valor).lower() or str(valor).upper() == "N/A":
            evidencia[campo] = {
                "encontrado": False,
                "pagina": None,
                "parrafo": None
            }
            confiabilidad_campos[campo] = 0.0
            continue
        
        # Usar la búsqueda mejorada
        valor_str = str(valor)
        pos = _buscar_valor_en_texto(valor_str, text_ocr, campo)
        
        if pos >= 0:
            # Encontrar página y párrafo
            ubicacion = _find_page_and_paragraph(text_ocr, valor_str, pos)
            evidencia[campo] = {
                "encontrado": True,
                "pagina": ubicacion["pagina"],
                "parrafo": ubicacion["parrafo"]
            }
            confiabilidad_campos[campo] = 1.0
        else:
            # Intentar encontrar contexto aproximado basado en palabras clave del campo
            parrafo_aproximado, pagina_aproximada = _buscar_contexto_aproximado(campo, valor_str, text_ocr)
            evidencia[campo] = {
                "encontrado": False,
                "pagina": pagina_aproximada,
                "parrafo": parrafo_aproximado,
                "nota": "Valor extraído por LLM, contexto aproximado"
            }
            confiabilidad_campos[campo] = 0.7 if parrafo_aproximado else 0.5
    
    result["_evidencia_extraccion"] = evidencia
    result["_confiabilidad_campos"] = confiabilidad_campos
    
    # Calcular confiabilidad promedio
    if confiabilidad_campos:
        result["_confiabilidad_promedio"] = round(
            sum(confiabilidad_campos.values()) / len(confiabilidad_campos), 2
        )
    
    return result


def extract_acta_fields(text_ocr: str, llm) -> dict:
    """
    Extrae campos de un Acta Constitutiva con alta precisión.
    
    CAMPOS CRÍTICOS Y SUS FUENTES:
    - numero_escritura_poliza: En encabezado "ESCRITURA PÚBLICA NÚMERO X"
    - fecha_constitucion: En el cuerpo del acta "a los X días del mes de Y del año Z"
    - fecha_expedicion: En la NOTA AL CALCE o al final "GUADALAJARA, JALISCO, A X DE Y DE Z"
    - folio_mercantil: En BOLETA DE INSCRIPCIÓN campo "FME" (ej: N-2019050847)
    - estado_notaria: Donde se ubica la notaría
    - numero_notaria: Número de la notaría pública
    - nombre_notario: Nombre completo del notario
    - clausula_extranjeros: ADMISIÓN o EXCLUSIÓN de extranjeros
    - denominacion_social: Nombre de la sociedad (Cláusula PRIMERA)
    """
    if not text_ocr.strip():
        return {"error": "Texto vacío"}
    
    # Dividimos el texto si supera 200k caracteres
    MAX_CHUNK = 200000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)]
    
    # Plantilla JSON con descripción detallada
    json_template = """
    {
      "numero_escritura_poliza": "",
      "fecha_expedicion": "",
      "fecha_constitucion": "",
      "estado_notaria": "",
      "numero_notaria": "",
      "folio_mercantil": "",
      "nombre_notario": "",
      "clausula_extranjeros": "",
      "denominacion_social": "",
      "capital_social": "",
      "moneda_capital": "MXN",
      "total_acciones": "",
      "valor_nominal_accion": "",
      "estructura_accionaria": [],
      "campos_no_encontrados": []
    }
    """
    
    # Diccionario para acumular resultados
    extracted_data = {k: [] if isinstance(v, list) else "" for k, v in json.loads(json_template).items()}
    
    for idx, chunk in enumerate(chunks, start=1):
        prompt = dedent(f"""
        Eres un analista legal experto en Actas Constitutivas mexicanas. 
        Tu tarea: EXTRAER valores EXACTOS del texto con ALTA PRECISIÓN.

        ══════════════════════════════════════════════════════════════════════════════
        DEFINICIONES CRÍTICAS - LEE CON ATENCIÓN:
        ══════════════════════════════════════════════════════════════════════════════

        1. "numero_escritura_poliza" (OBLIGATORIO):
           - Busca: "ESCRITURA PÚBLICA NÚMERO", "ESCRITURA NÚMERO", "PÓLIZA NÚMERO"
           - Ejemplo en texto: "ESCRITURA PÚBLICA NÚMERO 2,072 (DOS MIL SETENTA Y DOS)"
           - Extrae SOLO el número: "2072"
           - Ignora números de tomo, libro, volumen

        2. "fecha_constitucion" (OBLIGATORIO):
           - Es la fecha en que SE FIRMA el acta ante el notario
           - Busca en la primera página: "a los X días del mes de Y del año Z"
           - Ejemplo: "a los 22 veintidós días del mes de mayo del año 2019"
           - Formato de salida: "22/05/2019"

        3. "fecha_expedicion" (OBLIGATORIO - DIFERENTE a fecha_constitucion):
           - Es la fecha en que SE EXPIDE EL TESTIMONIO (puede ser posterior)
           - Busca al FINAL del documento en:
             * "GUADALAJARA, JALISCO, A X DE Y DE Z"
             * "SE SACÓ DE SU MATRIZ ESTE... TESTIMONIO"
             * NOTA AL CALCE
           - Si hay SEGUNDO TESTIMONIO, usa la fecha más reciente
           - Ejemplo: "GUADALAJARA, JALISCO, A 04 CUATRO DE JUNIO DE 2019"
           - Formato de salida: "04/06/2019"
           - IMPORTANTE: NO confundir con fecha_constitucion

        4. "folio_mercantil" (OBLIGATORIO):
           - Busca en la BOLETA DE INSCRIPCIÓN del Registro Público de Comercio
           - Campo etiquetado como "FME" (Folio Mercantil Electrónico)
           - Ejemplo: "FME: N-2019050847"
           - Extrae: "N-2019050847"
           - También puede aparecer como "NCI" (Número de Control Interno)
           - Si no hay boleta de inscripción, busca "FOLIO MERCANTIL ELECTRÓNICO"
           - Si no existe, pon "PENDIENTE DE INSCRIPCIÓN"

        5. "numero_notaria" (OBLIGATORIO):
           - Busca: "NOTARIO PÚBLICO NÚMERO", "NOTARÍA NÚMERO", "NOTARÍA NO."
           - Ejemplo: "NOTARIO PUBLICO No. 49"
           - Extrae SOLO el número: "49"

        6. "estado_notaria" (OBLIGATORIO):
           - Estado donde se ubica la notaría
           - Ejemplo: "GUADALAJARA, JALISCO" → "Jalisco"
           - Si dice "DISTRITO FEDERAL" → "Ciudad de México"

        7. "nombre_notario" (OBLIGATORIO):
           - Nombre completo del notario/fedatario
           - Busca: "LICENCIADO", "LIC.", "NOTARIO PÚBLICO TITULAR"
           - Ejemplo: "LICENCIADO RICARDO LOPEZ CAMARENA"
           - Extrae: "Ricardo López Camarena" (capitalizado correctamente)

        8. "clausula_extranjeros" (OBLIGATORIO - MUY IMPORTANTE):
           - Busca la cláusula que menciona inversionistas extranjeros
           - DOS POSIBILIDADES MUTUAMENTE EXCLUYENTES:
           
           A) "EXCLUSIÓN DE EXTRANJEROS" - La sociedad NO admite extranjeros:
              * Busca: "CLÁUSULA DE EXCLUSIÓN DE EXTRANJEROS"
              * Busca: "NO admitirá directa, ni indirectamente... inversionistas extranjeros"
              * Busca: "La inversión extranjera no podrá participar"
              * Extrae: "EXCLUSIÓN DE EXTRANJEROS"
              
           B) "ADMISIÓN DE EXTRANJEROS" - La sociedad SÍ admite extranjeros:
              * Busca: "CLÁUSULA DE ADMISIÓN DE EXTRANJEROS"
              * Busca: "podrán participar inversionistas extranjeros"
              * Extrae: "ADMISIÓN DE EXTRANJEROS"
           
           IMPORTANTE - NO CONFUNDIR:
           - Las palabras "capital", "investment", "variable" en "S.A.P.I. de C.V." 
             NO indican participación extranjera, son parte del tipo societario
           - Busca la CLÁUSULA ESPECÍFICA sobre extranjeros

        9. "denominacion_social" (OBLIGATORIO):
           - Nombre legal de la sociedad que se está constituyendo
           - Busca en la Cláusula PRIMERA de los Estatutos
           - Patrones comunes:
             * "La Sociedad se denomina..."
             * "DENOMINACIÓN:..."
             * "denominada..."
             * "bajo la denominación..."
           - Extrae SOLO el nombre de la sociedad, SIN incluir:
             * Tipo societario: "Sociedad Anónima", "S.A.", "de C.V.", etc.
             * Descripciones: "Sociedad Financiera", "Institución de...", etc.
           - Ejemplo: "La Sociedad se denomina ALMIRANTE CAPITAL, Sociedad Anónima..."
           - Extrae: "ALMIRANTE CAPITAL"
           - Mantén el formato original (mayúsculas/minúsculas)

        10. "rfc" (OPCIONAL):
            - RFC (Registro Federal de Contribuyentes) de la SOCIEDAD
            - Formato Persona Moral: 3 letras + 6 dígitos + 3 alfanuméricos (12 caracteres)
            - Ejemplo: "ABC123456XYZ"
            - Ubicaciones comunes:
              * Sección de "otorgantes" o "comparecientes"
              * Boletas de pago SAT o tesorería municipal
              * Datos de inscripción fiscal
              * Cerca de: "RFC:", "R.F.C:", "Registro Federal de Contribuyentes"
            - IMPORTANTE - NO EXTRAER:
              * RFCs de personas físicas (notarios, apoderados individuales)
              * RFCs que claramente pertenecen a terceros
            - Si la sociedad AÚN NO tiene RFC (es constitución nueva), déjalo vacío
            - Formato: Solo letras mayúsculas y números, SIN guiones ni espacios

        11. "capital_social" (OBLIGATORIO):
            - Monto total del capital social de la sociedad
            - Busca: "CAPITAL SOCIAL", "CAPITAL MÍNIMO FIJO", "CAPITAL VARIABLE"
            - Ejemplo: "$2,500,000.00 (DOS MILLONES QUINIENTOS MIL PESOS 00/100 M.N.)"
            - Extrae SOLO el número: "2500000.00" (sin símbolos ni comas)
            - Si hay capital fijo Y variable con monto concreto, suma ambos
            - Si el capital variable es "ilimitado", "sin límite" o no tiene monto concreto,
              extrae SOLO el capital mínimo fijo
            - Si no encuentras monto numérico, devuelve ""

        12. "moneda_capital" (OBLIGATORIO):
            - Moneda del capital social
            - Valores posibles: "MXN", "USD", "EUR"
            - Busca: "M.N.", "MONEDA NACIONAL", "PESOS", "DÓLARES"
            - Default: "MXN"

        13. "total_acciones" (OBLIGATORIO):
            - Número total de acciones en que se divide el capital
            - Busca: "dividido en X acciones", "X acciones nominativas"
            - Ejemplo: "dividido en 2,500 (DOS MIL QUINIENTAS) acciones"
            - Extrae SOLO el número: "2500"

        14. "valor_nominal_accion" (OBLIGATORIO):
            - Valor nominal de cada acción
            - Cálculo: capital_social / total_acciones
            - Busca: "valor nominal de $X", "cada una con valor de"
            - Ejemplo: "$1,000.00 (MIL PESOS 00/100 M.N.) cada una"
            - Extrae: "1000.00"

        15. "estructura_accionaria" (MUY IMPORTANTE - LISTA DE ACCIONISTAS):
            - Identifica TODOS los socios/accionistas fundadores
            - Para CADA accionista extraer ÚNICAMENTE estos tres campos:
              * "nombre": Nombre completo en MAYÚSCULAS
              * "tipo": "fisica" o "moral"
                - PERSONA MORAL: Contiene "S.A.", "S.A. DE C.V.", "S. DE R.L.",
                  "S.C.", "A.C.", "SOCIEDAD", "FIDEICOMISO", o RFC de 12 chars
                - PERSONA FÍSICA: Nombre de individuo sin sufijos corporativos
              * "porcentaje": Porcentaje del capital social que posee (número float, null si no se puede determinar)
                - Busca porcentajes explícitos: "N% del capital", "representativas del N%"
                - Si encuentras acciones individuales y el total, calcula: (acciones_socio / total_acciones) * 100
                - NUNCA inventar o asumir distribución igualitaria
                - Si no hay suficiente información, deja null
                - Los porcentajes conocidos DEBEN sumar ~100%

            DÓNDE BUSCAR SOCIOS FUNDADORES:
            1. TABLAS DE DISTRIBUCIÓN - tabla "Accionista | Acciones | Valor"
            2. SECCIÓN DE COMPARECIENTES - "comparecen los señores X y Y"
            3. CLÁUSULAS DE CAPITAL SOCIAL - "suscripción y pago de acciones"
            4. TEXTO LIBRE - "[NOMBRE] suscribe N acciones", "N% del capital social representado por [NOMBRE]"

            Ejemplo de salida:
            [
              {{
                "nombre": "JUAN PÉREZ GARCÍA",
                "tipo": "fisica",
                "porcentaje": 60.0
              }},
              {{
                "nombre": "INVERSIONES XYZ S.A. DE C.V.",
                "tipo": "moral",
                "porcentaje": 40.0
              }}
            ]

        ══════════════════════════════════════════════════════════════════════════════
        REGLAS DE FORMATO:
        ══════════════════════════════════════════════════════════════════════════════
        - Fechas: SIEMPRE en formato dd/mm/aaaa
        - Convierte fechas en palabras: "tres de enero de dos mil veintitrés" → "03/01/2023"
        - Convierte números en palabras: "cuarenta y nueve" → "49"
        - Si un campo NO se encuentra, agrégalo a "campos_no_encontrados"
        - Responde SOLO con JSON válido, sin texto adicional

        JSON esperado:
        {json_template}

        ══════════════════════════════════════════════════════════════════════════════
        TEXTO A ANALIZAR (fragmento {idx}/{len(chunks)}):
        ══════════════════════════════════════════════════════════════════════════════
        {chunk[:18000]}
        """)

        resp = llm.invoke(prompt).content.strip()
        resp = re.sub(r"^```(?:json)?|```$", "", resp).strip()
        match = re.search(r"\{.*\}", resp, re.S)
        
        try:
            partial_data = json.loads(match.group(0)) if match else {}
        except:
            partial_data = {}

        # Fusionamos: si un campo sigue vacío y en este chunk aparece, lo tomamos
        for key in extracted_data.keys():
            if isinstance(extracted_data[key], list):
                # Para listas, extendemos sin duplicados
                if partial_data.get(key):
                    for item in partial_data[key]:
                        if item not in extracted_data[key]:
                            extracted_data[key].append(item)
            else:
                # Para strings, tomamos el valor si el campo está vacío
                if not extracted_data[key] and partial_data.get(key):
                    extracted_data[key] = partial_data[key]

    # ═══════════════════════════════════════════════════════════════════════════
    # POST-PROCESAMIENTO: Validar y corregir campos con reglas de negocio
    # ═══════════════════════════════════════════════════════════════════════════
    extracted_data = _validate_and_correct_acta_fields(extracted_data, text_ocr, llm)

    # Bug 1: Secondary fallback — compute capital_social = total_acciones × valor_nominal_accion
    # when _regex_fallback_extraction didn't find it in the OCR text.
    # Strip commas so "1,000" and "2,500.00" are parsed correctly.
    try:
        cs_raw = str(extracted_data.get("capital_social") or "").strip().replace(",", "")
        cs = float(cs_raw) if cs_raw else 0.0
        if cs == 0:
            ta_raw = str(extracted_data.get("total_acciones") or "").strip().replace(",", "")
            vn_raw = str(extracted_data.get("valor_nominal_accion") or "").strip().replace(",", "")
            ta = float(ta_raw) if ta_raw else 0.0
            vn = float(vn_raw) if vn_raw else 0.0
            if ta > 0 and vn > 0:
                extracted_data["capital_social"] = round(ta * vn, 2)
                logger.info(
                    "[capital_social] Calculado desde total_acciones × valor_nominal_accion: %s",
                    extracted_data["capital_social"],
                )
    except (ValueError, TypeError):
        pass

    # Agregar evidencia de extracción (página y párrafo)
    campos_a_buscar = [
        "numero_escritura_poliza", "fecha_expedicion", "fecha_constitucion", 
        "estado_notaria", "numero_notaria", "folio_mercantil", 
        "nombre_notario", "clausula_extranjeros", "denominacion_social",
        "capital_social", "total_acciones", "valor_nominal_accion"
    ]
    extracted_data = _add_extraction_evidence_generic(extracted_data, text_ocr, campos_a_buscar)

    # Bug 4: Sync estructura_accionaria confidence from _validate_estructura_accionaria
    # (list fields are excluded from _add_extraction_evidence_generic, so they default to 0
    # in the validation wrapper unless we write the value explicitly here)
    _est_conf = extracted_data.get("_estructura_confiabilidad")
    if _est_conf is not None:
        conf_campos = extracted_data.get("_confiabilidad_campos", {})
        conf_campos["estructura_accionaria"] = _est_conf
        extracted_data["_confiabilidad_campos"] = conf_campos

    # Minor: boost valor_nominal_accion confidence to 1.0 when it can be verified
    # by the identity: capital_social == total_acciones × valor_nominal_accion (±1%)
    try:
        cs = float(extracted_data.get("capital_social") or 0)
        ta = float(extracted_data.get("total_acciones") or 0)
        vn = float(extracted_data.get("valor_nominal_accion") or 0)
        if cs > 0 and ta > 0 and vn > 0:
            expected_vn = cs / ta
            if abs(expected_vn - vn) / max(expected_vn, 1) < 0.01:
                conf_campos = extracted_data.get("_confiabilidad_campos", {})
                conf_campos["valor_nominal_accion"] = 1.0
                extracted_data["_confiabilidad_campos"] = conf_campos
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    return extracted_data


def _extract_accionistas_regex_backup(text_ocr: str, accionistas_existentes: list) -> list:
    """
    Función de backup: extrae accionistas usando regex del texto OCR.
    Busca patrones como:
    - "Nombre Apellido RFC: XXXX 584 $584,000.00 35.98%"
    - "Empresa S.A.P.I. de C.V. RFC: XXXX 412 25.51%"
    
    Returns:
        Lista de accionistas encontrados que NO estaban en la lista existente
    """
    import unicodedata
    
    def normalizar_nombre(nombre: str) -> str:
        if not nombre:
            return ""
        nombre = unicodedata.normalize('NFKD', nombre)
        nombre = ''.join(c for c in nombre if not unicodedata.combining(c))
        nombre = ' '.join(nombre.upper().split())
        return nombre
    
    # Obtener nombres existentes normalizados
    nombres_existentes = {normalizar_nombre(a.get("nombre", "")) for a in accionistas_existentes}
    
    nuevos_accionistas = []
    
    # Múltiples patrones para diferentes formatos de tablas
    patrones = [
        # Patrón 1: Empresa S.A.P.I. de C.V. RFC: XXX acciones porcentaje%
        # Ejemplo: "Bastión Capital, S.A.P.I. de C.V. RFC: BCA1809035Z7 412 $412,000.00 25.51%"
        re.compile(
            r'([A-ZÁÉÍÓÚÑ][^%\n]{5,60}(?:S\.?A\.?P\.?I\.?|LLC|S\.?A\.?)(?:\s*de\s*C\.?V\.?)?)\s*' +
            r'(?:RFC[:\.\s]*)?([A-Z]{3,4}\d{6}[A-Z0-9]{3})?\s*' +
            r'(\d{1,6})\s*' +
            r'(?:\$[\d,\.\']+)?\s*' +
            r'([\d\.]+)\s*%',
            re.IGNORECASE | re.MULTILINE
        ),
        # Patrón 2: Nombre Apellido RFC: XXX acciones valor% (personas físicas)
        # Ejemplo: "Arturo Pons Aguirre RFC: POAA950325AKS 584 $584,000.00 36.16%"
        re.compile(
            r'([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4})\s+' +
            r'(?:RFC[:\.\s]*)?([A-Z]{3,4}\d{6}[A-Z0-9]{3})\s*' +
            r'(\d{1,6})\s*' +
            r'(?:\$[\d,\.]+)?\s*' +
            r'([\d\.]+)\s*%',
            re.IGNORECASE
        ),
        # Patrón 3: Formato línea simplificado con .- separadores
        # Ejemplo: "--- Bastión Capital, S.A.P.I. de C.V ..- Representada por: ... .- RFC: BCA1809035Z7 .- 412 .- 25.51%"
        re.compile(
            r'([A-ZÁÉÍÓÚÑ][^-\n]{5,60}(?:S\.?A\.?P\.?I\.?|LLC|S\.?A\.?)(?:\s*de\s*C\.?V\.?)?)[^\d]*' +
            r'RFC[:\s]*([A-Z]{3,4}\d{6}[A-Z0-9]{3})[^\d]*' +
            r'(\d{1,6})[^\d%]*' +
            r'([\d\.]+)\s*%',
            re.IGNORECASE
        ),
    ]
    
    # Buscar con todos los patrones
    for patron in patrones:
        for match in patron.finditer(text_ocr):
            nombre_raw = match.group(1).strip()
            rfc = match.group(2) or ""
            acciones = match.group(3)
            porcentaje = match.group(4)
            
            # Limpiar nombre
            nombre_limpio = re.sub(r'\s+', ' ', nombre_raw).strip()
            nombre_limpio = re.sub(r'^[-\s\.]+|[-\s\.]+$', '', nombre_limpio)  # Quitar guiones/puntos al inicio/fin
            nombre_norm = normalizar_nombre(nombre_limpio)
            
            # Filtrar nombres genéricos
            nombres_excluir = ["TESORERIA", "EN TESORERIA", "RESERVA", "ACCIONISTAS", "TOTAL", "TOTALES", "REPRESENTADA POR"]
            if nombre_norm in nombres_excluir or len(nombre_norm) < 5:
                continue
            
            # Filtrar si contiene palabras que indican que no es nombre de accionista
            if any(x in nombre_norm for x in ["REPRESENTADA", "CELEBRADA", "ASAMBLEA", "ARTICULO"]):
                continue
            
            # Verificar si ya existe - algoritmo mejorado
            ya_existe = False
            for existente in nombres_existentes:
                # Coincidencia exacta
                if existente == nombre_norm:
                    ya_existe = True
                    break
                # Coincidencia parcial (una contiene a la otra)
                if len(nombre_norm) > 10 and len(existente) > 10:
                    if nombre_norm in existente or existente in nombre_norm:
                        ya_existe = True
                        break
                    # Verificar palabras clave compartidas (apellidos o nombre empresa)
                    palabras_norm = set(nombre_norm.split()) - {"DE", "LA", "LOS", "S", "A", "P", "I", "C", "V"}
                    palabras_exist = set(existente.split()) - {"DE", "LA", "LOS", "S", "A", "P", "I", "C", "V"}
                    if len(palabras_norm & palabras_exist) >= 2:
                        ya_existe = True
                        break
            
            if not ya_existe and nombre_norm and len(nombre_limpio) >= 5:
                # Determinar tipo
                es_moral = any(suf in nombre_limpio.upper() for suf in ["S.A.", "S.A.P.I.", "LLC", "S.C.", "S. DE R.L.", "SAPI", "CV"])
                
                try:
                    nuevo = {
                        "nombre": nombre_limpio,
                        "acciones": int(acciones),
                        "porcentaje": float(porcentaje),
                        "tipo": "moral" if es_moral else "fisica",
                        "_extraido_por_regex": True
                    }
                    nuevos_accionistas.append(nuevo)
                    nombres_existentes.add(nombre_norm)
                except (ValueError, TypeError):
                    continue
    
    return nuevos_accionistas


def _reextract_estructura_accionaria(text_ocr: str, llm, total_acciones: int = None) -> list:
    """
    Re-extrae estructura accionaria con un prompt MUY específico y enfocado.
    Se usa cuando la extracción inicial tiene suma de porcentajes < 98%.
    
    Busca en TODAS las secciones del documento:
    - Tablas de distribución de capital
    - Comparecientes con datos de acciones
    - Cláusulas de capital social / suscripción y pago
    - Texto libre con keywords de participación
    """
    # Tomar texto relevante - más amplio para no perder secciones
    texto_relevante = text_ocr[:40000] if len(text_ocr) > 40000 else text_ocr
    
    prompt = dedent(f"""
    TAREA: Extraer TODOS los accionistas/socios de este documento legal mexicano.
    
    INSTRUCCIONES CRÍTICAS - BUSCAR EN MÚLTIPLES SECCIONES:
    
    1. TABLAS DE DISTRIBUCIÓN DE CAPITAL (fuente más confiable):
       - Busca tablas con columnas: Accionista | Acciones | Valor | Porcentaje
       - CUIDADO: El OCR puede partir un nombre en 2 líneas
       - Ejemplo OCR partido: "MARTHA GONZÁLEZ" (línea 1) + "GARCÍA  100" (línea 2)
       - Agrupa las líneas para obtener el nombre completo
    
    2. SECCIÓN DE COMPARECIENTES (al inicio del documento):
       - "ante mi, el notario... comparecen los señores X y Y"
       - A veces dice "titular de X acciones" junto al nombre
       - Incluir estos socios aunque solo tengan nombre sin acciones
    
    3. CLÁUSULAS DE CAPITAL SOCIAL:
       - "el capital social se divide en..."
       - "suscripción y pago de acciones"
       - "NOMBRE suscribe N acciones", "NOMBRE aporta N acciones"
    
    4. TEXTO LIBRE:
       - "[NOMBRE] es titular de [N] partes sociales"
       - "correspondiéndole a [NOMBRE] [N] acciones"
       - "[NOMBRE] aporta $[X] correspondiente a [N] acciones"
    
    INCLUIR: personas físicas Y empresas (S.A.P.I., LLC, S.A. de C.V., etc.)
    NO INCLUIR: "Tesorería", "Total", "Subtotal", notarios, fedatarios
    
    La suma de porcentajes debe ser ~100%. Si falta un socio, BÚSCALO.
    
    Si encuentras socios como comparecientes pero SIN datos de acciones en 
    ninguna parte del documento, inclúyelos con acciones=null y 
    porcentaje=null, agregando "_nota": "Compareciente sin acciones explícitas"
    
    {f'Total de acciones esperado: {total_acciones}' if total_acciones else ''}
    
    Responde SOLO con JSON array:
    [
      {{"nombre": "Nombre completo", "acciones": número_o_null, "porcentaje": decimal_o_null, "tipo": "fisica" o "moral"}},
      ...
    ]
    
    Texto del documento:
    {texto_relevante}
    """)
    
    try:
        resp = llm.invoke(prompt).content.strip()
        # Buscar el array JSON
        match = re.search(r'\[.*\]', resp, re.S)
        if match:
            estructura = json.loads(match.group(0))
            # Marcar como re-extraídos
            for acc in estructura:
                acc["_reextraido"] = True
            return estructura
    except Exception as e:
        logger.warning(f"[WARN] Re-extracción estructura fallida: {e}")
    
    return []


def extract_reforma_fields(text_ocr: str, llm, acta_text: str | None = None) -> dict:
    """
    Extrae campos de una Reforma de Estatutos usando LLM.
    Campos extraídos:
    - Datos de la escritura: numero_escritura, fecha_otorgamiento, fecha_expedicion
    - Datos notariales: nombre_notario, numero_notaria, estado_notaria
    - Datos de la sociedad: razon_social, objeto_social, capital_social, domicilio_social
    - Estructura: estructura_accionaria, consejo_administracion
    - Registro: folio_mercantil
    """
    if not text_ocr.strip() and not (acta_text or "").strip():
        return {"error": "Texto vacío"}

    # Split Reforma text into manageable chunks
    MAX_CHUNK = 20000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)] or [""]

    acta_context = (acta_text or "").strip()
    acta_context_trimmed = acta_context[:10000] if acta_context else ""

    json_template = """
    {
      "numero_escritura": "",
      "fecha_otorgamiento": "",
      "fecha_expedicion": "",
      "nombre_notario": "",
      "numero_notaria": "",
      "estado_notaria": "",
      "razon_social": "",
      "objeto_social": "",
      "capital_social": "",
      "total_acciones": null,
      "estructura_accionaria": [],
      "consejo_administracion": [],
      "domicilio_social": "",
      "folio_mercantil": "",
      "campos_no_encontrados": []
    }
    """

    extracted_data = json.loads(json_template)

    for idx, chunk in enumerate(chunks, start=1):
        prompt = dedent(f"""
        Eres un analista experto en reformas de estatutos sociales mexicanas.
        Extrae la información solicitada de este documento de Reforma de Estatutos.
        
        CAMPOS A EXTRAER:
        
        1. "numero_escritura": Número de escritura pública o póliza (solo dígitos)
        2. "fecha_otorgamiento": Fecha en que se otorgó la escritura ante notario (formato DD/MM/AAAA)
        3. "fecha_expedicion": Fecha en que se expidió el testimonio (formato DD/MM/AAAA, buscar "SE EXPIDE", "EXPIDO EL PRESENTE")
        4. "nombre_notario": Nombre completo del notario público
        5. "numero_notaria": Número de la notaría (solo dígitos)
        6. "estado_notaria": Estado/entidad donde se ubica la notaría
        7. "razon_social": Denominación o razón social de la empresa (con tipo societario: S.A., S.A.P.I., etc.)
        8. "objeto_social": Resumen del objeto social de la empresa (máximo 200 palabras)
        9. "capital_social": Monto del capital social (puede ser fijo, variable o ambos)
        10. "total_acciones": Total de acciones de la sociedad (número entero, sin comas). Usar el total más reciente de Serie "A" si existen múltiples series.
        11. "estructura_accionaria": Lista de accionistas con la distribución VIGENTE/FINAL.
            
            === REGLAS CRÍTICAS PARA IDENTIFICAR LA TABLA CORRECTA ===
            
            PRIORIDAD DE SERIES DE ACCIONES (usar en este orden):
            1. Serie "A" = CAPITAL FIJO con derecho a voto (PRIORIZAR SIEMPRE)
            2. Ignorar Serie "B", Serie "I" u otras series sin derecho a voto
            3. Ignorar "Acciones de Inversión", "Accionistas de Inversión"
            
            CÓMO IDENTIFICAR LA TABLA MÁS RECIENTE:
            - Buscar frases como: "el cuadro accionario QUEDA", "la distribución QUEDA", "COMO CONSECUENCIA de lo anterior"
            - La tabla correcta suele estar DESPUÉS de la última resolución de la asamblea
            - Si hay múltiples asambleas históricas, usar SOLO la del acta que se protocoliza (la más reciente)
            - El total debe coincidir con el capital fijo reformado más reciente
            
            QUÉ INCLUIR (OBLIGATORIO extraer TODOS estos):
            - TODAS las personas físicas con acciones Serie "A"
            - TODAS las personas morales/empresas con acciones Serie "A" (ej: "Bastión Capital, S.A.P.I.", "Vinsa Investment Group, LLC", "Fund Asymetric, S.A.P.I.")
            - Empresas holding, fondos de inversión, S.A.P.I., LLC que tengan acciones
            
            QUÉ EXCLUIR (NO incluir estos):
            - "Tesorería", "En tesorería de la Sociedad"
            - "Reservas", "Fondo de reserva"
            - "Accionistas de Inversión" (categoría genérica sin nombre específico)
            - Totales o subtotales
            - Tablas históricas de asambleas anteriores
            
            VERIFICACIÓN: La suma de porcentajes de TODOS los accionistas Serie "A" debe ser aproximadamente 100%
            
            DEDUPLICACIÓN:
            - Cada persona/empresa DEBE APARECER UNA SOLA VEZ
            - Si ves "JUAN PÉREZ" y "Juan Pérez", es la MISMA persona - usar solo una entrada
            - Si ves "Aldo Aceves González" y "SANTIAGO ALDO ACEVES GONZÁLEZ", probablemente son la misma persona
            
            Formato: [{{"nombre": "Nombre completo", "acciones": número_entero, "porcentaje": decimal, "tipo": "fisica" o "moral"}}]
            - "acciones": número de acciones Serie A (entero sin comas, ej: 584)
            - "porcentaje": porcentaje de participación (decimal, ej: 35.98)
            - "tipo": "fisica" para personas físicas, "moral" para empresas (S.A., S.A.P.I., LLC, etc.)

        12. "consejo_administracion": Lista de miembros del consejo ACTUAL (el más reciente nombrado en el documento):
            [{{"nombre": "Nombre completo", "cargo": "Presidente/Secretario/Tesorero/Vocal/etc"}}]
        13. "domicilio_social": Dirección del domicilio social de la empresa
        14. "folio_mercantil": Número de folio mercantil electrónico (formato XXXXX*XX o N-XXXXXXXXX)
        
        REGLAS GENERALES:
        - Responde SOLO con JSON válido
        - Convierte fechas en palabras a formato DD/MM/AAAA (ej: "cinco de marzo de dos mil trece" -> "05/03/2013")
        - Si un campo no aparece, déjalo vacío y agrégalo a "campos_no_encontrados"
        - Para listas vacías, usa []
        - NO inventes datos
        - Si hay duda entre dos tablas, preferir la que suma exactamente 100% en porcentajes
        
        JSON esperado:
        {json_template}

        Texto de Reforma de Estatutos (fragmento {idx}/{len(chunks)}):
        {chunk}

        {"Contexto adicional del Acta Constitutiva (usar solo si falta el dato en la Reforma):" + acta_context_trimmed if acta_context_trimmed else ""}
        """)

        resp = llm.invoke(prompt).content.strip()
        resp = re.sub(r"^```(?:json)?|```$", "", resp).strip()
        match = re.search(r"\{.*\}", resp, re.S)

        try:
            partial_data = json.loads(match.group(0)) if match else {}
        except:
            partial_data = {}

        # Merge results - LÓGICA ESPECIAL para estructura_accionaria
        for key in extracted_data.keys():
            if key == "estructura_accionaria":
                # Para estructura accionaria: ser CONSERVADOR - preferir la primera tabla válida
                if partial_data.get(key) and len(partial_data[key]) > 0:
                    nueva_estructura = partial_data[key]
                    estructura_actual = extracted_data[key]
                    
                    # Calcular suma de porcentajes
                    def calc_suma_pct(lista):
                        return sum(a.get("porcentaje", 0) or 0 for a in lista if isinstance(a, dict))
                    
                    suma_nueva = calc_suma_pct(nueva_estructura)
                    suma_actual = calc_suma_pct(estructura_actual) if estructura_actual else 0
                    
                    # REGLA: Si ya tenemos una estructura que suma ~100%, NO reemplazar
                    # Solo reemplazar si la actual está vacía o muy incompleta
                    if not estructura_actual or len(estructura_actual) == 0:
                        # No hay estructura actual, usar la nueva
                        extracted_data[key] = nueva_estructura
                    elif suma_actual >= 95 and suma_actual <= 105:
                        # La actual ya suma ~100%, mantenerla (es probablemente correcta)
                        pass
                    elif suma_nueva >= 95 and suma_nueva <= 105 and (suma_actual < 90 or suma_actual > 110):
                        # La nueva suma ~100% y la actual no - reemplazar
                        extracted_data[key] = nueva_estructura
                    # En cualquier otro caso, mantener la estructura actual (primera encontrada)
            elif key == "consejo_administracion":
                # Similar para consejo: preferir el último (más reciente)
                if partial_data.get(key) and len(partial_data[key]) > 0:
                    if not extracted_data[key] or len(extracted_data[key]) == 0:
                        extracted_data[key] = partial_data[key]
                    else:
                        # Reemplazar si el nuevo tiene datos y parece un consejo completo
                        nuevo_consejo = partial_data[key]
                        if len(nuevo_consejo) >= 3:  # Un consejo mínimo tiene Presidente, Secretario, Tesorero
                            extracted_data[key] = nuevo_consejo
            elif isinstance(extracted_data[key], list):
                # Para otras listas, acumular sin duplicados
                if partial_data.get(key):
                    for item in partial_data[key]:
                        if item not in extracted_data[key]:
                            extracted_data[key].append(item)
            else:
                if not extracted_data[key] and partial_data.get(key):
                    extracted_data[key] = partial_data[key]

    # Post-procesamiento con backup robusto
    extracted_data = _validate_and_correct_reforma_fields(extracted_data, text_ocr, llm)
    
    # Agregar evidencia de extracción (página y párrafo)
    campos_a_buscar = [
        "numero_escritura", "fecha_otorgamiento", "fecha_expedicion",
        "nombre_notario", "numero_notaria", "estado_notaria",
        "razon_social", "objeto_social", "capital_social",
        "domicilio_social", "folio_mercantil"
    ]
    extracted_data = _add_extraction_evidence_generic(extracted_data, text_ocr, campos_a_buscar)

    return extracted_data


def _validate_and_correct_reforma_fields(data: dict, text_ocr: str, llm=None) -> dict:
    """
    Post-procesamiento para campos de Reforma de Estatutos.
    Similar a _validate_and_correct_acta_fields.
    Incluye backup con regex y re-extracción con LLM si la suma de porcentajes es baja.
    """
    result = data.copy()
    text_lower = text_ocr.lower()
    
    # Meses para conversión
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. NÚMERO DE ESCRITURA - Limpiar y validar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("numero_escritura"):
        num = re.sub(r'[^\d]', '', str(result["numero_escritura"]))
        if num:
            result["numero_escritura"] = num
    else:
        # Buscar con regex
        patterns = [
            r'ESCRITURA\s+P[ÚU]BLICA\s+(?:N[ÚU]MERO\s+)?(\d{1,6})',
            r'ESCRITURA\s+(?:N[ÚU]MERO\s+)?(\d{1,6})',
            r'P[ÓO]LIZA\s+(?:N[ÚU]MERO\s+)?(\d{1,6})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_escritura"] = match.group(1)
                break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. NÚMERO DE NOTARÍA - Limpiar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("numero_notaria"):
        num = re.sub(r'[^\d]', '', str(result["numero_notaria"]))
        if num:
            result["numero_notaria"] = num
    else:
        # Buscar con regex
        patterns = [
            r'NOTAR[ÍI]A\s+P[ÚU]BLICA\s+(?:N[ÚU]MERO\s+)?(\d{1,4})',
            r'NOTAR[ÍI]O\s+P[ÚU]BLICO\s+(?:N[ÚU]MERO\s+)?(\d{1,4})',
            r'NOTARIA\s+(\d{1,4})\s+DEL',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_notaria"] = match.group(1)
                break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. FOLIO MERCANTIL - Buscar si está vacío
    # ═══════════════════════════════════════════════════════════════════════════
    if not result.get("folio_mercantil") or "pendiente" in str(result.get("folio_mercantil", "")).lower():
        folio_patterns = [
            r'FOLIO\s+MERCANTIL\s+(?:ELECTR[ÓO]NICO\s+)?(?:N[ÚU]MERO\s+)?(\d{4,12}[\*\-]?\d{0,4})',
            r'FOLIO\s+(?:MERCANTIL\s+)?(?:N[ÚU]MERO\s+)?(\d{4,12}[\*\-]?\d{0,4})',
            r'N-?20\d{2}\d+',
        ]
        for pattern in folio_patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["folio_mercantil"] = match.group(1) if match.lastindex else match.group(0)
                break
    
    # Restauración global: si el folio final es puramente numérico,
    # intentar restaurar prefijo N-/M- desde el texto OCR original
    folio_final = str(result.get("folio_mercantil", "")).strip()
    if folio_final and re.match(r'^\d+$', folio_final):
        prefix_check = re.search(
            r'([NM])-' + re.escape(folio_final),
            text_ocr, re.IGNORECASE
        )
        if prefix_check:
            result["folio_mercantil"] = f"{prefix_check.group(1).upper()}-{folio_final}"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. FECHA DE EXPEDICIÓN - Buscar en la nota al calce
    # ═══════════════════════════════════════════════════════════════════════════
    fecha_exp_actual = str(result.get("fecha_expedicion", "")).lower()
    necesita_buscar_fecha = (
        not result.get("fecha_expedicion") or
        "pendiente" in fecha_exp_actual or
        fecha_exp_actual in ["n/a", "", "null", "none"]
    )
    
    if necesita_buscar_fecha:
        texto_final = text_ocr[-15000:] if len(text_ocr) > 15000 else text_ocr
        
        expedicion_patterns = [
            r'(?:SE\s+EXPIDE|EXPIDO\s+EL\s+PRESENTE|LO\s+EXPIDO)[^\d]*(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de[l]?\s+)?(?:año\s+)?(\d{4}|\d{2}\s*mil\s*\d+)',
            r'(?:EN\s+)?(?:LA\s+CIUDAD\s+DE\s+)?[A-ZÁÉÍÓÚ][a-záéíóú]+[,\s]+(?:A\s+)?(?:LOS\s+)?(\d{1,2})\s+(?:D[ÍI]AS?\s+)?(?:DEL?\s+MES\s+DE\s+)?([A-ZÁÉÍÓÚa-záéíóú]+)\s+(?:DEL?\s+)?(?:AÑO\s+)?(\d{4})',
        ]
        
        for pattern in expedicion_patterns:
            match = re.search(pattern, texto_final, re.IGNORECASE)
            if match:
                dia = match.group(1).zfill(2)
                mes_texto = match.group(2).lower()
                anio = match.group(3)
                
                if mes_texto in meses:
                    mes = meses[mes_texto]
                    result["fecha_expedicion"] = f"{dia}/{mes}/{anio}"
                    break
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. RAZÓN SOCIAL - Limpiar
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("razon_social"):
        razon = str(result["razon_social"])
        # Quitar comillas y normalizar
        razon = razon.strip('"\'').strip()
        result["razon_social"] = razon
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 6. NOMBRE NOTARIO - Limpiar saltos de línea
    # ═══════════════════════════════════════════════════════════════════════════
    if result.get("nombre_notario"):
        nombre = str(result["nombre_notario"])
        nombre = nombre.split('\n')[0].strip()
        nombre = nombre.split('\\n')[0].strip()
        nombre = re.sub(r'\s*(?:ESC|Esc|LIBRO|Libro|NOTARIO)[:\s].*$', '', nombre, flags=re.IGNORECASE)
        result["nombre_notario"] = nombre.strip()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 7. CAMPOS NO ENCONTRADOS - Actualizar lista
    # ═══════════════════════════════════════════════════════════════════════════
    campos_obligatorios = [
        "numero_escritura", "fecha_otorgamiento", "razon_social",
        "numero_notaria", "nombre_notario", "folio_mercantil"
    ]
    
    if "campos_no_encontrados" not in result:
        result["campos_no_encontrados"] = []
    
    for campo in campos_obligatorios:
        valor = result.get(campo)
        if isinstance(valor, list):
            es_vacio = not valor
        else:
            valor_str = str(valor).lower().strip()
            es_vacio = not valor_str or valor_str in ["", "n/a", "null", "none", "pendiente"]
        
        if es_vacio:
            if campo not in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].append(campo)
        else:
            if campo in result["campos_no_encontrados"]:
                result["campos_no_encontrados"].remove(campo)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 8. VALIDACIÓN DE ESTRUCTURA ACCIONARIA (similar a Actas)
    # ═══════════════════════════════════════════════════════════════════════════
    estructura = result.get("estructura_accionaria", [])
    
    if estructura:
        # Función para normalizar nombres (quitar acentos, mayúsculas, etc.)
        def normalizar_nombre(nombre: str) -> str:
            import unicodedata
            if not nombre:
                return ""
            # Quitar acentos
            nombre = unicodedata.normalize('NFKD', nombre)
            nombre = ''.join(c for c in nombre if not unicodedata.combining(c))
            # Mayúsculas y quitar espacios extra
            nombre = ' '.join(nombre.upper().split())
            return nombre
        
        # Filtrar entradas que no son accionistas reales
        # NOTA: Solo excluir nombres que son EXACTAMENTE estas categorías, no parte de nombres de empresas
        nombres_excluir_exactos = ["TESORERIA", "EN TESORERIA", "RESERVA", "ACCIONISTAS DE INVERSION", 
                          "ACCIONISTAS", "OTROS", "TOTAL", "TOTALES", "CAPITAL SOCIAL", "CAPITAL FIJO", "CAPITAL VARIABLE"]
        estructura_filtrada = []
        for acc in estructura:
            nombre_norm = normalizar_nombre(acc.get("nombre", ""))
            # Solo excluir si el nombre ES EXACTAMENTE una categoría genérica
            # No excluir si contiene la palabra (ej: "Bastión Capital" no debe excluirse)
            if nombre_norm and nombre_norm not in nombres_excluir_exactos:
                estructura_filtrada.append(acc)
        estructura = estructura_filtrada
        
        # Función para detectar si dos nombres son probablemente la misma persona
        def nombres_similares(nombre1: str, nombre2: str) -> bool:
            """Detecta si dos nombres normalizados son probablemente la misma persona"""
            if nombre1 == nombre2:
                return True
            
            # Separar en palabras
            palabras1 = set(nombre1.split())
            palabras2 = set(nombre2.split())
            
            # Ignorar palabras muy cortas (preposiciones, artículos)
            palabras_ignorar = {"DE", "LA", "LOS", "LAS", "DEL", "Y", "E"}
            palabras1 = palabras1 - palabras_ignorar
            palabras2 = palabras2 - palabras_ignorar
            
            if not palabras1 or not palabras2:
                return False
            
            # Si comparten al menos 2 palabras significativas (apellidos), probablemente son la misma persona
            # Ej: "Aldo Aceves González" vs "SANTIAGO ALDO ACEVES GONZÁLEZ"
            palabras_comunes = palabras1 & palabras2
            
            # Si comparten 2+ palabras de 4+ caracteres, probablemente son la misma persona
            palabras_significativas = [p for p in palabras_comunes if len(p) >= 4]
            if len(palabras_significativas) >= 2:
                return True
            
            # Un nombre contiene al otro completamente
            if nombre1 in nombre2 or nombre2 in nombre1:
                return True
            
            return False
        
        # Deduplicar accionistas por nombre normalizado con detección de similitud
        nombres_vistos = {}  # nombre_normalizado -> índice en estructura_limpia
        estructura_limpia = []
        
        for acc in estructura:
            nombre_norm = normalizar_nombre(acc.get("nombre", ""))
            if not nombre_norm:
                continue
            
            # Buscar si ya existe un nombre similar
            nombre_existente = None
            for nombre_visto in nombres_vistos:
                if nombres_similares(nombre_norm, nombre_visto):
                    nombre_existente = nombre_visto
                    break
            
            if nombre_existente is None:
                # Nuevo accionista
                nombres_vistos[nombre_norm] = len(estructura_limpia)
                estructura_limpia.append(acc)
            else:
                # Duplicado detectado - NO fusionar, mantener el que ya tenemos
                # (la nueva lógica de merge ya prioriza la última tabla)
                pass
        
        estructura = estructura_limpia
        result["estructura_accionaria"] = estructura
        
        # Normalizar acciones (quitar comas, convertir a entero)
        for acc in estructura:
            if acc.get("acciones"):
                try:
                    acciones_str = str(acc["acciones"]).replace(",", "").replace(" ", "")
                    # Si tiene % es un porcentaje guardado como acciones
                    if "%" in acciones_str:
                        porcentaje_match = re.search(r"([\d.]+)", acciones_str)
                        if porcentaje_match and not acc.get("porcentaje"):
                            acc["porcentaje"] = float(porcentaje_match.group(1))
                        acc["acciones"] = None
                    else:
                        acc["acciones"] = int(float(acciones_str))
                except (ValueError, TypeError):
                    acc["acciones"] = None
            
            # Normalizar porcentaje
            if acc.get("porcentaje"):
                try:
                    acc["porcentaje"] = float(str(acc["porcentaje"]).replace(",", "").replace("%", "").strip())
                except (ValueError, TypeError):
                    acc["porcentaje"] = None
            
            # Determinar tipo (fisica/moral)
            if not acc.get("tipo") or acc.get("tipo") in ["ordinarias", "preferentes"]:
                nombre = (acc.get("nombre") or "").upper()
                if any(suf in nombre for suf in ["S.A.", "S.A.P.I.", "S.C.", "S. DE R.L.", "LLC", "S.A.S.", "A.C."]):
                    acc["tipo"] = "moral"
                else:
                    acc["tipo"] = "fisica"
        
        # Obtener total de acciones
        total_acciones = result.get("total_acciones")
        if total_acciones:
            try:
                total_acciones = int(str(total_acciones).replace(",", "").replace(".", ""))
            except (ValueError, TypeError):
                total_acciones = None
        
        # Si no hay total_acciones pero todos tienen acciones, calcular suma
        if not total_acciones:
            acciones_lista = [a.get("acciones") for a in estructura if a.get("acciones")]
            if acciones_lista and len(acciones_lista) == len(estructura):
                total_acciones = sum(acciones_lista)
                result["_total_acciones_calculado"] = total_acciones
        
        # Calcular porcentajes si faltan
        if total_acciones and total_acciones > 0:
            for acc in estructura:
                if acc.get("acciones") and not acc.get("porcentaje"):
                    acc["porcentaje"] = round((acc["acciones"] / total_acciones) * 100, 2)
                    acc["_porcentaje_calculado"] = True
        
        # Análisis de calidad
        accionistas_completos = 0
        accionistas_incompletos = 0
        accionistas_requieren_verificacion = 0
        
        for acc in estructura:
            tiene_acciones = acc.get("acciones") is not None
            tiene_porcentaje = acc.get("porcentaje") is not None
            requiere_verificacion = acc.get("_requiere_verificacion", False)
            
            if tiene_acciones or tiene_porcentaje:
                accionistas_completos += 1
            else:
                accionistas_incompletos += 1
            
            if requiere_verificacion:
                accionistas_requieren_verificacion += 1
        
        # Verificar suma de porcentajes
        porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
        total_porcentaje = sum(porcentajes)
        
        result["_suma_porcentajes"] = round(total_porcentaje, 2) if porcentajes else None
        result["_porcentajes_validos"] = abs(total_porcentaje - 100.0) <= 0.5 if porcentajes else False
        
        # ═══════════════════════════════════════════════════════════════════════════
        # BACKUP ROBUSTO: Si la suma de porcentajes es baja, intentar recuperar accionistas
        # ═══════════════════════════════════════════════════════════════════════════
        if total_porcentaje < 98 and total_porcentaje > 0:
            logger.info(f"[INFO] Suma de porcentajes baja ({total_porcentaje:.2f}%). Intentando backup...")
            
            # PASO 1: Intentar extraer con regex del OCR
            accionistas_regex = _extract_accionistas_regex_backup(text_ocr, estructura)
            if accionistas_regex:
                logger.info(f"[INFO] Backup regex encontró {len(accionistas_regex)} accionistas adicionales")
                for acc_nuevo in accionistas_regex:
                    # Solo agregar si el nombre es suficientemente largo y no es fragmento
                    nombre_nuevo = acc_nuevo.get("nombre", "")
                    if len(nombre_nuevo) >= 15 or any(suf in nombre_nuevo.upper() for suf in ["S.A.", "LLC", "S.A.P.I."]):
                        # Verificar que no sea fragmento de nombre existente
                        es_fragmento = False
                        for acc_exist in estructura:
                            nombre_exist = acc_exist.get("nombre", "")
                            if nombre_nuevo in nombre_exist or len(nombre_nuevo) < 12:
                                es_fragmento = True
                                break
                        if not es_fragmento:
                            estructura.append(acc_nuevo)
                
                # Deduplicar post-backup: eliminar nombres cortos que son fragmentos de otros
                estructura_limpia = []
                nombres_agregados = set()
                for acc in sorted(estructura, key=lambda x: -len(x.get("nombre", ""))):  # Ordenar por largo, más largos primero
                    nombre = acc.get("nombre", "")
                    nombre_norm = normalizar_nombre(nombre)
                    
                    # Si es muy corto (<15 chars) y parece fragmento, ignorar
                    if len(nombre) < 12:
                        continue
                    
                    # Verificar si es fragmento de uno ya agregado
                    es_duplicado = False
                    for agregado in nombres_agregados:
                        # Si comparten 2+ palabras significativas, es duplicado
                        palabras_nuevo = set(nombre_norm.split()) - {"DE", "LA", "LOS", "S", "A", "P", "I", "C", "V"}
                        palabras_exist = set(agregado.split()) - {"DE", "LA", "LOS", "S", "A", "P", "I", "C", "V"}
                        if len(palabras_nuevo & palabras_exist) >= 2:
                            es_duplicado = True
                            break
                        if nombre_norm in agregado or agregado in nombre_norm:
                            es_duplicado = True
                            break
                    
                    if not es_duplicado:
                        estructura_limpia.append(acc)
                        nombres_agregados.add(nombre_norm)
                
                estructura = estructura_limpia
                result["estructura_accionaria"] = estructura
                
                # Recalcular porcentajes
                porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
                total_porcentaje = sum(porcentajes)
                result["_suma_porcentajes"] = round(total_porcentaje, 2)
                result["_porcentajes_validos"] = abs(total_porcentaje - 100.0) <= 0.5
                result["_backup_regex_usado"] = True
            
            # PASO 2: Si aún es bajo y tenemos LLM, re-extraer
            if total_porcentaje < 98 and llm:
                logger.info(f"[INFO] Suma aún baja ({total_porcentaje:.2f}%). Intentando re-extracción LLM...")
                estructura_nueva = _reextract_estructura_accionaria(text_ocr, llm, total_acciones)
                
                if estructura_nueva:
                    # Verificar si la nueva extracción es mejor
                    nueva_suma = sum(a.get("porcentaje", 0) for a in estructura_nueva if a.get("porcentaje"))
                    if abs(nueva_suma - 100) < abs(total_porcentaje - 100):
                        logger.info(f"[INFO] Re-extracción mejor ({nueva_suma:.2f}% vs {total_porcentaje:.2f}%). Usando nueva estructura.")
                        estructura = estructura_nueva
                        result["estructura_accionaria"] = estructura
                        total_porcentaje = nueva_suma
                        result["_suma_porcentajes"] = round(nueva_suma, 2)
                        result["_porcentajes_validos"] = abs(nueva_suma - 100.0) <= 0.5
                        result["_reextraccion_usada"] = True
                    else:
                        # Intentar agregar accionistas faltantes de la re-extracción
                        nombres_existentes = {normalizar_nombre(a.get("nombre", "")) for a in estructura}
                        for acc_nuevo in estructura_nueva:
                            nombre_norm = normalizar_nombre(acc_nuevo.get("nombre", ""))
                            if nombre_norm and nombre_norm not in nombres_existentes:
                                estructura.append(acc_nuevo)
                                nombres_existentes.add(nombre_norm)
                        
                        # Recalcular
                        porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
                        total_porcentaje = sum(porcentajes)
                        result["_suma_porcentajes"] = round(total_porcentaje, 2)
                        result["_porcentajes_validos"] = abs(total_porcentaje - 100.0) <= 0.5
            
            # Actualizar estructura final
            result["estructura_accionaria"] = estructura
        
        # Verificar suma de acciones
        acciones_lista = [a.get("acciones", 0) for a in estructura if a.get("acciones") is not None]
        suma_acciones = sum(acciones_lista)
        if total_acciones and acciones_lista:
            result["_suma_acciones"] = suma_acciones
            result["_acciones_validas"] = suma_acciones == total_acciones
        
        # Recalcular contadores para confiabilidad (después del backup)
        accionistas_completos = 0
        accionistas_incompletos = 0
        accionistas_requieren_verificacion = 0
        
        for acc in estructura:
            tiene_acciones = acc.get("acciones") is not None
            tiene_porcentaje = acc.get("porcentaje") is not None
            requiere_verificacion = acc.get("_requiere_verificacion", False)
            
            if tiene_acciones or tiene_porcentaje:
                accionistas_completos += 1
            else:
                accionistas_incompletos += 1
            
            if requiere_verificacion:
                accionistas_requieren_verificacion += 1
        
        # Recalcular suma de porcentajes final
        porcentajes = [a.get("porcentaje", 0) for a in estructura if a.get("porcentaje") is not None]
        total_porcentaje = sum(porcentajes)
        result["_suma_porcentajes"] = round(total_porcentaje, 2) if porcentajes else None
        result["_porcentajes_validos"] = abs(total_porcentaje - 100.0) <= 1.0 if porcentajes else False  # Tolerancia de 1%
        
        # Calcular confiabilidad
        if len(estructura) == 0:
            confiabilidad = 0.0
        elif accionistas_completos == len(estructura) and result.get("_porcentajes_validos"):
            confiabilidad = 1.0
        elif accionistas_completos == len(estructura):
            confiabilidad = 0.8
        elif accionistas_completos > 0:
            confiabilidad = 0.5 * (accionistas_completos / len(estructura))
        else:
            confiabilidad = 0.2
        
        if accionistas_requieren_verificacion > 0 and not result.get("_porcentajes_validos"):
            confiabilidad *= 0.5
        
        result["_estructura_confiabilidad"] = round(confiabilidad, 2)
        
        # Determinar estado
        if confiabilidad >= 0.9:
            status = "Verificada"
        elif confiabilidad >= 0.6:
            status = "Parcial"
        elif confiabilidad >= 0.3:
            status = "Requiere_Verificacion"
        else:
            status = "No_Confiable"
        
        result["_estructura_accionaria_status"] = status
    
    return result


def extract_address_fields(text_ocr: str, llm) -> dict:
    """
    Envía texto OCR a un LLM para extraer un JSON con campos de dirección del titular.

    Args:
        text_ocr (str): Texto extraído mediante OCR.
        llm: Cliente con método invoke() para llamar al modelo.

    Returns:
        dict: Diccionario con campos extraídos o con clave 'error' si falla.
    """
    if not text_ocr or len(text_ocr.strip()) == 0:
        logger.error("[ERROR] Texto OCR vacío.")
        return {"error": "Texto OCR vacío"}

    prompt = dedent(f"""
        Eres un experto en comprobantes de domicilio mexicanos (CFE, agua, teléfono, etc.).

        El documento puede tener varias direcciones (sucursales, oficinas corporativas, etc.).
        Extrae SOLO la dirección del TITULAR/CLIENTE/USUARIO del servicio.

        REGLAS CRÍTICAS:
        1. "calle": nombre completo de la calle/avenida (ej: "AV LAZARO CARDENAS", "Meseta y Rumbo Hotel Ibis")
        2. "numero_exterior": SOLO el número principal de la calle. Si ves formato "SM15 MZ8 LT7", extrae "15". Si ves "303", usa "303"
        3. "numero_interior": departamento/interior/piso (ej: "N2", "DEPTO 5"). Si no hay, usa "N/A"
        4. "colonia": nombre de la colonia o fraccionamiento
        5. "alcaldia": delegación (CDMX) o municipio (otros estados)
        6. "ciudad": ciudad o población
        7. "entidad_federativa": nombre completo del estado ("Nuevo León", "Quintana Roo", "Jalisco", etc.)
        8. "estado": estado abreviado ("N.L.", "Q.R.", "JAL", "CHIS.", etc.)
        9. "codigo_postal": CP de 5 dígitos
        10. "fecha_emision": fecha del documento en formato YYYY-MM-DD. Busca "PERIODO FACTURADO", "FECHA LIMITE DE PAGO", "FECHA DE CORTE" o similar

        NO expandas abreviaturas en calle (conserva "AV", "BLVD", etc. tal como aparecen).
        Si un campo no aparece claramente, usa "N/A" (no vacío).
        Devuelve SOLO JSON válido, sin texto extra.

        Ejemplo:
        {{
          "calle": "AV LAZARO CARDENAS",
          "numero_exterior": "303",
          "numero_interior": "N2",
          "colonia": "DEL VALLE",
          "alcaldia": "SAN PEDRO GARZA GARCIA",
          "ciudad": "MONTERREY",
          "entidad_federativa": "Nuevo León",
          "estado": "N.L.",
          "codigo_postal": "66220",
          "fecha_emision": "2025-09-30"
        }}

        Texto del documento (max 25000 chars):
        {text_ocr[:25000]}
    """)

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()

        # Limpiar backticks ``` si vienen en la respuesta (markdown)
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw[3:-3].strip()

    except Exception as e:
        logger.error(f"[ERROR] Error al invocar al modelo: {e}")
        return {"error": f"Error invocación modelo: {e}"}

    # Mostrar raw para debug si no es JSON
    if not raw.lstrip().startswith("{"):
        logger.warning("[ADVERTENCIA] La respuesta no empieza con JSON. Mostrando raw para debug:")
        logger.info(raw)
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        raw = m.group(0) if m else '{"error":"json parsing"}'

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("[ERROR] Error al parsear JSON del modelo.")
        logger.info("Respuesta cruda:")
        logger.info(raw)
        return {"error": "No se pudo parsear JSON"}

    # Validar campos completos, agregando N/A si faltan
    campos = [
        "calle", "numero_exterior", "numero_interior", "colonia",
        "alcaldia", "ciudad", "entidad_federativa", "estado", "codigo_postal"
    ]
    for campo in campos:
        if campo not in data:
            data[campo] = "N/A"

    # ═══════════════════════════════════════════════════════════════════════════
    # MEJORAS DE ROBUSTEZ
    # ═══════════════════════════════════════════════════════════════════════════
    data = _domicilio_regex_fallback(data, text_ocr)
    data = _fix_campos_no_encontrados_generic(data, ["calle", "colonia", "codigo_postal", "entidad_federativa"])
    # Incluir TODOS los campos del domicilio para evidencia
    campos_domicilio = [
        "calle", "numero_exterior", "numero_interior", "colonia",
        "alcaldia", "ciudad", "entidad_federativa", "estado", "codigo_postal", "fecha_emision"
    ]
    data = _add_extraction_evidence_generic(data, text_ocr, campos_domicilio)

    return data


def _domicilio_regex_fallback(data: dict, text_ocr: str) -> dict:
    """Regex fallback para Comprobante de Domicilio."""
    result = data.copy()
    
    # Fecha de emisión - buscar múltiples formatos
    if not result.get("fecha_emision") or result.get("fecha_emision") == "N/A":
        # Formato: "31 AGO 25-30 SEP 25" -> tomar la fecha final
        match = re.search(r'PERIODO\s*FACTURADO[:\s]*\d+\s*\w+\s*\d+-?(\d{1,2})\s*(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s*(\d{2,4})', text_ocr, re.IGNORECASE)
        if match:
            dia, mes_str, anio = match.groups()
            meses = {"ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
                     "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12"}
            mes = meses.get(mes_str.upper(), "01")
            anio_full = f"20{anio}" if len(anio) == 2 else anio
            result["fecha_emision"] = f"{anio_full}-{mes}-{dia.zfill(2)}"
        else:
            # Formato: FECHA LIMITE DE PAGO:13 OCT 25
            match = re.search(r'FECHA\s*L[IÍ]MITE\s*(?:DE\s*)?PAGO[:\s]*(\d{1,2})\s*(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s*(\d{2,4})', text_ocr, re.IGNORECASE)
            if match:
                dia, mes_str, anio = match.groups()
                meses = {"ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
                         "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12"}
                mes = meses.get(mes_str.upper(), "01")
                anio_full = f"20{anio}" if len(anio) == 2 else anio
                result["fecha_emision"] = f"{anio_full}-{mes}-{dia.zfill(2)}"
    
    # Código Postal (5 dígitos)
    if not result.get("codigo_postal") or result.get("codigo_postal") == "N/A":
        match = re.search(r'\b(?:C\.?P\.?|C[ÓO]DIGO\s+POSTAL)[:\s]*(\d{5})\b', text_ocr, re.IGNORECASE)
        if match:
            result["codigo_postal"] = match.group(1)
        else:
            # Buscar cualquier secuencia de 5 dígitos cerca de "CP" o similar
            match = re.search(r'\b(\d{5})\b', text_ocr)
            if match:
                result["codigo_postal"] = match.group(1)
    
    # Estado / Entidad Federativa
    if not result.get("entidad_federativa") or result.get("entidad_federativa") == "N/A":
        estados = [
            "AGUASCALIENTES", "BAJA CALIFORNIA", "BAJA CALIFORNIA SUR", "CAMPECHE",
            "CHIAPAS", "CHIHUAHUA", "CIUDAD DE MEXICO", "CDMX", "COAHUILA", "COLIMA",
            "DURANGO", "GUANAJUATO", "GUERRERO", "HIDALGO", "JALISCO", "MEXICO",
            "MICHOACAN", "MORELOS", "NAYARIT", "NUEVO LEON", "OAXACA", "PUEBLA",
            "QUERETARO", "QUINTANA ROO", "SAN LUIS POTOSI", "SINALOA", "SONORA",
            "TABASCO", "TAMAULIPAS", "TLAXCALA", "VERACRUZ", "YUCATAN", "ZACATECAS"
        ]
        text_upper = text_ocr.upper()
        for estado in estados:
            if estado in text_upper:
                result["entidad_federativa"] = estado.title()
                break
    
    return result


def extract_estado_cuenta_fields(text_ocr: str, llm) -> dict:
    """
    Extracts fields from Estado de Cuenta (bank statement) using LLM.

    Args:
        text_ocr (str): Text extracted via OCR.
        llm: Client with invoke() method.

    Returns:
        dict: Dictionary with extracted fields or 'error' key if fails.
    """
    if not text_ocr or len(text_ocr.strip()) == 0:
        logger.error("[ERROR] Texto OCR vacío.")
        return {"error": "Texto OCR vacío"}

    prompt = dedent(f"""
        Eres un asistente experto en documentos bancarios mexicanos.

        Estás analizando un Estado de Cuenta bancario.

        Extrae ÚNICAMENTE los siguientes campos:
        - banco: Nombre del banco emisor (ejemplo: "BBVA", "Santander", "Banorte", etc.)
        - clabe: CLABE interbancaria (18 dígitos)
        - numero_cuenta: Número de cuenta del cliente
        - titular: Nombre del titular de la cuenta (persona física o moral dueña de la cuenta).
          IMPORTANTE: El titular aparece en el ENCABEZADO o DATOS GENERALES de la primera página,
          NO en los detalles de transacciones/movimientos. Ignora nombres de terceros que aparecen
          en transferencias SPEI, depósitos o retiros.
        - periodo: Período del estado de cuenta (ejemplo: "01/10/2025 - 31/10/2025")
        - saldo_inicial: Saldo inicial del período
        - saldo_final: Saldo final del período
        - total_depositos: Total de depósitos en el período
        - total_retiros: Total de retiros en el período

        Si algún campo no está presente, déjalo vacío ("").
        Para montos, incluye solo el número sin símbolo de moneda.
        Devuelve SOLO el JSON, sin texto adicional ni explicaciones.

        Ejemplo de salida JSON:
        {{
          "banco": "BBVA",
          "clabe": "012180001234567890",
          "numero_cuenta": "0123456789",
          "titular": "JUAN PEREZ GARCIA",
          "periodo": "01/10/2025 - 31/10/2025",
          "saldo_inicial": "50000.00",
          "saldo_final": "45000.00",
          "total_depositos": "20000.00",
          "total_retiros": "25000.00"
        }}

        TEXTO DEL DOCUMENTO (máximo 30000 caracteres):
        -----------------------------------------------
        {text_ocr[:30000]}
    """)

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()

        # Clean markdown backticks if present
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw[3:-3].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

    except Exception as e:
        logger.error(f"[ERROR] Error al invocar al modelo: {e}")
        return {"error": f"Error invocación modelo: {e}"}

    # Parse JSON
    if not raw.lstrip().startswith("{"):
        logger.warning("[ADVERTENCIA] La respuesta no empieza con JSON. Mostrando raw para debug:")
        logger.info(raw)
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        raw = m.group(0) if m else '{"error":"json parsing"}'

    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[ERROR] Error al parsear JSON: {e}")
        logger.info(f"Raw: {raw[:500]}")
        return {"error": f"Error parsing JSON: {e}"}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MEJORAS DE ROBUSTEZ
    # ═══════════════════════════════════════════════════════════════════════════
    extracted = _estado_cuenta_regex_fallback(extracted, text_ocr)
    extracted = _limpiar_titular_estado_cuenta(extracted, text_ocr)
    extracted = _fix_campos_no_encontrados_generic(extracted, ["banco", "clabe", "numero_cuenta", "titular"])
    # Incluir TODOS los campos del estado de cuenta para evidencia
    campos_edo_cuenta = [
        "banco", "clabe", "numero_cuenta", "titular", "periodo",
        "saldo_inicial", "saldo_final", "total_depositos", "total_retiros"
    ]
    extracted = _add_extraction_evidence_generic(extracted, text_ocr, campos_edo_cuenta)
    
    return extracted


def _limpiar_titular_estado_cuenta(data: dict, text_ocr: str) -> dict:
    """Filtra titulares que son disclaimers/basura del banco en vez del nombre real."""
    result = data.copy()
    titular = result.get("titular", "")
    if not titular:
        return result

    _TITULAR_BASURA = [
        "BENEFICIARIO", "DATO NO CERTIFICADO", "ESTE DOCUMENTO",
        "PARA EFECTOS", "INFORMACION CONFIDENCIAL", "ESTIMADO CLIENTE",
        "NO CERTIFICADO POR ESTA INSTITUCION", "CERTIFICADO POR",
    ]

    norm = titular.upper().strip()
    es_corrupto = (
        "\n" in titular
        or "\r" in titular
        or len(titular) > 80
        or any(b in norm for b in _TITULAR_BASURA)
    )

    if es_corrupto:
        logger.warning(f"[TITULAR] Titular corrupto detectado: {titular[:80]!r}")
        # Intentar re-extraer con regex desde el ENCABEZADO (primera página)
        header_text = text_ocr[:2000]
        patterns = [
            r'(?:TITULAR|CLIENTE|RAZÓN\s*SOCIAL)[:\s]*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,60})',
            r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}\s+S\.?A\.?\s*(?:DE\s*)?C\.?V\.?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, header_text)
            if match:
                candidato = match.group(1).strip()
                candidato_upper = candidato.upper()
                if not any(b in candidato_upper for b in _TITULAR_BASURA) and len(candidato) <= 80:
                    result["titular"] = candidato
                    logger.info(f"[TITULAR] Re-extraído: {candidato!r}")
                    return result
        # Si no se pudo recuperar, dejar vacío para que sea evidente
        result["titular"] = ""
        logger.warning("[TITULAR] No se pudo recuperar un titular válido")

    return result


def _estado_cuenta_regex_fallback(data: dict, text_ocr: str) -> dict:
    """Regex fallback para Estado de Cuenta Bancario."""
    result = data.copy()
    
    # CLABE (18 dígitos)
    if not result.get("clabe") or result.get("clabe") == "":
        match = re.search(r'\b(\d{18})\b', text_ocr)
        if match:
            result["clabe"] = match.group(1)
    
    # Número de cuenta (10-12 dígitos típicamente)
    if not result.get("numero_cuenta") or result.get("numero_cuenta") == "":
        match = re.search(r'(?:CUENTA|CTA\.?)[:\s]*(\d{10,12})', text_ocr, re.IGNORECASE)
        if match:
            result["numero_cuenta"] = match.group(1)
    
    # Banco
    if not result.get("banco") or result.get("banco") == "":
        bancos = ["BBVA", "SANTANDER", "BANORTE", "HSBC", "SCOTIABANK", "BANAMEX", "CITIBANAMEX", 
                  "INBURSA", "BANREGIO", "BAJIO", "BANBAJIO", "AFIRME", "MULTIVA", "BANCO AZTECA",
                  "BANCREA", "CIBANCO", "BANSI", "MIFEL", "VE POR MAS", "INTERCAM"]
        text_upper = text_ocr.upper()
        for banco in bancos:
            if banco in text_upper:
                result["banco"] = banco.title()
                break
    
    # Titular - buscar en el ENCABEZADO (primera página, ~2000 chars)
    # NO buscar en todo el texto para evitar capturar terceros de transacciones SPEI
    if not result.get("titular") or result.get("titular") in ["", "N/A"]:
        header_text = text_ocr[:2000]  # Solo encabezado / primera página
        patterns = [
            r'RFC[:\s]+[A-Z0-9]{12,13}\s+([A-Z][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+(?:S\.?A\.?\s*(?:DE\s*)?C\.?V\.?)?)',
            r'(?:TITULAR|CLIENTE|RAZÓN\s*SOCIAL)[:\s]*([A-Z][A-ZÁÉÍÓÚÑ\s]+(?:S\.?A\.?\s*(?:DE\s*)?C\.?V\.?)?)',
            r'(?:NOMBRE|BENEFICIARIO)[:\s]*([A-Z][A-ZÁÉÍÓÚÑ\s]+(?:S\.?A\.?\s*(?:DE\s*)?C\.?V\.?)?)',
            # Buscar empresa SA DE CV solo en encabezado
            r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}\s+S\.?A\.?\s*(?:DE\s*)?C\.?V\.?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, header_text, re.IGNORECASE)
            if match:
                titular = match.group(1).strip()
                # Limpiar y validar
                if len(titular) > 5 and not any(x in titular.upper() for x in ["PÁGINA", "ESTADO DE CUENTA", "PERIODO"]):
                    result["titular"] = titular
                    break
    
    return result


def extract_csf_fields(text_ocr: str, llm) -> dict:
    """Extract fields from CSF including new business details."""
    if not text_ocr or len(text_ocr.strip()) == 0:
        logger.error("[ERROR] Texto OCR vacío.")
        return {"error": "Texto OCR vacío"}

    prompt = dedent(f"""
        Eres un analista experto en Constancias de Situación Fiscal (CSF) de México.

        Devuelve SOLO JSON con las llaves exactas y SIN texto adicional.

        Campos requeridos:
        - razon_social: nombre o razón social de la empresa
        - rfc: RFC de la empresa
        - nombre_comercial: nombre comercial si aparece
        - giro_mercantil: actividad u objeto social (giro mercantil / actividad preponderante)
        - telefono: teléfono DE LA EMPRESA si aparece (NO el teléfono del SAT/MarcaSAT que es 55 627 22 728)
        - extranjeras: true/false. Si dice "Sin obligaciones" o "No aplica" para extranjeras, usa false.
        - fecha_emision: fecha de emisión del documento. Busca "Lugar y Fecha de Emisión" o similar. Formato: DD/MM/YYYY
        - codigo_postal: código postal del domicilio fiscal
        - estatus_padron: estatus en el padrón (ACTIVO, SUSPENDIDO, etc.)
        - domicilio_fiscal: dirección completa del domicilio fiscal

        Reglas:
        - Si un campo no se encuentra, déjalo como "" (string vacío), excepto extranjeras que debe ser booleano (default false).
        - No inventes valores.
        - No incluyas comentarios ni texto fuera del JSON.
        - IMPORTANTE: El teléfono del SAT (MarcaSAT 55 627 22 728 / 5562722728) NO es el teléfono de la empresa. Déjalo vacío si solo aparece ese.
        - IMPORTANTE: La fecha_emision está en "Lugar y Fecha de Emisión: CIUDAD A DD DE MES DE YYYY"

        Ejemplo de salida:
        {{
          "razon_social": "ACME SA DE CV",
          "rfc": "ACM123456789",
          "nombre_comercial": "ACME",
          "giro_mercantil": "Comercio al por mayor",
          "telefono": "5555123456",
          "extranjeras": false,
          "fecha_emision": "12/08/2025",
          "codigo_postal": "06600",
          "estatus_padron": "ACTIVO",
          "domicilio_fiscal": "CALLE EJEMPLO 123, COL. CENTRO, CP 06600"
        }}

        Texto (truncado a 12000 chars):
        {text_ocr[:12000]}
    """)

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()

        if raw.startswith("```") and raw.endswith("```"):
            raw = raw[3:-3].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

    except Exception as e:
        logger.error(f"[ERROR] Error al invocar al modelo: {e}")
        return {"error": f"Error invocación modelo: {e}"}

    if not raw.lstrip().startswith("{"):
        logger.warning("[ADVERTENCIA] La respuesta no empieza con JSON. Mostrando raw para debug:")
        logger.info(raw)
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        raw = m.group(0) if m else '{"error":"json parsing"}'

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("[ERROR] Error al parsear JSON del modelo.")
        logger.info("Respuesta cruda:")
        logger.info(raw)
        return {"error": "No se pudo parsear JSON"}

    campos = [
        "razon_social",
        "rfc",
        "nombre_comercial",
        "giro_mercantil",
        "telefono",
        "extranjeras",
        "fecha_emision",
        "codigo_postal",
        "estatus_padron",
        "domicilio_fiscal",
    ]
    for campo in campos:
        if campo not in data:
            data[campo] = False if campo == "extranjeras" else ""
    if not isinstance(data.get("extranjeras"), bool):
        data["extranjeras"] = False

    missing = [c for c in campos if (data.get(c) in ("", None)) and c != "extranjeras"]
    data["campos_no_encontrados"] = missing
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MEJORAS DE ROBUSTEZ: Regex fallback, evidencia y corrección de inconsistencias
    # ═══════════════════════════════════════════════════════════════════════════
    data = _csf_regex_fallback(data, text_ocr)
    data = _csf_filter_sat_phone(data)  # Filtrar teléfono del SAT
    data = _fix_campos_no_encontrados_generic(data, ["rfc", "razon_social", "giro_mercantil", "fecha_emision"])
    # Incluir TODOS los campos de CSF para evidencia
    campos_csf = [
        "razon_social", "rfc", "nombre_comercial", "giro_mercantil", "telefono",
        "fecha_emision", "codigo_postal", "estatus_padron", "domicilio_fiscal"
    ]
    data = _add_extraction_evidence_generic(data, text_ocr, campos_csf)

    return data


def _csf_filter_sat_phone(data: dict) -> dict:
    """Filtra el teléfono del SAT (MarcaSAT) que no es el teléfono de la empresa."""
    result = data.copy()
    telefono = result.get("telefono", "")
    
    if telefono:
        # Normalizar: quitar espacios y guiones
        telefono_normalizado = re.sub(r'[\s\-\(\)]', '', str(telefono))
        
        # Teléfonos conocidos del SAT que NO son de la empresa
        telefonos_sat = [
            "5562722728",   # MarcaSAT nacional
            "556272272",    # Variante
            "8004636728",   # Línea 01-800
            "018004636728", # Con prefijo
        ]
        
        if telefono_normalizado in telefonos_sat or telefono_normalizado.startswith("556272272"):
            result["telefono"] = ""
            # Actualizar campos_no_encontrados
            if "campos_no_encontrados" in result:
                if "telefono" not in result["campos_no_encontrados"]:
                    result["campos_no_encontrados"].append("telefono")
    
    return result


def _csf_regex_fallback(data: dict, text_ocr: str) -> dict:
    """Regex fallback para CSF."""
    result = data.copy()
    
    # RFC (12-13 caracteres)
    if not result.get("rfc") or result.get("rfc") == "":
        match = re.search(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b', text_ocr.upper())
        if match:
            result["rfc"] = match.group(1)
    
    # Razón social (buscar después de "DENOMINACIÓN" o "RAZÓN SOCIAL")
    if not result.get("razon_social") or result.get("razon_social") == "":
        patterns = [
            r'(?:DENOMINACI[ÓO]N|RAZ[ÓO]N\s+SOCIAL)[:\s]+([A-ZÁÉÍÓÚÑ\s,\.]+(?:S\.?A\.?|S\.?C\.?|S\.?DE\s*R\.?L\.?|S\.?A\.?P\.?I\.?)[^\n]*)',
            r'(?:DENOMINACI[ÓO]N|RAZ[ÓO]N\s+SOCIAL)[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,\.]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["razon_social"] = match.group(1).strip()[:100]
                break
    
    # Fecha de emisión - CRÍTICA para validación de vigencia
    if not result.get("fecha_emision") or result.get("fecha_emision") == "":
        # Patrón: "A DD DE MES DE YYYY" o "DD DE MES DE YYYY"
        meses = {
            'ENERO': '01', 'FEBRERO': '02', 'MARZO': '03', 'ABRIL': '04',
            'MAYO': '05', 'JUNIO': '06', 'JULIO': '07', 'AGOSTO': '08',
            'SEPTIEMBRE': '09', 'OCTUBRE': '10', 'NOVIEMBRE': '11', 'DICIEMBRE': '12'
        }
        # Buscar "Fecha de Emisión" o similar
        pattern = r'(?:FECHA\s+DE\s+EMISI[ÓO]N|EMISI[ÓO]N)[^\d]*(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})'
        match = re.search(pattern, text_ocr.upper())
        if match:
            dia = match.group(1).zfill(2)
            mes_nombre = match.group(2)
            anio = match.group(3)
            mes = meses.get(mes_nombre, '01')
            result["fecha_emision"] = f"{dia}/{mes}/{anio}"
        else:
            # Buscar patrón alternativo: "A DD DE MES DE YYYY"
            pattern2 = r'A\s+(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})'
            match2 = re.search(pattern2, text_ocr.upper())
            if match2:
                dia = match2.group(1).zfill(2)
                mes_nombre = match2.group(2)
                anio = match2.group(3)
                mes = meses.get(mes_nombre, '01')
                result["fecha_emision"] = f"{dia}/{mes}/{anio}"
    
    # Código postal
    if not result.get("codigo_postal") or result.get("codigo_postal") == "":
        match = re.search(r'C[ÓO]DIGO\s+POSTAL[:\s]*(\d{5})', text_ocr.upper())
        if match:
            result["codigo_postal"] = match.group(1)
    
    # Estatus en el padrón
    if not result.get("estatus_padron") or result.get("estatus_padron") == "":
        match = re.search(r'ESTATUS\s+EN\s+EL\s+PADR[ÓO]N[:\s]*([A-ZÁÉÍÓÚ]+)', text_ocr.upper())
        if match:
            result["estatus_padron"] = match.group(1)
    
    return result


def extract_fiel_fields(text_ocr: str, llm) -> dict:
    """Extract fields from FIEL (Firma Electrónica) acknowledgments.

    Returns JSON with:
    - rfc, razon_social, extranjeras (bool)
    - numero_serie_certificado, fecha_solicitud, vigencia_desde, vigencia_hasta
    Missing optional fields return empty strings; `extranjeras` defaults to False.
    """
    if not text_ocr or len(text_ocr.strip()) == 0:
        logger.error("[ERROR] Texto OCR vacío.")
        return {"error": "Texto OCR vacío"}

    prompt = dedent(f"""
        Eres un analista experto en acuses de la FIEL (Firma Electrónica Avanzada) del SAT.
        Devuelve SOLO JSON válido sin texto adicional.

        Extrae estos campos si aparecen exactamente del documento:
        - rfc: RFC del titular (persona moral o física)
        - razon_social: denominación o razón social (o nombre completo si es persona física)
        - numero_serie_certificado: número de serie del certificado (puede llamarse "Número de serie" o similar)
        - fecha_solicitud: fecha de la solicitud o expedición
        - vigencia_desde: inicio de vigencia del certificado
        - vigencia_hasta: fin de vigencia del certificado
        - extranjeras: true/false (si no hay evidencia clara de exterior, usa false)

        Reglas:
        - Si algún campo no aparece, deja "" excepto extranjeras que debe ser booleano.
        - Normaliza fechas al formato dd/mm/aaaa cuando sea posible.
        - No inventes valores.

        Ejemplo de salida:
        {{
          "rfc": "ACM010101ABC",
          "razon_social": "ACME S.A. DE C.V.",
          "numero_serie_certificado": "0003-12A4-56BC-7890",
          "fecha_solicitud": "05/07/2024",
          "vigencia_desde": "05/07/2024",
          "vigencia_hasta": "05/07/2026",
          "extranjeras": false
        }}

        Texto (truncado a 15000 chars):
        {text_ocr[:15000]}
    """)

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw[3:-3].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    except Exception as e:
        logger.error(f"[ERROR] Error al invocar al modelo: {e}")
        return {"error": f"Error invocación modelo: {e}"}

    if not raw.lstrip().startswith("{"):
        logger.warning("[ADVERTENCIA] La respuesta no empieza con JSON. Mostrando raw para debug:")
        logger.info(raw)
        m = re.search(r"\{.*\}", raw, re.S)
        raw = m.group(0) if m else '{"error":"json parsing"}'

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("[ERROR] Error al parsear JSON del modelo.")
        logger.info("Respuesta cruda:")
        logger.info(raw)
        return {"error": "No se pudo parsear JSON"}

    campos = [
        "rfc",
        "razon_social",
        "numero_serie_certificado",
        "fecha_solicitud",
        "vigencia_desde",
        "vigencia_hasta",
        "extranjeras",
    ]
    for campo in campos:
        if campo not in data:
            data[campo] = False if campo == "extranjeras" else ""
    if not isinstance(data.get("extranjeras"), bool):
        data["extranjeras"] = False

    # ═══════════════════════════════════════════════════════════════════════════
    # MEJORAS DE ROBUSTEZ
    # ═══════════════════════════════════════════════════════════════════════════
    data = _fiel_regex_fallback(data, text_ocr)
    data = _fix_campos_no_encontrados_generic(data, ["rfc", "razon_social", "numero_serie_certificado", "vigencia_desde", "vigencia_hasta"])
    # Incluir TODOS los campos de FIEL para evidencia
    campos_fiel = [
        "rfc", "razon_social", "numero_serie_certificado", 
        "fecha_solicitud", "vigencia_desde", "vigencia_hasta"
    ]
    data = _add_extraction_evidence_generic(data, text_ocr, campos_fiel)

    return data


def _fiel_regex_fallback(data: dict, text_ocr: str) -> dict:
    """Regex fallback para FIEL."""
    result = data.copy()
    
    # RFC
    if not result.get("rfc") or result.get("rfc") == "":
        match = re.search(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b', text_ocr.upper())
        if match:
            result["rfc"] = match.group(1)
    
    # Número de serie del certificado
    if not result.get("numero_serie_certificado") or result.get("numero_serie_certificado") == "":
        patterns = [
            r'(?:N[ÚU]MERO\s+DE\s+SERIE|SERIE)[:\s]+([0-9A-Fa-f\-]{16,})',
            r'(?:CERTIFICADO)[:\s]+([0-9A-Fa-f\-]{16,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_ocr, re.IGNORECASE)
            if match:
                result["numero_serie_certificado"] = match.group(1).strip()
                break
    
    # Fechas de vigencia
    fecha_pattern = r'(\d{2}/\d{2}/\d{4})'
    if not result.get("vigencia_desde") or not result.get("vigencia_hasta"):
        fechas = re.findall(fecha_pattern, text_ocr)
        if len(fechas) >= 2:
            if not result.get("vigencia_desde"):
                result["vigencia_desde"] = fechas[0]
            if not result.get("vigencia_hasta"):
                result["vigencia_hasta"] = fechas[-1]
    
    return result