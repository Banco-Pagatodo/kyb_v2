"""
Tests for DocumentIdentifierAgent.
Validates document type classification based on OCR text.
"""

import pytest
from api.service.document_identifier import (
    DocumentIdentifierAgent,
    DocumentType,
    IdentificationResult,
    identify_document_type,
)


class TestDocumentIdentifierAgent:
    """Test suite for DocumentIdentifierAgent."""

    def setup_method(self):
        """Set up test fixtures."""
        self.agent = DocumentIdentifierAgent()

    # ==========================================================================
    # CSF (Constancia de Situación Fiscal) Tests
    # ==========================================================================

    def test_csf_correct_identification(self):
        """CSF document should be identified correctly."""
        ocr_text = """
        SERVICIO DE ADMINISTRACIÓN TRIBUTARIA
        CONSTANCIA DE SITUACIÓN FISCAL
        CÉDULA DE IDENTIFICACIÓN FISCAL
        RFC: ABC123456789
        RÉGIMEN FISCAL: Persona Moral
        OBLIGACIONES FISCALES:
        - ISR
        - IVA
        """
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        assert result.is_correct is True
        assert result.confidence >= 0.5
        assert result.expected_type == "csf"

    def test_csf_wrong_document_acta(self):
        """Acta Constitutiva uploaded as CSF should be detected."""
        ocr_text = """
        ESCRITURA PÚBLICA NÚMERO 12345
        NOTARÍA PÚBLICA 15
        PROTOCOLIZACIÓN
        ACTA CONSTITUTIVA
        DENOMINACIÓN SOCIAL: EMPRESA XYZ S.A. DE C.V.
        CAPITAL SOCIAL: $100,000.00
        OBJETO SOCIAL: Comercialización de productos
        RFC: ABC123456789
        """
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        assert result.is_correct is False
        assert result.detected_type in ["acta_constitutiva", "poder"]

    def test_csf_wrong_document_poder(self):
        """Poder Notarial uploaded as CSF should be detected."""
        ocr_text = """
        PODER NOTARIAL
        ESCRITURA PÚBLICA NÚMERO 5678
        ANTE NOTARIO PÚBLICO
        PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN
        OTORGANTE: JUAN PÉREZ
        APODERADO: MARÍA GARCÍA
        RFC: DEF456789012
        """
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        assert result.is_correct is False
        assert "poder" in result.detected_type.lower() or result.detected_type == "unknown"

    def test_csf_wrong_document_cfe_recibo(self):
        """Recibo CFE (comprobante domicilio) uploaded as CSF should be detected."""
        ocr_text = """
        RFC: CFE370814QI0
        Comisión Federal de Electricidad
        Av. Paseo de la Reforma 164, Col. Juárez,
        Alcaldía: Cuauhtémoc, Código Postal: 06600
        Lectura actual Medida Estimada
        Lectura anterior Estimada
        PERIODO DE CONSUMO
        kWh
        IMPORTE A PAGAR
        """
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        assert result.is_correct is False
        assert result.should_reject is True
        # Debería detectar que es un comprobante de domicilio
        assert "comprobante" in result.detected_type.lower() or "domicilio" in result.detected_type.lower()

    def test_telmex_recibo_in_csf_endpoint(self):
        """TELMEX receipt should NOT be identified as CSF - should detect comprobante_domicilio."""
        ocr_text = """
        TELMEX®
        TELEFONOS DE MEXICO S.A.B. DE C.V.
        Parque Via 198, Col. Cuauhtémoc
        C.P. 06500 Ciudad de México
        RFC: TME840315-KT6
        AVANZA SOLIDO
        AV EL OCOTE NO. 405 MZ 5 LT 3
        Total a Pagar: $ 1,718.00
        Pagar antes de: 08-OCT-2025
        Mes de Facturación: Septiembre
        Teléfono: 961612 1024
        Factura No.: 080625090006282
        
        Resumen del Estado de Cuenta
        Saldo Anterior 1,719.00
        Cargos del Mes + 1,718.53
        
        Cargos del Mes
        Servicios de Telecomunicaciones 1,265.66
        Servicios Especiales 219.53
        IVA 16% 206.76
        Total $ 1,718.53
        """
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        assert result.is_correct is False
        assert result.should_reject is True
        # Debería detectar que es un comprobante de domicilio, NO ine_reverso
        assert result.detected_type == "comprobante_domicilio", (
            f"Expected 'comprobante_domicilio', got '{result.detected_type}'"
        )

    # ==========================================================================
    # Acta Constitutiva Tests
    # ==========================================================================

    def test_acta_correct_identification(self):
        """Acta Constitutiva should be identified correctly."""
        ocr_text = """
        ESCRITURA PÚBLICA NÚMERO 12345
        NOTARÍA PÚBLICA NÚMERO 15
        ACTA CONSTITUTIVA
        CONSTITUCION DE SOCIEDAD
        LOS COMPARECIENTES CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO UNA 
        SOCIEDAD ANONIMA DE CAPITAL VARIABLE
        DENOMINACIÓN DE LA SOCIEDAD: EMPRESA ABC S.A. DE C.V.
        CLAUSULA PRIMERA - DENOMINACION
        CLAUSULA SEGUNDA - DOMICILIO SOCIAL
        CLAUSULA TERCERA - DURACION DE LA SOCIEDAD: NOVENTA Y NUEVE AÑOS
        OBJETO SOCIAL: Prestación de servicios
        CAPITAL SOCIAL MINIMO: $50,000.00
        ACCIONES SERIE A: 500 acciones
        ASAMBLEA DE ACCIONISTAS
        ADMINISTRADOR UNICO: JUAN PÉREZ GARCÍA
        COMISARIO: CARLOS RUIZ MENDEZ
        TRANSITORIAS
        FOLIO MERCANTIL ELECTRONICO: 12345
        """
        result = self.agent.identify(ocr_text, DocumentType.ACTA_CONSTITUTIVA)
        assert result.is_correct is True
        assert result.confidence >= 0.35

    def test_acta_wrong_document_csf(self):
        """CSF uploaded as Acta Constitutiva should be detected."""
        ocr_text = """
        SERVICIO DE ADMINISTRACIÓN TRIBUTARIA
        CONSTANCIA DE SITUACIÓN FISCAL
        RFC: XYZ987654321
        RÉGIMEN FISCAL: General de Ley
        OBLIGACIONES FISCALES: ISR, IVA
        DOMICILIO FISCAL: Calle Principal 123
        """
        result = self.agent.identify(ocr_text, DocumentType.ACTA_CONSTITUTIVA)
        assert result.is_correct is False
        assert "csf" in result.detected_type.lower() or "constancia" in result.detected_type.lower()

    def test_acta_with_poder_general_facultades(self):
        """
        CASO CRÍTICO: Acta Constitutiva que otorga PODER GENERAL a administradores.
        
        Las Actas Constitutivas típicamente otorgan facultades de PODER GENERAL,
        PODER ESPECIAL, PLEITOS Y COBRANZAS a los administradores. Esto NO las
        convierte en Poderes Notariales.
        
        La diferencia clave:
        - ACTA CONSTITUTIVA = CREA una empresa
        - PODER NOTARIAL = DELEGA facultades de una empresa YA EXISTENTE
        """
        # Este es texto real de una Acta Constitutiva que tiene facultades de poder
        ocr_text = """
        ESCRITURA NUMERO CINCUENTA Y SIETE MIL QUINIENTOS CUARENTA Y DOS
        
        ACTA CONSTITUTIVA
        
        Los comparecientes CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO una 
        SOCIEDAD ANONIMA DE CAPITAL VARIABLE que se denominará 
        "ARENOSOS OPCIONES EN CONSTRUCCION S.A. DE C.V."
        
        CLAUSULA PRIMERA - DENOMINACION DE LA SOCIEDAD
        CLAUSULA SEGUNDA - DOMICILIO SOCIAL
        CLAUSULA TERCERA - DURACION DE LA SOCIEDAD: NOVENTA Y NUEVE AÑOS
        CLAUSULA CUARTA - OBJETO SOCIAL
        
        CAPITAL SOCIAL MINIMO: $50,000.00 MONEDA NACIONAL
        ACCIONES SERIE A: 100 acciones
        
        ADMINISTRADOR UNICO: ROBERTO BIBIANO DORANTES
        
        Al ADMINISTRADOR UNICO se le otorgan las siguientes facultades:
        
        a) PODER GENERAL PARA PLEITOS Y COBRANZAS
        b) PODER GENERAL PARA ACTOS DE ADMINISTRACION  
        c) PODER GENERAL PARA ACTOS DE RIGUROSO DOMINIO
        d) PODER ESPECIAL PARA SUSCRIBIR TITULOS DE CREDITO
        
        ASAMBLEA DE ACCIONISTAS
        COMISARIO: LUIS JOAQUIN KAUIL CONTRERAS
        
        CLAUSULAS TRANSITORIAS
        
        FOLIO MERCANTIL ELECTRONICO No. 28308
        REGISTRO PUBLICO DE LA PROPIEDAD Y DEL COMERCIO
        BOLETA DE INSCRIPCION
        """
        result = self.agent.identify(ocr_text, DocumentType.ACTA_CONSTITUTIVA)
        
        # Aunque tiene "PODER GENERAL", es claramente una ACTA por los discriminantes
        assert result.is_correct is True, (
            f"Acta con facultades de PODER incorrectamente detectada como '{result.detected_type}'. "
            f"Discriminantes encontrados: {result.discriminants_found}. "
            f"Negativos encontrados: {result.negative_indicators}"
        )
        assert result.detected_type == "acta_constitutiva"
        assert result.confidence >= 0.40  # Alta confianza por múltiples discriminantes
        
        # Verificar que encontró discriminantes clave de ACTA
        found_lower = [d.lower() for d in result.discriminants_found]
        assert any("constituyen" in d or "constitucion" in d for d in found_lower), (
            f"Debería encontrar 'CONSTITUYEN' o 'CONSTITUCION'. Encontrados: {result.discriminants_found}"
        )

    # ==========================================================================
    # Poder Notarial Tests
    # ==========================================================================

    def test_poder_correct_identification(self):
        """Poder Notarial should be identified correctly."""
        ocr_text = """
        ESCRITURA PÚBLICA NÚMERO 9999
        PODER NOTARIAL
        
        COMPARECE COMO PODERDANTE: JUAN CARLOS MENDEZ RIVERA
        EN SU CALIDAD DE PODERDANTE declara que por medio del presente instrumento
        OTORGA PODER A FAVOR DE: PEDRO MARTÍNEZ LÓPEZ
        
        EL APODERADO DESIGNADO queda facultado para ejercer las siguientes facultades:
        - Representación legal ante autoridades
        - Actos de administración
        - Pleitos y cobranzas
        
        AL APODERADO SE LE CONFIERE poder amplio para todos los efectos legales.
        EL PRESENTE PODER tendrá vigencia indefinida hasta su revocación.
        
        INSTRUMENTO DE PODER otorgado ante la fe del notario público.
        """
        result = self.agent.identify(ocr_text, DocumentType.PODER)
        assert result.is_correct is True
        assert result.confidence >= 0.2

    # ==========================================================================
    # FIEL Tests
    # ==========================================================================

    def test_fiel_correct_identification(self):
        """FIEL certificate should be identified correctly."""
        ocr_text = """
        CERTIFICADO DE E.FIRMA
        FIRMA ELECTRÓNICA AVANZADA
        NÚMERO DE SERIE DEL CERTIFICADO: 12345678901234567890
        VIGENCIA: 2024-01-01 AL 2028-01-01
        TITULAR: EMPRESA ABC S.A. DE C.V.
        RFC: ABC123456789
        """
        result = self.agent.identify(ocr_text, DocumentType.FIEL)
        assert result.is_correct is True
        assert result.confidence >= 0.25

    def test_fiel_wrong_document_csf(self):
        """CSF uploaded as FIEL should be detected."""
        ocr_text = """
        CONSTANCIA DE SITUACIÓN FISCAL
        SERVICIO DE ADMINISTRACIÓN TRIBUTARIA
        RFC: ABC123456789
        RÉGIMEN FISCAL: Persona Moral
        """
        result = self.agent.identify(ocr_text, DocumentType.FIEL)
        assert result.is_correct is False

    # ==========================================================================
    # INE Tests
    # ==========================================================================

    def test_ine_correct_identification(self):
        """INE should be identified correctly."""
        ocr_text = """
        INSTITUTO NACIONAL ELECTORAL
        CREDENCIAL PARA VOTAR
        NOMBRE: JUAN PÉREZ GARCÍA
        DOMICILIO: CALLE PRINCIPAL 123
        CLAVE DE ELECTOR: ABCD123456HDFXYZ01
        CURP: PEGA800101HDFXYZ09
        VIGENCIA: 2030
        """
        result = self.agent.identify(ocr_text, DocumentType.INE)
        assert result.is_correct is True
        assert result.confidence >= 0.4

    def test_ine_reverso_correct_identification(self):
        """INE reverso should be identified correctly."""
        ocr_text = """
        IDMEX1234567890<<
        INSTITUTO NACIONAL ELECTORAL
        MRZ DATA
        CIC: 123456789
        OCR: 1234567890123
        """
        result = self.agent.identify(ocr_text, DocumentType.INE_REVERSO)
        assert result.is_correct is True
        assert result.confidence >= 0.5

    # ==========================================================================
    # Estado de Cuenta Tests
    # ==========================================================================

    def test_estado_cuenta_correct_identification(self):
        """Estado de Cuenta should be identified correctly."""
        ocr_text = """
        ESTADO DE CUENTA
        BANCO NACIONAL DE MÉXICO
        CUENTA: 1234567890
        CLABE INTERBANCARIA: 012345678901234567
        PERIODO: ENERO 2024
        SALDO INICIAL: $50,000.00
        DEPÓSITOS: $10,000.00
        RETIROS: $5,000.00
        SALDO FINAL: $55,000.00
        """
        result = self.agent.identify(ocr_text, DocumentType.ESTADO_CUENTA)
        assert result.is_correct is True
        assert result.confidence >= 0.3

    # ==========================================================================
    # Comprobante de Domicilio Tests
    # ==========================================================================

    def test_domicilio_correct_identification(self):
        """Comprobante de domicilio should be identified correctly."""
        ocr_text = """
        RECIBO DE LUZ
        COMISIÓN FEDERAL DE ELECTRICIDAD
        CFE SUMINISTRADOR DE SERVICIOS BÁSICOS
        SERVICIO DOMÉSTICO
        AVISO RECIBO
        DOMICILIO DEL SERVICIO: CALLE PRINCIPAL 123
        PERIODO DE CONSUMO: ENERO 2024
        CONSUMO: 150 kWh
        LECTURA ANTERIOR: 1000 LECTURA ACTUAL: 1150
        TARIFA DOMESTICA
        DATOS DEL SERVICIO
        MEDIDOR: 12345678
        TOTAL A PAGAR: $500.00
        IMPORTE A PAGAR
        """
        result = self.agent.identify(ocr_text, DocumentType.COMPROBANTE_DOMICILIO)
        assert result.is_correct is True
        assert result.confidence >= 0.25

    # ==========================================================================
    # Helper function tests
    # ==========================================================================

    def test_identify_document_type_helper(self):
        """Test the helper function."""
        ocr_text = "CONSTANCIA DE SITUACIÓN FISCAL RFC RÉGIMEN FISCAL"
        result = identify_document_type(ocr_text, "csf")
        assert isinstance(result, IdentificationResult)
        assert result.is_correct is True

    def test_identify_document_type_unknown_expected(self):
        """Test with unknown expected type defaults to CSF."""
        ocr_text = "CONSTANCIA DE SITUACIÓN FISCAL"
        result = identify_document_type(ocr_text, "tipo_inventado")
        # Should default to CSF
        assert isinstance(result, IdentificationResult)

    # ==========================================================================
    # Edge Cases
    # ==========================================================================

    def test_empty_text(self):
        """Empty text should return low confidence."""
        result = self.agent.identify("", DocumentType.CSF)
        assert result.confidence < 0.3
        assert result.is_correct is False

    def test_very_short_text(self):
        """Very short text should return low confidence."""
        result = self.agent.identify("RFC", DocumentType.CSF)
        assert result.confidence < 0.5

    def test_ambiguous_document(self):
        """Document with few keywords should have lower confidence."""
        ocr_text = "DOCUMENTO OFICIAL RFC NOMBRE DOMICILIO"
        result = self.agent.identify(ocr_text, DocumentType.CSF)
        # Should still work but with lower confidence
        assert isinstance(result, IdentificationResult)

    def test_to_dict_method(self):
        """IdentificationResult.to_dict() should return proper dict."""
        result = IdentificationResult(
            is_correct=True,
            expected_type="csf",
            detected_type="csf",
            confidence=0.85,
            discriminants_found=["CONSTANCIA", "RÉGIMEN FISCAL"],
            negative_indicators=[],
            reasoning="Documento identificado correctamente",
            should_reject=False
        )
        d = result.to_dict()
        assert d["is_correct"] is True
        assert d["expected_type"] == "csf"
        assert "reasoning" in d
        assert "should_reject" in d

    # ==========================================================================
    # Keywords coverage tests
    # ==========================================================================

    def test_discriminant_keywords_exist(self):
        """All document types should have discriminant keywords."""
        agent = DocumentIdentifierAgent()
        for doc_type in DocumentType:
            assert doc_type in agent.DISCRIMINANT_KEYWORDS, f"Missing keywords for {doc_type}"
            assert len(agent.DISCRIMINANT_KEYWORDS[doc_type]) > 0

    def test_negative_keywords_exist(self):
        """Most document types should have negative keywords."""
        agent = DocumentIdentifierAgent()
        # At least CSF, ACTA, PODER should have negatives
        assert DocumentType.CSF in agent.NEGATIVE_KEYWORDS
        assert DocumentType.ACTA_CONSTITUTIVA in agent.NEGATIVE_KEYWORDS
        assert DocumentType.PODER in agent.NEGATIVE_KEYWORDS


class TestDocumentScoring:
    """Test confidence scoring logic."""

    def setup_method(self):
        self.agent = DocumentIdentifierAgent()

    def test_multiple_discriminants_increase_confidence(self):
        """More discriminant keywords should increase confidence."""
        # Few keywords
        text_few = "CONSTANCIA DE SITUACIÓN FISCAL"
        result_few = self.agent.identify(text_few, DocumentType.CSF)

        # Many keywords
        text_many = """
        CONSTANCIA DE SITUACIÓN FISCAL
        SERVICIO DE ADMINISTRACIÓN TRIBUTARIA
        RÉGIMEN FISCAL
        OBLIGACIONES FISCALES
        CÉDULA DE IDENTIFICACIÓN FISCAL
        """
        result_many = self.agent.identify(text_many, DocumentType.CSF)

        assert result_many.confidence >= result_few.confidence

    def test_negative_keywords_reduce_confidence(self):
        """Negative keywords should reduce confidence or mark as incorrect."""
        # CSF text with negative keywords (Acta Constitutiva indicators)
        text_with_negatives = """
        RFC: ABC123456789
        ESCRITURA PÚBLICA
        PROTOCOLIZACIÓN
        ACTA CONSTITUTIVA
        """
        result = self.agent.identify(text_with_negatives, DocumentType.CSF)
        # Should be low confidence or incorrect
        assert result.confidence < 0.5 or result.is_correct is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
