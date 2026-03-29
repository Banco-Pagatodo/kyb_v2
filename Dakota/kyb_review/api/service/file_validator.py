# api/service/file_validator.py
"""
Módulo de validación de archivos de entrada.
Implementa validación de tamaño, tipo MIME y sanitización.
"""

import os
import re
import logging
from typing import Tuple, Optional
from fastapi import UploadFile, HTTPException

logger = logging.getLogger(__name__)

# Intentar importar python-magic, fallback a detección por extensión
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    logger.warning("python-magic not available, falling back to extension-based MIME detection")
    MAGIC_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

# Tamaños máximos por tipo de documento (en bytes)
MAX_FILE_SIZES = {
    "default": 50 * 1024 * 1024,      # 50 MB default
    "ine": 10 * 1024 * 1024,          # 10 MB para INE
    "ine_reverso": 10 * 1024 * 1024,  # 10 MB para INE reverso
    "csf": 5 * 1024 * 1024,           # 5 MB para CSF
    "fiel": 5 * 1024 * 1024,          # 5 MB para FIEL
    "domicilio": 10 * 1024 * 1024,    # 10 MB para comprobante
    "estado_cuenta": 30 * 1024 * 1024, # 30 MB para estados de cuenta
    "acta_constitutiva": 50 * 1024 * 1024,  # 50 MB para actas
    "poder_notarial": 50 * 1024 * 1024,     # 50 MB para poderes
    "reforma_estatutos": 50 * 1024 * 1024,  # 50 MB para reformas
}

# MIME types permitidos
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg", 
    "image/png",
    "image/tiff",
    "application/zip",  # Para FIEL (archivo ZIP con certificados)
}

# Extensiones permitidas
ALLOWED_EXTENSIONS = {".pdf", ".jpeg", ".jpg", ".png", ".tiff", ".tif", ".zip"}

# Caracteres peligrosos en nombres de archivo
DANGEROUS_PATTERNS = [
    r"\.\./",           # Path traversal
    r"\.\.\\",          # Path traversal Windows
    r"[<>:\"|?*]",      # Caracteres no válidos en Windows
    r"[\x00-\x1f]",     # Caracteres de control
    r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])$",  # Nombres reservados Windows
]


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN DE ARCHIVOS
# ═══════════════════════════════════════════════════════════════════════════════

class FileValidationError(HTTPException):
    """Excepción para errores de validación de archivo."""
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)


def get_real_mime_type(file_content: bytes, filename: str = "") -> str:
    """
    Detecta el tipo MIME real del archivo usando magic bytes.
    No confía en la extensión del archivo.
    
    Args:
        file_content: Contenido del archivo en bytes
        filename: Nombre del archivo (fallback si magic no disponible)
    
    Returns:
        Tipo MIME detectado
    """
    if MAGIC_AVAILABLE:
        try:
            mime_detector = magic.Magic(mime=True)
            return mime_detector.from_buffer(file_content)
        except Exception as e:
            logger.warning(f"Error detecting MIME type with magic: {e}")
    
    # Fallback: detectar por extensión
    ext_to_mime = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in ext_to_mime:
            return ext_to_mime[ext]
    
    # Detectar por magic bytes básicos
    if file_content.startswith(b'%PDF'):
        return "application/pdf"
    elif file_content.startswith(b'\xff\xd8\xff'):
        return "image/jpeg"
    elif file_content.startswith(b'\x89PNG'):
        return "image/png"
    elif file_content.startswith(b'II') or file_content.startswith(b'MM'):
        return "image/tiff"
    
    return "application/octet-stream"


def sanitize_filename(filename: str) -> str:
    """
    Sanitiza el nombre del archivo para prevenir ataques.
    
    Args:
        filename: Nombre original del archivo
    
    Returns:
        Nombre sanitizado
    """
    if not filename:
        return "unnamed_file"
    
    # Obtener solo el nombre base (sin path)
    filename = os.path.basename(filename)
    
    # Verificar patrones peligrosos
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            logger.warning(f"Dangerous filename pattern detected: {filename}")
            # Limpiar el patrón peligroso
            filename = re.sub(pattern, "_", filename, flags=re.IGNORECASE)
    
    # Remover caracteres no ASCII problemáticos pero mantener acentos
    # Solo remover caracteres de control
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
    
    # Limitar longitud
    name, ext = os.path.splitext(filename)
    if len(name) > 200:
        name = name[:200]
    
    # Asegurar que tenga extensión válida
    if ext.lower() not in ALLOWED_EXTENSIONS:
        # Intentar detectar extensión del contenido más tarde
        pass
    
    return f"{name}{ext}" if ext else name


async def validate_upload_file(
    file: UploadFile,
    doc_type: str = "default",
    validate_mime: bool = True
) -> Tuple[bytes, str]:
    """
    Valida un archivo subido y retorna su contenido.
    
    Args:
        file: Archivo subido via FastAPI
        doc_type: Tipo de documento para límite de tamaño
        validate_mime: Si validar el tipo MIME real
    
    Returns:
        Tuple[bytes, str]: (contenido del archivo, nombre sanitizado)
    
    Raises:
        FileValidationError: Si la validación falla
    """
    # Sanitizar nombre
    original_filename = file.filename or "unnamed"
    safe_filename = sanitize_filename(original_filename)
    
    # Leer contenido
    try:
        content = await file.read()
        # Reset file position for potential re-read
        await file.seek(0)
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise FileValidationError(f"Error leyendo archivo: {str(e)}")
    
    # Validar tamaño
    max_size = MAX_FILE_SIZES.get(doc_type, MAX_FILE_SIZES["default"])
    if len(content) > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = len(content) / (1024 * 1024)
        logger.warning(f"File too large: {actual_mb:.2f}MB > {max_mb:.2f}MB")
        raise FileValidationError(
            f"Archivo demasiado grande: {actual_mb:.1f}MB. "
            f"Máximo permitido para {doc_type}: {max_mb:.0f}MB"
        )
    
    # Validar contenido mínimo
    if len(content) < 100:
        raise FileValidationError("Archivo vacío o corrupto")
    
    # Validar tipo MIME real
    if validate_mime:
        real_mime = get_real_mime_type(content)
        
        if real_mime not in ALLOWED_MIME_TYPES:
            logger.warning(f"Invalid MIME type: {real_mime} for file {safe_filename}")
            raise FileValidationError(
                f"Tipo de archivo no soportado: {real_mime}. "
                f"Tipos permitidos: PDF, JPEG, PNG, TIFF"
            )
        
        # Verificar consistencia con extensión
        ext = os.path.splitext(safe_filename)[1].lower()
        expected_mimes = {
            ".pdf": {"application/pdf"},
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
            ".tiff": {"image/tiff"},
            ".tif": {"image/tiff"},
        }
        
        if ext in expected_mimes and real_mime not in expected_mimes[ext]:
            logger.warning(
                f"MIME type mismatch: extension={ext}, actual={real_mime}"
            )
            # No rechazar, pero loggear la inconsistencia
    
    logger.info(f"File validated: {safe_filename} ({len(content)} bytes, type={doc_type})")
    
    return content, safe_filename


def validate_file_extension(filename: str) -> bool:
    """
    Valida que la extensión del archivo sea permitida.
    
    Args:
        filename: Nombre del archivo
    
    Returns:
        True si la extensión es válida
    """
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


async def save_validated_file(
    file: UploadFile,
    temp_dir: str,
    prefix: str = "",
    doc_type: str = "default"
) -> str:
    """
    Valida y guarda un archivo de forma segura.
    
    Args:
        file: Archivo subido
        temp_dir: Directorio temporal
        prefix: Prefijo para el nombre
        doc_type: Tipo de documento
    
    Returns:
        Ruta al archivo guardado
    """
    # Validar archivo
    content, safe_filename = await validate_upload_file(file, doc_type)
    
    # Construir path seguro
    if prefix:
        safe_filename = f"{prefix}_{safe_filename}"
    
    # Asegurar que el directorio existe
    os.makedirs(temp_dir, exist_ok=True)
    
    # Guardar archivo
    file_path = os.path.join(temp_dir, safe_filename)
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    return file_path


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════════

def get_file_info(file_path: str) -> dict:
    """
    Obtiene información sobre un archivo.
    
    Args:
        file_path: Ruta al archivo
    
    Returns:
        Dict con información del archivo
    """
    try:
        stat = os.stat(file_path)
        with open(file_path, "rb") as f:
            content = f.read(8192)  # Solo leer primeros 8KB para MIME
            mime_type = get_real_mime_type(content)
        
        return {
            "path": file_path,
            "filename": os.path.basename(file_path),
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "mime_type": mime_type,
            "extension": os.path.splitext(file_path)[1].lower(),
        }
    except Exception as e:
        logger.error(f"Error getting file info: {e}")
        return {"error": str(e)}
