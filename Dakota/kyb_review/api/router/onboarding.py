"""
Router de Onboarding - Flujo unificado de revisión KYB.

Este módulo expone el endpoint principal para procesar todos los documentos
de onboarding en un solo llamado.

Endpoint principal:
    POST /onboarding/review - Procesa documentos y retorna veredicto

El flujo es:
    1. Recibe archivos (FormData multipart)
    2. Valida formato/tamaño (Guardrails)
    3. Extrae datos con OCR
    4. Valida especificaciones individuales (vigencia, protocolización)
    5. Si pasan individuales, valida cruces (RFC, domicilio, nombre)
    6. Retorna veredicto: APPROVED | REVIEW_REQUIRED | REJECTED
"""

from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import logging

from api.service.orchestrator import orchestrator_service
from api.model.orchestrator import (
    OnboardingReviewResponse,
    ReviewVerdict,
    DOCUMENT_NAMES,
    REQUIRED_DOCUMENTS,
    CONDITIONAL_DOCUMENTS
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/onboarding",
    tags=["Onboarding"],
    responses={
        400: {"description": "Error en documentos o parámetros"},
        422: {"description": "Error de validación"},
        500: {"description": "Error interno del servidor"}
    }
)


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/review",
    response_model=OnboardingReviewResponse,
    summary="Revisión completa de expediente KYB",
    description="""
Procesa todos los documentos de un expediente KYB en un solo llamado.

**Documentos requeridos:**
- `csf`: Constancia de Situación Fiscal
- `acta_constitutiva`: Acta Constitutiva de la empresa
- `ine`: INE del Representante Legal (frente)
- `poder`: Poder Notarial
- `comprobante_domicilio`: Comprobante de Domicilio (CFE, Telmex, agua, gas o predial)

**Documentos condicionales (opcionales):**
- `fiel`: Firma Electrónica Avanzada (certificado .cer)
- `estado_cuenta`: Estado de Cuenta Bancario
- `reforma`: Reforma de Estatutos (si aplica)

**Flujo de procesamiento:**
1. **Guardrails**: Valida formato y tamaño de cada archivo
2. **Extracción**: Procesa OCR y extrae datos estructurados
3. **Validación individual**: Verifica vigencia, protocolización, campos requeridos

**Opciones:**
- `fail_fast`: Si es True (default), detiene al primer error crítico

**Veredictos posibles:**
- `APPROVED`: Expediente aprobado automáticamente
- `REVIEW_REQUIRED`: Requiere revisión manual
- `REJECTED`: Rechazado por errores críticos múltiples
""",
    responses={
        200: {
            "description": "Revisión completada",
            "content": {
                "application/json": {
                    "examples": {
                        "approved": {
                            "summary": "Expediente aprobado",
                            "value": {
                                "expediente_id": "EXP-001",
                                "verdict": "APPROVED",
                                "resumen": "Expediente aprobado automáticamente. 5/5 documentos validados.",
                                "auto_aprobable": True
                            }
                        },
                        "review_required": {
                            "summary": "Requiere revisión",
                            "value": {
                                "expediente_id": "EXP-002",
                                "verdict": "REVIEW_REQUIRED",
                                "resumen": "1 error crítico: CSF vencida.",
                                "auto_aprobable": False
                            }
                        }
                    }
                }
            }
        }
    }
)
async def review_expediente(
    expediente_id: str = Form(..., description="ID único del expediente"),
    
    # Documentos requeridos
    csf: UploadFile = File(..., description="Constancia de Situación Fiscal (PDF o imagen)"),
    acta_constitutiva: UploadFile = File(..., description="Acta Constitutiva (PDF)"),
    ine: UploadFile = File(..., description="INE del Representante Legal - Frente (imagen)"),
    poder: UploadFile = File(..., description="Poder Notarial (PDF)"),
    comprobante_domicilio: UploadFile = File(..., description="Comprobante de Domicilio (PDF o imagen)"),
    
    # Documentos condicionales
    fiel: Optional[UploadFile] = File(None, description="Certificado FIEL (.cer o imagen del certificado)"),
    estado_cuenta: Optional[UploadFile] = File(None, description="Estado de Cuenta Bancario (PDF o imagen)"),
    reforma: Optional[UploadFile] = File(None, description="Reforma de Estatutos (PDF)"),
    
    # Opciones
    rfc: Optional[str] = Form(None, description="RFC de la empresa. Si se proporciona, persiste documentos y dispara validación cruzada automáticamente."),
    fail_fast: bool = Form(True, description="Detener al primer error crítico")
) -> OnboardingReviewResponse:
    """
    Ejecuta revisión completa de un expediente KYB.
    
    Recibe todos los documentos necesarios y ejecuta el flujo completo:
    guardrails → extracción → validación individual → veredicto.
    """
    
    logger.info(f"[ONBOARDING] Recibida solicitud de revisión para expediente: {expediente_id}")
    
    # Construir diccionario de archivos
    files = {
        "csf": csf,
        "acta_constitutiva": acta_constitutiva,
        "ine": ine,
        "poder": poder,
        "comprobante_domicilio": comprobante_domicilio
    }
    
    # Agregar documentos condicionales si fueron proporcionados
    if fiel:
        files["fiel"] = fiel
    if estado_cuenta:
        files["estado_cuenta"] = estado_cuenta
    if reforma:
        files["reforma"] = reforma
    
    logger.info(f"[ONBOARDING] Documentos recibidos: {list(files.keys())}")
    
    try:
        result = await orchestrator_service.process_review(
            expediente_id=expediente_id,
            files=files,
            fail_fast=fail_fast,
            rfc=rfc,
        )
        
        logger.info(f"[ONBOARDING] Revisión completada: {result.verdict.value}")
        return result
        
    except Exception as e:
        logger.error(f"[ONBOARDING] Error procesando expediente {expediente_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error interno procesando expediente: {str(e)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/documents-info",
    summary="Información de documentos requeridos",
    description="Retorna información sobre los documentos necesarios para onboarding"
)
async def get_documents_info():
    """Retorna información sobre los documentos requeridos y condicionales."""
    return {
        "documentos_requeridos": {
            doc_type: {
                "nombre": DOCUMENT_NAMES.get(doc_type, doc_type),
                "obligatorio": True
            }
            for doc_type in REQUIRED_DOCUMENTS
        },
        "documentos_condicionales": {
            doc_type: {
                "nombre": DOCUMENT_NAMES.get(doc_type, doc_type),
                "obligatorio": False
            }
            for doc_type in CONDITIONAL_DOCUMENTS
        },
        "formatos_aceptados": ["PDF", "JPEG", "JPG", "PNG", "TIFF"],
        "tamanos_maximos": {
            "default": "50 MB",
            "ine": "10 MB",
            "csf": "5 MB",
            "fiel": "5 MB"
        }
    }


@router.get(
    "/health",
    summary="Health check del servicio de onboarding",
    description="Verifica que el servicio de onboarding esté funcionando"
)
async def health_check():
    """Health check del servicio de onboarding."""
    return {
        "status": "healthy",
        "service": "onboarding",
        "version": "1.0.0"
    }
