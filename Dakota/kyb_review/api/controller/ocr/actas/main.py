import dotenv
import os
import json
from utils.file_selector import seleccionar_archivo
from utils.tesseract_check import verificar_tesseract
from ocr_processor import super_ocr
from user_input import pedir_datos_usuario
from llm_extractor import extract_acta_fields
from normalizer import normalizar
from reconciler import reportar
from langchain_openai import AzureChatOpenAI
from equivalences_agent import agente_equivalencias, normalizar_texto_simple  # Importar función

# -------------------------------------------
# 1. Cargar variables de entorno
# -------------------------------------------
dotenv.load_dotenv()

# -------------------------------------------
# 2. Definir carpeta donde se guardarán los JSON
# -------------------------------------------
JSON_DIR = r"C:\Users\oaguirre_ext\Documents\GitHub\KYB\OCR_AGENTS\Actas\JSON"
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
texto = super_ocr(archivo)
logger.info(f"[INFO] OCR completado. Longitud: {len(texto)} caracteres")

# Guardar texto OCR en .txt dentro de JSON_DIR
output_txt_path = os.path.join(JSON_DIR, "output.txt")
with open(output_txt_path, "w", encoding="utf-8") as f:
    f.write(texto)
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
# 7. Pedir datos al usuario
# -------------------------------------------
datos_usuario = pedir_datos_usuario()

# -------------------------------------------
# 8. Extraer datos desde el texto usando LLM
# -------------------------------------------
extraidos_raw = extract_acta_fields(texto, llm)

# Log para depuración: mostrar JSON crudo del LLM
logger.debug("\n=== JSON extraído por LLM (sin normalizar ni equivalencias) ===")
logger.info(json.dumps(extraidos_raw, ensure_ascii=False, indent=2))

# Guardar JSON crudo en JSON_DIR
raw_json_path = os.path.join(JSON_DIR, "extraidos_raw.json")
with open(raw_json_path, "w", encoding="utf-8") as jf:
    json.dump(extraidos_raw, jf, ensure_ascii=False, indent=2)
logger.info(f"[INFO] Archivo extraidos_raw.json generado en {raw_json_path}")

# -------------------------------------------
# 9. Aplicar agente de equivalencias
# -------------------------------------------
extraidos_eq = agente_equivalencias(extraidos_raw)

# Normalizar todos los valores extraídos
extraidos_norm = {
    k: normalizar(v) for k, v in extraidos_eq.items()}

# Guardar JSON con datos extraídos normalizados
extraidos_json_path = os.path.join(JSON_DIR, "extraidos.json")
with open(extraidos_json_path, "w", encoding="utf-8") as jf:
    json.dump(extraidos_norm, jf, ensure_ascii=False, indent=2)
logger.info(f"[INFO] Archivo extraidos.json generado en {extraidos_json_path}")

# -------------------------------------------
# 10. Normalizar datos de usuario
# -------------------------------------------
datos_usuario_norm = {
    k: normalizar_texto_simple(v) if isinstance(v, str) else v
    for k, v in datos_usuario.items()
}

extraidos_norm_simple = {
    k: normalizar_texto_simple(v) if isinstance(v, str) else v
    for k, v in extraidos_norm.items()
}

# -------------------------------------------
# 11. Conciliación
# -------------------------------------------
logger.debug("\n=== Conciliación con datos del usuario (normalizados) ===")
reportar(datos_usuario_norm, extraidos_norm_simple)

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
