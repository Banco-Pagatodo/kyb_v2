# router/docs.py
# API endpoints for document validation
import asyncio
import logging
import time
from fastapi import (
    APIRouter, 
    File,
    UploadFile,
    Query,
    Depends,
    HTTPException,
    Path,
)
from typing import Annotated, Any, Optional
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import prefix

from ..controller.files import save_file, delete_file
from ..controller.docs import (
    analyze_domicilio,
    analyze_constitutiva,
    analyze_poder,
    analyze_reforma,
    analyze_estado_cuenta,
    analyze_csf,
    analyze_fiel,
    analyze_ine,
    analyze_ine_reverso,
    get_docformat
)
from ..service.validation_wrapper import add_validation_to_response, get_validation_status, normalize_dates_in_result
from ..service.guardrails import guardrail_service
from ..middleware.auth import require_api_key
from ..db import session as db_session
from ..db import repository as repo
from ..client.colorado_client import trigger_validacion_cruzada

logger = logging.getLogger("kyb.router.docs")

router = APIRouter(
    prefix=prefix + "/docs",
    dependencies=[Depends(require_api_key)]  # Autenticacion requerida para todos los endpoints
)


# ---------------------------------------------------------------------------
# Helper de persistencia
# ---------------------------------------------------------------------------

def _extract_razon_social(result: dict) -> str | None:
    """
    Intenta extraer la razón social / denominación del resultado de extracción.
    Busca en datos_extraidos los campos más comunes donde aparece el nombre legal.
    """
    datos = result.get("datos_extraidos", {})
    # Orden de prioridad: campos donde aparece la razón social
    CANDIDATE_KEYS = [
        "denominacion_razon_social",
        "razon_social",
        "denominacion_social",
        "titular",
        "nombre_denominacion",
    ]
    for key in CANDIDATE_KEYS:
        val = datos.get(key)
        if not val:
            continue
        # El valor puede ser string directo o dict con "valor"
        if isinstance(val, dict):
            val = val.get("valor", "")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


async def _persist_if_rfc(
    rfc: str | None,
    doc_type: str,
    file_name: str,
    result: dict,
    db: AsyncSession | None,
    skip_colorado: bool = False,
) -> dict:
    """
    Si se proporcionó un RFC y hay sesión de BD, persiste el resultado.
    Agrega `_persistencia` al resultado para informar al caller.
    No lanza excepciones: si falla, solo logea y devuelve el resultado sin persistir.
    """
    if not rfc or db is None:
        return result

    try:
        razon_social = _extract_razon_social(result)
        empresa = await repo.get_or_create_empresa(db, rfc=rfc, razon_social=razon_social)

        fields = repo.extract_fields_for_db(result)
        doc = await repo.save_documento(
            db,
            empresa_id=empresa.id,
            doc_type=doc_type,
            file_name=file_name,
            **fields,
        )

        result["_persistencia"] = {
            "guardado": True,
            "empresa_id": str(empresa.id),
            "documento_id": str(doc.id),
            "rfc": empresa.rfc,
        }

        # ── Disparar Colorado (validación cruzada) en background ──
        if not skip_colorado:
            asyncio.ensure_future(_trigger_colorado_safe(str(empresa.id)))
        else:
            logger.info("skip_colorado=True → no se dispara Colorado (lo hará el caller)")

    except Exception as e:
        logger.error("Error al persistir documento: %s", e, exc_info=True)
        result["_persistencia"] = {"guardado": False, "error": str(e)}

    return result


async def _trigger_colorado_safe(empresa_id: str) -> None:
    """Wrapper seguro para disparar Colorado sin bloquear ni crash."""
    try:
        resultado = await trigger_validacion_cruzada(empresa_id)
        if resultado:
            logger.info(
                "Colorado completó: %s → %s",
                resultado.get("rfc", "?"),
                resultado.get("dictamen", "?"),
            )
    except Exception as e:
        logger.warning("Error disparando Colorado: %s", e)


async def _get_db_or_none():
    """Dependency opcional: retorna sesión de BD si está disponible, sino None."""
    factory = db_session._session_factory          # leer en runtime, NO al import
    if factory is None:
        yield None
        return
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

@router.post("/csf")
async def validate_csf(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado (para flujo orquestado)")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from a Constancia de Situación Fiscal.
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "csf")
    
    start_time = time.time()
    path = await save_file(file, prefix="csf_")
    try:
        result = await asyncio.to_thread(analyze_csf, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "csf", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "csf", file.filename or "unknown", result, db, skip_colorado)
    return result

@router.post("/fiel")
async def validate_fiel(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from FIEL (Firma Electrónica Avanzada).
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "fiel")
    
    start_time = time.time()
    path = await save_file(file, prefix="fiel_")
    try:
        result = await asyncio.to_thread(analyze_fiel, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "fiel", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "fiel", file.filename or "unknown", result, db, skip_colorado)
    return result

@router.post("/estado_cuenta")
async def validate_estado_cuenta(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from an Estado de Cuenta (bank statement).
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "estado_cuenta")
    
    start_time = time.time()
    path = await save_file(file, prefix="estado_cuenta_")
    try:
        result = await asyncio.to_thread(analyze_estado_cuenta, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "estado_cuenta", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "estado_cuenta", file.filename or "unknown", result, db, skip_colorado)
    return result

@router.post("/domicilio")
async def validate_domicilio(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from a Comprobante de Domicilio.
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "domicilio")
    
    start_time = time.time()
    path = await save_file(file, prefix="domicilio_")
    try:
        result = await asyncio.to_thread(analyze_domicilio, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "domicilio", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "domicilio", file.filename or "unknown", result, db, skip_colorado)
    return result

@router.post("/acta_constitutiva")
async def validate_acta_constitutiva(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate an acta constitutiva (articles of incorporation).
    Extracts structured fields from the document with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "acta")
    
    start_time = time.time()
    path = await save_file(file, prefix="acta_")
    try:
        result = await asyncio.to_thread(analyze_constitutiva, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "acta_constitutiva", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "acta_constitutiva", file.filename or "unknown", result, db, skip_colorado)
    return result

@router.post("/poder_notarial")
async def validate_poder_notarial(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from a Poder Notarial (notarial power of attorney).
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "poder")
    
    start_time = time.time()
    path = await save_file(file, prefix="poder_")
    try:
        result = await asyncio.to_thread(analyze_poder, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "poder", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "poder", file.filename or "unknown", result, db, skip_colorado)
    return result


@router.post("/reforma_estatutos")
async def validate_reforma_estatutos(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from a Reforma de Estatutos.
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "reforma")
    
    start_time = time.time()
    path = await save_file(file, prefix="reforma_")
    try:
        result = await asyncio.to_thread(analyze_reforma, path)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "reforma", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "reforma", file.filename or "unknown", result, db, skip_colorado)
    return result


@router.post("/ine")
async def validate_ine(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from an INE (Mexican Voter ID) front side.
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "ine")
    
    start_time = time.time()
    path = await save_file(file, prefix="ine_")
    try:
        def _extract_ine() -> dict:
            return analyze_ine(path, get_docformat(path))
        result = await asyncio.to_thread(_extract_ine)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "ine", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "ine", file.filename or "unknown", result, db, skip_colorado)
    return result


@router.post("/ine_reverso")
async def validate_ine_reverso(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Endpoint to validate and extract data from an INE (Mexican Voter ID) back side.
    Returns structured extracted data with optional validation scores.
    Si se proporciona `rfc`, persiste el resultado en la base de datos.
    """
    # Guardrail: validación temprana
    guardrail_service.validate_all(file, "ine")
    
    start_time = time.time()
    path = await save_file(file, prefix="ine_reverso_")
    try:
        def _extract_ine_reverso() -> dict:
            return analyze_ine_reverso(path, get_docformat(path))
        result = await asyncio.to_thread(_extract_ine_reverso)
    finally:
        try:
            await delete_file(path)
        except Exception:
            logger.debug("Could not delete temp file: %s", path)
    elapsed = time.time() - start_time
    
    if include_validation:
        result = add_validation_to_response(
            result, "ine_reverso", file.filename or "unknown", elapsed
        )
    else:
        result = normalize_dates_in_result(result)
    
    result = await _persist_if_rfc(rfc, "ine_reverso", file.filename or "unknown", result, db, skip_colorado)
    return result


# ---------------------------------------------------------------------------
# Import de OCR externo (PagaTodo Hub)
# ---------------------------------------------------------------------------

class ImportPayload(BaseModel):
    """Payload para importar datos OCR pre-extraídos (ej. desde PagaTodo Hub)."""
    datos_extraidos: dict[str, Any]
    texto_ocr: str = ""
    archivo_procesado: str = "pagatodo_import"

# Tipos de documento válidos para importación
_IMPORT_DOC_TYPES: set[str] = {
    "csf", "fiel", "acta_constitutiva", "poder", "reforma", "reforma_estatutos",
    "estado_cuenta", "domicilio", "ine", "ine_reverso",
    "ine_propietario_real", "domicilio_rl", "domicilio_propietario_real",
}


@router.post("/import/{doc_type}")
async def import_document(
    doc_type: Annotated[str, Path(description="Tipo de documento (csf, ine, acta_constitutiva, etc.)")],
    payload: ImportPayload,
    rfc: Annotated[str | None, Query(description="RFC de la empresa (si se proporciona, guarda en BD)")] = None,
    skip_colorado: Annotated[bool, Query(description="Si true, persiste pero NO dispara Colorado")] = False,
    db: AsyncSession | None = Depends(_get_db_or_none),
):
    """
    Importa datos OCR pre-extraídos sin ejecutar OCR propio.

    Ejecuta validación de campos + persistencia sobre el JSON recibido.
    Pensado para el flujo **PagaTodo Hub → Dakota** donde el OCR ya fue
    realizado externamente y solo se necesita validar y guardar.
    """
    doc_type = doc_type.strip().lower()
    if doc_type not in _IMPORT_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type '{doc_type}' no soportado. Valores válidos: {sorted(_IMPORT_DOC_TYPES)}",
        )

    start_time = time.time()

    # Construir el resultado con la misma estructura que los endpoints de OCR
    result: dict[str, Any] = {
        "archivo_procesado": payload.archivo_procesado,
        "datos_extraidos": payload.datos_extraidos,
        "texto_ocr": payload.texto_ocr,
        "origen": "import",
    }

    elapsed = time.time() - start_time

    result = add_validation_to_response(
        result, doc_type, payload.archivo_procesado, elapsed
    )

    result = await _persist_if_rfc(
        rfc, doc_type, payload.archivo_procesado, result, db, skip_colorado
    )
    return result


@router.get("/metrics")
async def get_metrics():
    """
    Endpoint to get current validation metrics.
    Returns summary of processed documents, scores and problematic fields.
    """
    return get_validation_status()


@router.get("/metrics/detailed")
async def get_detailed_metrics():
    """
    Endpoint to get detailed metrics including latency breakdown and cost estimates.
    Returns comprehensive metrics for monitoring dashboards.
    """
    from ..service.metrics import (
        get_metrics_summary, 
        get_service_metrics, 
        get_cost_estimate,
        get_recent_alerts
    )
    
    return {
        "validation_summary": get_metrics_summary(),
        "service_metrics": get_service_metrics(),
        "cost_estimate": get_cost_estimate(),
        "alerts": {
            "critical": get_recent_alerts("critical", 60),
            "warning": get_recent_alerts("warning", 60),
        }
    }


@router.get("/metrics/alerts")
async def get_alerts(
    severity: Annotated[Optional[str], Query(description="Filter by severity: info, warning, critical")] = None,
    minutes: Annotated[int, Query(description="Get alerts from last N minutes")] = 60
):
    """
    Endpoint to get recent alerts from the system.
    Useful for monitoring and alerting integrations.
    """
    from ..service.metrics import get_recent_alerts
    
    return {
        "alerts": get_recent_alerts(severity, minutes),
        "filter": {
            "severity": severity,
            "minutes": minutes
        }
    }


@router.get("/metrics/costs")
async def get_cost_breakdown():
    """
    Endpoint to get API cost estimates.
    Returns estimated costs for Azure DI and OpenAI services.
    """
    from ..service.metrics import get_cost_estimate
    
    return get_cost_estimate()


@router.get("/health/services")
async def get_services_health():
    """
    Endpoint to get health status of external services (Azure DI, OpenAI).
    Returns circuit breaker states and service availability.
    """
    from ..service.resilience import get_all_circuit_breakers_status
    
    circuit_breakers = get_all_circuit_breakers_status()
    
    # Determinar estado general
    all_healthy = all(cb["state"] == "closed" for cb in circuit_breakers)
    any_open = any(cb["state"] == "open" for cb in circuit_breakers)
    
    return {
        "status": "healthy" if all_healthy else "degraded" if not any_open else "unhealthy",
        "services": {
            cb["name"]: {
                "status": "healthy" if cb["state"] == "closed" else "recovering" if cb["state"] == "half_open" else "unavailable",
                "circuit_state": cb["state"],
                "failure_count": cb["failure_count"],
                "last_failure": cb["last_failure"]
            }
            for cb in circuit_breakers
        },
        "circuit_breakers": circuit_breakers
    }


@router.get("/metrics/guardrails")
async def get_guardrails_metrics():
    """
    Endpoint to get guardrail system metrics.
    Returns rejection counts and reasons for monitoring cost savings.
    """
    return guardrail_service.get_metrics()


@router.post("/metrics/guardrails/reset")
async def reset_guardrails_metrics():
    """
    Endpoint to reset guardrail metrics.
    Useful for testing or periodic metric resets.
    """
    guardrail_service.reset_metrics()
    return {"status": "metrics reset successfully"}