# api/service/resilience.py
"""
Módulo de resiliencia para servicios externos.
Implementa retry con backoff exponencial y circuit breaker.
"""

import time
import logging
import functools
from typing import Callable, Any, Optional, Type, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Estados del circuit breaker."""
    CLOSED = "closed"      # Normal - requests pasan
    OPEN = "open"          # Fallando - requests bloqueados
    HALF_OPEN = "half_open"  # Probando - algunos requests pasan


@dataclass
class CircuitBreakerConfig:
    """Configuración del circuit breaker."""
    failure_threshold: int = 5          # Fallos antes de abrir
    success_threshold: int = 2          # Éxitos para cerrar desde half-open
    timeout_seconds: float = 60.0       # Tiempo en OPEN antes de probar
    excluded_exceptions: Tuple[Type[Exception], ...] = ()  # Excepciones que no cuentan como fallo


@dataclass
class RetryConfig:
    """Configuración de retry."""
    max_attempts: int = 3
    base_delay: float = 1.0             # Delay base en segundos
    max_delay: float = 30.0             # Delay máximo
    exponential_base: float = 2.0       # Factor exponencial
    jitter: bool = True                 # Agregar variación aleatoria
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    retryable_status_codes: Tuple[int, ...] = (408, 429, 500, 502, 503, 504)


class CircuitBreaker:
    """
    Circuit Breaker para proteger llamadas a servicios externos.

    Estados:
    - CLOSED: Normal, requests pasan. Si hay muchos fallos consecutivos → OPEN
    - OPEN: Bloqueado, requests fallan inmediatamente. Después de timeout → HALF_OPEN
    - HALF_OPEN: Probando, algunos requests pasan. Si éxito → CLOSED, si fallo → OPEN
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Obtiene el estado actual, actualizando si es necesario."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Verificar si debemos pasar a HALF_OPEN
                if self._last_failure_time:
                    elapsed = datetime.now(tz=timezone.utc) - self._last_failure_time
                    if elapsed > timedelta(seconds=self.config.timeout_seconds):
                        self._state = CircuitState.HALF_OPEN
                        self._success_count = 0
                        logger.info(f"Circuit breaker '{self.name}' → HALF_OPEN (timeout elapsed)")
            return self._state

    def record_success(self):
        """Registra una llamada exitosa."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(f"Circuit breaker '{self.name}' → CLOSED (recovered)")
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0  # Reset en éxito

    def record_failure(self, exception: Exception):
        """Registra una llamada fallida."""
        # Verificar si la excepción está excluida
        if isinstance(exception, self.config.excluded_exceptions):
            return

        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now(tz=timezone.utc)

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit breaker '{self.name}' → OPEN (failed in half-open)")
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit breaker '{self.name}' → OPEN "
                        f"({self._failure_count} consecutive failures)"
                    )

    def can_execute(self) -> bool:
        """Verifica si se puede ejecutar una llamada."""
        state = self.state  # Esto actualiza el estado si es necesario
        return state != CircuitState.OPEN

    def get_status(self) -> dict:
        """Retorna el estado actual del circuit breaker."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None
        }


class CircuitBreakerOpen(Exception):
    """Excepción cuando el circuit breaker está abierto."""
    def __init__(self, circuit_name: str):
        self.circuit_name = circuit_name
        super().__init__(f"Circuit breaker '{circuit_name}' is OPEN - service unavailable")


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKERS GLOBALES
# ═══════════════════════════════════════════════════════════════════════════════

_circuit_breakers: dict[str, CircuitBreaker] = {}
_cb_lock = threading.Lock()


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """Obtiene o crea un circuit breaker por nombre."""
    with _cb_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(name, config)
        return _circuit_breakers[name]


def get_all_circuit_breakers_status() -> list[dict]:
    """Retorna el estado de todos los circuit breakers."""
    with _cb_lock:
        return [cb.get_status() for cb in _circuit_breakers.values()]


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY CON BACKOFF
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calcula el delay para un intento dado con backoff exponencial."""
    import random

    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    delay = min(delay, config.max_delay)

    if config.jitter:
        # Agregar jitter de ±25%
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)

    return max(0, delay)


def retry_with_backoff(
    func: Callable,
    config: Optional[RetryConfig] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    operation_name: str = "operation"
) -> Any:
    """
    Ejecuta una función con retry y backoff exponencial.

    Args:
        func: Función a ejecutar (sin argumentos - usar lambda o partial)
        config: Configuración de retry
        circuit_breaker: Circuit breaker opcional
        operation_name: Nombre para logging

    Returns:
        Resultado de la función

    Raises:
        La última excepción si todos los intentos fallan
        CircuitBreakerOpen si el circuit breaker está abierto
    """
    config = config or RetryConfig()
    last_exception: Optional[Exception] = None

    for attempt in range(1, config.max_attempts + 1):
        # Verificar circuit breaker
        if circuit_breaker and not circuit_breaker.can_execute():
            raise CircuitBreakerOpen(circuit_breaker.name)

        try:
            result = func()

            # Éxito - registrar en circuit breaker
            if circuit_breaker:
                circuit_breaker.record_success()

            if attempt > 1:
                logger.info(f"{operation_name} succeeded on attempt {attempt}")

            return result

        except Exception as e:
            last_exception = e

            # Verificar si es retryable
            is_retryable = isinstance(e, config.retryable_exceptions)

            # Para requests, verificar status code
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                is_retryable = e.response.status_code in config.retryable_status_codes

            if not is_retryable or attempt == config.max_attempts:
                # Registrar fallo en circuit breaker
                if circuit_breaker:
                    circuit_breaker.record_failure(e)

                logger.error(
                    f"{operation_name} failed after {attempt} attempts: {type(e).__name__}: {e}"
                )
                raise

            # Calcular delay y esperar
            delay = calculate_delay(attempt, config)
            logger.warning(
                f"{operation_name} attempt {attempt}/{config.max_attempts} failed: "
                f"{type(e).__name__}: {e}. Retrying in {delay:.2f}s..."
            )
            time.sleep(delay)

    # No debería llegar aquí, pero por si acaso
    if last_exception:
        raise last_exception


# ═══════════════════════════════════════════════════════════════════════════════
# DECORADORES
# ═══════════════════════════════════════════════════════════════════════════════

def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorador para agregar retry con backoff a una función.

    Example:
        @with_retry(max_attempts=3, base_delay=2.0)
        def call_external_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                retryable_exceptions=retryable_exceptions
            )
            return retry_with_backoff(
                lambda: func(*args, **kwargs),
                config=config,
                operation_name=func.__name__
            )
        return wrapper
    return decorator


def with_circuit_breaker(
    circuit_name: str,
    failure_threshold: int = 5,
    timeout_seconds: float = 60.0
):
    """
    Decorador para agregar circuit breaker a una función.

    Example:
        @with_circuit_breaker("azure_di", failure_threshold=3)
        def call_azure():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cb_config = CircuitBreakerConfig(
                failure_threshold=failure_threshold,
                timeout_seconds=timeout_seconds
            )
            cb = get_circuit_breaker(circuit_name, cb_config)

            if not cb.can_execute():
                raise CircuitBreakerOpen(circuit_name)

            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure(e)
                raise

        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES PARA OPENAI
# ═══════════════════════════════════════════════════════════════════════════════

class OpenAIRetryConfig(RetryConfig):
    """Configuración específica para OpenAI."""
    def __init__(self):
        super().__init__(
            max_attempts=3,
            base_delay=2.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(Exception,),  # OpenAI puede lanzar varios tipos
            retryable_status_codes=(429, 500, 502, 503, 504)
        )


class AzureDIRetryConfig(RetryConfig):
    """Configuración específica para Azure Document Intelligence."""
    def __init__(self):
        super().__init__(
            max_attempts=3,
            base_delay=3.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(Exception,),
            retryable_status_codes=(408, 429, 500, 502, 503, 504)
        )


def parse_json_safe(text: str, fallback: dict = None) -> dict:
    """
    Parsea JSON de forma segura, manejando casos comunes de error.

    Args:
        text: Texto que debería ser JSON
        fallback: Valor por defecto si falla el parsing

    Returns:
        Dict parseado o fallback
    """
    import json
    import re

    if fallback is None:
        fallback = {}

    if not text or not text.strip():
        logger.warning("Empty text provided for JSON parsing")
        return fallback

    # Intentar parseo directo
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Limpiar y reintentar
    cleaned = text.strip()

    # Remover markdown code blocks
    if cleaned.startswith("```"):
        # Buscar el contenido entre ```json y ```
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
        if match:
            cleaned = match.group(1).strip()

    # Intentar extraer objeto JSON
    json_match = re.search(r'\{[\s\S]*\}', cleaned)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Intentar reparar JSON común
    try:
        # Reemplazar comillas simples por dobles
        fixed = cleaned.replace("'", '"')
        # Remover trailing commas
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    logger.error(f"Failed to parse JSON: {text[:200]}...")
    return fallback
