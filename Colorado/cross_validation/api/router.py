"""
API REST para el agente de validación cruzada.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from typing import Annotated

from ..services.engine import validar_empresa, validar_todas
from ..services.data_loader import listar_empresas
from ..services.report_generator import generar_reporte_texto, generar_resumen_global_texto
from ..services.persistence import (
    obtener_validacion,
    obtener_ultima_validacion,
    listar_validaciones,
    contar_validaciones,
)
from ..models.schemas import ReporteValidacion, ResumenGlobal, ValidacionCruzadaDB

router = APIRouter(prefix="/api/v1/validacion", tags=["Validación Cruzada KYB"])


@router.get("/empresas")
async def list_empresas():
    """Lista todas las empresas con sus documentos disponibles."""
    return await listar_empresas()


@router.post("/empresa/{empresa_id}", response_model=ReporteValidacion)
async def validar_empresa_endpoint(
    empresa_id: str,
    portales: bool = Query(True, description="Ejecutar validación en portales gubernamentales"),
):
    """
    Ejecuta validación cruzada completa para una empresa.
    Devuelve JSON estructurado con hallazgos y dictamen.
    """
    try:
        reporte = await validar_empresa(empresa_id, portales=portales)
        return reporte
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al validar: {str(e)}")


@router.post("/empresa/{empresa_id}/reporte", response_class=PlainTextResponse)
async def reporte_empresa_texto(
    empresa_id: str,
    portales: bool = Query(True, description="Ejecutar validación en portales gubernamentales"),
):
    """
    Ejecuta validación cruzada y devuelve el reporte en texto formateado.
    """
    try:
        reporte = await validar_empresa(empresa_id, portales=portales)
        texto = generar_reporte_texto(reporte)
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al validar: {str(e)}")


@router.post("/todas", response_model=ResumenGlobal)
async def validar_todas_endpoint():
    """
    Ejecuta validación cruzada para TODAS las empresas.
    Devuelve JSON con resumen global y reportes individuales.
    """
    try:
        return await validar_todas()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/todas/reporte", response_class=PlainTextResponse)
async def reporte_todas_texto():
    """
    Ejecuta validación cruzada de todas las empresas y devuelve reporte en texto.
    """
    try:
        resumen = await validar_todas()
        texto = generar_resumen_global_texto(resumen)
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/health")
async def health():
    """Health check del servicio."""
    return {"status": "ok", "service": "cross-validation-agent", "version": "1.0.0"}


# ═════════════════════════════════════════════════════════════════
#  CONSULTA DE VALIDACIONES PERSISTIDAS
# ═════════════════════════════════════════════════════════════════


@router.get("/historial", response_model=list[ValidacionCruzadaDB])
async def historial_validaciones(
    empresa_id: str | None = Query(None, description="Filtrar por UUID de empresa"),
    rfc: str | None = Query(None, description="Filtrar por RFC"),
    dictamen: str | None = Query(None, description="Filtrar por dictamen: APROBADO, APROBADO_CON_OBSERVACIONES, RECHAZADO"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Lista el historial de validaciones cruzadas persistidas.
    Soporta filtros por empresa_id, RFC y dictamen.
    """
    total = await contar_validaciones(empresa_id=empresa_id, rfc=rfc, dictamen=dictamen)
    registros = await listar_validaciones(
        empresa_id=empresa_id, rfc=rfc, dictamen=dictamen,
        limit=limit, offset=offset,
    )
    return registros


@router.get("/historial/{validacion_id}", response_model=ValidacionCruzadaDB)
async def detalle_validacion(validacion_id: str):
    """Obtiene el detalle completo de una validación cruzada por su UUID."""
    registro = await obtener_validacion(validacion_id)
    if not registro:
        raise HTTPException(status_code=404, detail="Validación no encontrada")
    return registro


@router.get("/empresa/{empresa_id}/ultima", response_model=ValidacionCruzadaDB)
async def ultima_validacion_empresa(empresa_id: str):
    """
    Obtiene la validación cruzada más reciente de una empresa.
    Útil para consultar el último dictamen sin re-ejecutar.
    """
    registro = await obtener_ultima_validacion(empresa_id)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail=f"No hay validaciones previas para empresa {empresa_id}",
        )
    return registro
