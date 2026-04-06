"""
Router Pipeline — Endpoints del orquestador KYB (flujo Dakota).

Endpoints:
  POST /api/v1/pipeline/process             → Un doc (archivo) → Dakota → Colorado → …
  POST /api/v1/pipeline/expediente          → Multi-doc (archivos) → Dakota → Colorado → …
  GET  /api/v1/pipeline/status/{rfc}        → Progreso del expediente
  GET  /api/v1/pipeline/health              → Health check integrado (servicios)

Flujo Dakota:
  1. Cliente envía archivo(s) + RFC + tipo de documento
  2. Orquestrador envía cada archivo a Dakota para OCR + persistencia
  3. Dakota extrae datos y persiste en PostgreSQL
  4. Colorado → Arizona PLD → Compliance → Nevada
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .clients import (
    arizona_health,
    colorado_health,
    compliance_health,
    dakota_health,
)
from .config import DAKOTA_DOC_TYPES
from .persistence import obtener_estado_por_rfc
from .pipeline import (
    procesar_documento,
    procesar_expediente,
)

logger = logging.getLogger("orquestrator.router")

router = APIRouter(prefix="/api/v1/pipeline", tags=["Pipeline — Orquestador KYB (Dakota)"])

_DOC_TYPES_DESC = ", ".join(f"`{t}`" for t in sorted(DAKOTA_DOC_TYPES))


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /status/{rfc} — Estado del expediente
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/status/{rfc}",
    summary="Consultar estado del expediente por RFC",
    description="Retorna el estado end-to-end del pipeline y progreso de documentos.",
)
async def get_status(rfc: str):
    """Consulta el estado de un expediente por RFC."""
    estado_pipeline = None
    try:
        estado_pipeline = await obtener_estado_por_rfc(rfc.strip().upper())
    except Exception as e:
        logger.warning("[STATUS] Error consultando pipeline_resultados: %s", e)

    if not estado_pipeline:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC: {rfc}")

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

    return {"pipeline": pipeline_dict}


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /process — Documento individual (archivo → Dakota)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/process",
    summary="Procesar un documento KYB (flujo completo vía Dakota)",
    description=f"""
**Flujo automático con Dakota:**

1. El Orquestrador envía el archivo a **Dakota** para OCR + persistencia.
2. Dakota extrae datos del documento y los guarda en PostgreSQL.
3. Llama a **Colorado** para validación cruzada.
4. Llama a **Arizona** para análisis PLD/AML.
5. Llama a **Compliance** para dictamen PLD/FT.
6. Llama a **Nevada** para dictamen jurídico.

**Tipos de documento soportados:**
{_DOC_TYPES_DESC}
""",
)
async def process_document(
    file: Annotated[UploadFile, File(description="Archivo PDF o imagen del documento")],
    doc_type: Annotated[str, Form(description=f"Tipo de documento: {_DOC_TYPES_DESC}")],
    rfc: Annotated[str, Form(description="RFC de la empresa")],
):
    """Procesa un documento KYB: archivo → Dakota → validación → pipeline."""
    doc_type = doc_type.strip().lower()
    if doc_type not in DAKOTA_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type '{doc_type}' no reconocido. Valores válidos: {sorted(DAKOTA_DOC_TYPES)}",
        )
    if not rfc or not rfc.strip():
        raise HTTPException(status_code=422, detail="El campo 'rfc' es obligatorio.")

    try:
        file_content = await file.read()
        resultado = await procesar_documento(
            doc_type=doc_type,
            file_content=file_content,
            file_name=file.filename or "documento",
            rfc=rfc,
        )
        return resultado
    except Exception as e:
        logger.error("[PIPELINE-DK] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /expediente — Multi-documento (archivos → Dakota)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/expediente",
    summary="Procesar expediente KYB completo (múltiples archivos vía Dakota)",
    description=f"""
Procesa múltiples documentos de una empresa enviándolos a Dakota.

El Orquestrador:
1. Envía cada archivo a **Dakota** para OCR + persistencia.
2. Llama a **Colorado** una sola vez al final.
3. Ejecuta **Arizona PLD** → **Compliance** → **Nevada**.

Enviar los archivos como multipart/form-data:
- `files`: Lista de archivos PDF o imagen.
- `doc_types`: Lista de tipos de documento (mismo orden que los archivos).
- `rfc`: RFC de la empresa.

**Tipos de documento soportados:**
{_DOC_TYPES_DESC}
""",
)
async def process_expediente(
    files: Annotated[list[UploadFile], File(description="Archivos PDF o imagen de los documentos")],
    doc_types: Annotated[list[str], Form(description="Tipos de documento (mismo orden que los archivos)")],
    rfc: Annotated[str, Form(description="RFC de la empresa")],
):
    """Procesa expediente KYB completo: archivos → Dakota → pipeline."""
    if not rfc or not rfc.strip():
        raise HTTPException(status_code=422, detail="El campo 'rfc' es obligatorio.")

    if len(files) != len(doc_types):
        raise HTTPException(
            status_code=422,
            detail=f"Cantidad de archivos ({len(files)}) no coincide con tipos ({len(doc_types)})",
        )

    # Validar tipos de documento
    invalid = [dt for dt in doc_types if dt.strip().lower() not in DAKOTA_DOC_TYPES]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type(s) no reconocido(s): {invalid}. Valores válidos: {sorted(DAKOTA_DOC_TYPES)}",
        )

    try:
        # Leer contenido de los archivos
        archivos = []
        for f, dt in zip(files, doc_types):
            content = await f.read()
            archivos.append({
                "doc_type": dt.strip().lower(),
                "file_content": content,
                "file_name": f.filename or "documento",
            })

        resultado = await procesar_expediente(
            rfc=rfc,
            archivos=archivos,
        )
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[PIPELINE-DK] Error expediente: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /health — Health check integrado
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/health",
    summary="Health check del pipeline (Orquestrador + Dakota + Colorado + Arizona)",
)
async def pipeline_health():
    """Verifica que los servicios downstream estén disponibles."""
    d_ok = await dakota_health()
    c_ok = await colorado_health()
    a_ok = await arizona_health()
    comp_ok = await compliance_health()

    all_ok = d_ok and c_ok and a_ok and comp_ok
    status = "healthy" if all_ok else "degraded"

    return {
        "status": status,
        "orquestrator": {"status": "running"},
        "dakota": {"reachable": d_ok, "url": "http://localhost:8010"},
        "colorado": {"reachable": c_ok, "url": "http://localhost:8011"},
        "arizona_pld": {"reachable": a_ok, "url": "http://localhost:8012"},
        "arizona_compliance": {"reachable": comp_ok, "url": "http://localhost:8012"},
    }
