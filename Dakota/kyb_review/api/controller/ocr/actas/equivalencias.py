# Equivalencias de nombres de estados o entidades federativas
ESTADOS_EQUIVALENCIAS = {
    "DISTRITO FEDERAL": "Ciudad de México",
    "Distrito Federal": "Ciudad de México",
    "CDMX": "Ciudad de México",
    "D.F.": "Ciudad de México",
    "d.f.": "Ciudad de México",
    "AGUASCALIENTES": "Aguascalientes",
    "AGS": "Aguascalientes",
    "BAJA CALIFORNIA": "Baja California",
    "BC": "Baja California",
    "BAJA CALIFORNIA SUR": "Baja California Sur",
    "BCS": "Baja California Sur",
    "CAMPECHE": "Campeche",
    "CAMP": "Campeche",
    "COAHUILA": "Coahuila",
    "COAHUILA DE ZARAGOZA": "Coahuila",
    "COAH": "Coahuila",
    "COLIMA": "Colima",
    "COL": "Colima",
    "CHIAPAS": "Chiapas",
    "CHIS": "Chiapas",
    "CHIHUAHUA": "Chihuahua",
    "CHIH": "Chihuahua",
    "CIUDAD DE MÉXICO": "Ciudad de México",
    "cdmx": "Ciudad de México",
    "df": "Ciudad de México",
    "DF": "Ciudad de México",
    "DURANGO": "Durango",
    "DGO": "Durango",
    "GUANAJUATO": "Guanajuato",
    "GTO": "Guanajuato",
    "GUERRERO": "Guerrero",
    "GRO": "Guerrero",
    "HIDALGO": "Hidalgo",
    "HGO": "Hidalgo",
    "JALISCO": "Jalisco",
    "JAL": "Jalisco",
    "MÉXICO": "Estado de México",
    "ESTADO DE MÉXICO": "Estado de México",
    "EDOMEX": "Estado de México",
    "MEX": "Estado de México",
    "MICHOACÁN": "Michoacán",
    "MICHOACÁN DE OCAMPO": "Michoacán",
    "MICH": "Michoacán",
    "MORELOS": "Morelos",
    "MOR": "Morelos",
    "NAYARIT": "Nayarit",
    "NAY": "Nayarit",
    "NUEVO LEÓN": "Nuevo León",
    "NL": "Nuevo León",
    "OAXACA": "Oaxaca",
    "OAX": "Oaxaca",
    "PUEBLA": "Puebla",
    "PUE": "Puebla",
    "QUERÉTARO": "Querétaro",
    "QRO": "Querétaro",
    "QUINTANA ROO": "Quintana Roo",
    "QROO": "Quintana Roo",
    "SAN LUIS POTOSÍ": "San Luis Potosí",
    "SLP": "San Luis Potosí",
    "SINALOA": "Sinaloa",
    "SIN": "Sinaloa",
    "SONORA": "Sonora",
    "SON": "Sonora",
    "TABASCO": "Tabasco",
    "TAB": "Tabasco",
    "TAMAULIPAS": "Tamaulipas",
    "TAMPS": "Tamaulipas",
    "TLAXCALA": "Tlaxcala",
    "TLAX": "Tlaxcala",
    "VERACRUZ": "Veracruz",
    "VER": "Veracruz",
    "VERACRUZ DE IGNACIO DE LA LLAVE": "Veracruz",
    "YUCATÁN": "Yucatán",
    "YUC": "Yucatán",
    "ZACATECAS": "Zacatecas",
    "ZAC": "Zacatecas"
}

# Equivalencias para números escritos en palabras (puedes extender esta lista)
NUMEROS_PALABRAS = {
    # CERO a VEINTE
    "CERO": 0, "UNO": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5,
    "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9, "DIEZ": 10, "ONCE": 11,
    "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15, "DIECISÉIS": 16,
    "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20,
    # Decenas
    "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60, "SETENTA": 70,
    "OCHENTA": 80, "NOVENTA": 90,
    # Centenas
    "CIEN": 100, "CIENTO": 100, "DOSCIENTOS": 200, "TRESCIENTOS": 300, "CUATROCIENTOS": 400,
    "QUINIENTOS": 500, "SEISCIENTOS": 600, "SETECIENTOS": 700, "OCHOCIENTOS": 800,
    "NOVECIENTOS": 900,
    # Mil y hasta cuatro mil
    "MIL": 1000, "DOS MIL": 2000, "TRES MIL": 3000, "CUATRO MIL": 4000
}

def texto_a_numero(texto):
    """
    Convierte un número escrito en palabras (español) a entero.
    Ejemplo: 'MIL DOSCIENTOS TREINTA Y CUATRO' -> 1234
    """
    texto = texto.upper().replace(" Y ", " ")
    palabras = texto.split()
    total = 0
    actual = 0

    for palabra in palabras:
        if palabra in NUMEROS_PALABRAS:
            valor = NUMEROS_PALABRAS[palabra]
            if valor == 1000:
                if actual == 0:
                    actual = 1
                total += actual * 1000
                actual = 0
            elif valor == 100:
                if actual == 0:
                    actual = 1
                actual *= 100
            else:
                actual += valor
    total += actual
    return total

# -------------------------------
# MESES
# -------------------------------
MESES_EQUIVALENCIAS = {
    "ENE": "ENERO", "FEB": "FEBRERO", "MAR": "MARZO", "ABR": "ABRIL", "MAY": "MAYO",
    "JUN": "JUNIO", "JUL": "JULIO", "AGO": "AGOSTO", "SEP": "SEPTIEMBRE", "OCT": "OCTUBRE",
    "NOV": "NOVIEMBRE", "DIC": "DICIEMBRE"
}

# -------------------------------
# GÉNERO
# -------------------------------
GENERO_EQUIVALENCIAS = {
    "H": "HOMBRE", "M": "MUJER", "F": "FEMENINO", "MASC": "MASCULINO", "FEM": "FEMENINO"
}

# -------------------------------
# ABREVIATURAS LEGALES
# -------------------------------
ABREVIATURAS_LEGALES = {
    "S.A.": "SOCIEDAD ANÓNIMA",
    "S.A. DE C.V.": "SOCIEDAD ANÓNIMA DE CAPITAL VARIABLE",
    "S. DE R.L.": "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "S. DE R.L. DE C.V.": "SOCIEDAD DE RESPONSABILIDAD LIMITADA DE CAPITAL VARIABLE",
    "S.A.P.I. DE C.V.": "SOCIEDAD ANÓNIMA PROMOTORA DE INVERSIÓN DE CAPITAL VARIABLE",
    "A.C.": "ASOCIACIÓN CIVIL",
    "S.C.": "SOCIEDAD CIVIL"
}