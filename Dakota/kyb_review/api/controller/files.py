from fastapi import UploadFile
from ..config import TEMP_DIR
import os

async def save_file(file: UploadFile, prefix:str = "") -> str:
    """Save the uploaded file to a temporary location."""
    # Extract just the filename without path
    filename = os.path.basename(file.filename)
    
    # Add prefix with underscore separator if prefix provided
    if prefix:
        filename = f"{prefix}_{filename}"
    
    file_location = f"{TEMP_DIR}/{filename}"
    
    # Ensure temp directory exists
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    with open(file_location, "wb+") as file_object:
        file_object.write(file.file.read())
    return file_location

async def delete_file(file_location: str) -> None:
    """Delete the file at the specified location."""
    import os
    if os.path.exists(file_location):
        os.remove(file_location)
    else:
        raise FileNotFoundError(f"The file {file_location} does not exist.")


def cleanup_temp_files(max_age_days: int = 7, delete_all: bool = False) -> dict:
    """
    Purga archivos temporales del directorio temp/.
    
    Args:
        max_age_days: Eliminar archivos más antiguos que N días
        delete_all: Si True, elimina todos los archivos sin importar la edad
    
    Returns:
        dict con estadísticas de limpieza
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    
    stats = {
        "deleted_files": 0,
        "deleted_bytes": 0,
        "skipped_files": 0,
        "errors": []
    }
    
    temp_path = Path(TEMP_DIR)
    if not temp_path.exists():
        return stats
    
    cutoff_time = datetime.now() - timedelta(days=max_age_days)
    
    for subdir in ["json", "raw", ""]:  # Incluye raíz de temp/
        subdir_path = temp_path / subdir if subdir else temp_path
        if not subdir_path.exists():
            continue
            
        for file_path in subdir_path.iterdir():
            if file_path.is_file():
                try:
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    should_delete = delete_all or file_mtime < cutoff_time
                    
                    if should_delete:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        stats["deleted_files"] += 1
                        stats["deleted_bytes"] += file_size
                    else:
                        stats["skipped_files"] += 1
                except Exception as e:
                    stats["errors"].append(f"{file_path.name}: {str(e)}")
    
    return stats