import json, re
from textwrap import dedent

def extract_acta_fields(text_ocr: str, llm) -> dict:
    if not text_ocr.strip():
        return {"error": "Texto vacío"}
    
#Dividimos el texto si supera 200k caracteres
    MAX_CHUNK = 200000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)]
    
    #Plantilla JSON
    json_template = """
    {
      "numero_escritura_poliza": "",
      "fecha_constitucion": "",
      "folio_mercantil": "",
      "fecha_expedicion": "",
      "numero_notaria_correduria": "",
      "estado_notaria_correduria": "",
      "primer_nombre_fedatario": "",
      "segundo_nombre_fedatario": "",
      "primer_apellido_fedatario": "",
      "segundo_apellido_fedatario": "",
      "denominacion_social": ""
    }
    """
    
    #Diccionario para acumular resultados
    extracted_data = {k: "" for k in json.loads(json_template)}
    
    for idx, chunk in enumerate(chunks, start=1):
        prompt = dedent(f"""
            Eres un asistente experto en documentos legales mexicanos.
            Tu tarea: EXTRAER valores exactos del texto y normalizarlos según estas reglas.

            REGLAS GENERALES:
            - Si el valor NO aparece explícitamente, deja el campo vacío (solo para segundo_nombre_fedatario).
            - No inventes valores.
            - Convierte cualquier fecha a formato dd/mm/aaaa.
            - Convierte números escritos en palabras a su valor numérico.
            - Si dice "DISTRITO FEDERAL", interpreta como "Ciudad de México".
            - Si no hay segundo nombre, usa "N/A".
            - Responde SOLO con un JSON válido, sin texto adicional.

            REGLAS ESPECÍFICAS:

            1. numero_escritura_poliza:
            * Se encuentra casi al inicio del documento, ANTES de cualquier mención a la ciudad, fecha, nombre del Notario o la frase "hago constar".
            * El patrón típico es:
                - "VOLUMEN <número> ESCRITURA NÚMERO <número>"
                - "ESCRITURA NÚMERO <número>"
            * El número que buscamos es el de ESCRITURA (NO el de volumen).
            * Si aparece más de una vez, toma la PRIMERA coincidencia ANTES de "hago constar" o "contrato".
            * Ignora cualquier número que aparezca después de mencionar al Notario, la ubicación o el contrato.

            2. folio_mercantil:
            * El folio esta en números arábigos (ej. 123456), nunca escritos con letras.
            * Limítate a la sección encabezada por "REGISTRO PÚBLICO DE LA PROPIEDAD Y DE COMERCIO" o "BOLETA DE INSCRIPCIÓN".
            * Siempre esta después de:
                - "FOLIO MERCANTIL ELECTRÓNICO NÚMERO:"
            * No es el primer folio que encuentres, ya que puedes confundirte con el de notario.
            * Ignora cualquier "folio" que aparezca junto a la palabra "Notario" u otras secciones distintas.
            * Este dato casi siempre está en las últimas páginas, así que no tomes valores del inicio del documento.

            3. fecha_constitucion y fecha_expedicion:
            * Son la misma fecha: extrae una única vez si coincide.
            * Convierte fechas escritas en palabras a formato dd/mm/aaaa.

            4. denominacion_social:
            * Busca en las primeras páginas del documento, específicamente en:
                - Cláusula PRIMERA de los Estatutos
                - Después de frases como "La Sociedad se denomina", "denominada", "bajo la denominación"
            * Extrae SOLO el nombre de la sociedad, SIN incluir:
                - "Sociedad Anónima", "S.A.", "de C.V.", "SOCIEDAD FINANCIERA", etc.
                - Cualquier tipo societario o abreviatura
            * Ejemplo: Si dice "La Sociedad se denomina ALMIRANTE CAPITAL, Sociedad Anónima de Capital Variable"
              → Extraer solo: "ALMIRANTE CAPITAL"
            * Mantén el formato original (mayúsculas/minúsculas como aparece).
            * Si no encuentras la denominación explícita, déjalo vacío.

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

    # ============================================================================
    # Post-procesamiento: Construir campos compuestos para compatibilidad con validador
    # ============================================================================
    
    # 1. Construir nombre_notario completo a partir de los campos individuales
    partes_nombre = [
        extracted_data.get("primer_nombre_fedatario", "").strip(),
        extracted_data.get("segundo_nombre_fedatario", "").strip(),
        extracted_data.get("primer_apellido_fedatario", "").strip(),
        extracted_data.get("segundo_apellido_fedatario", "").strip()
    ]
    # Filtrar "N/A" y concatenar
    nombre_completo = " ".join([p for p in partes_nombre if p and p.upper() != "N/A"])
    if nombre_completo:
        extracted_data["nombre_notario"] = nombre_completo
    else:
        extracted_data["nombre_notario"] = ""
    
    # 2. Mapear campos con sufijo _correduria para compatibilidad
    if extracted_data.get("numero_notaria_correduria"):
        extracted_data["numero_notaria"] = extracted_data["numero_notaria_correduria"]
    else:
        extracted_data["numero_notaria"] = ""
    
    if extracted_data.get("estado_notaria_correduria"):
        extracted_data["estado_notaria"] = extracted_data["estado_notaria_correduria"]
    else:
        extracted_data["estado_notaria"] = ""
    
    return extracted_data
