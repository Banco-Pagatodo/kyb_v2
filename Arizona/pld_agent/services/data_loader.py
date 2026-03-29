"""
Carga datos del expediente PLD desde PostgreSQL.
Lee de las tablas: empresas, documentos, validaciones_cruzadas.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from ..core.database import get_pool
from ..models.schemas import ExpedientePLD


async def cargar_expediente_pld(empresa_id: str) -> ExpedientePLD:
    """
    Carga datos completos de la empresa para análisis PLD:
    - Datos de la empresa (empresas)
    - Documentos extraídos por Dakota (documentos)
    - Validación cruzada de Colorado si existe (validaciones_cruzadas)
    """
    pool = await get_pool()
    uid = _uuid.UUID(empresa_id)

    # 1. Info de la empresa
    row = await pool.fetchrow(
        "SELECT id, rfc, razon_social FROM empresas WHERE id = $1",
        uid,
    )
    if not row:
        raise ValueError(f"Empresa con ID '{empresa_id}' no encontrada en la BD")

    # 2. Documentos extraídos (más reciente por tipo)
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
        if dt not in documentos:
            datos = doc["datos_extraidos"]
            if isinstance(datos, str):
                datos = json.loads(datos)
            documentos[dt] = datos
            doc_types.append(dt)

    # 3. Validación cruzada de Colorado (si existe)
    vc_row = await pool.fetchrow(
        """
        SELECT dictamen, hallazgos, recomendaciones,
               documentos_presentes, resumen_bloques,
               total_pasan, total_criticos, total_medios, total_informativos,
               created_at
        FROM validaciones_cruzadas
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        uid,
    )

    validacion_cruzada: dict[str, Any] | None = None
    datos_clave: dict[str, Any] | None = None

    if vc_row:
        resumen_raw = vc_row["resumen_bloques"]
        if isinstance(resumen_raw, str):
            resumen_raw = json.loads(resumen_raw)

        hallazgos_raw = vc_row["hallazgos"]
        if isinstance(hallazgos_raw, str):
            hallazgos_raw = json.loads(hallazgos_raw)

        recomendaciones_raw = vc_row["recomendaciones"]
        if isinstance(recomendaciones_raw, str):
            recomendaciones_raw = json.loads(recomendaciones_raw)

        docs_presentes_raw = vc_row["documentos_presentes"]
        if isinstance(docs_presentes_raw, str):
            docs_presentes_raw = json.loads(docs_presentes_raw)

        validacion_cruzada = {
            "dictamen": vc_row["dictamen"],
            "hallazgos": hallazgos_raw,
            "recomendaciones": recomendaciones_raw,
            "documentos_presentes": docs_presentes_raw,
            "resumen_bloques": resumen_raw,
            "total_pasan": vc_row["total_pasan"],
            "total_criticos": vc_row["total_criticos"],
            "total_medios": vc_row["total_medios"],
            "total_informativos": vc_row["total_informativos"],
            "created_at": str(vc_row["created_at"]),
        }

        if resumen_raw and isinstance(resumen_raw, dict):
            datos_clave = resumen_raw.get("datos_clave")

    return ExpedientePLD(
        empresa_id=str(row["id"]),
        rfc=row["rfc"],
        razon_social=row["razon_social"],
        documentos=documentos,
        doc_types_presentes=sorted(doc_types),
        validacion_cruzada=validacion_cruzada,
        datos_clave=datos_clave,
    )


async def listar_empresas_pld() -> list[dict[str, Any]]:
    """Lista empresas con info de documentos y si tienen validación cruzada."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT e.id, e.rfc, e.razon_social,
               count(d.id) as total_docs,
               array_agg(DISTINCT d.doc_type ORDER BY d.doc_type) as doc_types,
               (SELECT dictamen FROM validaciones_cruzadas vc
                WHERE vc.empresa_id = e.id
                ORDER BY vc.created_at DESC LIMIT 1) as dictamen_colorado
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
            "dictamen_colorado": r["dictamen_colorado"],
        }
        for r in rows
    ]
