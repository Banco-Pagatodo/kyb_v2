# api/middleware/logging_middleware.py
"""
Middleware de logging estructurado para produccion.
"""

import os
import sys
import json
import time
import logging
import uuid
from datetime import datetime
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env")

# Configuracion
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # json | text
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


class JSONFormatter(logging.Formatter):
    """Formatter que produce logs en formato JSON."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": ENVIRONMENT,
        }
        
        # Agregar campos extra si existen
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "method"):
            log_data["method"] = record.method
        if hasattr(record, "path"):
            log_data["path"] = record.path
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "client_ip"):
            log_data["client_ip"] = record.client_ip
        
        # Agregar exception info si existe
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Formatter que produce logs en formato texto legible."""
    
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:8} {record.name}: {record.getMessage()}"
        
        # Agregar request info si existe
        extras = []
        if hasattr(record, "request_id"):
            extras.append(f"req={record.request_id[:8]}")
        if hasattr(record, "method"):
            extras.append(f"{record.method}")
        if hasattr(record, "path"):
            extras.append(f"{record.path}")
        if hasattr(record, "status_code"):
            extras.append(f"status={record.status_code}")
        if hasattr(record, "duration_ms"):
            extras.append(f"{record.duration_ms}ms")
        
        if extras:
            base += f" | {' '.join(extras)}"
        
        return base


def setup_logging() -> logging.Logger:
    """
    Configura el sistema de logging para la aplicacion.
    
    Returns:
        Logger raiz configurado
    """
    # Obtener logger raiz
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    # Limpiar handlers existentes
    root_logger.handlers.clear()
    
    # Crear handler para stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    # Seleccionar formatter segun configuracion
    if LOG_FORMAT == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()
    
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    # Reducir verbosidad de librerias externas
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return root_logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware que registra todas las requests HTTP."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generar ID unico para la request
        request_id = str(uuid.uuid4())
        
        # Obtener IP del cliente
        client_ip = request.headers.get("X-Forwarded-For", "")
        if not client_ip and request.client:
            client_ip = request.client.host
        
        # Registrar inicio de request
        start_time = time.time()
        logger = logging.getLogger("kyb.api")
        
        # Procesar request
        try:
            response = await call_next(request)
            
            # Calcular duracion
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # Log de la request
            log_record = logger.makeRecord(
                name="kyb.api",
                level=logging.INFO,
                fn="",
                lno=0,
                msg=f"{request.method} {request.url.path}",
                args=(),
                exc_info=None
            )
            log_record.request_id = request_id
            log_record.method = request.method
            log_record.path = request.url.path
            log_record.status_code = response.status_code
            log_record.duration_ms = duration_ms
            log_record.client_ip = client_ip
            
            # Ajustar nivel segun status code
            if response.status_code >= 500:
                log_record.levelno = logging.ERROR
                log_record.levelname = "ERROR"
            elif response.status_code >= 400:
                log_record.levelno = logging.WARNING
                log_record.levelname = "WARNING"
            
            logger.handle(log_record)
            
            # Agregar request ID al response
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            # Log de error
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.exception(
                f"Error processing request {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip
                }
            )
            raise
