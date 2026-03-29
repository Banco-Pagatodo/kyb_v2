import pytesseract
import subprocess
import shutil

TESSERACT_PATH = r"C:\Users\oaguirre_ext\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def verificar_tesseract() -> bool:
#Verifica que Tesseract esté instalado y accesible.
    try:
        if not shutil.which(TESSERACT_PATH):
            print("[ERROR] Tesseract no está en la ruta especificada.")
            return False
        result = subprocess.run([TESSERACT_PATH, '--version'], capture_output=True, text=True, check=True)
        print("[OK] Tesseract detectado:", result.stdout.splitlines()[0])
        return True
    except Exception as e:
        print(f"[ERROR] Error verificando Tesseract: {e}")
        return False
