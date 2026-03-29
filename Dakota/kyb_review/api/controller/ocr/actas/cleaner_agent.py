import os
import time
import re
from dotenv import load_dotenv
from tkinter import Tk, filedialog
from langchain_openai import AzureChatOpenAI
from langchain.schema import HumanMessage

# Carga variables de entorno desde .env (si existe)
load_dotenv()

# Carpeta de salida para archivos limpios
CARPETA_SALIDA = r"C:\Users\oaguirre_ext\Documents\GitHub\KYB\OCR_AGENTS\Actas\DOClimipio"

# Prompt para corrección segura (solo ortografía/OCR, sin cambiar estructura)
PROMPT_LIMPIEZA = """
Eres un asistente experto en corrección de documentos legales en español.
Recibirás texto OCR con separadores de páginas [[[PÁGINA:X]]].
Tu tarea es:

1. Corregir únicamente errores ortográficos y errores comunes de OCR 
   (ej. "P0DER" → "PODER", "nimero" → "número").
2. NO eliminar ni agregar saltos de línea.
3. NO cambiar el orden de palabras ni de líneas.
4. NO eliminar ni agregar texto.
5. Mantener intactos los separadores originales: [[[PÁGINA:X]]].
6. Si el contenido de una página está vacío, coloca `<VACÍA>` justo después de su separador.
7. Devuelve SOLO el texto corregido, sin comentarios ni JSON.
"""

def seleccionar_archivo():
    Tk().withdraw()
    return filedialog.askopenfilename(
        title="Selecciona el archivo OCR (TXT)",
        filetypes=[("Archivos de texto", "*.txt")]
    )

def dividir_por_paginas(texto):
    """
    Divide el texto en páginas usando [[[PÁGINA:X]]].
    Retorna lista de (numero_pagina, contenido_original).
    """
    partes = re.split(r"(\[\[\[PÁGINA:(\d+)\]\]\])", texto)
    paginas = []
    i = 0
    # partes alterna: [antes, separador, numero, después, ...]
    while i < len(partes) - 1:
        sep = partes[i+1]            # '[[[PÁGINA:X]]]'
        numero = partes[i+2]         # 'X'
        contenido = partes[i+3]      # texto hasta siguiente separador
        paginas.append((int(numero), contenido.strip()))
        i += 3
    return paginas

def limpiar_texto_con_llm(llm, texto_ocr: str, carpeta_salida: str, nombre_salida: str):
    start_total = time.time()
    paginas = dividir_por_paginas(texto_ocr)
    total_pag = len(paginas)
    logger.info(f"[INFO] Detectadas {total_pag} páginas en el OCR.")

    os.makedirs(carpeta_salida, exist_ok=True)
    ruta_salida = os.path.join(carpeta_salida, f"{nombre_salida}_limpio.txt")
    # Abrimos en modo escritura inicial (sobreescribe si existe)
    with open(ruta_salida, "w", encoding="utf-8") as f_out:
        for idx, (num, contenido) in enumerate(paginas, start=1):
            logger.info(f"[INFO] Procesando página {idx}/{total_pag} (Página {num})...")
            t0 = time.time()

            # Si está vacía, preparamos indicador
            if not contenido.strip():
                bloque = f"[[[PÁGINA:{num}]]]\n<VACÍA>\n"
            else:
                bloque = f"[[[PÁGINA:{num}]]]\n{contenido}\n"

            # Llamada al LLM
            mensaje = f"{PROMPT_LIMPIEZA}\n\nTexto OCR:\n{bloque}"
            resp = llm.invoke([HumanMessage(content=mensaje)])
            limpio = resp.content

            # Si la respuesta inesperadamente vino vacía, reutilizamos el bloque original
            if not limpio.strip():
                logger.warning(f"[WARN] Página {num} no modificada (respuesta vacía).")
                limpio = bloque

            # Escribimos el resultado corregido
            f_out.write(limpio.strip() + "\n\n")
            logger.info(f"[INFO] Página {num} procesada en {time.time() - t0:.2f}s.")

    logger.info(f"[INFO] Texto limpio guardado en: {ruta_salida}")
    logger.info(f"[INFO] Limpieza completa en {time.time() - start_total:.2f} segundos.")
    return ruta_salida

if __name__ == "__main__":
    llm = AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        temperature=0.2,
        max_tokens=2048
    )

    logger.info("[INFO] Selecciona el archivo TXT con el OCR a limpiar...")
    archivo = seleccionar_archivo()
    if not archivo:
        logger.error("[ERROR] No se seleccionó ningún archivo.")
        exit(1)

    with open(archivo, "r", encoding="utf-8") as f:
        texto = f.read()
    nombre = os.path.splitext(os.path.basename(archivo))[0]

    limpiar_texto_con_llm(llm, texto, CARPETA_SALIDA, nombre)
