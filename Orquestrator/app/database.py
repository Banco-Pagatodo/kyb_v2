"""
Pool asyncpg compartido para el Orquestrador.
Mismo patrón que Colorado, Arizona y Nevada.
"""

import asyncio
import asyncpg
from . import config

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Obtiene (o crea) el pool de conexiones a PostgreSQL."""
    global _pool
    if _pool is None or _pool._closed:
        async with _lock:
            if _pool is None or _pool._closed:
                _pool = await asyncpg.create_pool(
                    host=config.DB_HOST,
                    port=config.DB_PORT,
                    database=config.DB_NAME,
                    user=config.DB_USER,
                    password=config.DB_PASS,
                    min_size=1,
                    max_size=5,
                )
    return _pool


async def close_pool() -> None:
    """Cierra el pool de conexiones."""
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        _pool = None
