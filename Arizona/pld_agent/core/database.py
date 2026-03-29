"""
Conexión asíncrona a PostgreSQL con asyncpg.
Misma BD que Dakota y Colorado (kyb).
"""
import asyncio
import logging

import asyncpg
from .config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

logger = logging.getLogger("arizona.db")

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Obtiene o crea el lock del pool (lazy, dentro de un event loop)."""
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_pool() -> asyncpg.Pool:
    """Obtiene o crea el pool de conexiones a PostgreSQL (thread-safe)."""
    global _pool
    if _pool is not None:
        return _pool

    async with _get_lock():
        if _pool is not None:
            return _pool

        if not DB_PASS:
            raise RuntimeError(
                "DB_PASS no configurado. Establece la variable de entorno "
                "DB_PASS (o PASSWORD) antes de iniciar el servicio."
            )

        _pool = await asyncpg.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            min_size=1,
            max_size=5,
        )
        logger.info("Pool PostgreSQL creado: %s@%s:%s/%s", DB_USER, DB_HOST, DB_PORT, DB_NAME)
    return _pool


async def close_pool() -> None:
    """Cierra el pool de conexiones."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
