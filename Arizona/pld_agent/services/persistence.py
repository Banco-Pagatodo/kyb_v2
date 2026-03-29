"""
Persistencia de análisis PLD en PostgreSQL.
Tabla: analisis_pld (migración 0009 — un registro por empresa).
Patrón idéntico a Colorado (validaciones_cruzadas).
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

import asyncpg

from ..core.database import get_pool
from ..services.report_generator import ResultadoReporteUnificado

logger = logging.getLogger("arizona.persistence")


# ═══════════════════════════════════════════════════════════════════
#  GUARDAR
# ═══════════════════════════════════════════════════════════════════

async def guardar_analisis_pld(
    resultado: ResultadoReporteUnificado,
    *,
    screening_ejecutado: bool = False,
    screening_results: dict[str, Any] | None = None,
    conn: asyncpg.Connection | None = None,
) -> str:
    """
    Persiste el análisis PLD completo en la tabla analisis_pld.
    Un solo registro por empresa_id (UPSERT ON CONFLICT empresa_id).
    Retorna el UUID del registro.

    Si se pasa *conn*, usa esa conexión (para participar en una transacción
    externa). De lo contrario, obtiene una conexión del pool.
    """
    _conn: asyncpg.Connection | asyncpg.Pool = conn or await get_pool()

    hallazgos_json = [h.model_dump(mode="json") if hasattr(h, "model_dump") else h
                      for h in resultado.hallazgos]

    resumen = _construir_resumen_bloques(resultado.hallazgos)

    row = await _conn.fetchrow(
        """
        INSERT INTO analisis_pld (
            empresa_id, rfc, razon_social,
            dictamen, total_pasan, total_criticos, total_altos, total_medios, total_informativos,
            hallazgos, recomendaciones, documentos_presentes,
            screening_ejecutado, screening_results,
            reporte_texto, resumen_bloques
        ) VALUES (
            $1::uuid, $2, $3,
            $4, $5, $6, $7, $8, $9,
            $10::jsonb, $11::jsonb, $12::jsonb,
            $13, $14::jsonb,
            $15, $16::jsonb
        )
        ON CONFLICT (empresa_id) DO UPDATE SET
            rfc                = EXCLUDED.rfc,
            razon_social       = EXCLUDED.razon_social,
            dictamen           = EXCLUDED.dictamen,
            total_pasan        = EXCLUDED.total_pasan,
            total_criticos     = EXCLUDED.total_criticos,
            total_altos        = EXCLUDED.total_altos,
            total_medios       = EXCLUDED.total_medios,
            total_informativos = EXCLUDED.total_informativos,
            hallazgos          = EXCLUDED.hallazgos,
            recomendaciones    = EXCLUDED.recomendaciones,
            documentos_presentes = EXCLUDED.documentos_presentes,
            screening_ejecutado  = EXCLUDED.screening_ejecutado,
            screening_results    = EXCLUDED.screening_results,
            reporte_texto        = EXCLUDED.reporte_texto,
            resumen_bloques      = EXCLUDED.resumen_bloques,
            created_at           = now()
        RETURNING id, created_at
        """,
        _uuid.UUID(resultado.empresa_id),                       # $1
        resultado.rfc,                                          # $2
        resultado.razon_social,                                 # $3
        resultado.dictamen,                                     # $4
        resultado.total_pasan,                                  # $5
        resultado.total_criticos,                               # $6
        resultado.total_altos,                                  # $7
        resultado.total_medios,                                 # $8
        resultado.total_informativos,                           # $9
        json.dumps(hallazgos_json, ensure_ascii=False),         # $10
        json.dumps(resultado.recomendaciones, ensure_ascii=False),  # $11
        json.dumps(resultado.documentos_presentes, ensure_ascii=False),  # $12
        screening_ejecutado,                                    # $13
        json.dumps(screening_results, ensure_ascii=False) if screening_results else None,  # $14
        resultado.texto,                                        # $15
        json.dumps(resumen, ensure_ascii=False),                # $16
    )

    vid = str(row["id"])
    logger.info(
        "Análisis PLD guardado (upsert): %s | empresa=%s | dictamen=%s",
        vid, resultado.rfc, resultado.dictamen,
    )
    return vid


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

_NOMBRES_BLOQUE = {
    1: "DOCUMENTOS OBLIGATORIOS",
    2: "DATOS DE LA PERSONA MORAL",
    3: "DOMICILIO COMPLETO",
    4: "PERSONAS IDENTIFICADAS",
    5: "PODER BANCARIO",
}


def _construir_resumen_bloques(hallazgos: list[dict[str, Any]]) -> dict[str, Any]:
    """Construye un resumen estructurado agrupado por bloque."""
    bloques: dict[int, list[dict]] = {}
    for h in hallazgos:
        bloque = h.get("bloque", 0)
        bloques.setdefault(bloque, []).append(h)

    resumen: dict[str, Any] = {}
    for num in sorted(bloques):
        items = bloques[num]
        pasan = sum(1 for h in items if h.get("pasa") is True)
        fallan = sum(1 for h in items if h.get("pasa") is False)
        na = sum(1 for h in items if h.get("pasa") is None)
        criticos = sum(1 for h in items if h.get("pasa") is False and h.get("severidad") == "CRITICA")
        altos = sum(1 for h in items if h.get("pasa") is False and h.get("severidad") == "ALTA")
        medios = sum(1 for h in items if h.get("pasa") is False and h.get("severidad") == "MEDIA")
        informativos = sum(1 for h in items if h.get("severidad") == "INFORMATIVA")

        resumen[str(num)] = {
            "nombre": _NOMBRES_BLOQUE.get(num, f"BLOQUE {num}"),
            "total": len(items),
            "pasan": pasan,
            "fallan": fallan,
            "na": na,
            "criticos": criticos,
            "altos": altos,
            "medios": medios,
            "informativos": informativos,
            "codigos": [h.get("codigo", "") for h in items],
        }
    return resumen


# ═══════════════════════════════════════════════════════════════════
#  CONSULTAR
# ═══════════════════════════════════════════════════════════════════

async def obtener_analisis_pld(empresa_id: str) -> dict[str, Any] | None:
    """Obtiene el análisis PLD de una empresa (un solo registro)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM analisis_pld WHERE empresa_id = $1::uuid",
        _uuid.UUID(empresa_id),
    )
    return dict(row) if row else None


async def listar_analisis_pld(
    empresa_id: str | None = None,
    rfc: str | None = None,
    dictamen: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Lista análisis PLD con filtros opcionales."""
    pool = await get_pool()

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if empresa_id:
        conditions.append(f"empresa_id = ${idx}::uuid")
        params.append(_uuid.UUID(empresa_id))
        idx += 1
    if rfc:
        conditions.append(f"rfc = ${idx}")
        params.append(rfc.upper())
        idx += 1
    if dictamen:
        conditions.append(f"dictamen = ${idx}")
        params.append(dictamen.upper())
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    params.append(offset)

    rows = await pool.fetch(
        f"""
        SELECT * FROM analisis_pld
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════
#  DICTAMEN PLD/FT
# ═══════════════════════════════════════════════════════════════════

async def guardar_dictamen_pld(
    empresa_id: str,
    rfc: str,
    razon_social: str,
    dictamen_json: dict[str, Any],
    dictamen_txt: str,
    grado_riesgo: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> str:
    """
    Persiste el dictamen PLD/FT en la tabla dictamenes_pld.
    Tabla creada en migración 0007 (Nevada), columnas Arizona en 0010.
    UPSERT por empresa_id. Retorna UUID del registro.

    Si se pasa *conn*, usa esa conexión (para participar en una transacción
    externa). De lo contrario, obtiene una conexión del pool.
    """
    _conn: asyncpg.Connection | asyncpg.Pool = conn or await get_pool()

    # Mapear grado → dictamen de la tabla original
    _MAPA_DICTAMEN = {"bajo": "APROBADO", "medio": "APROBADO_CON_CONDICIONES", "alto": "ESCALADO_A_COMITE"}
    dictamen_label = _MAPA_DICTAMEN.get(grado_riesgo, "APROBADO")

    row = await _conn.fetchrow(
        """
        INSERT INTO dictamenes_pld (
            empresa_id, rfc, razon_social,
            dictamen, nivel_riesgo_residual,
            dictamen_json, dictamen_txt,
            agente
        ) VALUES (
            $1::uuid, $2, $3,
            $4, $5,
            $6::jsonb, $7,
            $8
        )
        ON CONFLICT (empresa_id) DO UPDATE SET
            rfc                   = EXCLUDED.rfc,
            razon_social          = EXCLUDED.razon_social,
            dictamen              = EXCLUDED.dictamen,
            nivel_riesgo_residual = EXCLUDED.nivel_riesgo_residual,
            dictamen_json         = EXCLUDED.dictamen_json,
            dictamen_txt          = EXCLUDED.dictamen_txt,
            agente                = EXCLUDED.agente,
            updated_at            = now()
        RETURNING id, created_at
        """,
        _uuid.UUID(empresa_id),                                      # $1
        rfc,                                                         # $2
        razon_social,                                                # $3
        dictamen_label,                                              # $4
        grado_riesgo.upper(),                                        # $5
        json.dumps(dictamen_json, ensure_ascii=False, default=str),  # $6
        dictamen_txt,                                                # $7
        "Arizona v2.3",                                              # $8
    )

    vid = str(row["id"])
    logger.info(
        "Dictamen PLD guardado (upsert): %s | empresa=%s | riesgo=%s",
        vid, rfc, grado_riesgo,
    )
    return vid


# ═══════════════════════════════════════════════════════════════════
#  GUARDAR TODO EN TRANSACCIÓN
# ═══════════════════════════════════════════════════════════════════

async def guardar_resultado_completo(
    resultado: ResultadoReporteUnificado,
    dictamen_json: dict[str, Any],
    dictamen_txt: str,
    grado_riesgo: str,
    *,
    screening_ejecutado: bool = False,
    screening_results: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """
    Persiste análisis PLD + dictamen PLD/FT en una sola transacción.

    Garantiza atomicidad: si falla cualquiera de los dos INSERTs,
    se hace rollback de ambos y no queda estado inconsistente.

    Returns:
        Tupla (id_analisis, id_dictamen).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            id_analisis = await guardar_analisis_pld(
                resultado,
                screening_ejecutado=screening_ejecutado,
                screening_results=screening_results,
                conn=conn,
            )
            id_dictamen = await guardar_dictamen_pld(
                empresa_id=resultado.empresa_id,
                rfc=resultado.rfc,
                razon_social=resultado.razon_social,
                dictamen_json=dictamen_json,
                dictamen_txt=dictamen_txt,
                grado_riesgo=grado_riesgo,
                conn=conn,
            )
    logger.info(
        "Resultado completo guardado (tx): analisis=%s dictamen=%s empresa=%s",
        id_analisis, id_dictamen, resultado.empresa_id,
    )
    return id_analisis, id_dictamen


async def obtener_dictamen_pld(empresa_id: str) -> dict[str, Any] | None:
    """Obtiene el dictamen PLD/FT de una empresa."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM dictamenes_pld WHERE empresa_id = $1::uuid",
        _uuid.UUID(empresa_id),
    )
    return dict(row) if row else None
