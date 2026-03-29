from fastapi import (
    APIRouter,
    File,
    UploadFile,
    Form,
    Query,
    Depends
)
from typing import Annotated, Optional

from ..config import prefix, TEMP_DIR
from ..controller.files import save_file, delete_file, cleanup_temp_files
from ..middleware.auth import require_api_key

router = APIRouter(
    dependencies=[Depends(require_api_key)]  # Autenticacion requerida para todos los endpoints
)

@router.post(prefix + "/files")
async def create_file(file: Annotated[bytes, File()]):
    return {"file_size": len(file)}

@router.post(prefix + "/uploadfile")
async def create_upload_file(file: Annotated[UploadFile, File()]):
    return {"filename": file.filename}

@router.post(prefix + "/write-file")
async def write_upload_file(uploaded_file: Annotated[UploadFile, File()]):
    file_location = f"{TEMP_DIR}/{uploaded_file.filename}"
    with open(file_location, "wb+") as file_object:
        file_object.write(uploaded_file.file.read())
    return {"info": f"file '{uploaded_file.filename}' saved at '{file_location}'"}

@router.post(prefix + "/other_files")
async def create_other_file(
    file: Annotated[bytes, File()],
    fileb: Annotated[UploadFile, File()],
    token: Annotated[str, Form()],
):
    return {
        "file_size": len(file),
        "token": token,
        "fileb_content_type": fileb.content_type,
    }


@router.delete(prefix + "/temp/cleanup")
async def cleanup_temp(
    days: Optional[int] = Query(7, description="Eliminar archivos más antiguos que N días"),
    all: Optional[bool] = Query(False, description="Eliminar TODOS los archivos temporales")
):
    """
    Purga archivos temporales del directorio temp/.
    
    - **days**: Elimina archivos más antiguos que N días (default: 7)
    - **all**: Si true, elimina TODOS los archivos sin importar la edad
    
    Returns:
        Estadísticas de limpieza (archivos eliminados, espacio liberado, errores)
    """
    stats = cleanup_temp_files(max_age_days=days, delete_all=all)
    
    # Formatear bytes para respuesta legible
    def format_bytes(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
    
    return {
        "message": "Limpieza completada",
        "deleted_files": stats["deleted_files"],
        "space_freed": format_bytes(stats["deleted_bytes"]),
        "space_freed_bytes": stats["deleted_bytes"],
        "skipped_files": stats["skipped_files"],
        "errors": stats["errors"]
    }