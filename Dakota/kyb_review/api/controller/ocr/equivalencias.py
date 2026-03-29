import re
import unicodedata
import datetime
 
# -------------------------------------------
# EQUIVALENCIAS PARA PODERES NOTARIALES Y FUTUROS AGENTES
# -------------------------------------------
 
ABREVIATURAS_LEGALES = {
    "S.A.": "SOCIEDAD ANÓNIMA",
    "S.A. DE C.V.": "SOCIEDAD ANÓNIMA DE CAPITAL VARIABLE",
    "S. DE R.L.": "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "S. DE R.L. DE C.V.": "SOCIEDAD DE RESPONSABILIDAD LIMITADA DE CAPITAL VARIABLE",
    "S.A.P.I. DE C.V.": "SOCIEDAD ANÓNIMA PROMOTORA DE INVERSIÓN DE CAPITAL VARIABLE",
    "A.C.": "ASOCIACIÓN CIVIL",
    "S.C.": "SOCIEDAD CIVIL"
}

def normalizar(texto: str) -> str:
    """
    Normaliza un texto realizando:
    - Eliminación de caracteres extraños fuera del rango ASCII y acentos comunes.
    - Consolidación de espacios múltiples en uno solo.
    - Conversión a mayúsculas y luego a formato título.
    """
    if not texto:
        return ""

    # Eliminar caracteres fuera de rango imprimible y acentos básicos
    t = re.sub(r"[^\x20-\x7EÁÉÍÓÚÜÑáéíóúüñ]", " ", texto)
    # Convertir a mayúsculas y colapsar espacios
    t = re.sub(r"\s+", " ", t.strip().upper())
    # Formatear cada palabra con mayúscula inicial
    return t.title()

# -------------------------------
# ESTADOS Y ENTIDADES FEDERATIVAS
# -------------------------------
ESTADOS_EQUIVALENCIAS = {
    "DISTRITO FEDERAL": "Ciudad de México",
    "CDMX": "Ciudad de México",
    "C.D.M.X.": "Ciudad de México",
    "D.F.": "Ciudad de México",
    "DF": "Ciudad de México",
    "AGUASCALIENTES": "Aguascalientes",
    "BAJA CALIFORNIA": "Baja California",
    "BAJA CALIFORNIA SUR": "Baja California Sur",
    "CAMPECHE": "Campeche",
    "COAHUILA": "Coahuila",
    "COLIMA": "Colima",
    "CHIAPAS": "Chiapas",
    "CHIHUAHUA": "Chihuahua",
    "CIUDAD DE MÉXICO": "Ciudad de México",
    "DURANGO": "Durango",
    "GUANAJUATO": "Guanajuato",
    "GUERRERO": "Guerrero",
    "HIDALGO": "Hidalgo",
    "JALISCO": "Jalisco",
    "MÉXICO": "Estado de México",
    "ESTADO DE MÉXICO": "Estado de México",
    "MICHOACÁN": "Michoacán",
    "MORELOS": "Morelos",
    "NAYARIT": "Nayarit",
    "NUEVO LEÓN": "Nuevo León",
    "OAXACA": "Oaxaca",
    "PUEBLA": "Puebla",
    "QUERÉTARO": "Querétaro",
    "QUINTANA ROO": "Quintana Roo",
    "SAN LUIS POTOSÍ": "San Luis Potosí",
    "SINALOA": "Sinaloa",
    "SONORA": "Sonora",
    "TABASCO": "Tabasco",
    "TAMAULIPAS": "Tamaulipas",
    "TLAXCALA": "Tlaxcala",
    "VERACRUZ": "Veracruz",
    "YUCATÁN": "Yucatán",
    "ZACATECAS": "Zacatecas"
}
 
def normalizar_estado(texto: str) -> str:
    t = texto.strip().upper()
    for k, v in ESTADOS_EQUIVALENCIAS.items():
        if k.upper() == t or k.upper() in t or t in k.upper():
            return v
    return texto
 
# -------------------------------
# MESES
# -------------------------------
MESES_EQUIVALENCIAS = {
    "ENE": "ENERO", "FEB": "FEBRERO", "MAR": "MARZO",
    "ABR": "ABRIL", "MAY": "MAYO", "JUN": "JUNIO",
    "JUL": "JULIO", "AGO": "AGOSTO", "SEP": "SEPTIEMBRE",
    "OCT": "OCTUBRE", "NOV": "NOVIEMBRE", "DIC": "DICIEMBRE"
}
 
def normalizar_mes(texto: str) -> str:
    t = texto.strip().upper()
    return MESES_EQUIVALENCIAS.get(t, texto)
 
# -------------------------------
# GÉNERO
# -------------------------------
GENERO_EQUIVALENCIAS = {
    "H": "HOMBRE", "M": "MUJER", "F": "FEMENINO",
    "MASC": "MASCULINO", "FEM": "FEMENINO"
}
 
def normalizar_genero(texto: str) -> str:
    t = texto.strip().upper()
    return GENERO_EQUIVALENCIAS.get(t, texto)
 
# -------------------------------
# ROLES EN PODER NOTARIAL
# -------------------------------
ROLES_LEGALES = {
    "OTORGANTE": "PODERDANTE",
    "PODERDANTE": "PODERDANTE",
    "APODERADO": "APODERADO",
    "MANDATARIO": "APODERADO",
    "MANDANTE": "PODERDANTE",
    "REPRESENTANTE": "APODERADO",
    "TESTIGO": "TESTIGO",
}
 
def normalizar_rol(texto: str) -> str:
    t = texto.strip().upper()
    return ROLES_LEGALES.get(t, texto)
 
# -------------------------------
# TIPOS DE PODER
# -------------------------------
TIPOS_PODER = {
    "PODER GENERAL PARA PLEITOS Y COBRANZAS": "PLEITOS_Y_COBRANZAS",
    "PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN": "ADMINISTRACION",
    "PODER GENERAL PARA ACTOS DE DOMINIO": "DOMINIO",
    "PODER ESPECIAL": "ESPECIAL",
    "PODER AMPLIO Y CUMPLIDO": "AMPLIO"
}
 
def normalizar_tipo_poder(texto: str) -> str:
    t = texto.strip().upper()
    return TIPOS_PODER.get(t, texto)
 
# -------------------------------
# ATRIBUCIONES COMUNES
# -------------------------------
ATRIBUCIONES = [
    "PLEITOS", "COBRANZAS", "ACTOS DE ADMINISTRACIÓN", "ACTOS DE DOMINIO",
    "SUSCRIPCIÓN DE TÍTULOS", "ABRIR CUENTAS", "ENDOSAR", "DELEGAR", "SUSTITUIR"
]
 
def encontrar_atribuciones(texto: str) -> list:
    t = texto.strip().upper()
    return [a for a in ATRIBUCIONES if a in t]
 
# -------------------------------
# DOCUMENTOS DE IDENTIDAD
# -------------------------------
IDENTIFICACIONES = {
    "INE": "CREDENCIAL PARA VOTAR",
    "IFE": "CREDENCIAL PARA VOTAR",
    "PASAPORTE": "PASAPORTE",
    "CÉDULA PROFESIONAL": "CÉDULA PROFESIONAL",
    "LICENCIA DE CONDUCIR": "LICENCIA DE CONDUCIR"
}
 
def normalizar_identificacion(texto: str) -> str:
    t = texto.strip().upper()
    for k, v in IDENTIFICACIONES.items():
        if k in t:
            return v
    return texto
 
# -------------------------------
# CORRECCIÓN DE ERRORES COMUNES DE OCR
# -------------------------------
CORRECCION_OCR = {
    "P0DER": "PODER",
    "AP0DERAD0": "APODERADO",
    "OT0RGANTE": "OTORGANTE",
    "ACT0S": "ACTOS"
}
 
def corregir_ocr(texto: str) -> str:
    t = texto.upper()
    for err, corr in CORRECCION_OCR.items():
        t = re.sub(rf"\b{err}\b", corr, t)
    return t
 
# -------------------------------
# NÚMEROS EN PALABRAS (hasta 4,000)
# -------------------------------
NUMEROS_PALABRAS = {
    "CERO": 0, "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5,
    # ... hasta CUATRO MIL ...
    "MIL": 1000, "DOS MIL": 2000, "TRES MIL": 3000, "CUATRO MIL": 4000
}
 
def texto_a_numero(texto: str) -> int:
    texto = texto.upper().replace(" Y ", " ")
    total = actual = 0
    for palabra in texto.split():
        if palabra in NUMEROS_PALABRAS:
            val = NUMEROS_PALABRAS[palabra]
            if val == 1000:
                actual = actual or 1
                total += actual * 1000
                actual = 0
            elif val == 100:
                actual = actual or 1
                actual *= 100
            else:
                actual += val
    return total + actual
 
# -------------------------------
# TOKENS NULOS
# -------------------------------
NULL_TOKENS = {"", "N/A", "NA", "SIN NÚMERO", "S/N", "SN"}
 
# -------------------------------
# EQUIVALENCIAS DE PAÍSES
# -------------------------------
PAISES_EQUIVALENCIAS = {
    "MEXICO": "MÉXICO",
    "MÉXICO": "MÉXICO",
    "ESTADOS UNIDOS MEXICANOS": "MÉXICO",
    "MX": "MÉXICO",
    "USA": "ESTADOS UNIDOS",
    "UNITED STATES": "ESTADOS UNIDOS",
    "U.S.A.": "ESTADOS UNIDOS",
    "CANADA": "CANADÁ",
    "CANADÁ": "CANADÁ",
    "ESPANA": "ESPAÑA",
    "ESPAÑA": "ESPAÑA",
    "ARGENTINA": "ARGENTINA",
    "COLOMBIA": "COLOMBIA",
    "CHILE": "CHILE",
    "PERU": "PERÚ",
    "PERÚ": "PERÚ",
    "BRASIL": "BRASIL",
    "BRAZIL": "BRASIL",
    "ALEMANIA": "ALEMANIA",
    "GERMANY": "ALEMANIA",
    "FRANCIA": "FRANCIA",
    "FRANCE": "FRANCIA",
    "ITALIA": "ITALIA",
    "ITALY": "ITALIA"
}
 
def limpiar_texto(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()
 
def equivalencia_pais(texto: str) -> str:
    if not texto or not texto.strip():
        return texto
    limpio = limpiar_texto(texto)
    if limpio in PAISES_EQUIVALENCIAS:
        return PAISES_EQUIVALENCIAS[limpio]
    for key, val in PAISES_EQUIVALENCIAS.items():
        if key in limpio:
            return val
    return texto.strip()

def normalizar_texto_simple(texto: str) -> str:
    """
    Normaliza texto para comparación:
    - Elimina acentos.
    - Convierte a mayúsculas.
    - Quita espacios extras.
    """
    if not texto:
        return ""
    # Quitar acentos
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Mayúsculas y strip de espacios repetidos
    return " ".join(sin_acentos.upper().strip().split())

def reemplazar_numeros_palabras(texto: str) -> str:
    """Reemplaza números escritos en palabras dentro de un texto."""
    if not texto:
        return texto
    texto = texto.upper()
    for palabra, numero in NUMEROS_PALABRAS.items():
        texto = re.sub(rf'\b{palabra}\b', str(numero), texto)
    return texto

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
            fecha = datetime.datetime.strptime(fecha_str, fmt)
            return fecha.strftime("%d/%m/%Y")
        except ValueError:
            continue

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
        except (ValueError, TypeError):
            pass

    return fecha_str

def agente_equivalencias_poder(datos: dict) -> dict:
    """
    Recibe un dict con campos extraídos de un Poder Notarial y aplica:
      - Strip de espacios.
      - Normalizar 'nacionalidad' y 'pais_nacimiento' vía equivalencia_pais.
      - Sanitizar 'telefono' (solo dígitos y '+').
      - Convertir 'correo_electronico' a minúsculas.
      - Para otros campos, limpiar texto simple.
    """
    salida = {}
    for campo, valor in datos.items():
        if not isinstance(valor, str):
            salida[campo] = valor
            continue

        v = valor.strip()

        if campo in ("nacionalidad", "pais_nacimiento"):
            v = equivalencia_pais(v)

        elif campo == "telefono":
            v = re.sub(r"[^\d+]", "", v)

        elif campo == "correo_electronico":
            v = v.lower().strip()

        else:
            # Para cualquier otro campo: normalizar texto simple
            v = normalizar_texto_simple(v)

        salida[campo] = v

    return salida

def agente_equivalencias(datos: dict) -> dict:
    """
    Recibe diccionario de datos extraídos, aplica equivalencias para unificar valores:
    - Normaliza fechas y las unifica si falta alguna.
    - Normaliza estados, género y tipo de sociedad.
    - Convierte capital social escrito en texto a número.
    - Reemplaza números escritos en palabras en todos los campos string.
    """
    salida = datos.copy()

    # Normalizar fechas y unificar expedición = constitución si falta
    f_const = salida.get("fecha_constitucion", "")
    f_exped = salida.get("fecha_expedicion", "")

    # Only normalize if the field exists (don't create empty fields)
    if f_const:
        f_const_norm = normalizar_fecha(f_const)
    else:
        f_const_norm = ""
        
    if f_exped:
        f_exped_norm = normalizar_fecha(f_exped)
    else:
        f_exped_norm = ""

    # Unify dates: if only one is present, use it for both
    if f_const_norm and not f_exped_norm:
        f_exped_norm = f_const_norm
    elif f_exped_norm and not f_const_norm:
        f_const_norm = f_exped_norm

    # Only update if we had values to normalize
    if "fecha_constitucion" in salida:
        salida["fecha_constitucion"] = f_const_norm
    if "fecha_expedicion" in salida:
        salida["fecha_expedicion"] = f_exped_norm

    # Normalizar estado - support both old and new field names
    if "estado_notaria_correduria" in salida:
        salida["estado_notaria_correduria"] = normalizar_estado(salida.get("estado_notaria_correduria", ""))
    if "estado_notaria" in salida:
        salida["estado_notaria"] = normalizar_estado(salida.get("estado_notaria", ""))

    # Normalizar género
    if "genero" in salida and salida["genero"]:
        genero_raw = salida["genero"].upper().strip()
        salida["genero"] = GENERO_EQUIVALENCIAS.get(genero_raw, salida["genero"])

    # Normalizar tipo de sociedad
    if "tipo_sociedad" in salida and salida["tipo_sociedad"]:
        tipo_raw = salida["tipo_sociedad"].upper().strip()
        salida["tipo_sociedad"] = ABREVIATURAS_LEGALES.get(tipo_raw, salida["tipo_sociedad"])

    # Convertir capital social a número
    if "capital_social" in salida and salida["capital_social"]:
        capital_raw = salida["capital_social"]
        if isinstance(capital_raw, str) and not capital_raw.isdigit():
            try:
                salida["capital_social"] = texto_a_numero(capital_raw)
            except (ValueError, TypeError):
                pass

    return salida