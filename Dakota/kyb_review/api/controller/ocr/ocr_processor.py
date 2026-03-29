import logging

from pdf2image import convert_from_path
from PIL import Image
import pytesseract
import re
import time
from tqdm import tqdm
from pydantic import FilePath

logger = logging.getLogger(__name__)

def super_ocr(file_path: FilePath, lang:str="spa+eng", save_every:int=20) -> str:
    """
    Extrae TODO el texto de un PDF o imagen usando OCR.
    - Agrega separadores claros entre páginas.
    - Procesa todas las páginas con barra de progreso y ETA.
    - Guarda avances cada 'save_every' páginas para evitar pérdida.
    - Muestra tiempo total al finalizar.
    
    :param file_path: Ruta del archivo PDF o imagen.
    :param lang: Idiomas para OCR (por defecto: español + inglés).
    :param save_every: Intervalo para guardar avances (por defecto: 20 páginas).
    :return: Texto limpio extraído.
    """
    start_time = time.time()
    text = ""
    ext = file_path.lower().split('.')[-1]

    if ext == "pdf":
        # Convertir PDF a imágenes
        pages = convert_from_path(file_path, dpi=300)
        total_pages = len(pages)
        logger.info(f"[INFO] Total de páginas a procesar: {total_pages}")

        # Procesamiento con barra de progreso
        for i, page in enumerate(tqdm(pages, desc="Procesando OCR", unit="pág"), start=1):
            try:
                page_text = pytesseract.image_to_string(page, lang=lang)

                # Limpieza básica por página
                page_text = re.sub(r"[^\x20-\x7E\nÁÉÍÓÚáéíóúÑñ]", " ", page_text)
                page_text = re.sub(r"\n+", "\n", page_text)
                page_text = re.sub(r" {2,}", " ", page_text)

                # Agregar separador
                text += f"\n\n[[[PÁGINA:{i}]]]\n\n{page_text}\n"

            finally:
                page.close()

            # Guardar avance cada 'save_every' páginas
            if i % save_every == 0:
                parcial_path = file_path.rsplit('.', 1)[0] + f"_parcial_{i}.txt"
                with open(parcial_path, "w", encoding="utf-8") as f:
                    f.write(text)
                logger.info(f"[INFO] Avance guardado en {parcial_path}")

        elapsed = time.time() - start_time
        logger.info(f"[INFO] OCR completado en {elapsed:.2f} segundos (~{elapsed/60:.2f} min)")

    elif ext in ["png", "jpg", "jpeg"]:
        logger.info("[INFO] Procesando imagen...")
        try:
            with Image.open(file_path) as img:
                page_text = pytesseract.image_to_string(img, lang=lang)

                # Limpieza básica
                page_text = re.sub(r"[^\x20-\x7E\nÁÉÍÓÚáéíóúÑñ]", " ", page_text)
                page_text = re.sub(r"\n+", "\n", page_text)
                page_text = re.sub(r" {2,}", " ", page_text)

                text = f"\n\n===== PÁGINA ÚNICA =====\n\n{page_text.strip()}\n"
        except Exception as e:
            logger.error(f"[ERROR] Error al procesar imagen: {e}")
            return ""
    else:
        logger.error(f"[ERROR] Formato no soportado: {ext}")
        return ""

    # Guardar archivo final
    output_path = file_path.rsplit('.', 1)[0] + "_ocr.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text.strip())
    logger.info(f"[INFO] Texto completo guardado en: {output_path}")
    logger.info(f"[INFO] Total de caracteres: {len(text)}")

    return text.strip()
