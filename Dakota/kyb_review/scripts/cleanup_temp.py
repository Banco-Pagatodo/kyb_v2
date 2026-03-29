#!/usr/bin/env python3
"""
Script para purgar archivos temporales del directorio temp/
Puede ejecutarse manualmente o programarse con cron/Task Scheduler

Uso:
    python cleanup_temp.py              # Elimina archivos > 7 días
    python cleanup_temp.py --days 1     # Elimina archivos > 1 día
    python cleanup_temp.py --all        # Elimina todos los archivos
"""

import os
import shutil
import argparse
from datetime import datetime, timedelta
from pathlib import Path


def get_temp_dir() -> Path:
    """Obtiene el directorio temp/ relativo al proyecto."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    return project_root / "temp"


def cleanup_old_files(temp_dir: Path, max_age_days: int = 7) -> dict:
    """
    Elimina archivos más antiguos que max_age_days.

    Returns:
        dict con estadísticas de limpieza
    """
    stats = {
        "deleted_files": 0,
        "deleted_bytes": 0,
        "skipped_files": 0,
        "errors": []
    }

    if not temp_dir.exists():
        print(f"Advertencia: Directorio no existe: {temp_dir}")
        return stats

    cutoff_time = datetime.now() - timedelta(days=max_age_days)

    for subdir in ["json", "raw"]:
        subdir_path = temp_dir / subdir
        if not subdir_path.exists():
            continue

        for file_path in subdir_path.iterdir():
            if file_path.is_file():
                try:
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_mtime < cutoff_time:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        stats["deleted_files"] += 1
                        stats["deleted_bytes"] += file_size
                        print(f"Eliminado: {file_path.name} ({file_size} bytes)")
                    else:
                        stats["skipped_files"] += 1
                except Exception as e:
                    stats["errors"].append(f"{file_path}: {e}")

    return stats


def cleanup_all_files(temp_dir: Path) -> dict:
    """Elimina TODOS los archivos temporales."""
    stats = {
        "deleted_files": 0,
        "deleted_bytes": 0,
        "errors": []
    }

    if not temp_dir.exists():
        print(f"Advertencia: Directorio no existe: {temp_dir}")
        return stats

    for subdir in ["json", "raw"]:
        subdir_path = temp_dir / subdir
        if not subdir_path.exists():
            continue

        for file_path in subdir_path.iterdir():
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    stats["deleted_files"] += 1
                    stats["deleted_bytes"] += file_size
                    print(f"Eliminado: {file_path.name}")
                except Exception as e:
                    stats["errors"].append(f"{file_path}: {e}")

    return stats


def format_bytes(size: int) -> str:
    """Formatea bytes a formato legible."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def main():
    parser = argparse.ArgumentParser(
        description="Purga archivos temporales del directorio temp/"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Eliminar archivos más antiguos que N días (default: 7)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Eliminar TODOS los archivos temporales"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo mostrar qué se eliminaría, sin eliminar"
    )

    args = parser.parse_args()
    temp_dir = get_temp_dir()

    print("=" * 60)
    print("LIMPIEZA DE ARCHIVOS TEMPORALES")
    print("=" * 60)
    print(f"Directorio: {temp_dir}")

    if args.dry_run:
        print("MODO DRY-RUN: No se eliminara nada")
        return

    if args.all:
        print("Eliminando TODOS los archivos temporales...")
        stats = cleanup_all_files(temp_dir)
    else:
        print(f"Eliminando archivos > {args.days} dias...")
        stats = cleanup_old_files(temp_dir, args.days)

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Archivos eliminados: {stats['deleted_files']}")
    print(f"Espacio liberado: {format_bytes(stats['deleted_bytes'])}")

    if "skipped_files" in stats:
        print(f"Archivos omitidos: {stats['skipped_files']}")

    if stats["errors"]:
        print(f"\nErrores ({len(stats['errors'])}):")
        for error in stats["errors"]:
            print(f"   - {error}")


if __name__ == "__main__":
    main()
