"""
Persistencia del estado del pipeline en PostgreSQL.
Tabla: pipeline_resultados (migración 0008).

Permite al Orquestador registrar el progreso end-to-end de cada empresa
a través de los 4 agentes (Dakota → Colorado → Arizona → Nevada).
Cualquier servicio puede leer esta tabla para obtener un resumen rápido.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
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

    Returns:
        UUID del registro.
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


# ═══════════════════════════════════════════════════════════════════
#  Persistencia directa: empresas + documentos
#  (reemplaza la escritura a través de Dakota)
# ═══════════════════════════════════════════════════════════════════

async def get_or_create_empresa(
    rfc: str,
    razon_social: str = "",
) -> str:
    """
    Busca una empresa por RFC.  Si no existe, la crea.

    Returns:
        empresa_id (UUID como string).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Intentar encontrar primero
        row = await conn.fetchrow(
            "SELECT id FROM empresas WHERE rfc = $1",
            rfc,
        )
        if row:
            empresa_id = str(row["id"])
            # Actualizar razón social si viene y la actual es placeholder
            if razon_social:
                await conn.execute(
                    """
                    UPDATE empresas SET razon_social = $2
                    WHERE id = $1::uuid AND (razon_social = '' OR razon_social = rfc)
                    """,
                    empresa_id, razon_social,
                )
            return empresa_id

        # Crear nueva empresa
        row = await conn.fetchrow(
            """
            INSERT INTO empresas (id, rfc, razon_social)
            VALUES (uuid_generate_v4(), $1, $2)
            RETURNING id
            """,
            rfc, razon_social or rfc,
        )
        empresa_id = str(row["id"])
        logger.info("Empresa creada: %s rfc=%s", empresa_id, rfc)
        return empresa_id


async def persist_documento(
    empresa_id: str,
    doc_type: str,
    file_name: str,
    datos_extraidos: dict[str, Any],
) -> str:
    """
    UPSERT de un documento en la tabla ``documentos``.

    Usa ON CONFLICT(empresa_id, doc_type) para ser idempotente:
    la primera llamada inserta, las subsiguientes actualizan.

    Returns:
        documento_id (UUID como string).
    """
    pool = await get_pool()
    # Serializar valores no-JSON-safe (datetime, UUID, etc.)
    safe = json.dumps(datos_extraidos, default=str)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documentos (id, empresa_id, doc_type, file_name,
                                    datos_extraidos, created_at)
            VALUES (uuid_generate_v4(), $1::uuid, $2, $3,
                    $4::jsonb, NOW())
            ON CONFLICT (empresa_id, doc_type) DO UPDATE SET
                file_name       = EXCLUDED.file_name,
                datos_extraidos = EXCLUDED.datos_extraidos,
                created_at      = NOW()
            RETURNING id
            """,
            empresa_id, doc_type, file_name, safe,
        )
        doc_id = str(row["id"])
        logger.debug(
            "Documento persistido: %s empresa=%s type=%s",
            doc_id, empresa_id, doc_type,
        )
        return doc_id
