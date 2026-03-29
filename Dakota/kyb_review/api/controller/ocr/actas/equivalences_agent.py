# equivalences_agent.py

import re
from datetime import datetime
from equivalencias import (
    ESTADOS_EQUIVALENCIAS,
    NUMEROS_PALABRAS,
    GENERO_EQUIVALENCIAS,
    ABREVIATURAS_LEGALES,
    MESES_EQUIVALENCIAS,
    texto_a_numero
)

def reemplazar_numeros_palabras(texto: str) -> str:
    """Reemplaza números escritos en palabras dentro de un texto."""
    if not texto:
        return texto
    texto = texto.upper()
    for palabra, numero in NUMEROS_PALABRAS.items():
        texto = re.sub(rf'\b{palabra}\b', numero, texto)
    return texto

def normalizar_estado(estado: str) -> str:
    """Aplica equivalencias para estados con búsqueda flexible."""
    if not estado:
        return estado
    estado_upper = estado.strip().upper()
    for clave, valor in ESTADOS_EQUIVALENCIAS.items():
        if clave.upper() == estado_upper:
            return valor
    # Si no coincide exacto, intentar buscar por inclusión (opcional)
    for clave, valor in ESTADOS_EQUIVALENCIAS.items():
        if clave.upper() in estado_upper or estado_upper in clave.upper():
            return valor
    return estado

def normalizar_fecha(fecha_str: str) -> str:
#Normaliza fechas a dd/mm/yyyy, incluso escritas con palabras.
    if not fecha_str:
        return ""

    fecha_str = fecha_str.strip().upper()

    # Normalizar mes abreviado
    for abrev, completo in MESES_EQUIVALENCIAS.items():
        if abrev in fecha_str:
            fecha_str = fecha_str.replace(abrev, completo)

    formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formatos:
        try:
            fecha = datetime.strptime(fecha_str, fmt)
            return fecha.strftime("%d/%m/%Y")
        except:
            pass

    meses = {
        "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
        "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12
    }

    dia = re.search(r"\b(\d{1,2})\b", fecha_str)
    mes = None
    for m in meses.keys():
        if m in fecha_str:
            mes = meses[m]
            break
    anio = re.search(r"\b(19|20)\d{2}\b", fecha_str)

    if dia and mes and anio:
        try:
            fecha = datetime(int(anio.group(0)), mes, int(dia.group(1)))
            return fecha.strftime("%d/%m/%Y")
        except:
            pass

    return fecha_str

def normalizar_texto_simple(texto: str) -> str:
#Normaliza texto simple para comparación (mayúsculas, espacios, caracteres especiales)."""
    if not texto:
        return ""
    texto = texto.upper().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto

def agente_equivalencias(datos: dict) -> dict:
    """
    Recibe diccionario de datos extraídos, aplica equivalencias para unificar valores:
    - Normaliza fechas y las unifica si falta alguna.
    - Normaliza estados, género y tipo de sociedad.
    - Convierte capital social escrito en texto a número.
    - Reemplaza números escritos en palabras en todos los campos string.
    """
    salida = datos.copy()

#Normalizar fechas y unificar expedición = constitución si falta
    f_const = salida.get("fecha_constitucion", "")
    f_exped = salida.get("fecha_expedicion", "")

    f_const_norm = normalizar_fecha(f_const)
    f_exped_norm = normalizar_fecha(f_exped)

    if f_const_norm and (not f_exped_norm or f_const_norm != f_exped_norm):
        f_exped_norm = f_const_norm

    salida["fecha_constitucion"] = f_const_norm
    salida["fecha_expedicion"] = f_exped_norm

#Normalizar estado
    salida["estado_notaria_correduria"] = normalizar_estado(salida.get("estado_notaria_correduria", ""))

#Normalizar género
    if "genero" in salida and salida["genero"]:
        genero_raw = salida["genero"].upper().strip()
        salida["genero"] = GENERO_EQUIVALENCIAS.get(genero_raw, salida["genero"])

#Normalizar tipo de sociedad
    if "tipo_sociedad" in salida and salida["tipo_sociedad"]:
        tipo_raw = salida["tipo_sociedad"].upper().strip()
        salida["tipo_sociedad"] = ABREVIATURAS_LEGALES.get(tipo_raw, salida["tipo_sociedad"])

#Reemplazar números escritos en palabras en todos los campos string
    for k, v in salida.items():
        if isinstance(v, str):
            salida[k] = reemplazar_numeros_palabras(v)

#Convertir capital social a número
    if "capital_social" in salida and salida["capital_social"]:
        capital_raw = salida["capital_social"]
        if isinstance(capital_raw, str) and not capital_raw.isdigit():
            try:
                salida["capital_social"] = texto_a_numero(capital_raw)
            except:
                pass

    return salida
