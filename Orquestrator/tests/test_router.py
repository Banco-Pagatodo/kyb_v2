"""
Tests de integración para el router del Orquestrator con TestClient.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestRootEndpoint:
    def test_root_info(self):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "Orquestrator" in data["service"]
        assert "endpoints" in data


class TestHealthEndpoint:
    @patch("app.router.compliance_health", new_callable=AsyncMock)
    @patch("app.router.arizona_health", new_callable=AsyncMock)
    @patch("app.router.colorado_health", new_callable=AsyncMock)
    @patch("app.router.dakota_health", new_callable=AsyncMock)
    def test_health_all_up(self, mock_dakota, mock_colorado, mock_arizona, mock_compliance):
        mock_dakota.return_value = True
        mock_colorado.return_value = True
        mock_arizona.return_value = True
        mock_compliance.return_value = True

        resp = client.get("/api/v1/pipeline/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["dakota"]["reachable"] is True
        assert data["colorado"]["reachable"] is True
        assert data["arizona_pld"]["reachable"] is True
        assert data["arizona_compliance"]["reachable"] is True

    @patch("app.router.compliance_health", new_callable=AsyncMock)
    @patch("app.router.arizona_health", new_callable=AsyncMock)
    @patch("app.router.colorado_health", new_callable=AsyncMock)
    @patch("app.router.dakota_health", new_callable=AsyncMock)
    def test_health_degraded(self, mock_dakota, mock_colorado, mock_arizona, mock_compliance):
        mock_dakota.return_value = True
        mock_colorado.return_value = False
        mock_arizona.return_value = True
        mock_compliance.return_value = True

        resp = client.get("/api/v1/pipeline/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["colorado"]["reachable"] is False


class TestProcessEndpoint:
    @patch("app.router.procesar_documento", new_callable=AsyncMock)
    def test_process_sin_rfc(self, mock_proc):
        resp = client.post(
            "/api/v1/pipeline/process",
            json={"prospect_id": "abc-123", "document_type": "Csf", "rfc": ""},
        )
        assert resp.status_code == 422

    @patch("app.router.procesar_documento", new_callable=AsyncMock)
    def test_process_tipo_invalido(self, mock_proc):
        resp = client.post(
            "/api/v1/pipeline/process",
            json={"prospect_id": "abc-123", "document_type": "Inventado", "rfc": "TST000101AA0"},
        )
        assert resp.status_code == 422

    @patch("app.router.procesar_documento", new_callable=AsyncMock)
    def test_process_exitoso(self, mock_proc):
        mock_proc.return_value = {
            "rfc": "TST000101AA0",
            "pagatodo_ocr": {"ok": True},
            "dakota_import": {"doc_type": "csf"},
            "validacion_cruzada": {"dictamen": "APROBADO"},
        }
        resp = client.post(
            "/api/v1/pipeline/process",
            json={"prospect_id": "abc-123", "document_type": "Csf", "rfc": "TST000101AA0"},
        )
        assert resp.status_code == 200
        assert resp.json()["rfc"] == "TST000101AA0"


class TestExpedienteEndpoint:
    @patch("app.router.procesar_expediente", new_callable=AsyncMock)
    def test_expediente_sin_rfc(self, mock_proc):
        resp = client.post(
            "/api/v1/pipeline/expediente",
            json={"prospect_id": "abc-123", "rfc": "", "document_types": ["Csf"]},
        )
        assert resp.status_code == 422

    @patch("app.router.procesar_expediente", new_callable=AsyncMock)
    def test_expediente_tipo_invalido(self, mock_proc):
        resp = client.post(
            "/api/v1/pipeline/expediente",
            json={"prospect_id": "abc-123", "rfc": "TST000101AA0", "document_types": ["Inventado"]},
        )
        assert resp.status_code == 422

    @patch("app.router.procesar_expediente", new_callable=AsyncMock)
    def test_expediente_exitoso(self, mock_proc):
        mock_proc.return_value = {
            "rfc": "TST000101AA0",
            "documentos_procesados": 2,
            "documentos_exitosos": 2,
        }
        resp = client.post(
            "/api/v1/pipeline/expediente",
            json={
                "prospect_id": "abc-123",
                "rfc": "TST000101AA0",
                "document_types": ["Csf", "ActaCons"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["documentos_procesados"] == 2


class TestStatusEndpoint:
    @patch("app.router.obtener_estado_por_rfc", new_callable=AsyncMock)
    @patch("app.router.dakota_empresa_by_rfc", new_callable=AsyncMock)
    def test_rfc_no_encontrado(self, mock_by_rfc, mock_pipeline):
        mock_by_rfc.return_value = None
        mock_pipeline.return_value = None
        resp = client.get("/api/v1/pipeline/status/XXXX")
        assert resp.status_code == 404

    @patch("app.router.obtener_estado_por_rfc", new_callable=AsyncMock)
    @patch("app.router.dakota_empresa_by_rfc", new_callable=AsyncMock)
    def test_rfc_encontrado(self, mock_by_rfc, mock_pipeline):
        mock_by_rfc.return_value = {"rfc": "TST000101AA0", "razon_social": "TEST"}
        mock_pipeline.return_value = {"pipeline_status": "COMPLETADO", "rfc": "TST000101AA0"}
        resp = client.get("/api/v1/pipeline/status/TST000101AA0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["empresa"]["rfc"] == "TST000101AA0"
        assert body["pipeline"]["pipeline_status"] == "COMPLETADO"
