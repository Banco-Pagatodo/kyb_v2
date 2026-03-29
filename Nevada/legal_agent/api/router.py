"""
Router de la API REST de Nevada (Dictamen Jurídico).
Prefijo: /api/v1/legal
"""
from __future__ import annotations

import logging
import time
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.data_loader import cargar_expediente_legal
from ..services.rules_engine import evaluar_reglas
from ..services.dictamen_generator import generar_dictamen
from ..services.persistence import guardar_dictamen, obtener_dictamen, _generar_texto_plano

logger = logging.getLogger("nevada.router")

router = APIRouter(prefix="/api/v1/legal", tags=["legal"])


def _validar_uuid(empresa_id: str) -> str:
    """Valida que empresa_id sea un UUID válido; lanza 400 si no."""
    try:
        _uuid.UUID(empresa_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"empresa_id '{empresa_id}' no es un UUID válido",
        )
    return empresa_id


@router.get("/health")
async def health():
    """Health check del servicio Nevada."""
    return {"status": "ok", "service": "nevada", "version": "1.0.0"}


@router.post("/dictamen/{empresa_id}")
async def generar_dictamen_juridico(empresa_id: str) -> dict[str, Any]:
    """
    Genera el Dictamen Jurídico completo para una empresa.

    1. Carga expediente de la BD (datos de Dakota, Colorado, Arizona)
    2. Evalúa reglas deterministas
    3. Genera narrativa con LLM
    4. Persiste en dictamenes_legales
    5. Retorna dictamen completo
    """
    _validar_uuid(empresa_id)
    t0 = time.time()
    logger.info("[API] POST /dictamen/%s", empresa_id)

    # 1. Cargar expediente
    try:
        expediente = await cargar_expediente_legal(empresa_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 2. Evaluar reglas
    resultado_reglas = evaluar_reglas(expediente)

    # 3. Generar dictamen (determinista + LLM)
    dictamen = await generar_dictamen(expediente, resultado_reglas)

    # 4. Persistir
    record_id = await guardar_dictamen(
        empresa_id=empresa_id,
        dictamen=dictamen,
        resultado_reglas=resultado_reglas,
        datos_expediente={
            "rfc": expediente.rfc,
            "razon_social": expediente.razon_social,
            "tipos_documento": expediente.tipos_documento,
            "tiene_colorado": expediente.validacion_cruzada is not None,
            "tiene_arizona": expediente.analisis_pld is not None,
        },
        documentos_ocr=expediente.documentos,
    )

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[API] Dictamen generado en %dms: %s → %s",
        elapsed_ms, expediente.razon_social, dictamen.dictamen_resultado,
    )

    return {
        "id": record_id,
        "empresa_id": empresa_id,
        "rfc": dictamen.rfc,
        "razon_social": dictamen.razon_social,
        "dictamen": dictamen.dictamen_resultado,
        "fundamento_legal": dictamen.fundamento_legal,
        "dictamen_json": dictamen.model_dump(),
        "dictamen_texto": _generar_texto_plano(dictamen, resultado_reglas, documentos_ocr=expediente.documentos),
        "reglas": resultado_reglas.model_dump(),
        "elapsed_ms": elapsed_ms,
    }


@router.get("/dictamen/{empresa_id}")
async def consultar_dictamen(empresa_id: str) -> dict[str, Any]:
    """Consulta el último dictamen jurídico guardado para una empresa."""
    _validar_uuid(empresa_id)
    logger.info("[API] GET /dictamen/%s", empresa_id)
    result = await obtener_dictamen(empresa_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró dictamen jurídico para empresa {empresa_id}",
        )
    return result


@router.get("/expediente/{empresa_id}")
async def preview_expediente(empresa_id: str) -> dict[str, Any]:
    """
    Preview de los datos consolidados del expediente (sin generar dictamen).
    Útil para inspeccionar qué datos tiene Nevada disponibles.
    """
    _validar_uuid(empresa_id)
    logger.info("[API] GET /expediente/%s", empresa_id)
    try:
        expediente = await cargar_expediente_legal(empresa_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "empresa_id": expediente.empresa_id,
        "rfc": expediente.rfc,
        "razon_social": expediente.razon_social,
        "tipos_documento": expediente.tipos_documento,
        "documentos_disponibles": list(expediente.documentos.keys()),
        "tiene_validacion_cruzada": expediente.validacion_cruzada is not None,
        "dictamen_colorado": (expediente.validacion_cruzada or {}).get("dictamen"),
        "tiene_analisis_pld": expediente.analisis_pld is not None,
        "resultado_pld": (expediente.analisis_pld or {}).get("resultado"),
        "tiene_dictamen_pld": expediente.dictamen_pld is not None,
    }
