"""
Integración con Azure AI Search — Índice kyb-mer-search.

Consulta el manual MER PLD/FT v7.0 indexado para obtener
contexto cualitativo sobre factores de riesgo, mitigantes
y procedimientos de debida diligencia.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("arizona.mer_search")

# ── Cargar .env ──────────────────────────────────────────────────
_service_root = Path(__file__).resolve().parent.parent
_project_root = _service_root.parent.parent
for env_path in [
    _service_root / ".env",
    _project_root / ".env",
    _project_root / "Dakota" / "kyb_review" / ".env",
    _project_root / "Dakota" / "kyb_review" / "api" / "service" / ".env",
    Path.cwd() / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)
        break

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY", "")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "mer-pld-chunks")

# Azure OpenAI (para búsqueda semántica)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")


def _get_search_client():
    """Crea un SearchClient bajo demanda."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    if not AZURE_SEARCH_ENDPOINT or not AZURE_SEARCH_KEY:
        raise RuntimeError(
            "Variables AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY no configuradas. "
            "Revisa el .env."
        )
    return SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )


def consultar_mer(query: str, top: int = 5) -> list[dict]:
    """
    Busca en el índice ``kyb-mer-search`` fragmentos relevantes del manual MER.

    Devuelve una lista de dicts con ``content`` y ``score``.
    """
    try:
        client = _get_search_client()
        results = client.search(
            search_text=query,
            top=top,
            query_type="simple",
        )
        hits: list[dict] = []
        for r in results:
            hits.append({
                "content": r.get("content", r.get("chunk", "")),
                "score": r.get("@search.score", 0),
                "title": r.get("title", ""),
            })
        return hits
    except Exception as exc:
        logger.warning("Error al consultar kyb-mer-search: %s", exc)
        return []


def consultar_mer_semantica(query: str, top: int = 5) -> list[dict]:
    """
    Búsqueda semántica (vectorial) en el índice MER.
    Requiere configuración semántica en el índice de Azure AI Search.
    Falls back a búsqueda simple si falla.
    """
    try:
        client = _get_search_client()
        results = client.search(
            search_text=query,
            top=top,
            query_type="semantic",
            semantic_configuration_name="default",
        )
        hits: list[dict] = []
        for r in results:
            hits.append({
                "content": r.get("content", r.get("chunk", "")),
                "score": r.get("@search.reranker_score", r.get("@search.score", 0)),
                "title": r.get("title", ""),
            })
        return hits
    except Exception:
        logger.info("Búsqueda semántica no disponible, usando búsqueda simple")
        return consultar_mer(query, top)
