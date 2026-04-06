"""
Tests unitarios para Orquestrator/app/pipeline.py.
Mockea los clients — no requiere servicios reales.

Flujo Dakota: archivos → Dakota OCR → Colorado → Arizona → Compliance → Nevada.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.pipeline import procesar_documento, procesar_expediente


# ═══════════════════════════════════════════════════════════════════
#  procesar_documento (archivo → Dakota OCR → pipeline)
# ═══════════════════════════════════════════════════════════════════


class TestProcesarDocumento:
    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_get_empresa", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_upload_document", new_callable=AsyncMock)
    async def test_flujo_completo_exitoso(
        self, mock_upload, mock_get_empresa, mock_colorado,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        mock_upload.return_value = {
            "doc_type": "csf",
            "archivo_procesado": "test.pdf",
            "persistencia": {"guardado": True, "empresa_id": "emp-1"},
            "datos_extraidos": {"razon_social": {"valor": "TEST SA"}},
        }
        mock_get_empresa.return_value = None  # No necesario si upload devuelve empresa_id
        mock_colorado.return_value = {
            "dictamen": "APROBADO",
            "hallazgos": [],
            "criticos": 0,
            "pasan": 10,
        }
        mock_arizona.return_value = {"riesgo": "bajo", "resultado": "COMPLETO", "porcentaje_completitud": 95}
        mock_compliance.return_value = {"dictamen": "APROBADO", "score": {"riesgo_residual": 0.2, "nivel_residual": "BAJO"}}
        mock_nevada.return_value = {"dictamen": "FAVORABLE", "fundamento_legal": "Art. 25 LFPIORPI"}

        result = await procesar_documento(
            doc_type="csf",
            file_content=b"fake-pdf",
            file_name="test.pdf",
            rfc="TST000101AA0",
        )

        assert result["rfc"] == "TST000101AA0"
        assert result["extraccion"] is not None
        assert result["persistencia"]["guardado"] is True
        assert "tiempos" in result
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.pipeline.dakota_upload_document", new_callable=AsyncMock)
    async def test_dakota_no_responde(self, mock_upload):
        mock_upload.return_value = None

        result = await procesar_documento(
            doc_type="csf",
            file_content=b"fake-pdf",
            file_name="test.pdf",
            rfc="TST000101AA0",
        )

        assert result["extraccion"]["error"] is not None
        assert result["persistencia"] is None

    @pytest.mark.asyncio
    @patch("app.pipeline.dakota_get_empresa", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_upload_document", new_callable=AsyncMock)
    async def test_sin_empresa_id(self, mock_upload, mock_get_empresa):
        mock_upload.return_value = {
            "doc_type": "csf",
            "datos_extraidos": {},
        }
        mock_get_empresa.return_value = None  # Tampoco se encuentra por RFC

        result = await procesar_documento(
            doc_type="csf",
            file_content=b"fake-pdf",
            file_name="test.pdf",
            rfc="TST000101AA0",
        )

        assert result["persistencia"]["guardado"] is False
        assert result["validacion_cruzada"] is None


# ═══════════════════════════════════════════════════════════════════
#  procesar_expediente (multi-documento Dakota)
# ═══════════════════════════════════════════════════════════════════


class TestProcesarExpediente:
    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_get_empresa", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_upload_document", new_callable=AsyncMock)
    async def test_expediente_multidoc(
        self, mock_upload, mock_get_empresa, mock_colorado,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        mock_upload.return_value = {
            "doc_type": "csf",
            "persistencia": {"guardado": True, "empresa_id": "emp-1"},
            "datos_extraidos": {"razon_social": {"valor": "TEST SA"}},
        }
        mock_get_empresa.return_value = None
        mock_colorado.return_value = {
            "dictamen": "APROBADO",
            "hallazgos": [],
            "criticos": 0,
            "pasan": 5,
            "portales_ejecutados": False,
        }
        mock_arizona.return_value = {"resultado": "COMPLETO", "porcentaje_completitud": 90}
        mock_compliance.return_value = {"dictamen": "APROBADO", "score": {"riesgo_residual": 0.1, "nivel_residual": "BAJO"}}
        mock_nevada.return_value = {"dictamen": "FAVORABLE"}

        result = await procesar_expediente(
            rfc="TST000101AA0",
            archivos=[
                {"doc_type": "csf", "file_content": b"pdf1", "file_name": "csf.pdf"},
                {"doc_type": "ine", "file_content": b"pdf2", "file_name": "ine.pdf"},
            ],
        )

        assert result["rfc"] == "TST000101AA0"
        assert result["documentos_procesados"] == 2
        assert result["documentos_exitosos"] == 2
        assert mock_upload.call_count == 2

    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_get_empresa", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_upload_document", new_callable=AsyncMock)
    async def test_un_doc_falla(
        self, mock_upload, mock_get_empresa, mock_colorado,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        # Primer doc OK, segundo falla
        mock_upload.side_effect = [
            {
                "doc_type": "csf",
                "persistencia": {"guardado": True, "empresa_id": "emp-1"},
            },
            None,
        ]
        mock_get_empresa.return_value = None
        mock_colorado.return_value = {"dictamen": "APROBADO", "hallazgos": [], "criticos": 0, "pasan": 5}
        mock_arizona.return_value = {"resultado": "COMPLETO", "porcentaje_completitud": 90}
        mock_compliance.return_value = {"dictamen": "APROBADO", "score": {}}
        mock_nevada.return_value = {"dictamen": "FAVORABLE"}

        result = await procesar_expediente(
            rfc="TST000101AA0",
            archivos=[
                {"doc_type": "csf", "file_content": b"pdf1", "file_name": "csf.pdf"},
                {"doc_type": "ine", "file_content": b"pdf2", "file_name": "ine.pdf"},
            ],
        )
        assert result["documentos_procesados"] == 2
        assert result["documentos_exitosos"] == 1
