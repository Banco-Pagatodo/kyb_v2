"""
Nevada — Agente de Dictamen Jurídico para KYB
Punto de entrada: servidor API (puerto 8013).
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
from .services.persistence import crear_tabla_si_no_existe


# ═══════════════════════════════════════════════════════════════════
#  FastAPI Application
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa y cierra la conexión a la BD."""
    await get_pool()
    await crear_tabla_si_no_existe()
    yield
    await close_pool()


app = FastAPI(
    title="Nevada — Agente de Dictamen Jurídico para KYB",
    description=(
        "Genera el Dictamen Jurídico (DJ-1) para personas morales "
        "basándose en la documentación legal persistida por Dakota, "
        "las validaciones de Colorado y el análisis PLD de Arizona. "
        "Aplica las reglas de BPT y genera narrativa con Azure OpenAI."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "legal_agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )
