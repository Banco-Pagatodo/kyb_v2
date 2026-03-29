"""
Middleware de Guardrails para FastAPI.

Aplica validaciones de guardrail de forma transparente a los endpoints.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class GuardrailMiddleware(BaseHTTPMiddleware):
    """
    Middleware que registra las validaciones de guardrail.
    
    Este middleware no bloquea las requests, solo registra
    cuando los guardrails rechazan archivos.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.routes_with_guardrails = [
            "/docs/",
            "/persona_fisica/"
        ]
    
    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """
        Procesa la request y registra validaciones de guardrail.
        
        Args:
            request: Request de FastAPI
            call_next: Siguiente handler en la cadena
            
        Returns:
            Response del endpoint
        """
        path = request.url.path
        
        # Solo registrar en rutas con guardrails
        is_guardrail_route = any(path.startswith(route) for route in self.routes_with_guardrails)
        
        if is_guardrail_route:
            logger.info(f"Guardrail check on {path}")
        
        # Continuar con el request normal
        response = await call_next(request)
        
        # Registrar rechazos (status 400, 413, 415, 422)
        if is_guardrail_route and response.status_code in [400, 413, 415, 422]:
            logger.warning(f"Guardrail rejection on {path}: {response.status_code}")
        
        return response
