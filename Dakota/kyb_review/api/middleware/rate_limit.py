# api/middleware/rate_limit.py
"""
Middleware de rate limiting para proteger la API.
"""

import os
import time
from typing import Dict, Tuple
from collections import defaultdict
from fastapi import HTTPException, Request, status
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env")

# Configuracion
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", "60"))  # segundos
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


def get_rate_limit_config() -> Dict[str, int]:
    """Obtiene la configuracion de rate limiting."""
    return {
        "requests": RATE_LIMIT_REQUESTS,
        "period_seconds": RATE_LIMIT_PERIOD
    }


class RateLimiter:
    """
    Rate limiter en memoria usando sliding window.
    
    Para produccion con multiples instancias, usar Redis.
    """
    
    def __init__(self, requests: int = 100, period: int = 60):
        """
        Args:
            requests: Numero maximo de requests permitidos
            period: Periodo de tiempo en segundos
        """
        self.requests = requests
        self.period = period
        self.clients: Dict[str, list] = defaultdict(list)
    
    def _get_client_id(self, request: Request) -> str:
        """Obtiene identificador del cliente (IP o API key)."""
        # Usar X-Forwarded-For si hay proxy
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        # Usar API key si esta presente
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"key:{api_key[:8]}..."
        
        # Fallback a IP del cliente
        return request.client.host if request.client else "unknown"
    
    def _cleanup_old_requests(self, client_id: str, now: float) -> None:
        """Elimina requests fuera de la ventana de tiempo."""
        cutoff = now - self.period
        self.clients[client_id] = [
            ts for ts in self.clients[client_id] if ts > cutoff
        ]
    
    def is_allowed(self, request: Request) -> Tuple[bool, Dict[str, int]]:
        """
        Verifica si el request esta permitido.
        
        Returns:
            Tuple[bool, Dict]: (permitido, info de rate limit)
        """
        now = time.time()
        client_id = self._get_client_id(request)
        
        # Limpiar requests antiguos
        self._cleanup_old_requests(client_id, now)
        
        # Contar requests actuales
        current_requests = len(self.clients[client_id])
        remaining = max(0, self.requests - current_requests)
        
        info = {
            "limit": self.requests,
            "remaining": remaining,
            "reset": int(now + self.period)
        }
        
        if current_requests >= self.requests:
            return False, info
        
        # Registrar request
        self.clients[client_id].append(now)
        info["remaining"] = remaining - 1
        
        return True, info
    
    def check(self, request: Request) -> Dict[str, int]:
        """
        Verifica rate limit y lanza excepcion si excedido.
        
        Returns:
            Dict con info de rate limit para headers
            
        Raises:
            HTTPException: Si se excede el limite
        """
        allowed, info = self.is_allowed(request)
        
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit excedido. Maximo {self.requests} requests por {self.period} segundos.",
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset"]),
                    "Retry-After": str(self.period)
                }
            )
        
        return info


# Instancia global del rate limiter
rate_limiter = RateLimiter(
    requests=RATE_LIMIT_REQUESTS,
    period=RATE_LIMIT_PERIOD
)


async def rate_limit_middleware(request: Request, call_next):
    """
    Middleware de rate limiting.
    
    En desarrollo, el rate limiting esta desactivado.
    """
    # Desactivar en desarrollo
    if ENVIRONMENT != "production":
        response = await call_next(request)
        return response
    
    # Excluir health check del rate limiting
    if "/health" in request.url.path:
        response = await call_next(request)
        return response
    
    # Verificar rate limit
    info = rate_limiter.check(request)
    
    # Procesar request
    response = await call_next(request)
    
    # Agregar headers de rate limit
    response.headers["X-RateLimit-Limit"] = str(info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(info["reset"])
    
    return response
