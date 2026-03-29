"""
Tests unitarios para Orquestrator/app/pipeline.py.
Mockea los clients — no requiere servicios reales.

Flujo: PagaTodo (prospect_data + OCR) → Dakota import → Colorado → Arizona → Compliance → Nevada.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.pipeline import procesar_documento, procesar_expediente
from app.clients import transformar_datos_prospecto


# ═══════════════════════════════════════════════════════════════════
#  procesar_documento (PagaTodo → Dakota import → pipeline)
# ═══════════════════════════════════════════════════════════════════


class TestProcesarDocumento:
    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_empresa_progress", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_import", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_ocr_result", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_prospect_data", new_callable=AsyncMock)
    async def test_flujo_completo_exitoso(
        self, mock_prospect, mock_ocr, mock_import, mock_colorado, mock_progress,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        mock_prospect.return_value = {
            "personaMoral": {"razonSocial": "TEST SA", "rfc": "TST000101AA0"},
            "domicilioFiscal": {"calle": "Reforma", "cp": "06600"},
        }
        mock_ocr.return_value = ({"rfc": "TST000101AA0", "razon_social": "TEST SA"}, "csf")
        mock_import.return_value = {
            "doc_type": "csf",
            "_persistencia": {"guardado": True, "empresa_id": "emp-1"},
            "razon_social": "TEST SA",
        }
        mock_colorado.return_value = {
            "dictamen": "APROBADO",
            "hallazgos": [],
            "criticos": 0,
            "pasan": 10,
        }
        mock_progress.return_value = {"total_docs": 1, "doc_types": ["csf"]}
        mock_arizona.return_value = {"riesgo": "bajo"}
        mock_compliance.return_value = {"dictamen": "APROBADO"}
        mock_nevada.return_value = {"dictamen_legal": "FAVORABLE"}

        result = await procesar_documento(
            prospect_id="abc-123",
            document_type="Csf",
            rfc="TST000101AA0",
        )

        assert result["rfc"] == "TST000101AA0"
        assert result["datos_prospecto"] is not None
        assert result["datos_prospecto"]["persona_moral"]["rfc"] == "TST000101AA0"
        assert "tiempos" in result
        mock_prospect.assert_called_once_with("abc-123")
        mock_ocr.assert_called_once()
        mock_import.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.pipeline.pagatodo_prospect_data", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_ocr_result", new_callable=AsyncMock)
    async def test_pagatodo_ocr_falla(self, mock_ocr, mock_prospect):
        mock_prospect.return_value = {
            "personaMoral": {"razonSocial": "TEST SA", "rfc": "TST000101AA0"},
        }
        mock_ocr.return_value = (None, None)

        result = await procesar_documento(
            prospect_id="abc-123",
            document_type="Csf",
            rfc="TST000101AA0",
        )

        assert result["extraccion"]["error"] is not None
        assert result["persistencia"] is None
        # Datos de prospecto sí deben estar aunque OCR falle
        assert result["datos_prospecto"] is not None

    @pytest.mark.asyncio
    @patch("app.pipeline.pagatodo_prospect_data", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_import", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_ocr_result", new_callable=AsyncMock)
    async def test_dakota_import_falla(self, mock_ocr, mock_import, mock_prospect):
        mock_prospect.return_value = None  # sin datos de registro manual
        mock_ocr.return_value = ({"rfc": "TST000101AA0"}, "csf")
        mock_import.return_value = None

        result = await procesar_documento(
            prospect_id="abc-123",
            document_type="Csf",
            rfc="TST000101AA0",
        )

        assert result["extraccion"]["error"] is not None
        assert result["validacion_cruzada"] is None
        assert result["datos_prospecto"] is None  # prospect_data no disponible


# ═══════════════════════════════════════════════════════════════════
#  procesar_expediente (multi-documento PagaTodo)
# ═══════════════════════════════════════════════════════════════════


class TestProcesarExpediente:
    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_empresa_progress", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_import", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_ocr_result", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_prospect_data", new_callable=AsyncMock)
    async def test_expediente_multidoc(
        self, mock_prospect, mock_ocr, mock_import, mock_colorado, mock_progress,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        mock_prospect.return_value = {
            "personaMoral": {"razonSocial": "TEST SA", "rfc": "TST000101AA0"},
            "domicilioFiscal": {"calle": "Reforma", "cp": "06600"},
        }
        mock_ocr.return_value = ({"rfc": "TST000101AA0", "razon_social": "TEST SA"}, "csf")
        mock_import.return_value = {
            "doc_type": "csf",
            "_persistencia": {"guardado": True, "empresa_id": "emp-1"},
        }
        mock_colorado.return_value = {
            "dictamen": "RECHAZADO",
            "hallazgos": [{"codigo": "V1.1"}],
            "criticos": 1,
            "pasan": 5,
        }
        mock_progress.return_value = {"total_docs": 2}
        mock_arizona.return_value = {"riesgo": "medio"}
        mock_compliance.return_value = {"dictamen": "CONDICIONADO"}
        mock_nevada.return_value = {"dictamen_legal": "CON_OBSERVACIONES"}

        result = await procesar_expediente(
            prospect_id="abc-123",
            rfc="TST000101AA0",
            document_types=["Csf", "IneFrente"],
        )

        assert result["rfc"] == "TST000101AA0"
        assert result["documentos_procesados"] == 2
        assert result["documentos_exitosos"] == 2
        assert result["datos_prospecto"] is not None
        assert result["datos_prospecto"]["persona_moral"]["rfc"] == "TST000101AA0"
        mock_prospect.assert_called_once_with("abc-123")

    @pytest.mark.asyncio
    @patch("app.pipeline.nevada_dictamen_legal", new_callable=AsyncMock)
    @patch("app.pipeline.compliance_dictamen", new_callable=AsyncMock)
    @patch("app.pipeline.arizona_pld_analyze", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_empresa_progress", new_callable=AsyncMock)
    @patch("app.pipeline.colorado_validate", new_callable=AsyncMock)
    @patch("app.pipeline.dakota_import", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_ocr_result", new_callable=AsyncMock)
    @patch("app.pipeline.pagatodo_prospect_data", new_callable=AsyncMock)
    async def test_un_doc_falla(
        self, mock_prospect, mock_ocr, mock_import, mock_colorado, mock_progress,
        mock_arizona, mock_compliance, mock_nevada,
    ):
        mock_prospect.return_value = None  # Prospect data no disponible
        # Primer doc OK, segundo falla en OCR
        mock_ocr.side_effect = [
            ({"rfc": "TST000101AA0"}, "csf"),
            (None, None),
        ]
        mock_import.return_value = {
            "doc_type": "csf",
            "_persistencia": {"guardado": True, "empresa_id": "emp-1"},
        }
        mock_colorado.return_value = {"dictamen": "APROBADO", "hallazgos": [], "criticos": 0, "pasan": 5}
        mock_progress.return_value = {}
        mock_arizona.return_value = {"riesgo": "bajo"}
        mock_compliance.return_value = {"dictamen": "APROBADO"}
        mock_nevada.return_value = {"dictamen_legal": "FAVORABLE"}

        result = await procesar_expediente(
            prospect_id="abc-123",
            rfc="TST000101AA0",
            document_types=["Csf", "IneFrente"],
        )
        assert result["documentos_procesados"] == 2
        assert result["documentos_exitosos"] == 1
        assert result["datos_prospecto"] is None  # prospect_data no disponible


# ═══════════════════════════════════════════════════════════════════
#  transformar_datos_prospecto (normalización PagaTodo → interno)
# ═══════════════════════════════════════════════════════════════════


class TestTransformarDatosProspecto:
    def test_transformacion_completa(self):
        raw = {
            "personaMoral": {
                "razonSocial": "Stellar Solutions SA de CV",
                "rfc": "LIO970711TND",
                "nacionalidad": "México",
                "nombreComercial": "Quantum Tech",
                "giroMercantil": "Compra y venta",
                "numeroEmpleados": 1233,
                "paginaWeb": "example.com",
                "serieFEA": None,
                "telefono": "5571223123",
                "correo": "test@test.com",
            },
            "domicilioFiscal": {
                "calle": "Oriente 168",
                "noExterior": "35",
                "noInterior": None,
                "cp": "23019",
                "colonia": "La Paz",
                "municipio": "La Paz",
                "ciudad": "La Paz",
                "estado": "Baja California Sur",
            },
            "actaConstitutiva": {
                "instrumentoPublico": "324423423",
                "fechaConstitucion": "2025-12-09",
                "numeroNotaria": "2341234",
                "folioMercantil": "LKDSFKQWE23",
                "nombreNotario": "Juan Fuentes Flores",
            },
            "representanteLegal": {
                "nombres": "Jose",
                "primerApellido": "Licona",
                "segundoApellido": "Orduña",
                "rfc": "LIOI970711TN8",
                "domicilio": {
                    "calle": "Manantial",
                    "noExterior": "234",
                    "cp": "23019",
                },
            },
            "perfilTransaccional": {
                "entradas": [{"monto": "1.00 - 4000000.00)", "frecuencia": "Quincenal"}],
                "salidas": [],
            },
        }

        result = transformar_datos_prospecto(raw)

        assert result["persona_moral"]["razon_social"] == "Stellar Solutions SA de CV"
        assert result["persona_moral"]["rfc"] == "LIO970711TND"
        assert result["persona_moral"]["numero_empleados"] == 1233
        assert result["domicilio_fiscal"]["calle"] == "Oriente 168"
        assert result["domicilio_fiscal"]["codigo_postal"] == "23019"
        assert result["acta_constitutiva"]["folio_mercantil"] == "LKDSFKQWE23"
        assert result["representante_legal"]["nombre_completo"] == "Jose Licona Orduña"
        assert result["representante_legal"]["rfc"] == "LIOI970711TN8"
        assert result["representante_legal"]["domicilio"]["calle"] == "Manantial"
        assert len(result["perfil_transaccional"]["entradas"]) == 1
        assert result["perfil_transaccional"]["salidas"] == []

    def test_respuesta_vacia(self):
        result = transformar_datos_prospecto({})

        assert result["persona_moral"]["rfc"] == ""
        assert result["domicilio_fiscal"]["calle"] == ""
        assert result["representante_legal"]["nombre_completo"] == ""
        assert result["perfil_transaccional"]["entradas"] == []
        assert result["declaraciones_regulatorias"] is None

    def test_nombre_completo_parcial(self):
        raw = {
            "representanteLegal": {
                "nombres": "Maria",
                "primerApellido": "Lopez",
                "segundoApellido": "",
            },
        }
        result = transformar_datos_prospecto(raw)
        assert result["representante_legal"]["nombre_completo"] == "Maria Lopez"
