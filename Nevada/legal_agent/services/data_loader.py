"""
Carga datos del expediente legal completo desde PostgreSQL.
Lee de: empresas, documentos, validaciones_cruzadas, dictamenes_pld, analisis_pld.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from ..core.database import get_pool
from ..models.schemas import ExpedienteLegal


def _parse_json(val: Any) -> Any:
    """Parsea un valor JSON si viene como string."""
    if isinstance(val, str):
        return json.loads(val)
    return val


async def cargar_expediente_legal(empresa_id: str) -> ExpedienteLegal:
    """
    Carga datos consolidados de la empresa para el dictamen jurídico:
    - Datos de la empresa (empresas)
    - Documentos extraídos por Dakota (documentos)
    - Validación cruzada de Colorado (validaciones_cruzadas)
    - Análisis PLD de Arizona (analisis_pld)
    - Dictamen PLD de Arizona (dictamenes_pld)
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
            datos = _parse_json(doc["datos_extraidos"])
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
        resumen_raw = _parse_json(vc_row["resumen_bloques"])
        validacion_cruzada = {
            "dictamen": vc_row["dictamen"],
            "hallazgos": _parse_json(vc_row["hallazgos"]),
            "recomendaciones": _parse_json(vc_row["recomendaciones"]),
            "documentos_presentes": _parse_json(vc_row["documentos_presentes"]),
            "resumen_bloques": resumen_raw,
            "total_pasan": vc_row["total_pasan"],
            "total_criticos": vc_row["total_criticos"],
            "total_medios": vc_row["total_medios"],
            "total_informativos": vc_row["total_informativos"],
        }
        if isinstance(resumen_raw, dict):
            datos_clave = resumen_raw.get("datos_clave")

    # 4. Análisis PLD de Arizona
    pld_row = await pool.fetchrow(
        """
        SELECT dictamen, hallazgos, resumen_bloques,
               screening_ejecutado, screening_results,
               total_pasan, total_criticos, total_altos, total_medios, total_informativos,
               created_at
        FROM analisis_pld
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        uid,
    )

    analisis_pld: dict[str, Any] | None = None
    if pld_row:
        analisis_pld = {
            "resultado": pld_row["dictamen"],
            "hallazgos": _parse_json(pld_row["hallazgos"]),
            "resumen_bloques": _parse_json(pld_row["resumen_bloques"]),
            "screening": _parse_json(pld_row["screening_results"]),
            "total_pasan": pld_row["total_pasan"],
            "total_criticos": pld_row["total_criticos"],
        }

    # 5. Dictamen PLD de Arizona
    dict_row = await pool.fetchrow(
        """
        SELECT dictamen, nivel_riesgo_residual, dictamen_json,
               created_at
        FROM dictamenes_pld
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        uid,
    )

    dictamen_pld: dict[str, Any] | None = None
    if dict_row:
        dj = _parse_json(dict_row["dictamen_json"])
        dictamen_pld = {
            "dictamen": dj,
            "dictamen_resultado": dict_row["dictamen"],
            "nivel_riesgo_residual": dict_row["nivel_riesgo_residual"],
        }

    return ExpedienteLegal(
        empresa_id=str(row["id"]),
        rfc=row["rfc"],
        razon_social=row["razon_social"],
        documentos=documentos,
        tipos_documento=sorted(doc_types),
        validacion_cruzada=validacion_cruzada,
        analisis_pld=analisis_pld,
        dictamen_pld=dictamen_pld,
        datos_clave=datos_clave,
    )
