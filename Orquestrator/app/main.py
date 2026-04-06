"""
Orquestrator — FastAPI Application.

Punto de entrada del servidor. Ejecutar con:
    uvicorn app.main:app --port 8002
"""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import close_pool
from .router import router

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orquestrator")


# ── Lifecycle ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown: gestión del pool asyncpg."""
    logger.info("Orquestrator iniciando — pool PostgreSQL se creará en primer uso")
    yield
    logger.info("Orquestrator cerrando — liberando pool PostgreSQL")
    await close_pool()


# ── FastAPI App ──────────────────────────────────────────────────────────
app = FastAPI(
    title="Orquestrator Dakota — Agente Orquestador KYB",
    description=(
        "Coordina los agentes Dakota (OCR/persistencia), Colorado (validación cruzada), "
        "Arizona (PLD/AML + dictamen PLD/FT) y Nevada (dictamen jurídico) en un flujo "
        "automatizado end-to-end. Recibe archivos PDF/imagen + RFC y orquesta todo el "
        "pipeline KYB enviando documentos a Dakota para extracción y persistencia."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — whitelist explícito (env CORS_ORIGINS para extender en producción)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Incluir router
app.include_router(router)


@app.get("/")
async def root():
    """Info básica del servicio."""
    return {
        "service": "Orquestrator Dakota — Agente Orquestador KYB",
        "version": "2.0.0",
        "flujo": "Archivos → Dakota (OCR + persistencia) → Colorado → Arizona → Nevada",
        "docs": "/docs",
        "endpoints": {
            "process": "POST /api/v1/pipeline/process (archivo + doc_type + rfc)",
            "expediente": "POST /api/v1/pipeline/expediente (archivos + doc_types + rfc)",
            "status": "GET /api/v1/pipeline/status/{rfc}",
            "health": "GET /api/v1/pipeline/health",
        },
    }
