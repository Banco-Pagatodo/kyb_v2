# api/server.py
# This file defines the startup configuration for the FastMCP server.
# Calls to: router.py
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from api.router import router as router_api
from api.router import docs as router_docs
from api.router import files as router_files
from api.router import people as router_people
from api.router import validator as router_validator
from api.router import empresas as router_empresas
from api.controller.files import cleanup_temp_files
from api.middleware.logging_middleware import LoggingMiddleware, setup_logging
from api.middleware.rate_limit import rate_limit_middleware
from api.middleware.guardrails import GuardrailMiddleware
from api.db.session import init_db, close_db

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env", override=True)

# Configuracion desde variables de entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
CLEANUP_ON_STARTUP = os.getenv("CLEANUP_ON_STARTUP", "true").lower() == "true"
CLEANUP_MAX_AGE_DAYS = int(os.getenv("CLEANUP_MAX_AGE_DAYS", "7"))

# Configurar logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager - ejecuta codigo al inicio y cierre del servidor."""
    # === STARTUP ===
    logger.info(f"Iniciando KYB API en modo {ENVIRONMENT}")
    
    if CLEANUP_ON_STARTUP:
        logger.info("Ejecutando limpieza automatica de archivos temporales...")
        stats = cleanup_temp_files(max_age_days=CLEANUP_MAX_AGE_DAYS)
        logger.info(f"Limpieza completada: {stats['deleted_files']} archivos eliminados, {stats['deleted_bytes']} bytes liberados")
        if stats['errors']:
            logger.warning(f"Errores durante limpieza: {len(stats['errors'])}")
    
    # Inicializar base de datos PostgreSQL
    try:
        await init_db()
        logger.info("PostgreSQL conectado correctamente")
    except Exception as e:
        logger.warning(f"No se pudo conectar a PostgreSQL: {e}. La API funcionará sin persistencia.")

    logger.info("KYB API iniciada correctamente")
    
    yield  # Aqui corre la aplicacion
    
    # === SHUTDOWN ===
    logger.info("Cerrando KYB API...")
    await close_db()


def create_server():
    """Crea y configura la instancia de FastAPI."""
    
    # Configuracion segun ambiente
    is_production = ENVIRONMENT == "production"
    
    server = FastAPI(
        title="KYB API",
        description="API para automatizacion de procesos Know-Your-Business",
        version="1.0.0",
        debug=not is_production,
        lifespan=lifespan,
        # Deshabilitar docs en produccion
        docs_url="/docs" if not is_production else None,
        redoc_url="/redoc" if not is_production else None,
    )
    
    # CORS - restrictivo en producción, abierto en desarrollo
    if is_production:
        allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
        if not allowed_origins_raw:
            logger.warning(
                "ALLOWED_ORIGINS no configurado en producción. "
                "CORS bloqueará todas las peticiones cross-origin."
            )
        allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]
    else:
        allowed_origins = ["*"]

    server.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=bool(allowed_origins and allowed_origins != ["*"]),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Middleware de logging (registra todas las requests)
    server.add_middleware(LoggingMiddleware)
    
    # Middleware de guardrails (validaciones tempranas)
    server.add_middleware(GuardrailMiddleware)
    
    # Rate limiting middleware (solo en produccion)
    if is_production:
        @server.middleware("http")
        async def rate_limit(request, call_next):
            return await rate_limit_middleware(request, call_next)
    
    # Incluir routers
    server.include_router(router_api.router)
    server.include_router(router_docs.router)
    server.include_router(router_files.router)
    server.include_router(router_people.router)
    server.include_router(router_validator.router)
    server.include_router(router_empresas.router)
    
    return server