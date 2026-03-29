# llm_extractor.py

import json
import re
from textwrap import dedent


def extract_poder_fields(text_ocr: str, llm) -> dict:
    """
    Extrae los campos de un Poder Notarial:
      - ocupacion
      - nacionalidad
      - pais_nacimiento
      - telefono
      - correo_electronico

    Si algún valor no aparece explícitamente, deja el campo vacío.
    """
    if not text_ocr.strip():
        return {"error": "Texto vacío"}

    # Dividir en chunks de hasta MAX_CHUNK caracteres
    MAX_CHUNK = 200_000
    chunks = [text_ocr[i:i+MAX_CHUNK] for i in range(0, len(text_ocr), MAX_CHUNK)]

    # Plantilla JSON con los campos que queremos
    json_template = """
    {
      "ocupacion": "",
      "nacionalidad": "",
      "pais_nacimiento": "",
      "telefono": "",
      "correo_electronico": ""
    }
    """
    extracted_data = {k: "" for k in json.loads(json_template)}

    for idx, chunk in enumerate(chunks, start=1): 
        prompt = dedent(f"""
        Eres un asistente experto en documentos notariales mexicanos para empresas. 
        Tu tarea es EXTRAER valores exactos del texto del Poder Notarial y devolverlos en JSON estrictamente según esta plantilla:

        Plantilla JSON esperada:
        {json_template}

        REGLAS IMPORTANTES:
        - No inventes datos, pero los campos 'ocupacion', 'nacionalidad' y 'pais_nacimiento' NUNCA deben quedar vacíos.
        Si no encuentras información explícita, asigna el valor exacto: "NO ESPECIFICADO".
        - No agregues texto adicional fuera del JSON.
        - Normaliza espacios múltiples a uno solo.
        - Las fechas deben estar en formato "DD/MM/AAAA" cuando sea posible; si no, deja el texto original.
        - Para campos que son listas (como facultades o atribuciones), devuelve un arreglo JSON con cadenas.
        - Para 'telefono', solo conserva dígitos y un posible '+' inicial.
        - Para 'correo_electronico', asegúrate que tenga formato válido o usa "NO ESPECIFICADO".
        - Para 'nacionalidad' y 'pais_nacimiento', utiliza el nombre completo y correcto del país. Si no está claro, usa "NO ESPECIFICADO".
        - No agregues campos que no estén en la plantilla ni cambies el orden.

        TEXTO DEL PODER (fragmento {idx}/{len(chunks)}):
        "{chunk}"
        """)



        # Invocación al LLM
        resp = llm.invoke(prompt).content.strip()
        # Quitar posibles backticks
        resp = re.sub(r"^```(?:json)?|```$", "", resp).strip()
        match = re.search(r"\{.*\}", resp, re.S)
        try:
            partial = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            partial = {}

        # Fusionar resultados: solo rellenar campos vacíos
        for key in extracted_data:
            if not extracted_data[key] and partial.get(key):
                extracted_data[key] = partial[key]

    return extracted_data
