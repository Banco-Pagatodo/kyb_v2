"""
Cliente HTTP para el agente Colorado (Validación Cruzada).

Dakota llama a Colorado automáticamente después de persistir un documento.
Colorado corre en http://localhost:8001 y expone:
  POST /api/v1/validacion/empresa/{empresa_id}  → ejecuta validación cruzada

Este módulo proporciona:
  - trigger_validacion_cruzada(): fire-and-forget en background
  - validar_empresa_sync(): espera el resultado (para uso directo)
"""

import logging
import os

import httpx

logger = logging.getLogger("kyb.client.colorado")

# URL base configurable vía variable de entorno
COLORADO_BASE_URL = os.getenv("COLORADO_BASE_URL", "http://localhost:8011")
COLORADO_TIMEOUT = float(os.getenv("COLORADO_TIMEOUT", "300"))  # 5 min default (portales son lentos)


async def trigger_validacion_cruzada(empresa_id: str) -> dict | None:
    """
    Dispara la validación cruzada de Colorado para una empresa.

    Hace POST a Colorado, espera el resultado y lo devuelve.
    Si Colorado no está disponible o falla, logea y retorna None.
    No lanza excepciones: diseñado para ser seguro en background tasks.

    Args:
        empresa_id: UUID de la empresa en la tabla `empresas`.

    Returns:
        dict con el reporte de validación, o None si falló.
    """
    url = f"{COLORADO_BASE_URL}/api/v1/validacion/empresa/{empresa_id}"
    logger.info("Disparando validación cruzada → %s", url)

    try:
        async with httpx.AsyncClient(timeout=COLORADO_TIMEOUT) as client:
            response = await client.post(url)

        if response.status_code == 200:
            data = response.json()
            dictamen = data.get("dictamen", "?")
            rfc = data.get("rfc", "?")
            logger.info(
                "Validación cruzada completada: %s → %s (empresa=%s)",
                rfc, dictamen, empresa_id,
            )
            return data
        else:
            logger.warning(
                "Colorado respondió HTTP %d para empresa %s: %s",
                response.status_code, empresa_id, response.text[:200],
            )
            return None

    except httpx.ConnectError:
        logger.warning(
            "Colorado no disponible (%s). ¿Está corriendo el servidor? "
            "Iniciar con: python -m cross_validation server",
            COLORADO_BASE_URL,
        )
        return None

    except httpx.TimeoutException:
        logger.warning(
            "Timeout esperando a Colorado (%.0fs) para empresa %s",
            COLORADO_TIMEOUT, empresa_id,
        )
        return None

    except Exception as e:
        logger.warning(
            "Error inesperado al contactar Colorado para empresa %s: %s",
            empresa_id, e,
        )
        return None


async def health_check() -> bool:
    """Verifica si Colorado está activo."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{COLORADO_BASE_URL}/api/v1/validacion/health")
            return r.status_code == 200
    except Exception:
        return False
