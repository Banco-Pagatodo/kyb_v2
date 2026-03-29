# api/router.py
# Describe the API routes and their handlers.
# Calls to: controller.py

import os
import httpx
from datetime import datetime
from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv

from ..config import prefix
from ..middleware.auth import require_api_key

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint - informacion basica de la API."""
    return {
        "service": "KYB API",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
        "docs": "/docs"
    }


@router.get(prefix + "/health")
async def health_check():
    """
    Health check endpoint para Kubernetes/Docker.
    No requiere autenticacion.
    
    Returns:
        JSON con estado del servicio
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "kyb-api",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "environment": ENVIRONMENT
        },
        status_code=200
    )


@router.get(prefix + "/health/ready")
async def readiness_check():
    """
    Readiness check - verifica que el servicio puede procesar requests.
    Usado por Kubernetes para determinar si enviar trafico.
    Incluye verificación de conectividad a Azure Document Intelligence.
    """
    checks: dict[str, str] = {"api": "ok"}
    overall_status = "ready"

    # Verificar conectividad a Azure Document Intelligence
    di_endpoint = os.getenv("DI_ENDPOINT", "")
    di_key = os.getenv("DI_KEY", "")

    if di_endpoint and di_key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{di_endpoint.rstrip('/')}/documentintelligence/info",
                    headers={"Ocp-Apim-Subscription-Key": di_key},
                    params={"api-version": "2024-11-30"},
                )
                checks["azure_di"] = "ok" if resp.status_code < 400 else f"http_{resp.status_code}"
                if resp.status_code >= 400:
                    overall_status = "degraded"
        except httpx.TimeoutException:
            checks["azure_di"] = "timeout"
            overall_status = "degraded"
        except Exception:
            checks["azure_di"] = "unreachable"
            overall_status = "degraded"
    else:
        checks["azure_di"] = "not_configured"

    status_code = 200 if overall_status == "ready" else 503
    return JSONResponse(
        content={
            "status": overall_status,
            "checks": checks,
        },
        status_code=status_code,
    )


@router.get(prefix + "/health/live")
async def liveness_check():
    """
    Liveness check - verifica que el proceso esta vivo.
    Usado por Kubernetes para reiniciar pods muertos.
    """
    return PlainTextResponse("OK", status_code=200)


@router.get(prefix + "/info", dependencies=[Depends(require_api_key)])
async def api_info():
    """
    Informacion detallada de la API (requiere autenticacion).
    """
    return {
        "service": "KYB API",
        "version": "1.0.0",
        "description": "API para automatizacion de procesos Know-Your-Business",
        "environment": ENVIRONMENT,
        "endpoints": {
            "docs": "/kyb/api/v1.0.0/docs",
            "people": "/kyb/api/v1.0.0/persona_fisica",
            "files": "/kyb/api/v1.0.0/files"
        }
    }