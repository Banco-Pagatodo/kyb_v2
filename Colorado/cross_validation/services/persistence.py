"""
Servicio de persistencia: guarda y consulta validaciones cruzadas en PostgreSQL.
Tabla: validaciones_cruzadas (creada por migración 0004).
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from ..core.database import get_pool
from ..models.schemas import (
    Dictamen,
    Hallazgo,
    ReporteValidacion,
    Severidad,
    ValidacionCruzadaDB,
)

logger = logging.getLogger("cross_validation.persistence")


# ═══════════════════════════════════════════════════════════════════
#  GUARDAR
# ═══════════════════════════════════════════════════════════════════

async def guardar_validacion(
    reporte: ReporteValidacion,
    *,
    portales_ejecutados: bool = False,
    modulos_portales: set[str] | None = None,
) -> str:
    """
    Persiste un ReporteValidacion en la tabla validaciones_cruzadas.
    Retorna el UUID del registro creado.
    """
    pool = await get_pool()

    hallazgos_json = [h.model_dump(mode="json") for h in reporte.hallazgos]
    modulos_json = sorted(modulos_portales) if modulos_portales else None

    reporte_texto = None  # TODO: generar_reporte_texto(reporte) cuando se active

    # Generar resumen estructurado por bloques
    resumen = _construir_resumen_bloques(reporte.hallazgos)

    # Incluir datos clave de la persona moral en el resumen
    if reporte.datos_clave:
        resumen["datos_clave"] = reporte.datos_clave.model_dump(mode="json")
        logger.info("datos_clave incluido en resumen: %d apoderados, %d accionistas", 
                    len(reporte.datos_clave.apoderados), len(reporte.datos_clave.accionistas))
    else:
        logger.warning("reporte.datos_clave es None — no se incluirá en resumen_bloques")

    row = await pool.fetchrow(
        """
        INSERT INTO validaciones_cruzadas (
            empresa_id, rfc, razon_social,
            dictamen, total_pasan, total_criticos, total_medios, total_informativos,
            hallazgos, recomendaciones, documentos_presentes,
            portales_ejecutados, modulos_portales,
            reporte_texto, resumen_bloques
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6, $7, $8,
            $9::jsonb, $10::jsonb, $11::jsonb,
            $12, $13::jsonb,
            $14, $15::jsonb
        )
        ON CONFLICT (empresa_id) DO UPDATE SET
            rfc               = EXCLUDED.rfc,
            razon_social      = EXCLUDED.razon_social,
            dictamen          = EXCLUDED.dictamen,
            total_pasan       = EXCLUDED.total_pasan,
            total_criticos    = EXCLUDED.total_criticos,
            total_medios      = EXCLUDED.total_medios,
            total_informativos= EXCLUDED.total_informativos,
            hallazgos         = EXCLUDED.hallazgos,
            recomendaciones   = EXCLUDED.recomendaciones,
            documentos_presentes = EXCLUDED.documentos_presentes,
            portales_ejecutados  = EXCLUDED.portales_ejecutados,
            modulos_portales     = EXCLUDED.modulos_portales,
            reporte_texto        = EXCLUDED.reporte_texto,
            resumen_bloques      = EXCLUDED.resumen_bloques,
            created_at           = now()
        RETURNING id, created_at
        """,
        _uuid.UUID(reporte.empresa_id),
        reporte.rfc,
        reporte.razon_social,
        reporte.dictamen.value,
        reporte.total_pasan,
        reporte.total_criticos,
        reporte.total_medios,
        reporte.total_informativos,
        json.dumps(hallazgos_json, ensure_ascii=False),
        json.dumps(reporte.recomendaciones, ensure_ascii=False),
        json.dumps(reporte.documentos_presentes, ensure_ascii=False),
        portales_ejecutados,
        json.dumps(modulos_json, ensure_ascii=False) if modulos_json else None,
        reporte_texto,
        json.dumps(resumen, ensure_ascii=False),
    )

    vid = str(row["id"])
    logger.info(
        "Validación guardada (upsert): %s | empresa=%s | dictamen=%s",
        vid, reporte.rfc, reporte.dictamen.value,
    )
    return vid


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

_NOMBRES_BLOQUE = {
    1: "IDENTIDAD CORPORATIVA",
    2: "DOMICILIO",
    3: "VIGENCIA DE DOCUMENTOS",
    4: "APODERADO LEGAL",
    5: "ESTRUCTURA SOCIETARIA",
    6: "DATOS BANCARIOS",
    7: "CONSISTENCIA NOTARIAL",
    8: "CALIDAD DE EXTRACCIÓN",
    9: "COMPLETITUD DEL EXPEDIENTE",
    10: "VALIDACIÓN EN PORTALES GUBERNAMENTALES",
}


def _construir_resumen_bloques(hallazgos: list[Hallazgo]) -> dict[str, Any]:
    """Construye un resumen estructurado agrupado por bloque."""
    bloques: dict[int, list[Hallazgo]] = {}
    for h in hallazgos:
        bloques.setdefault(h.bloque, []).append(h)

    resumen: dict[str, Any] = {}
    for num in sorted(bloques):
        items = bloques[num]
        pasan = sum(1 for h in items if h.pasa is True)
        fallan = sum(1 for h in items if h.pasa is False)
        na = sum(1 for h in items if h.pasa is None)
        criticos = sum(1 for h in items if h.pasa is False and h.severidad == Severidad.CRITICA)
        medios = sum(1 for h in items if h.pasa is False and h.severidad == Severidad.MEDIA)
        informativos = sum(1 for h in items if h.severidad == Severidad.INFORMATIVA)

        resumen[str(num)] = {
            "nombre": _NOMBRES_BLOQUE.get(num, f"BLOQUE {num}"),
            "total": len(items),
            "pasan": pasan,
            "fallan": fallan,
            "na": na,
            "criticos": criticos,
            "medios": medios,
            "informativos": informativos,
            "codigos": [h.codigo for h in items],
        }
    return resumen


# ═══════════════════════════════════════════════════════════════════
#  CONSULTAR
# ═══════════════════════════════════════════════════════════════════

def _row_to_model(row) -> ValidacionCruzadaDB:
    """Convierte un asyncpg.Record en ValidacionCruzadaDB."""
    hallazgos = row["hallazgos"]
    if isinstance(hallazgos, str):
        hallazgos = json.loads(hallazgos)

    recomendaciones = row["recomendaciones"]
    if isinstance(recomendaciones, str):
        recomendaciones = json.loads(recomendaciones)

    docs = row["documentos_presentes"]
    if isinstance(docs, str):
        docs = json.loads(docs)

    modulos = row["modulos_portales"]
    if isinstance(modulos, str):
        modulos = json.loads(modulos)

    resumen_bloques = row["resumen_bloques"]
    if isinstance(resumen_bloques, str):
        resumen_bloques = json.loads(resumen_bloques)

    return ValidacionCruzadaDB(
        id=str(row["id"]),
        empresa_id=str(row["empresa_id"]),
        rfc=row["rfc"],
        razon_social=row["razon_social"],
        dictamen=Dictamen(row["dictamen"]),
        total_pasan=row["total_pasan"],
        total_criticos=row["total_criticos"],
        total_medios=row["total_medios"],
        total_informativos=row["total_informativos"],
        hallazgos=hallazgos,
        recomendaciones=recomendaciones,
        documentos_presentes=docs,
        portales_ejecutados=row["portales_ejecutados"],
        modulos_portales=modulos,
        reporte_texto=row["reporte_texto"],
        resumen_bloques=resumen_bloques,
        created_at=row["created_at"],
    )


async def obtener_validacion(validacion_id: str) -> ValidacionCruzadaDB | None:
    """Obtiene una validación cruzada por su UUID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM validaciones_cruzadas WHERE id = $1",
        _uuid.UUID(validacion_id),
    )
    return _row_to_model(row) if row else None


async def obtener_ultima_validacion(empresa_id: str) -> ValidacionCruzadaDB | None:
    """Obtiene la validación más reciente de una empresa."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM validaciones_cruzadas
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        _uuid.UUID(empresa_id),
    )
    return _row_to_model(row) if row else None


async def listar_validaciones(
    empresa_id: str | None = None,
    rfc: str | None = None,
    dictamen: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ValidacionCruzadaDB]:
    """
    Lista validaciones cruzadas con filtros opcionales.
    Ordenadas por created_at DESC (más reciente primero).
    """
    pool = await get_pool()

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if empresa_id:
        conditions.append(f"empresa_id = ${idx}")
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
        SELECT * FROM validaciones_cruzadas
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return [_row_to_model(r) for r in rows]


async def contar_validaciones(
    empresa_id: str | None = None,
    rfc: str | None = None,
    dictamen: str | None = None,
) -> int:
    """Cuenta validaciones con los mismos filtros que listar_validaciones."""
    pool = await get_pool()

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if empresa_id:
        conditions.append(f"empresa_id = ${idx}")
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

    row = await pool.fetchval(
        f"SELECT count(*) FROM validaciones_cruzadas {where}",
        *params,
    )
    return row or 0
