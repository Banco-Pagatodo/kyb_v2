# api/db/session.py
# Configuración de conexión async a PostgreSQL con SQLAlchemy 2.0
#
# Variables de entorno requeridas:
#   DATABASE_URL = postgresql+asyncpg://user:pass@host:5432/kyb
#   (o las variables individuales DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME)

import os
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv(dotenv_path="api/service/.env")

logger = logging.getLogger("kyb.db")

# ---------------------------------------------------------------------------
# Construir URL de conexión
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    """Construye la URL de conexión a PostgreSQL desde variables de entorno."""
    url = os.getenv("DATABASE_URL")
    if url:
        # Normalizar driver: si viene con 'postgresql://', cambiar a 'postgresql+asyncpg://'
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # Fallback: construir desde variables individuales
    user = os.getenv("DB_USER", "kyb_app")
    password = os.getenv("DB_PASS", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "kyb")
    ssl = os.getenv("DB_SSL", "prefer")

    base = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    if ssl and ssl != "disable":
        base += f"?ssl={ssl}"
    return base


# ---------------------------------------------------------------------------
# Engine y Session Factory (lazy init)
# ---------------------------------------------------------------------------

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Inicializa el engine y la session factory. Llamar en el startup de FastAPI."""
    global _engine, _session_factory

    if _engine is not None:
        return  # Ya inicializado

    db_url = _build_database_url()

    # Ocultar contraseña para el log
    safe_url = db_url.split("@")[-1] if "@" in db_url else db_url
    logger.info("Conectando a PostgreSQL: %s", safe_url)

    _engine = create_async_engine(
        db_url,
        echo=os.getenv("DB_ECHO", "false").lower() == "true",
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_pre_ping=True,          # detecta conexiones rotas
        pool_recycle=300,             # reciclar cada 5 min (Azure cierra idle)
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("PostgreSQL engine inicializado correctamente")


async def close_db() -> None:
    """Cierra el engine. Llamar en el shutdown de FastAPI."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("PostgreSQL engine cerrado")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency de FastAPI: genera una sesión async por request.

    Uso:
        @router.post("/endpoint")
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    if _session_factory is None:
        raise RuntimeError(
            "Base de datos no inicializada. "
            "¿Olvidaste llamar init_db() en el lifespan de FastAPI?"
        )

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
