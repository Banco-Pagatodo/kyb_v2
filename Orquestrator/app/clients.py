"""
Clientes HTTP para los agentes Colorado, Arizona, Nevada y PagaTodo Hub.

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
    PAGATODO_HUB_BASE_URL,
    PAGATODO_HUB_API_KEY,
    PAGATODO_HUB_TIMEOUT,
    PAGATODO_DOCTYPE_MAP,
)

logger = logging.getLogger("orquestrator.clients")

# ── Timeout constants ──────────────────────────────────────────────────
HEALTH_CHECK_TIMEOUT = 10
QUERY_TIMEOUT = 15


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
        # Circuito abierto — verificar ventana de recuperación
        if time.monotonic() - self._opened_at >= self.recovery_secs:
            # Half-open: dar otra oportunidad
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
    Incluye retry con exponential backoff y circuit breaker (cb de Arizona).
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


# ═══════════════════════════════════════════════════════════════════════════
#  PagaTodo Hub — API externa de prospectos y OCR
# ═══════════════════════════════════════════════════════════════════════════

_cb_pagatodo = CircuitBreaker("pagatodo_hub", CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RECOVERY)


def _pagatodo_headers() -> dict[str, str]:
    """Headers de autenticación para PagaTodo Hub."""
    return {"bpt-apikey": PAGATODO_HUB_API_KEY}


async def pagatodo_prospect_data(prospect_id: str) -> dict[str, Any] | None:
    """
    Obtiene la información del prospecto desde PagaTodo Hub.

    GET /prospects/data/{prospect_id}
    """
    if _cb_pagatodo.is_open:
        logger.warning("[PAGATODO] Circuit breaker abierto — omitiendo request")
        return None

    url = f"{PAGATODO_HUB_BASE_URL}/prospects/data/{prospect_id}"
    logger.info("[PAGATODO] GET %s", url)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=PAGATODO_HUB_TIMEOUT) as client:
                return await client.get(url, headers=_pagatodo_headers())

        response = await _call()

        if response.status_code == 200:
            _cb_pagatodo.record_success()
            return response.json()
        else:
            _cb_pagatodo.record_failure()
            logger.warning(
                "[PAGATODO] HTTP %d para prospect %s: %s",
                response.status_code, prospect_id, response.text[:300],
            )
            return None

    except _RETRYABLE as exc:
        _cb_pagatodo.record_failure()
        logger.warning("[PAGATODO] Falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None
    except Exception as e:
        _cb_pagatodo.record_failure()
        logger.warning("[PAGATODO] Error inesperado: %s", e)
        return None


async def pagatodo_ocr_result(
    prospect_id: str,
    document_type: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Obtiene el resultado OCR de un documento desde PagaTodo Hub.

    POST /ocr
    Body: {"CustomerId": prospect_id, "DocumentType": document_type}

    Args:
        prospect_id: UUID del prospecto en PagaTodo (CustomerId).
        document_type: Tipo de documento externo (e.g. "RL_FrenteIne", "ActaCons").

    Returns:
        Tupla (datos_ocr, doc_type_interno).
        doc_type_interno es el nombre mapeado a nuestro sistema (e.g. "ine", "acta_constitutiva").
        Si el document_type externo no se reconoce, retorna (None, None).
    """
    doc_type_interno = PAGATODO_DOCTYPE_MAP.get(document_type)
    if not doc_type_interno:
        logger.warning(
            "[PAGATODO] DocumentType no reconocido: '%s'. Valores válidos: %s",
            document_type, ", ".join(PAGATODO_DOCTYPE_MAP.keys()),
        )
        return None, None

    if _cb_pagatodo.is_open:
        logger.warning("[PAGATODO] Circuit breaker abierto — omitiendo request")
        return None, doc_type_interno

    url = f"{PAGATODO_HUB_BASE_URL}/ocr"
    logger.info("[PAGATODO] POST %s (CustomerId=%s, DocumentType=%s) → interno: %s",
                url, prospect_id, document_type, doc_type_interno)

    try:
        @_retry_decorator()
        async def _call():
            async with httpx.AsyncClient(timeout=PAGATODO_HUB_TIMEOUT) as client:
                return await client.post(
                    url,
                    json={"CustomerId": prospect_id, "DocumentType": document_type},
                    headers=_pagatodo_headers(),
                )

        response = await _call()

        if response.status_code == 200:
            _cb_pagatodo.record_success()
            return response.json(), doc_type_interno

        # 204 No Content → documento no existe en PagaTodo (legítimo, no es fallo)
        if response.status_code == 204:
            _cb_pagatodo.record_success()
            logger.info(
                "[PAGATODO] 204 No Content para OCR %s/%s — documento no disponible",
                prospect_id, document_type,
            )
            return None, doc_type_interno

        # Cualquier otro código sí es un error real
        _cb_pagatodo.record_failure()
        logger.warning(
            "[PAGATODO] HTTP %d para OCR %s/%s: %s",
            response.status_code, prospect_id, document_type, response.text[:300],
        )
        return None, doc_type_interno

    except _RETRYABLE as exc:
        _cb_pagatodo.record_failure()
        logger.warning("[PAGATODO] OCR falló tras %d reintentos: %s", RETRY_MAX_ATTEMPTS, exc)
        return None, doc_type_interno
    except Exception as e:
        _cb_pagatodo.record_failure()
        logger.warning("[PAGATODO] OCR error inesperado: %s", e)
        return None, doc_type_interno


# ═══════════════════════════════════════════════════════════════════════════
#  Transformación: /prospects/data/ → formato interno
# ═══════════════════════════════════════════════════════════════════════════


def transformar_datos_prospecto(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normaliza la respuesta de PagaTodo ``/prospects/data/`` al formato
    interno que usa Dakota y los agentes downstream.

    Convierte los nombres camelCase de PagaTodo a snake_case y agrupa
    los datos en la estructura que los agentes esperan:
    ``persona_moral``, ``domicilio_fiscal``, ``acta_constitutiva``,
    ``representante_legal``, ``perfil_transaccional``, ``usuario_banca``,
    ``declaraciones_regulatorias``.

    Retorna un dict listo para enviar a Dakota vía ``/datos-prospecto/import``.
    """
    pm = raw.get("personaMoral") or {}
    dom = raw.get("domicilioFiscal") or {}
    acta = raw.get("actaConstitutiva") or {}
    rl = raw.get("representanteLegal") or {}
    rl_dom = rl.get("domicilio") or {}
    perfil = raw.get("perfilTransaccional") or {}
    ubi = raw.get("usuarioBancaInternet") or {}
    decl = raw.get("declaracionesRegulatorias")

    return {
        "persona_moral": {
            "razon_social": pm.get("razonSocial", ""),
            "rfc": pm.get("rfc", ""),
            "nacionalidad": pm.get("nacionalidad", ""),
            "nombre_comercial": pm.get("nombreComercial", ""),
            "giro_mercantil": pm.get("giroMercantil", ""),
            "numero_empleados": pm.get("numeroEmpleados"),
            "pagina_web": pm.get("paginaWeb", ""),
            "serie_fea": pm.get("serieFEA", ""),
            "telefono": pm.get("telefono", ""),
            "correo": pm.get("correo", ""),
        },
        "domicilio_fiscal": {
            "calle": dom.get("calle", ""),
            "numero_exterior": dom.get("noExterior", ""),
            "numero_interior": dom.get("noInterior", ""),
            "codigo_postal": dom.get("cp", ""),
            "colonia": dom.get("colonia", ""),
            "municipio": dom.get("municipio", ""),
            "ciudad": dom.get("ciudad", ""),
            "estado": dom.get("estado", ""),
        },
        "acta_constitutiva": {
            "instrumento_publico": acta.get("instrumentoPublico", ""),
            "fecha_expedicion": acta.get("fechaExpedicion", ""),
            "fecha_constitucion": acta.get("fechaConstitucion", ""),
            "entidad_notaria": acta.get("entidadNotaria", ""),
            "numero_notaria": acta.get("numeroNotaria", ""),
            "folio_mercantil": acta.get("folioMercantil", ""),
            "nombre_notario": acta.get("nombreNotario", ""),
        },
        "representante_legal": {
            "nombres": rl.get("nombres", ""),
            "primer_apellido": rl.get("primerApellido", ""),
            "segundo_apellido": rl.get("segundoApellido", ""),
            "nombre_completo": " ".join(
                p for p in [
                    rl.get("nombres", ""),
                    rl.get("primerApellido", ""),
                    rl.get("segundoApellido", ""),
                ] if p
            ),
            "fecha_nacimiento": rl.get("fechaNacimiento", ""),
            "entidad_nacimiento": rl.get("entidadNacimiento", ""),
            "genero": rl.get("genero", ""),
            "rfc": rl.get("rfc", ""),
            "correo": rl.get("correo", ""),
            "telefono": rl.get("telefono", ""),
            "facultades": rl.get("facultades", ""),
            "ocupacion": rl.get("ocupacion", ""),
            "pais_nacimiento": rl.get("paisNacimiento", ""),
            "nacionalidad": rl.get("nacionalidad", ""),
            "domicilio": {
                "calle": rl_dom.get("calle", ""),
                "numero_exterior": rl_dom.get("noExterior", ""),
                "numero_interior": rl_dom.get("noInterior", ""),
                "codigo_postal": rl_dom.get("cp", ""),
                "colonia": rl_dom.get("colonia", ""),
                "municipio": rl_dom.get("municipio", ""),
                "ciudad": rl_dom.get("ciudad", ""),
                "estado": rl_dom.get("estado", ""),
                "pais": rl_dom.get("pais", ""),
            },
        },
        "perfil_transaccional": {
            "entradas": perfil.get("entradas", []),
            "salidas": perfil.get("salidas", []),
        },
        "usuario_banca": {
            "nombres": ubi.get("nombres", ""),
            "primer_apellido": ubi.get("primerApellido", ""),
            "segundo_apellido": ubi.get("segundoApellido", ""),
            "telefono": ubi.get("telefono", ""),
            "correo": ubi.get("correo", ""),
        },
        "declaraciones_regulatorias": decl,
    }
