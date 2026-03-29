"""
Router Pipeline — Endpoints del orquestador KYB.

Endpoints:
  POST /api/v1/pipeline/process             → Un doc (PagaTodo OCR) → BD → Colorado → …
  POST /api/v1/pipeline/expediente          → Multi-doc (PagaTodo OCR) → BD → Colorado → …
  GET  /api/v1/pipeline/status/{rfc}        → Progreso del expediente
  GET  /api/v1/pipeline/health              → Health check integrado (servicios)

Flujo único (PagaTodo Hub):
  1. Cliente envía prospect_id + DocumentType
  2. Orquestrador obtiene OCR pre-extraído de PagaTodo Hub
  3. Persiste directamente en PostgreSQL (empresas + documentos)
  4. Colorado → Arizona PLD → Compliance → Nevada
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .clients import (
    arizona_health,
    colorado_health,
    compliance_health,
)
from .config import PAGATODO_DOCTYPE_MAP
from .persistence import obtener_estado_por_rfc
from .pipeline import (
    procesar_documento,
    procesar_expediente,
)

logger = logging.getLogger("orquestrator.router")

router = APIRouter(prefix="/api/v1/pipeline", tags=["Pipeline — Orquestador KYB"])


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /status/{rfc} — Estado del expediente
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/status/{rfc}",
    summary="Consultar estado del expediente por RFC",
    description="Retorna el estado end-to-end del pipeline y progreso de documentos.",
)
async def get_status(rfc: str):
    """
    Consulta el estado de un expediente por RFC.
    Busca en pipeline_resultados (estado unificado).
    """
    # 1. Consultar pipeline_resultados
    estado_pipeline = None
    try:
        estado_pipeline = await obtener_estado_por_rfc(rfc.strip().upper())
    except Exception as e:
        logger.warning("[STATUS] Error consultando pipeline_resultados: %s", e)

    if not estado_pipeline:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC: {rfc}")

    # 2. Formatear resultado
    result: dict = {}
    if estado_pipeline:
        # Serializar tipos no-JSON (datetime, UUID, Decimal)
        pipeline_dict = {}
        for k, v in estado_pipeline.items():
            if hasattr(v, "isoformat"):
                pipeline_dict[k] = v.isoformat()
            elif hasattr(v, "hex"):  # UUID
                pipeline_dict[k] = str(v)
            elif isinstance(v, (int, float, str, bool, list, dict)) or v is None:
                pipeline_dict[k] = v
            else:
                pipeline_dict[k] = str(v)
        result["pipeline"] = pipeline_dict
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /process — Documento individual (PagaTodo Hub)
# ═══════════════════════════════════════════════════════════════════════════════

_DOC_TYPES_DESC = ", ".join(f"`{k}`" for k in PAGATODO_DOCTYPE_MAP)


class PagatodoDocRequest(BaseModel):
    """Solicitud para procesar un documento vía PagaTodo Hub."""
    prospect_id: str = Field(..., description="UUID del prospecto en PagaTodo Hub")
    document_type: str = Field(
        ...,
        description=f"Tipo de documento externo PagaTodo ({_DOC_TYPES_DESC})",
    )
    rfc: str = Field(..., description="RFC de la empresa (obligatorio)")


class PagatodoExpedienteRequest(BaseModel):
    """Solicitud para procesar un expediente completo vía PagaTodo Hub."""
    prospect_id: str = Field(..., description="UUID del prospecto en PagaTodo Hub")
    rfc: str = Field(..., description="RFC de la empresa (obligatorio)")
    document_types: list[str] = Field(
        ...,
        description=f"Lista de tipos de documento externos a procesar ({_DOC_TYPES_DESC})",
    )


@router.post(
    "/process",
    summary="Procesar un documento KYB (flujo completo)",
    description=f"""
**Flujo automático con OCR externo (PagaTodo Hub):**

1. El Orquestrador obtiene el OCR pre-extraído desde PagaTodo Hub.
2. Persiste directamente en **PostgreSQL** (empresas + documentos).
3. Llama a **Colorado** para validación cruzada.
4. Llama a **Arizona** para análisis PLD/AML.
5. Llama a **Compliance** para dictamen PLD/FT.
6. Llama a **Nevada** para dictamen jurídico.

**Tipos de documento soportados (PagaTodo):**
{_DOC_TYPES_DESC}
""",
)
async def process_document(body: PagatodoDocRequest):
    """Procesa un documento KYB: PagaTodo OCR → validación → BD → pipeline."""
    if body.document_type not in PAGATODO_DOCTYPE_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"DocumentType '{body.document_type}' no reconocido. Valores válidos: {list(PAGATODO_DOCTYPE_MAP.keys())}",
        )
    if not body.rfc or not body.rfc.strip():
        raise HTTPException(status_code=422, detail="El campo 'rfc' es obligatorio.")

    try:
        resultado = await procesar_documento(
            prospect_id=body.prospect_id,
            document_type=body.document_type,
            rfc=body.rfc,
        )
        return resultado
    except Exception as e:
        logger.error("[PIPELINE-PT] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /expediente — Multi-documento (PagaTodo Hub)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/expediente",
    summary="Procesar expediente KYB completo",
    description=f"""
Procesa múltiples documentos de un prospecto PagaTodo.

El Orquestrador:
1. Obtiene el OCR de cada documento desde PagaTodo Hub.
2. Persiste cada resultado directamente en **PostgreSQL**.
3. Llama a **Colorado** una sola vez al final.
4. Ejecuta **Arizona PLD** → **Compliance** → **Nevada**.

**Tipos de documento soportados:**
{_DOC_TYPES_DESC}
""",
)
async def process_expediente(body: PagatodoExpedienteRequest):
    """Procesa expediente KYB completo."""
    if not body.rfc or not body.rfc.strip():
        raise HTTPException(status_code=422, detail="El campo 'rfc' es obligatorio.")

    # Validar todos los document_types
    invalid = [dt for dt in body.document_types if dt not in PAGATODO_DOCTYPE_MAP]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"DocumentType(s) no reconocido(s): {invalid}. Valores válidos: {list(PAGATODO_DOCTYPE_MAP.keys())}",
        )

    try:
        resultado = await procesar_expediente(
            prospect_id=body.prospect_id,
            rfc=body.rfc,
            document_types=body.document_types,
        )
        return resultado
    except Exception as e:
        logger.error("[PIPELINE-PT] Error expediente: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /health — Health check integrado
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/health",
    summary="Health check del pipeline (Orquestrador + Colorado + Arizona)",
)
async def pipeline_health():
    """Verifica que los servicios downstream estén disponibles."""
    c_ok = await colorado_health()
    a_ok = await arizona_health()
    comp_ok = await compliance_health()

    all_ok = c_ok and a_ok and comp_ok
    status = "healthy" if all_ok else "degraded"

    return {
        "status": status,
        "orquestrator": {"status": "running"},
        "colorado": {"reachable": c_ok, "url": "http://localhost:8011"},
        "arizona_pld": {"reachable": a_ok, "url": "http://localhost:8012"},
        "arizona_compliance": {"reachable": comp_ok, "url": "http://localhost:8012"},
    }
