"""
Arizona — Agente PLD/AML + Oficial de Cumplimiento PLD/FT

Punto de entrada UNIFICADO que monta dos routers en una sola app FastAPI:
  • pld_agent     → /api/v1/pld          (completitud, screening, propietarios reales)
  • compliance    → /api/v1/compliance    (scoring MER v7.0 + dictamen LLM + RAG)

Puerto: 8012  (uno solo para ambos módulos).
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys

# ── Windows: forzar ProactorEventLoop ──
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Forzar UTF-8 en stdout/stderr para soportar emojis en Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from fastapi import FastAPI

# ── Imports de ambos sub-paquetes ──
from pld_agent.core.database import (
    get_pool as pld_get_pool,
    close_pool as pld_close_pool,
)
from pld_agent.core.config import API_HOST, API_PORT
from pld_agent.api.router import router as pld_router
from pld_agent.api.mer_router import mer_router

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-22s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("arizona")


# ═══════════════════════════════════════════════════════════════════
#  Lifespan — inicializa y cierra AMBOS pools
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown: pools de BD + RAG."""
    log.info("Arizona iniciando — PLD en puerto %s", API_PORT)

    await pld_get_pool()
    log.info("Pool PLD listo")

    yield

    await pld_close_pool()
    log.info("Arizona detenido — pool cerrado")


# ═══════════════════════════════════════════════════════════════════
#  FastAPI Application
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Arizona — Agente PLD/AML",
    description=(
        "Servicio de prevención de lavado de dinero. Análisis de completitud "
        "documental (DCG Art.115), screening contra listas negras, generación "
        "de reporte PLD unificado, y scoring MER v7.0 + RAG."
    ),
    version="2.1.0",
    lifespan=lifespan,
)

app.include_router(pld_router)
app.include_router(mer_router)


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
