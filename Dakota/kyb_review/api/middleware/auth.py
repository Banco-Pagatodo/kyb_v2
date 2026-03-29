# api/middleware/auth.py
"""
Middleware de autenticacion por API Key.
La validación se aplica en TODOS los entornos (desarrollo y producción).
"""

import hmac
import logging
import os
from typing import Optional
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

logger = logging.getLogger("kyb.auth")

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env")

# Configuracion
API_KEY = os.getenv("API_KEY", "")
API_KEY_NAME = "X-API-Key"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Validar que API_KEY esté configurada — obligatorio en TODOS los entornos
if not API_KEY:
    raise RuntimeError(
        "FATAL: API_KEY no configurada. "
        "Establece la variable de entorno API_KEY antes de iniciar el servicio."
    )

# Security schemes — solo header, nunca query param (evita exposición en logs/URL)
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def get_api_key() -> str:
    """Obtiene la API key configurada."""
    return API_KEY


def api_key_auth(
    api_key_header_value: Optional[str] = Security(api_key_header),
) -> str:
    """
    Valida la API key del request.
    
    La API key se envía exclusivamente por header:
    - Header: X-API-Key: <key>
    
    La autenticación es obligatoria en TODOS los entornos.
    
    Returns:
        str: La API key validada
        
    Raises:
        HTTPException: Si la API key es invalida o falta
    """
    # Obtener la key del header
    api_key = api_key_header_value
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key requerida. Enviar en header 'X-API-Key'",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Comparación en tiempo constante para evitar timing attacks
    if not hmac.compare_digest(api_key.encode(), API_KEY.encode()):
        logger.warning("Intento de acceso con API key inválida")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key invalida",
        )
    
    return api_key


# Dependency para usar en routers protegidos
def require_api_key(api_key: str = Security(api_key_auth)) -> str:
    """Dependency que requiere API key valida."""
    return api_key
