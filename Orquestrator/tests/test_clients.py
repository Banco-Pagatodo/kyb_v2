"""
Tests unitarios para Orquestrator/app/clients.py.
Todos los tests mockean httpx — no requieren servicios corriendo.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.clients import (
    dakota_health,
    dakota_empresa_by_rfc,
    dakota_empresa_progress,
    dakota_import,
    colorado_validate,
    colorado_health,
    colorado_last_validation,
    SUPPORTED_IMPORT_DOC_TYPES,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _mock_response(status: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


# ═══════════════════════════════════════════════════════════════════
#  dakota_import
# ═══════════════════════════════════════════════════════════════════


class TestDakotaImport:
    @pytest.mark.asyncio
    async def test_import_exitoso(self):
        mock_resp = _mock_response(200, {"doc_type": "csf", "_persistencia": {"guardado": True, "empresa_id": "abc"}})
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await dakota_import(
                doc_type="csf",
                ocr_json={"rfc": "TST000101AA0", "razon_social": "TEST"},
                rfc="TST000101AA0",
            )
        assert result is not None
        assert result["doc_type"] == "csf"

    @pytest.mark.asyncio
    async def test_import_error_conexion(self):
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.side_effect = httpx.ConnectError("No server")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await dakota_import(
                doc_type="csf",
                ocr_json={"rfc": "TST000101AA0"},
                rfc="TST000101AA0",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_import_http_500(self):
        mock_resp = _mock_response(500, text="Internal error")
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await dakota_import(
                doc_type="csf",
                ocr_json={"rfc": "TST000101AA0"},
                rfc="TST000101AA0",
            )
        assert result is None


# ═══════════════════════════════════════════════════════════════════
#  dakota_health / colorado_health
# ═══════════════════════════════════════════════════════════════════


class TestHealthChecks:
    @pytest.mark.asyncio
    async def test_dakota_health_ok(self):
        mock_resp = _mock_response(200)
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            assert await dakota_health() is True

    @pytest.mark.asyncio
    async def test_dakota_health_down(self):
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.side_effect = httpx.ConnectError("down")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            assert await dakota_health() is False

    @pytest.mark.asyncio
    async def test_colorado_health_ok(self):
        mock_resp = _mock_response(200)
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            assert await colorado_health() is True


# ═══════════════════════════════════════════════════════════════════
#  colorado_validate
# ═══════════════════════════════════════════════════════════════════


class TestColoradoValidate:
    @pytest.mark.asyncio
    async def test_validacion_exitosa(self):
        data = {
            "rfc": "TST000101AA0",
            "dictamen": "APROBADO",
            "hallazgos": [{"codigo": "V1.1"}],
        }
        mock_resp = _mock_response(200, data)
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await colorado_validate("abc-123")
        assert result is not None
        assert result["dictamen"] == "APROBADO"

    @pytest.mark.asyncio
    async def test_colorado_no_disponible(self):
        with patch("app.clients.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.side_effect = httpx.ConnectError("down")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await colorado_validate("abc-123")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
#  SUPPORTED_IMPORT_DOC_TYPES
# ═══════════════════════════════════════════════════════════════════


class TestSupportedImportDocTypes:
    def test_contiene_tipos_base(self):
        for dt in ["csf", "acta_constitutiva", "ine", "poder", "fiel"]:
            assert dt in SUPPORTED_IMPORT_DOC_TYPES

    def test_no_vacio(self):
        assert len(SUPPORTED_IMPORT_DOC_TYPES) >= 7
