"""
Persistencia del estado del pipeline en PostgreSQL.
Tabla: pipeline_resultados (migración 0008).

Versión Dakota: solo tracking del pipeline (Dakota se encarga de
persistir empresas y documentos).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .database import get_pool

logger = logging.getLogger("orquestrator.persistence")


# ═══════════════════════════════════════════════════════════════════
#  Crear / Iniciar registro del pipeline
# ═══════════════════════════════════════════════════════════════════

async def iniciar_pipeline(
    empresa_id: str,
    rfc: str,
    razon_social: str,
) -> str:
    """
    Crea (o reinicia) el registro de pipeline para una empresa.
    UPSERT por empresa_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pipeline_resultados (
                id, empresa_id, rfc, razon_social,
                pipeline_status, created_at
            ) VALUES (
                uuid_generate_v4(), $1::uuid, $2, $3,
                'EN_PROCESO', NOW()
            )
            ON CONFLICT (empresa_id) DO UPDATE SET
                rfc              = EXCLUDED.rfc,
                razon_social     = EXCLUDED.razon_social,
                pipeline_status  = 'EN_PROCESO',
                dakota_status    = NULL,
                colorado_status  = NULL,
                arizona_status   = NULL,
                nevada_status    = NULL,
                completed_at     = NULL,
                updated_at       = NOW()
            RETURNING id
            """,
            empresa_id, rfc, razon_social,
        )
        record_id = str(row["id"])
        logger.info("Pipeline iniciado: id=%s empresa=%s", record_id, empresa_id)
        return record_id


# ═══════════════════════════════════════════════════════════════════
#  Actualizar paso Dakota
# ═══════════════════════════════════════════════════════════════════

async def actualizar_dakota(
    empresa_id: str,
    *,
    status: str = "COMPLETADO",
    documentos_extraidos: int | None = None,
    tipos_documentos: list[str] | None = None,
) -> None:
    """Registra el resultado de Dakota en pipeline_resultados."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_resultados SET
                dakota_status        = $2,
                documentos_extraidos = $3,
                tipos_documentos     = $4::jsonb,
                dakota_ts            = NOW(),
                updated_at           = NOW()
            WHERE empresa_id = $1::uuid
            """,
            empresa_id,
            status,
            documentos_extraidos,
            json.dumps(tipos_documentos) if tipos_documentos else None,
        )
        logger.debug("Dakota actualizado: empresa=%s status=%s", empresa_id, status)


# ═══════════════════════════════════════════════════════════════════
#  Actualizar paso Colorado
# ═══════════════════════════════════════════════════════════════════

async def actualizar_colorado(
    empresa_id: str,
    *,
    status: str = "COMPLETADO",
    dictamen: str | None = None,
    hallazgos: int | None = None,
    criticos: int | None = None,
) -> None:
    """Registra el resultado de Colorado en pipeline_resultados."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_resultados SET
                colorado_status    = $2,
                colorado_dictamen  = $3,
                colorado_hallazgos = $4,
                colorado_criticos  = $5,
                colorado_ts        = NOW(),
                updated_at         = NOW()
            WHERE empresa_id = $1::uuid
            """,
            empresa_id, status, dictamen, hallazgos, criticos,
        )
        logger.debug("Colorado actualizado: empresa=%s status=%s", empresa_id, status)


# ═══════════════════════════════════════════════════════════════════
#  Actualizar paso Arizona
# ═══════════════════════════════════════════════════════════════════

async def actualizar_arizona(
    empresa_id: str,
    *,
    status: str = "COMPLETADO",
    resultado: str | None = None,
    completitud_pct: float | None = None,
    screening: str | None = None,
) -> None:
    """Registra el resultado de Arizona en pipeline_resultados."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_resultados SET
                arizona_status         = $2,
                arizona_resultado      = $3,
                arizona_completitud_pct = $4,
                arizona_screening      = $5,
                arizona_ts             = NOW(),
                updated_at             = NOW()
            WHERE empresa_id = $1::uuid
            """,
            empresa_id, status, resultado, completitud_pct, screening,
        )
        logger.debug("Arizona actualizado: empresa=%s status=%s", empresa_id, status)


# ═══════════════════════════════════════════════════════════════════
#  Actualizar paso Nevada
# ═══════════════════════════════════════════════════════════════════

async def actualizar_nevada(
    empresa_id: str,
    *,
    status: str = "COMPLETADO",
    dictamen: str | None = None,
    nivel_riesgo: str | None = None,
    riesgo_residual: float | None = None,
) -> None:
    """Registra el resultado de Nevada en pipeline_resultados."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_resultados SET
                nevada_status         = $2,
                nevada_dictamen       = $3,
                nevada_nivel_riesgo   = $4,
                nevada_riesgo_residual = $5,
                nevada_ts             = NOW(),
                updated_at            = NOW()
            WHERE empresa_id = $1::uuid
            """,
            empresa_id, status, dictamen, nivel_riesgo,
            riesgo_residual,
        )
        logger.debug("Nevada actualizado: empresa=%s status=%s", empresa_id, status)


# ═══════════════════════════════════════════════════════════════════
#  Finalizar pipeline
# ═══════════════════════════════════════════════════════════════════

async def finalizar_pipeline(
    empresa_id: str,
    *,
    status: str = "COMPLETADO",
    tiempos_ms: dict[str, Any] | None = None,
) -> None:
    """Marca el pipeline como finalizado con tiempos."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_resultados SET
                pipeline_status = $2,
                tiempos_ms      = $3::jsonb,
                completed_at    = NOW(),
                updated_at      = NOW()
            WHERE empresa_id = $1::uuid
            """,
            empresa_id,
            status,
            json.dumps(tiempos_ms) if tiempos_ms else None,
        )
        logger.info(
            "Pipeline finalizado: empresa=%s status=%s", empresa_id, status,
        )


# ═══════════════════════════════════════════════════════════════════
#  Consultar estado
# ═══════════════════════════════════════════════════════════════════

async def obtener_estado_pipeline(empresa_id: str) -> dict[str, Any] | None:
    """Obtiene el estado del pipeline de una empresa por empresa_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pipeline_resultados WHERE empresa_id = $1::uuid",
            empresa_id,
        )
        return dict(row) if row else None


async def obtener_estado_por_rfc(rfc: str) -> dict[str, Any] | None:
    """Obtiene el estado del pipeline por RFC (el más reciente)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM pipeline_resultados
            WHERE rfc = $1
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """,
            rfc,
        )
        return dict(row) if row else None
