"""
Clientes HTTP para Dakota, Colorado, Arizona y Nevada.

Flujo Dakota: envía archivos directamente a Dakota para OCR + persistencia.

Todas las funciones son async y manejan errores de forma segura:
- Si un agente no responde → retorna None + log warning
- Nunca lanzan excepciones al caller
- Retry con exponential backoff (3 reintentos por defecto)
- Circuit breaker por agente (corte tras N fallos consecutivos)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from .config import (
    DAKOTA_BASE_URL,
    DAKOTA_TIMEOUT,
    DAKOTA_API_PREFIX,
    DAKOTA_API_KEY,
    COLORADO_BASE_URL,
    COLORADO_TIMEOUT,
    COLORADO_API_PREFIX,
    ARIZONA_BASE_URL,
    ARIZONA_TIMEOUT,
    ARIZONA_API_PREFIX,
    COMPLIANCE_API_PREFIX,
    NEVADA_BASE_URL,
    NEVADA_TIMEOUT,
    NEVADA_API_PREFIX,
    RETRY_MAX_ATTEMPTS,
    RETRY_WAIT_MIN,
    RETRY_WAIT_MAX,
    CIRCUIT_BREAKER_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY,
)

logger = logging.getLogger("orquestrator.clients")

# ── Timeout constants ──────────────────────────────────────────────────
HEALTH_CHECK_TIMEOUT = 10
QUERY_TIMEOUT = 15


def _dakota_headers() -> dict[str, str]:
    """Headers de autenticación para Dakota."""
    h: dict[str, str] = {}
    if DAKOTA_API_KEY:
        h["X-API-Key"] = DAKOTA_API_KEY
    return h


# ═══════════════════════════════════════════════════════════════════════════════
#  Circuit Breaker — por agente
# ═══════════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Circuit breaker sencillo por agente.

    Después de *threshold* fallos consecutivos, se abre el circuito durante
    *recovery_secs* segundos y rechaza llamadas inmediatamente.
    """

    def __init__(self, name: str, threshold: int, recovery_secs: float):
        self.name = name
        self.threshold = threshold
        self.recovery_secs = recovery_secs
        self._fail_count = 0
        self._opened_at: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._fail_count < self.threshold:
            return False
        if time.monotonic() - self._opened_at >= self.recovery_secs:
            return False
        return True

    def record_success(self) -> None:
        self._fail_count = 0

    def record_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= self.threshold:
            self._opened_at = time.monotonic()
            logger.warning(
                "[CB] Circuit breaker ABIERTO para %s tras %d fallos consecutivos (recovery=%ds)",
                self.name, self._fail_count, int(self.recovery_secs),
            )


class CircuitBreakerOpen(Exception):
    """Excepción cuando el circuit breaker está abierto."""
    pass


# Instancias por agente
_cb_dakota = CircuitBreaker("DAKOTA", CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RECOVERY)
_cb_colorado = CircuitBreaker("COLORADO", CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RECOVERY)
_cb_arizona = CircuitBreaker("ARIZONA", CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RECOVERY)
_cb_nevada = CircuitBreaker("NEVADA", CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RECOVERY)


# ═══════════════════════════════════════════════════════════════════════════════
#  Retry helpers
# ═══════════════════════════════════════════════════════════════════════════════

_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)


def _retry_decorator():
    """Tenacity decorator para reintentos con exponential backoff."""
    return retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  DAKOTA — OCR + Persistencia de documentos
# ═══════════════════════════════════════════════════════════════════════════════

async def dakota_upload_document(
    doc_type: str,
    file_content: bytes,
    file_name: str,
    rfc: str,
    *,
    skip_colorado: bool = True,
) -> dict[str, Any] | None:
    """
    Envía un archivo a Dakota para OCR + persistencia.

    Dakota realiza:
    1. OCR del documento (Azure DI + OpenAI)
    2. Validación de campos
    3. Persistencia en PostgreSQL (si se proporciona rfc)

    Args:
        doc_type: Tipo de documento (csf, ine, acta_constitutiva, etc.)
        file_content: Contenido del archivo en bytes.
        file_name: Nombre del archivo original.
        rfc: RFC de la empresa (para persistencia).
        skip_colorado: Si True, Dakota NO dispara Colorado automáticamente.

    Returns:
        dict con datos_extraidos, validacion, etc. o None si error.
    """
    if _cb_dakota.is_open:
        logger.warning("[DAKOTA] Circuit breaker abierto — omitiendo request")
        return None

    url = (
        f"{DAKOTA_BASE_URL}{DAKOTA_API_PREFIX}/docs/{doc_type}"
        f"?rfc={rfc}&skip_colorado={str(skip_colorado).lower()}"
    )
    logger.info("[DAKOTA] POST %s (file=%s)", url, file_name)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=DAKOTA_TIMEOUT) as client:
                return await client.post(
                    url,
                    headers=_dakota_headers(),
                    files={"file": (file_name, file_content, "application/octet-stream")},
                )

        response = await _call()

        if response.status_code == 200:
            _cb_dakota.record_success()
            data = response.json()
            logger.info(
                "[DAKOTA] Documento procesado: %s → %s (archivo=%s)",
                doc_type, data.get("archivo_procesado", "?"), file_name,
            )
            return data
        else:
            _cb_dakota.record_failure()
            logger.warning(
                "[DAKOTA] HTTP %d para %s: %s",
                response.status_code, doc_type, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_dakota.record_failure()
        logger.warning("[DAKOTA] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_dakota.record_failure()
        logger.warning("[DAKOTA] Error inesperado: %s", e)
        return None


async def dakota_get_empresa(rfc: str) -> dict[str, Any] | None:
    """
    Obtiene información de una empresa por RFC desde Dakota.

    Returns:
        dict con id, rfc, razon_social, etc. o None si no existe.
    """
    url = f"{DAKOTA_BASE_URL}{DAKOTA_API_PREFIX}/empresas/{rfc}"
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            r = await client.get(url, headers=_dakota_headers())
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


async def dakota_health() -> bool:
    """Health check de Dakota."""
    url = f"{DAKOTA_BASE_URL}{DAKOTA_API_PREFIX}/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            r = await client.get(url, headers=_dakota_headers())
        return r.status_code == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  COLORADO — Validación cruzada
# ═══════════════════════════════════════════════════════════════════════════════

async def colorado_validate(empresa_id: str, *, portales: bool = False) -> dict[str, Any] | None:
    """
    Ejecuta validación cruzada en Colorado para una empresa.
    Incluye retry con exponential backoff y circuit breaker.
    """
    if _cb_colorado.is_open:
        logger.warning("[COLORADO] Circuit breaker abierto — omitiendo request")
        return None

    url = f"{COLORADO_BASE_URL}{COLORADO_API_PREFIX}/empresa/{empresa_id}?portales={str(portales).lower()}"
    logger.info("[COLORADO] POST %s", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=COLORADO_TIMEOUT) as client:
                return await client.post(url)

        response = await _call()

        if response.status_code == 200:
            _cb_colorado.record_success()
            data = response.json()
            logger.info(
                "[COLORADO] Validación completada: %s → %s (%d hallazgos)",
                data.get("rfc", "?"),
                data.get("dictamen", "?"),
                len(data.get("hallazgos", [])),
            )
            return data
        else:
            _cb_colorado.record_failure()
            logger.warning(
                "[COLORADO] HTTP %d para empresa %s: %s",
                response.status_code, empresa_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_colorado.record_failure()
        logger.warning("[COLORADO] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_colorado.record_failure()
        logger.warning("[COLORADO] Error inesperado: %s", e)
        return None


async def colorado_health() -> bool:
    """Health check de Colorado."""
    url = f"{COLORADO_BASE_URL}{COLORADO_API_PREFIX}/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            r = await client.get(url)
        return r.status_code == 200
    except Exception:
        return False


async def colorado_last_validation(empresa_id: str) -> dict[str, Any] | None:
    """Obtiene la última validación cruzada de una empresa (sin re-ejecutar)."""
    url = f"{COLORADO_BASE_URL}{COLORADO_API_PREFIX}/empresa/{empresa_id}/ultima"
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  ARIZONA — Análisis PLD/AML
# ═════════════════════════════════════════════════════════════════════════════

async def arizona_pld_analyze(empresa_id: str) -> dict[str, Any] | None:
    """
    Ejecuta análisis PLD Etapa 1 (completitud) en Arizona.
    Incluye retry con exponential backoff y circuit breaker.
    """
    if _cb_arizona.is_open:
        logger.warning("[ARIZONA] Circuit breaker abierto — omitiendo request")
        return None

    url = f"{ARIZONA_BASE_URL}{ARIZONA_API_PREFIX}/etapa1/{empresa_id}"
    logger.info("[ARIZONA] POST %s", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=ARIZONA_TIMEOUT) as client:
                return await client.post(url)

        response = await _call()

        if response.status_code == 200:
            _cb_arizona.record_success()
            data = response.json()
            logger.info(
                "[ARIZONA] Análisis PLD completado: %s → %s (%.1f%% completitud)",
                data.get("razon_social", "?"),
                data.get("resultado", "?"),
                data.get("porcentaje_completitud", 0),
            )
            return data
        else:
            _cb_arizona.record_failure()
            logger.warning(
                "[ARIZONA] HTTP %d para empresa %s: %s",
                response.status_code, empresa_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_arizona.record_failure()
        logger.warning("[ARIZONA] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_arizona.record_failure()
        logger.warning("[ARIZONA] Error inesperado: %s", e)
        return None


async def arizona_health() -> bool:
    """Health check de Arizona."""
    url = f"{ARIZONA_BASE_URL}{ARIZONA_API_PREFIX}/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            r = await client.get(url)
        return r.status_code == 200
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  COMPLIANCE — Dictamen PLD/FT (scoring + LLM + RAG) — servido desde Arizona
# ═════════════════════════════════════════════════════════════════════════════

async def compliance_dictamen(empresa_id: str) -> dict[str, Any] | None:
    """
    Solicita dictamen PLD/FT completo al módulo de compliance (Arizona).
    Incluye retry con exponential backoff y circuit breaker (usa cb de Arizona).
    """
    if _cb_arizona.is_open:
        logger.warning("[COMPLIANCE] Circuit breaker abierto — omitiendo request")
        return None

    url = f"{ARIZONA_BASE_URL}{COMPLIANCE_API_PREFIX}/dictamen/{empresa_id}"
    logger.info("[COMPLIANCE] POST %s", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=ARIZONA_TIMEOUT) as client:
                return await client.post(url)

        response = await _call()

        if response.status_code == 200:
            _cb_arizona.record_success()
            data = response.json()
            logger.info(
                "[COMPLIANCE] Dictamen completado: %s → %s (residual=%.2f %s)",
                data.get("razon_social", "?"),
                data.get("dictamen", "?"),
                data.get("score", {}).get("riesgo_residual", 0),
                data.get("score", {}).get("nivel_residual", "?"),
            )
            return data
        else:
            _cb_arizona.record_failure()
            logger.warning(
                "[COMPLIANCE] HTTP %d para empresa %s: %s",
                response.status_code, empresa_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_arizona.record_failure()
        logger.warning("[COMPLIANCE] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_arizona.record_failure()
        logger.warning("[COMPLIANCE] Error inesperado: %s", e)
        return None


async def compliance_score(empresa_id: str) -> dict[str, Any] | None:
    """
    Solicita solo el scoring PLD/FT (sin dictamen narrativo).
    """
    if _cb_arizona.is_open:
        logger.warning("[COMPLIANCE] Circuit breaker abierto — omitiendo score")
        return None

    url = f"{ARIZONA_BASE_URL}{COMPLIANCE_API_PREFIX}/score/{empresa_id}"
    logger.info("[COMPLIANCE] POST %s (score only)", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=ARIZONA_TIMEOUT) as client:
                return await client.post(url)

        response = await _call()

        if response.status_code == 200:
            _cb_arizona.record_success()
            data = response.json()
            logger.info(
                "[COMPLIANCE] Score: LD=%.2f, FT=%.2f → residual=%.2f (%s)",
                data.get("riesgo_inherente_ld", 0),
                data.get("riesgo_inherente_ft", 0),
                data.get("riesgo_residual", 0),
                data.get("nivel_residual", "?"),
            )
            return data
        else:
            _cb_arizona.record_failure()
            logger.warning(
                "[COMPLIANCE] HTTP %d score para empresa %s: %s",
                response.status_code, empresa_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_arizona.record_failure()
        logger.warning("[COMPLIANCE] Falló score tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_arizona.record_failure()
        logger.warning("[COMPLIANCE] Error inesperado: %s", e)
        return None


async def compliance_health() -> bool:
    """Health check del módulo Compliance (servido desde Arizona)."""
    url = f"{ARIZONA_BASE_URL}{COMPLIANCE_API_PREFIX}/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            r = await client.get(url)
        return r.status_code == 200
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  NEVADA — Dictamen Jurídico Legal
# ═════════════════════════════════════════════════════════════════════════════

async def nevada_dictamen_legal(empresa_id: str) -> dict[str, Any] | None:
    """
    Solicita dictamen jurídico completo al agente Nevada.
    Incluye retry con exponential backoff y circuit breaker.
    """
    if _cb_nevada.is_open:
        logger.warning("[NEVADA] Circuit breaker abierto — omitiendo request")
        return None

    url = f"{NEVADA_BASE_URL}{NEVADA_API_PREFIX}/dictamen/{empresa_id}"
    logger.info("[NEVADA] POST %s", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=NEVADA_TIMEOUT) as client:
                return await client.post(url)

        response = await _call()

        if response.status_code == 200:
            _cb_nevada.record_success()
            data = response.json()
            logger.info(
                "[NEVADA] Dictamen jurídico completado: %s → %s",
                data.get("razon_social", "?"),
                data.get("dictamen", "?"),
            )
            return data
        else:
            _cb_nevada.record_failure()
            logger.warning(
                "[NEVADA] HTTP %d para empresa %s: %s",
                response.status_code, empresa_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_nevada.record_failure()
        logger.warning("[NEVADA] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_nevada.record_failure()
        logger.warning("[NEVADA] Error inesperado: %s", e)
        return None


async def nevada_health() -> bool:
    """Health check del servicio Nevada."""
    url = f"{NEVADA_BASE_URL}{NEVADA_API_PREFIX}/health"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            r = await client.get(url)
        return r.status_code == 200
    except Exception:
        return False
