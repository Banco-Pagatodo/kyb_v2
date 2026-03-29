import dotenv
import os
import json
from utils.file_selector import seleccionar_archivo
from utils.tesseract_check import verificar_tesseract
from ocr_processor import super_ocr
from user_input import pedir_datos_usuario
from llm_extractor import extract_poder_fields  # Adaptado para poderes notariales
from ..equivalencias import agente_equivalencias_poder, normalizar_texto_simple
from normalizer import normalizar
from reconciler import reportar
from langchain_openai import AzureChatOpenAI

# -------------------------------------------
# 1. Cargar variables de entorno
# -------------------------------------------
dotenv.load_dotenv()

# -------------------------------------------
# 2. Definir carpeta donde se guardarán los JSON
# -------------------------------------------
JSON_DIR = r"C:\Users\oaguirre_ext\Documents\GitHub\KYB\OCR_AGENTS\PoderNota\JSON"
os.makedirs(JSON_DIR, exist_ok=True)  # Crea la carpeta si no existe

# -------------------------------------------
# 3. Verificar instalación de Tesseract
# -------------------------------------------
if not verificar_tesseract():
    logger.error("[ERROR] Tesseract no está instalado o no se encuentra en el PATH.")
    exit(1)

# -------------------------------------------
# 4. Seleccionar archivo PDF o imagen
# -------------------------------------------
archivo = seleccionar_archivo()
if not archivo:
    logger.error("[ERROR] No se seleccionó ningún archivo.")
    exit(1)

# -------------------------------------------
# 5. Ejecutar OCR completo
# -------------------------------------------
txt_raw = super_ocr(archivo)
logger.info(f"[INFO] OCR completado. Longitud: {len(txt_raw)} caracteres")

# Guardar texto bruto en .txt
output_txt_path = os.path.join(JSON_DIR, "output.txt")
with open(output_txt_path, "w", encoding="utf-8") as f:
    f.write(txt_raw)
logger.info(f"[INFO] Texto OCR guardado en {output_txt_path}")

# -------------------------------------------
# 6. Inicializar modelo LLM (Azure OpenAI)
# -------------------------------------------
llm = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

# -------------------------------------------
# 7. Pedir datos al usuario (opcional)
# -------------------------------------------
datos_usuario = pedir_datos_usuario()

# -------------------------------------------
# 8. Extraer datos con LLM (poder notarial)
# -------------------------------------------
extraidos_raw = extract_poder_fields(txt_raw, llm)
logger.debug("\n=== JSON extraído por LLM (sin normalizar ni equivalencias) ===")
logger.info(json.dumps(extraidos_raw, ensure_ascii=False, indent=2))

# -------------------------------------------
# 9. Aplicar agente de equivalencias y normalización
# -------------------------------------------
extraidos_eq = agente_equivalencias_poder(extraidos_raw)
extraidos_norm = {
    k: (normalizar_texto_simple(v) if isinstance(v, str) else v)
    for k, v in extraidos_eq.items()
}

# Guardar JSON con datos extraídos normalizados
extraidos_json_path = os.path.join(JSON_DIR, "extraidos.json")
with open(extraidos_json_path, "w", encoding="utf-8") as jf:
    json.dump(extraidos_norm, jf, ensure_ascii=False, indent=2)
logger.info(f"[INFO] Archivo extraidos.json generado en {extraidos_json_path}")

# -------------------------------------------
# 10. Normalizar datos del usuario
# -------------------------------------------
datos_usuario_norm = {
    k: (normalizar_texto_simple(v) if isinstance(v, str) else v)
    for k, v in datos_usuario.items()
}

# -------------------------------------------
# 11. Conciliación
# -------------------------------------------
logger.debug("\n=== Conciliación con datos del usuario (normalizados) ===")
reportar(datos_usuario_norm, extraidos_norm)

# -------------------------------------------
# 12. Consolidar JSON final
# -------------------------------------------
resultado = {
    "archivo_procesado": os.path.basename(archivo),
    "texto_extraido": output_txt_path,
    "datos_extraidos": extraidos_norm,
    "datos_usuario": datos_usuario_norm
}

output_json_path = os.path.join(JSON_DIR, "output.json")
with open(output_json_path, "w", encoding="utf-8") as jf:
    json.dump(resultado, jf, ensure_ascii=False, indent=2)
logger.info(f"[INFO] Archivo output.json generado en {output_json_path}")
