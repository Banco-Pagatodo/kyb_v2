# api/router/empresas.py
# Endpoints para gestión de empresas y consulta de documentos persistidos.

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import prefix
from api.db.session import get_db
from api.db import repository as repo
from api.middleware.auth import require_api_key


router = APIRouter(
    prefix=prefix + "/empresas",
    tags=["Empresas"],
    dependencies=[Depends(require_api_key)],
)


# ---------------------------------------------------------------------------
# Schemas de request/response (Pydantic)
# ---------------------------------------------------------------------------

class EmpresaCreate(BaseModel):
    rfc: str = Field(..., min_length=12, max_length=13, description="RFC de la empresa")
    razon_social: str = Field(..., min_length=1, description="Razón social / nombre legal")


class EmpresaOut(BaseModel):
    id: uuid.UUID
    rfc: str
    razon_social: str
    fecha_registro: datetime

    model_config = {"from_attributes": True}


class DocumentoOut(BaseModel):
    id: uuid.UUID
    doc_type: str
    file_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=EmpresaOut, status_code=201)
async def crear_empresa(
    body: EmpresaCreate,
    db: AsyncSession = Depends(get_db),
):
    """Registra una nueva empresa (o retorna la existente si el RFC ya existe)."""
    empresa = await repo.get_or_create_empresa(
        db, rfc=body.rfc, razon_social=body.razon_social
    )
    return empresa


@router.get("", response_model=list[EmpresaOut])
async def listar_empresas(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Lista todas las empresas."""
    return await repo.list_empresas(db, limit=limit, offset=offset)


@router.get("/{rfc}", response_model=EmpresaOut)
async def obtener_empresa(rfc: str, db: AsyncSession = Depends(get_db)):
    """Busca una empresa por RFC."""
    empresa = await repo.get_empresa_by_rfc(db, rfc)
    if not empresa:
        raise HTTPException(404, f"Empresa con RFC '{rfc}' no encontrada")
    return empresa


@router.get("/{rfc}/documentos", response_model=list[DocumentoOut])
async def documentos_de_empresa(
    rfc: str,
    doc_type: Annotated[str | None, Query(description="Filtrar por tipo de documento")] = None,
    db: AsyncSession = Depends(get_db),
):
    """Lista todos los documentos procesados de una empresa."""
    empresa = await repo.get_empresa_by_rfc(db, rfc)
    if not empresa:
        raise HTTPException(404, f"Empresa con RFC '{rfc}' no encontrada")
    return await repo.get_documentos_by_empresa(db, empresa.id, doc_type=doc_type)


@router.get("/{rfc}/progress")
async def progreso_kyb(rfc: str, db: AsyncSession = Depends(get_db)):
    """
    Muestra el progreso KYB de una empresa:
    cuántos documentos faltan, cuáles ya están aprobados, etc.
    """
    empresa = await repo.get_empresa_by_rfc(db, rfc)
    if not empresa:
        raise HTTPException(404, f"Empresa con RFC '{rfc}' no encontrada")
    progress = await repo.get_empresa_progress(db, empresa.id)
    progress["rfc"] = empresa.rfc
    progress["razon_social"] = empresa.razon_social
    return progress
