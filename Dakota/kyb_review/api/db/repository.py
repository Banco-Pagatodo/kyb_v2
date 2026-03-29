# api/db/repository.py
# Funciones CRUD para Empresa y Documento.
# Todas las operaciones son async y reciben la sesión como parámetro.

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Empresa, Documento

logger = logging.getLogger("kyb.db.repo")


# ═══════════════════════════════════════════════════════════════════════════
# EMPRESAS
# ═══════════════════════════════════════════════════════════════════════════

async def get_or_create_empresa(
    db: AsyncSession,
    rfc: str,
    razon_social: str | None = None,
) -> Empresa:
    """
    Busca una empresa por RFC. Si no existe, la crea.
    Retorna la empresa (existente o nueva).
    """
    rfc = rfc.strip().upper()

    stmt = select(Empresa).where(Empresa.rfc == rfc)
    result = await db.execute(stmt)
    empresa = result.scalar_one_or_none()

    if empresa is not None:
        # Si la razón social era el placeholder genérico y ahora tenemos la real, actualizar
        if razon_social and empresa.razon_social.startswith("Empresa "):
            empresa.razon_social = razon_social
            logger.info("Razón social actualizada: rfc=%s → %s", rfc, razon_social)
        logger.debug("Empresa encontrada: rfc=%s id=%s", rfc, empresa.id)
        return empresa

    # Crear nueva empresa
    empresa = Empresa(
        rfc=rfc,
        razon_social=razon_social or f"Empresa {rfc}",
    )
    db.add(empresa)
    await db.flush()  # Genera el UUID sin hacer commit
    logger.info("Empresa creada: rfc=%s id=%s", rfc, empresa.id)
    return empresa


async def get_empresa_by_rfc(db: AsyncSession, rfc: str) -> Empresa | None:
    """Busca una empresa por RFC."""
    stmt = select(Empresa).where(Empresa.rfc == rfc.strip().upper())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_empresa_by_id(db: AsyncSession, empresa_id: uuid.UUID) -> Empresa | None:
    """Busca una empresa por su UUID."""
    stmt = select(Empresa).where(Empresa.id == empresa_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_empresas(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> list[Empresa]:
    """Lista empresas."""
    stmt = select(Empresa).order_by(Empresa.fecha_registro.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════════════
# DOCUMENTOS
# ═══════════════════════════════════════════════════════════════════════════

async def save_documento(
    db: AsyncSession,
    *,
    empresa_id: uuid.UUID,
    doc_type: str,
    file_name: str,
    datos_extraidos: dict[str, Any],
) -> Documento:
    """
    Persiste un documento procesado en la base de datos (upsert).
    Si ya existe un registro con la misma (empresa_id, doc_type),
    actualiza datos_extraidos y file_name; de lo contrario inserta uno nuevo.
    """
    # Buscar documento existente
    stmt = select(Documento).where(
        Documento.empresa_id == empresa_id,
        Documento.doc_type == doc_type,
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is not None:
        # UPDATE
        doc.file_name = file_name
        doc.datos_extraidos = datos_extraidos
        doc.created_at = datetime.now(tz=timezone.utc)  # refrescar timestamp (UTC)
        await db.flush()
        logger.info(
            "Documento actualizado (upsert): id=%s type=%s empresa=%s",
            doc.id, doc_type, empresa_id,
        )
    else:
        # INSERT
        doc = Documento(
            empresa_id=empresa_id,
            doc_type=doc_type,
            file_name=file_name,
            datos_extraidos=datos_extraidos,
        )
        db.add(doc)
        await db.flush()
        logger.info(
            "Documento creado (upsert): id=%s type=%s empresa=%s",
            doc.id, doc_type, empresa_id,
        )
    return doc


async def get_documentos_by_empresa(
    db: AsyncSession,
    empresa_id: uuid.UUID,
    doc_type: str | None = None,
) -> list[Documento]:
    """Obtiene todos los documentos de una empresa, con filtro opcional de tipo."""
    stmt = (
        select(Documento)
        .where(Documento.empresa_id == empresa_id)
        .order_by(Documento.created_at.desc())
    )
    if doc_type:
        stmt = stmt.where(Documento.doc_type == doc_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_documento_by_id(
    db: AsyncSession, doc_id: uuid.UUID
) -> Documento | None:
    """Busca un documento por UUID."""
    stmt = select(Documento).where(Documento.id == doc_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_empresa_progress(
    db: AsyncSession, empresa_id: uuid.UUID
) -> dict[str, Any]:
    """
    Calcula el progreso KYB de una empresa:
    cuántos tipos de documento ya fueron subidos y su estado.
    """
    REQUIRED_DOCS = [
        "csf", "acta_constitutiva", "poder", "ine", "ine_reverso",
        "fiel", "estado_cuenta", "domicilio", "reforma_estatutos",
        "ine_propietario_real", "domicilio_rl", "domicilio_propietario_real",
    ]

    stmt = (
        select(Documento.doc_type)
        .where(Documento.empresa_id == empresa_id)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    uploaded = set(rows)

    docs_status = []
    for dt in REQUIRED_DOCS:
        docs_status.append({
            "doc_type": dt,
            "uploaded": dt in uploaded,
        })

    total = len(REQUIRED_DOCS)
    done = sum(1 for dt in REQUIRED_DOCS if dt in uploaded)

    return {
        "empresa_id": str(empresa_id),
        "total_required": total,
        "total_uploaded": done,
        "progress_pct": round(done / total * 100, 1),
        "documents": docs_status,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS — Extraer campos del resultado de la API para persistir
# ═══════════════════════════════════════════════════════════════════════════

def _make_json_safe(obj: Any) -> Any:
    """
    Convierte recursivamente objetos date/datetime a strings ISO
    para que sean serializables a JSONB por PostgreSQL.
    """
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, (date,)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(item) for item in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


def extract_fields_for_db(api_result: dict[str, Any]) -> dict[str, Any]:
    """
    Dado el dict que devuelve un endpoint de docs (con validation wrapper),
    extrae los campos necesarios para save_documento().

    Retorna un dict listo para pasarse como **kwargs a save_documento().
    """
    fields: dict[str, Any] = {}

    # datos_extraidos — hacer JSON-safe (fechas → ISO strings)
    fields["datos_extraidos"] = _make_json_safe(api_result.get("datos_extraidos", {}))

    return fields
