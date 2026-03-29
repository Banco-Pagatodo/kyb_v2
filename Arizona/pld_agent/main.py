"""
Arizona — Agente PLD/AML para KYB
Punto de entrada: servidor API (puerto 8012).
"""
from __future__ import annotations

import asyncio
import io
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

from .core.database import get_pool, close_pool
from .core.config import API_HOST, API_PORT
from .api.router import router


# ═══════════════════════════════════════════════════════════════════
#  FastAPI Application
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa y cierra la conexión a la BD."""
    await get_pool()
    yield
    await close_pool()


app = FastAPI(
    title="Arizona — Agente PLD/AML para KYB",
    description=(
        "Análisis de Prevención de Lavado de Dinero para Personas Morales. "
        "Etapa 1: Verificación de completitud documental (DCG Art.115 LIC)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "pld_agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
