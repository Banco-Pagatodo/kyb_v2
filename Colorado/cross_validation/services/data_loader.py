"""
Carga datos de empresas y documentos desde PostgreSQL.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from ..core.database import get_pool
from ..models.schemas import ExpedienteEmpresa


async def cargar_expediente(empresa_id: str) -> ExpedienteEmpresa:
    """
    Carga todos los documentos de una empresa desde la BD.
    Si hay duplicados del mismo tipo, conserva el más reciente.
    """
    pool = await get_pool()

    uid = _uuid.UUID(empresa_id)

    # Info de la empresa
    row = await pool.fetchrow(
        "SELECT id, rfc, razon_social FROM empresas WHERE id = $1",
        uid,
    )
    if not row:
        raise ValueError(f"Empresa con ID '{empresa_id}' no encontrada en la BD")

    # Todos los documentos, más reciente primero
    docs = await pool.fetch(
        """
        SELECT doc_type, datos_extraidos, created_at
        FROM documentos
        WHERE empresa_id = $1
        ORDER BY doc_type, created_at DESC
        """,
        uid,
    )

    documentos: dict[str, dict[str, Any]] = {}
    doc_types: list[str] = []

    for doc in docs:
        dt = doc["doc_type"]
        if dt not in documentos:  # Conservar solo el más reciente
            datos = doc["datos_extraidos"]
            if isinstance(datos, str):
                datos = json.loads(datos)
            documentos[dt] = datos
            doc_types.append(dt)

    return ExpedienteEmpresa(
        empresa_id=str(row["id"]),
        rfc=row["rfc"],
        razon_social=row["razon_social"],
        documentos=documentos,
        doc_types_presentes=sorted(doc_types),
    )


async def listar_empresas() -> list[dict[str, Any]]:
    """Lista todas las empresas con sus tipos de documentos."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT e.id, e.rfc, e.razon_social,
               count(d.id) as total_docs,
               array_agg(DISTINCT d.doc_type ORDER BY d.doc_type) as doc_types
        FROM empresas e
        LEFT JOIN documentos d ON d.empresa_id = e.id
        GROUP BY e.id, e.rfc, e.razon_social
        ORDER BY e.rfc
        """
    )
    return [
        {
            "id": str(r["id"]),
            "rfc": r["rfc"],
            "razon_social": r["razon_social"],
            "total_docs": r["total_docs"],
            "doc_types": r["doc_types"] or [],
        }
        for r in rows
    ]
