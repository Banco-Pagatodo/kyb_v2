# normalizer.py

import re

# normalizer.py (versión simplificada)
# Esta función solo realiza limpieza básica de texto:
# - Elimina caracteres no ASCII básicos
# - Colapsa espacios y convierte a mayúsculas
# - Aplica formato título

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
