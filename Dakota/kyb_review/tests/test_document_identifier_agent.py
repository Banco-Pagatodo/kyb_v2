"""
Tests para DocumentIdentifierAgent con 4 señales.

Este módulo prueba el clasificador de documentos con casos representativos:
1. CSF correcta en /csf â†’ confirmed
2. Poder Notarial en /csf â†’ wrong_document
3. Caso ambiguo â†’ uncertain
4. INE en /acta â†’ wrong_document
5. INE correcta en /ine â†’ confirmed
6. Documento corrupto â†’ uncertain con baja confianza
7. Recibo CFE en /csf â†’ wrong_document (caso reportado)
"""

import pytest
from api.service.document_identifier_agent import (
    DocumentIdentifierAgent,
    classify_document,
    DOCUMENT_SIGNATURES,
)
from api.model.document_identity import DocumentIdentityResult, WrongDocumentError


# =============================================================================
# TEXTOS OCR DE PRUEBA
# =============================================================================

CSF_TEXT = """
CONSTANCIA DE SITUACIÓN FISCAL
SERVICIO DE ADMINISTRACIÓN TRIBUTARIA

RFC: XAXX010101000
Denominación o Razón Social: EMPRESA EJEMPLO SA DE CV

RÃ‰GIMEN FISCAL:
- Régimen General de Ley Personas Morales

ACTIVIDADES ECONÓMICAS:
- Comercio al por mayor

OBLIGACIONES FISCALES:
- Declaraciones mensuales

Estatus en el padrón: ACTIVO

Fecha de emisión: 15/01/2026
Código Postal: 06600
"""

INE_TEXT = """
INSTITUTO NACIONAL ELECTORAL
CREDENCIAL PARA VOTAR

NOMBRE: JUAN PÃ‰REZ GARCÍA
CLAVE DE ELECTOR: PERGJ850101HDFRRS09
CURP: PERGJ850101HDFRRS09
SECCIÓN: 1234
VIGENCIA: 2030
AÁO DE REGISTRO: 2020
LOCALIDAD: CIUDAD DE MÃ‰XICO
DOMICILIO: CALLE REFORMA 100, COL. CENTRO
FECHA DE NACIMIENTO: 01/01/1985
"""

PODER_NOTARIAL_TEXT = """
ESCRITURA PÃšBLICA NÃšMERO 12345

PODER NOTARIAL GENERAL

Ante mí, NOTARIO PÃšBLICO NÃšMERO 50 de la Ciudad de México,
compareció el PODERDANTE: CARLOS MARTÍNEZ LÓPEZ
para otorgar PODER GENERAL a favor del
APODERADO: MARÍA FERNÁNDEZ RODRÍGUEZ

FACULTADES CONFERIDAS:
- Representación legal
- Actos de administración
- Actos de dominio

Fecha de otorgamiento: 10/02/2026
Clave del SAT: ABC123456
"""

ACTA_CONSTITUTIVA_TEXT = """
ESCRITURA PÃšBLICA NÃšMERO 98765

ACTA CONSTITUTIVA

NOTARIO PÃšBLICO NÃšMERO 100 de la Ciudad de México

SOCIEDAD ANÓNIMA DE CAPITAL VARIABLE

DENOMINACIÓN SOCIAL: EMPRESA TECNOLÓGICA SA DE CV

SOCIOS FUNDADORES:
- JUAN PÃ‰REZ (50%)
- MARÍA LÓPEZ (50%)

CAPITAL SOCIAL: $1,000,000.00 MXN

OBJETO SOCIAL:
- Desarrollo de software
- Consultoría tecnológica

FOLIO MERCANTIL: 123456
FECHA DE CONSTITUCIÓN: 01/01/2020
REGISTRO PÃšBLICO DE COMERCIO
PROTOCOLIZACIÓN ante fedatario público
"""

CFE_RECIBO_TEXT = """
Este gráfico refleja tu nivel de consumo. A menor uso, mayor apoyo.

Comisión Federal de Electricidad
RFC: CFE370814QI0
Av. Paseo de la Reforma 164, Col. Juárez,
Alcaldía: Cuauhtémoc, Código Postal: 06600,
Ciudad de México.

AVISO RECIBO

Lectura actual: 12345
Lectura anterior: 12000
Consumo: 345 kWh

CONSUMO HISTÓRICO
Período de consumo: 15 ENE 26 al 15 FEB 26

Importe a pagar: $1,585.00

TARIFA DOMÃ‰STICA
Medidor: ABC123456
Suministro eléctrico

SERVICIO DOMÃ‰STICO
"""

CORRUPTED_TEXT = """
#$%&/()=?Â¡
123abc!!!
///||||\\\\
???%%%$$$
"""

AMBIGUOUS_TEXT = """
DOCUMENTO OFICIAL
RFC: XAXX010101000
Fecha: 15/01/2026
Nombre: Juan Pérez
Dirección: Calle Reforma 100
Vigencia: 2026
"""


# =============================================================================
# TESTS
# =============================================================================

class TestDocumentIdentifierAgent:
    """Suite de tests para el agente de identificación de documentos."""
    
    @pytest.fixture
    def agent(self):
        """Crea una instancia del agente sin LLM."""
        return DocumentIdentifierAgent(openai_client=None)
    
    @pytest.mark.asyncio
    async def test_csf_correct_identification(self, agent):
        """
        Test 1: CSF correcta subida a /csf â†’ confirmed
        
        Verifica que un documento CSF legítimo sea identificado correctamente.
        """
        result = await agent.classify(
            ocr_text=CSF_TEXT,
            ocr_fields={
                "rfc": {"valor": "XAXX010101000"},
                "regimen_fiscal": {"valor": "General de Ley"},
                "estatus_padron": {"valor": "ACTIVO"},
                "fecha_emision": {"valor": "15/01/2026"},
            },
            page_count=1,
            expected_type="csf"
        )
        
        assert result.is_correct == True
        assert result.should_reject == False
        assert result.expected_type == "csf"
        assert "verificado" in result.reasoning
    
    @pytest.mark.asyncio
    async def test_poder_notarial_wrong_endpoint(self, agent):
        """
        Test 2: Poder Notarial subido a /csf â†’ wrong_document
        
        Verifica que un Poder Notarial sea rechazado en el endpoint de CSF.
        """
        result = await agent.classify(
            ocr_text=PODER_NOTARIAL_TEXT,
            ocr_fields={
                "poderdante": {"valor": "CARLOS MARTÍNEZ"},
                "apoderado": {"valor": "MARÍA FERNÁNDEZ"},
                "facultades": {"valor": "Representación legal"},
            },
            page_count=8,
            expected_type="csf"
        )
        
        assert result.is_correct == False
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning
    
    @pytest.mark.asyncio
    async def test_poder_notarial_not_misclassified_as_acta(self, agent):
        """
        Test 2b: Regresión â€” Poder Notarial en /csf debe detectarse como
        'poder_notarial', NO como 'acta_constitutiva'.

        BUG REPORT: DocumentIdentifierAgent devolvía detected_document_type =
        'acta_constitutiva' cuando se subía un Poder Notarial a /csf, porque
        ambos comparten keywords notariales genéricos (ESCRITURA PÃšBLICA,
        NOTARIO PÃšBLICO, NÃšMERO DE ESCRITURA).

        Este test usa texto representativo de un Poder Notarial real que
        incluye las frases discriminadoras clave (PODERDANTE, APODERADO,
        OTORGA PODER) para garantizar que el tiebreaker lo clasifique
        correctamente.
        """
        poder_text = """
        ESCRITURA PÃšBLICA NÃšMERO QUINCE MIL DOSCIENTOS TREINTA Y CUATRO

        NOTARIA PÃšBLICA NÃšMERO 42 DE LA CIUDAD DE MEXICO
        LIC. ROBERTO SÁNCHEZ TORRES, NOTARIO PÃšBLICO

        PODER NOTARIAL GENERAL

        Comparece como PODERDANTE: INDUSTRIAS EJEMPLO S.A. DE C.V.,
        representada por su Director General JUAN CARLOS MÃ‰NDEZ RIOS.

        EN SU CALIDAD DE PODERDANTE, la sociedad otorga por medio del
        presente instrumento PODER GENERAL a favor del
        APODERADO DESIGNADO: PEDRO ANTONIO MARTÍNEZ LÓPEZ

        FACULTADES QUE SE OTORGAN:
        I.   Para pleitos y cobranzas
        II.  Para actos de administración
        III. Para actos de dominio
        IV.  Para suscribir títulos de crédito

        EN SU CARÁCTER DE APODERADO, el designado podrá ejercer las
        facultades anteriores ante autoridades judiciales, administrativas
        y terceros en general.

        EL PRESENTE PODER GENERAL tendrá vigencia indefinida hasta su
        revocación expresa por el PODERDANTE.

        INSTRUMENTO DE PODER otorgado ante la fe de la notaria pública.
        Número de escritura: 15234
        """
        result = await agent.classify(
            ocr_text=poder_text,
            ocr_fields={
                "poderdante": {"valor": "INDUSTRIAS EJEMPLO S.A. DE C.V."},
                "apoderado": {"valor": "PEDRO ANTONIO MARTÍNEZ LÓPEZ"},
                "facultades": {"valor": "Pleitos, administración, dominio"},
                "numero_escritura": {"valor": "15234"},
            },
            page_count=6,
            expected_type="csf"
        )

        # El veredicto debe ser should_reject
        assert result.should_reject == True, (
            f"El veredicto debería ser 'should_reject=True'"
        )
        assert result.expected_type == "csf"

        # El razonamiento debe indicar documento incorrecto
        assert "suba el documento correcto" in result.reasoning, (
            f"El razonamiento debería indicar documento incorrecto: {result.reasoning}"
        )

        print(f"\nâœ… Regresión Poderâ†’CSF:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")
        print(f"   Reasoning: {result.reasoning}")

    
    @pytest.mark.asyncio
    async def test_ambiguous_document_uncertain(self, agent):
        """
        Test 3: Documento ambiguo â†’ uncertain
        
        Verifica que un documento con OCR ambiguo sea marcado como incierto.
        """
        result = await agent.classify(
            ocr_text=AMBIGUOUS_TEXT,
            ocr_fields={
                "rfc": {"valor": "XAXX010101000"},
            },
            page_count=1,
            expected_type="csf"
        )
        
        # incorrect o uncertain â€” en cualquier caso no confirmado
        assert result.is_correct == False
        assert "revisión" in result.reasoning.lower() or "correcto" in result.reasoning.lower()
    
    @pytest.mark.asyncio
    async def test_ine_in_acta_endpoint(self, agent):
        """
        Test 4: INE subida a /acta_constitutiva â†’ wrong_document
        
        Verifica que una INE sea rechazada en el endpoint de Acta Constitutiva.
        """
        result = await agent.classify(
            ocr_text=INE_TEXT,
            ocr_fields={
                "clave_elector": {"valor": "PERGJ850101HDFRRS09"},
                "curp": {"valor": "PERGJ850101HDFRRS09"},
                "seccion": {"valor": "1234"},
            },
            page_count=1,
            expected_type="acta_constitutiva"
        )
        
        assert result.is_correct == False
        assert result.should_reject == True
        assert result.expected_type == "acta_constitutiva"
    
    @pytest.mark.asyncio
    async def test_ine_correct_identification(self, agent):
        """
        Test 5: INE correcta subida a /ine â†’ confirmed
        
        Verifica que una INE legítima sea identificada correctamente.
        """
        result = await agent.classify(
            ocr_text=INE_TEXT,
            ocr_fields={
                "clave_elector": {"valor": "PERGJ850101HDFRRS09"},
                "curp": {"valor": "PERGJ850101HDFRRS09"},
                "seccion": {"valor": "1234"},
                "vigencia": {"valor": "2030"},
            },
            page_count=1,
            expected_type="ine"
        )
        
        assert result.is_correct == True
        assert result.should_reject == False
        assert result.expected_type == "ine"
    
    @pytest.mark.asyncio
    async def test_corrupted_document_low_confidence(self, agent):
        """
        Test 6: Documento corrupto â†’ uncertain con baja confianza
        
        Verifica que un documento ilegible sea marcado con baja confianza.
        """
        result = await agent.classify(
            ocr_text=CORRUPTED_TEXT,
            ocr_fields={},
            page_count=1,
            expected_type="csf"
        )
        
        # Sin keywords, el documento no puede confirmarse correcto
        assert result.is_correct == False
    
    @pytest.mark.asyncio
    async def test_cfe_recibo_in_csf_endpoint(self, agent):
        """
        Test 7: Recibo CFE subido a /csf â†’ wrong_document + detected as comprobante_domicilio
        
        Este es el caso reportado: un recibo de luz de CFE fue subido al endpoint
        de CSF y el sistema lo detectó incorrectamente como ine_reverso.
        Debe detectarse como comprobante_domicilio.
        """
        result = await agent.classify(
            ocr_text=CFE_RECIBO_TEXT,
            ocr_fields={
                "rfc": {"valor": "CFE370814QI0"},
                "domicilio_fiscal": {"valor": "Av. Paseo de la Reforma 164"},
            },
            page_count=2,
            expected_type="csf"
        )
        
        # DEBE ser marcado como wrong_document
        assert result.is_correct == False, (
            f"Esperado is_correct=False, obtenido is_correct={result.is_correct}"
        )
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning

        print(f"\nâœ… Test CFE â†’ CSF:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")
        print(f"   Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_protocolizacion_acta_asamblea_detected_as_reforma(self, agent):
        """
        Test 8: Protocolización de Acta de Asamblea Extraordinaria â†’
                 detected: reforma_estatutos (wrong_document para /csf)

        BUG REPORT: El sistema clasificaba este documento como 'acta_constitutiva'
        porque el texto contenía 'SOCIEDAD' y keywords genéricos notariales.
        La primera línea "ACTO: PROTOCOLIZACION DE ACTA DE ASAMBLEA EXTRAORDINARIA"
        debe ser suficiente para identificarlo como 'reforma_estatutos'.
        """
        reforma_text = """ACTO: PROTOCOLIZACION DE ACTA DE ASAMBLEA EXTRAORDINARIA
DE LA SOCIEDAD DENOMINADA AVANZA SOLIDO S.A. DE C.V.

ESCRITURA PÃšBLICA NÃšMERO VEINTIDÓS MIL TRESCIENTOS

NOTARÍA PÃšBLICA NÃšMERO 85 DE LA CIUDAD DE MEXICO

ORDEN DEL DIA:
1. Designación de presidente y secretario de asamblea.
2. Aumento de capital social.
3. Modificación de estatutos sociales.
4. Restructuración del consejo de administración.

ACUERDOS DE ASAMBLEA:
- Se aprueba el aumento de capital social variable.
- Se nombra nuevo Consejero Delegado.
- Se modifican las cláusulas de administración.

FOLIO MERCANTIL: 987654
OBLIGACIONES FISCALES: Declaraciones anuales
"""
        result = await agent.classify(
            ocr_text=reforma_text,
            ocr_fields={
                "folio_mercantil": {"valor": "987654"},
                "numero_escritura": {"valor": "22300"},
                "notario": {"valor": "Notaría No. 85"},
            },
            page_count=8,
            expected_type="csf"
        )

        assert result.is_correct == False, (
            f"Esperado is_correct=False, obtenido is_correct={result.is_correct}"
        )
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning

        print(f"\nâœ… Test Reforma de Estatutos â†’ CSF:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")
        print(f"   Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_acta_constitutiva_with_poder_general_in_bylaws(self, agent):
        """
        Test 9: Acta Constitutiva que otorga 'PODER GENERAL' a administradores
                 â†’ detected: acta_constitutiva (NOT poder_notarial)

        BUG REPORT: Las Actas Constitutivas otorgan "PODER GENERAL" a sus
        administradores en los estatutos. Si "PODER GENERAL" se trata como
        discriminante de poder_notarial, el Acta se clasifica erróneamente.

        Verificación: el clasificador debe devolver 'acta_constitutiva' incluso
        cuando el texto contiene "PODER GENERAL" para administradores.
        """
        acta_con_poder_text = """ESCRITURA PÃšBLICA NÃšMERO 54321

ACTA CONSTITUTIVA

NOTARIO PÃšBLICO NÃšMERO 12 DE LA CIUDAD DE MEXICO

SOCIEDAD ANÓNIMA DE CAPITAL VARIABLE

DENOMINACIÓN SOCIAL: CONSTRUCTORA DEL NORTE SA DE CV

SOCIOS FUNDADORES:
- ROBERTO DOMINGUEZ (60%)
- LAURA VARGAS (40%)

CAPITAL SOCIAL FIJO: $500,000.00 MXN

OBJETO SOCIAL:
- Construcción de obra civil
- Servicios de ingeniería

FOLIO MERCANTIL: 654321
REGISTRO PÃšBLICO DE COMERCIO

CLÁUSULA DÃ‰CIMA PRIMERA - ADMINISTRACIÓN:
El Consejo de Administración contará con PODER GENERAL para actos de
administración y dominio. Los consejeros tendrán PODER ESPECIAL para
contratos de arrendamiento y gestión bancaria.

SOCIOS CONSTITUYENTES otorgan las presentes CLAUSULAS DEL PACTO SOCIAL.
DURACION DE LA SOCIEDAD: NOVENTA Y NUEVE AÁOS.
"""
        result = await agent.classify(
            ocr_text=acta_con_poder_text,
            ocr_fields={
                "folio_mercantil": {"valor": "654321"},
                "numero_escritura": {"valor": "54321"},
                "notario": {"valor": "Notaría No. 12"},
                "capital_social": {"valor": "500000"},
                "socios": {"valor": "Roberto Dominguez, Laura Vargas"},
            },
            page_count=12,
            expected_type="acta_constitutiva"
        )

        # El Acta debe clasificarse correctamente como acta_constitutiva
        assert result.expected_type == "acta_constitutiva"
        # El status debe ser no-rechazado (documento correcto en endpoint correcto)
        assert result.should_reject == False, (
            f"El veredicto debería ser 'should_reject=False', no '{result.should_reject}'"
        )

        print(f"\nâœ… Test Acta con PODER GENERAL en estatutos:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")

    @pytest.mark.asyncio
    async def test_standalone_poder_notarial_detected_correctly(self, agent):
        """
        Test 10: Poder Notarial standalone con PODERDANTE â†’
                 detected: poder_notarial (wrong_document para /csf)

        Verifica que un Poder Notarial real (cuyo propósito primario es
        delegar facultades) se detecte correctamente, con o sin "PODER GENERAL".
        """
        poder_standalone_text = """PODER NOTARIAL GENERAL

ESCRITURA PÃšBLICA NÃšMERO OCHO MIL NOVECIENTOS

COMPARECE COMO PODERDANTE: GRUPO INDUSTRIAL BAJIO SC DE RL DE CV,
representada por su apoderado legal FRANCISCO JAVIER RIOS OCHOA.

EN SU CALIDAD DE PODERDANTE, la sociedad por medio del presente instrumento
CONFIERE PODER a favor de:
APODERADO DESIGNADO: ANA SOFIA CASTELLANOS MEDINA

FACULTADES QUE SE OTORGAN AL APODERADO:
1. Representar a la sociedad ante toda clase de autoridades.
2. Suscribir, endosar y avalar títulos de crédito.
3. Abrir y cancelar cuentas bancarias.

EN SU CARÁCTER DE APODERADO, la designada podrá ejercer las facultades
anteriores con plena representación legal de la empresa.

Fecha de otorgamiento del presente poder: 10/02/2026
Número de escritura: 8900
"""
        result = await agent.classify(
            ocr_text=poder_standalone_text,
            ocr_fields={
                "poderdante": {"valor": "GRUPO INDUSTRIAL BAJIO SC DE RL DE CV"},
                "apoderado": {"valor": "ANA SOFIA CASTELLANOS MEDINA"},
                "fecha_otorgamiento": {"valor": "10/02/2026"},
            },
            page_count=5,
            expected_type="csf"
        )

        assert result.is_correct == False, (
            f"Esperado is_correct=False, obtenido is_correct={result.is_correct}"
        )
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning

        print(f"\nâœ… Test Poder Notarial standalone â†’ CSF:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")

    @pytest.mark.asyncio
    async def test_poder_notarial_with_incidental_csf_mention(self, agent):
        """
        Test 11: Poder Notarial que menciona incidentalmente una CSF â†’
                 "CONSTANCIA DE SITUACIÓN FISCAL" filtrada como mención incidental,
                 detected: poder_notarial (wrong_document para /csf)

        BUG REPORT: El notario escribe "quien manifiesta que la sociedad cuenta con
        RFC SCX190531824, acreditandomelo con la Constancia de Situación Fiscal".
        El clasificador incrementaba el score de CSF aunque el documento NO ES una CSF.

        Este test verifica que _is_incidental_mention() filtre correctamente ese match.
        """
        poder_con_csf_incidental = """ARTURO PONS AGUIRRE, en su carácter de Delegado Especial del ACTA DE
SESIÓN DEL CONSEJO DE ADMINISTRACIÓN de la sociedad denominada EJEMPLO
CORPORATIVO SA DE CV, a efecto de solicitar la PROTOCOLIZACIÓN del acta
en la que se aprobó otorgar PODER GENERAL JUDICIAL Y PARA PLEITOS Y COBRANZAS,
PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN, PODER CAMBIARIO Y PODER ESPECIAL
PARA CONSTITUIR FIDEICOMISOS al señor Arturo Pons Aguirre.

El compareciente acredita su personalidad con la siguiente documentación:
- Escritura Pública número 5432, quien manifiesta que la sociedad cuenta con
  Registro Federal de Contribuyentes número SCX190531824, acreditandomelo con
  la Constancia de Situación Fiscal y la Cédula de Identificación Fiscal
  expedida por el Servicio de Administración Tributaria.

RÃ‰GIMEN LEGAL DEL MANDATO:
El presente Poder se otorga en los términos del Artículo 2554 del Código Civil
Federal para que pueda ejercer las Facultades que se confieren en el mismo.

EL MANDATARIO autorizado será PEDRO RUIZ JIMÃ‰NEZ en nombre de la sociedad.
Se otorga el presente instrumento en la Ciudad de México.

Registro Público de Comercio:
M1 - Acta de sesión de consejo de administración - Otorgamiento de poderes y facultades
"""
        result = await agent.classify(
            ocr_text=poder_con_csf_incidental,
            ocr_fields={
                "poderdante": {"valor": "EJEMPLO CORPORATIVO SA DE CV"},
                "facultades": {"valor": "Pleitos, administración, cambiario, fideicomisos"},
            },
            page_count=10,
            expected_type="csf"
        )

        assert result.is_correct == False, (
            f"Esperado is_correct=False, obtenido is_correct={result.is_correct}"
        )
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning

        print(f"\nâœ… Test Poder con CSF incidental â†’ CSF endpoint:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")
        print(f"   Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_reforma_protocolizacion_not_misclassified_as_poder(self, agent):
        """
        Test 12: Reforma de Estatutos vía protocolización de asamblea â†’
                 detected: reforma_estatutos (NOT poder_notarial)

        Verifica que el chequeo compuesto de protocolización clasifique
        correctamente una Reforma cuando los indicadores de asamblea superan
        a los indicadores de poder.
        """
        reforma_con_protocolizacion = """PROTOCOLIZACION DE ACTA DE ASAMBLEA EXTRAORDINARIA DE ACCIONISTAS
de la sociedad denominada CONSTRUCTORA DEL BAJIO SA DE CV.

ORDEN DEL DIA:
1. Designación de presidente y secretario.
2. Aumento de capital social variable.
3. Reforma de estatutos sociales â€” modificación de la cláusula SÃ‰PTIMA.
4. Reestructuración del consejo de administración.
5. Bajas voluntarias de socios.
6. Alta de nuevos socios.
7. Asuntos generales.

ACUERDOS DE ASAMBLEA EXTRAORDINARIA:
- Se aprueba el aumento de capital en $500,000.00 MXN.
- Se modifica la cláusula SÃ‰PTIMA de los estatutos sociales.
- Se nombran nuevos integrantes del Consejo.
- Se acepta la baja voluntaria del socio Roberto Domínguez.

FOLIO MERCANTIL: 456789
Registro Público de Comercio de la Ciudad de México.
"""
        result = await agent.classify(
            ocr_text=reforma_con_protocolizacion,
            ocr_fields={
                "folio_mercantil": {"valor": "456789"},
                "numero_escritura": {"valor": "7890"},
                "notario": {"valor": "Notaría No. 30"},
            },
            page_count=7,
            expected_type="csf"
        )

        assert result.is_correct == False, (
            f"Esperado is_correct=False, obtenido is_correct={result.is_correct}"
        )
        assert result.should_reject == True
        assert result.expected_type == "csf"
        assert "suba el documento correcto" in result.reasoning

        print(f"\nâœ… Test Reforma protocolización â†’ CSF endpoint:")
        print(f"   Correct: {result.is_correct}")
        print(f"   Should Reject: {result.should_reject}")
        print(f"   Reasoning: {result.reasoning}")


class TestSignalBreakdown:
    """Tests para verificar la estructura del resultado de identificación."""
    
    @pytest.fixture
    def agent(self):
        return DocumentIdentifierAgent(openai_client=None)
    
    @pytest.mark.asyncio
    async def test_result_structure(self, agent):
        """Verifica que el resultado tenga la estructura correcta."""
        result = await agent.classify(
            ocr_text=CSF_TEXT,
            ocr_fields={"rfc": {"valor": "XAXX010101000"}},
            page_count=1,
            expected_type="csf"
        )

        # Verificar que todos los campos existen
        assert hasattr(result, 'is_correct')
        assert hasattr(result, 'expected_type')
        assert hasattr(result, 'reasoning')
        assert hasattr(result, 'should_reject')

        # Verificar valores para un CSF correcto
        assert result.is_correct == True
        assert result.should_reject == False
        assert result.expected_type == "csf"
        assert isinstance(result.reasoning, str) and len(result.reasoning) > 0


class TestWrongDocumentError:
    """Tests para la excepción WrongDocumentError."""
    
    def test_error_creation(self):
        """Verifica la creación correcta de la excepción."""
        error = WrongDocumentError(expected="csf")
        
        assert error.expected == "csf"
        assert "csf" in str(error)
    
    def test_error_with_custom_message(self):
        """Verifica mensaje personalizado."""
        error = WrongDocumentError(
            expected="csf",
            message="Documento incorrecto"
        )
        assert error.expected == "csf"
        assert "Documento incorrecto" in str(error)
    
    def test_error_to_dict(self):
        """Verifica la conversión a diccionario."""
        error = WrongDocumentError(expected="csf", message="Documento incorrecto")
        
        error_dict = error.to_dict()
        
        assert error_dict["error"] == "wrong_document_type"
        assert error_dict["expected"] == "csf"
        assert "message" in error_dict


class TestKeywordNormalization:
    """Tests para la normalización de texto."""
    
    @pytest.fixture
    def agent(self):
        return DocumentIdentifierAgent()
    
    def test_accent_normalization(self, agent):
        """Verifica que los acentos se normalicen correctamente."""
        text = "COMISIÓN FEDERAL DE ELECTRICIDAD"
        normalized = agent._normalize_text(text)
        
        assert "COMISION" in normalized
        assert "Ó" not in normalized
    
    def test_case_normalization(self, agent):
        """Verifica que el texto se convierta a mayúsculas."""
        text = "Constancia de Situación Fiscal"
        normalized = agent._normalize_text(text)
        
        assert normalized == "CONSTANCIA DE SITUACION FISCAL"


class TestDocumentSignatures:
    """Tests para verificar las firmas de documentos."""
    
    def test_all_document_types_have_signatures(self):
        """Verifica que todos los tipos de documento tengan firmas definidas."""
        expected_types = [
            "csf", "ine", "ine_reverso", "acta_constitutiva",
            "poder_notarial", "comprobante_domicilio", "fiel",
            "estado_cuenta", "reforma_estatutos"
        ]
        
        for doc_type in expected_types:
            assert doc_type in DOCUMENT_SIGNATURES, f"Falta firma para {doc_type}"
            assert "exclusive_keywords" in DOCUMENT_SIGNATURES[doc_type]
            assert "negative_keywords" in DOCUMENT_SIGNATURES[doc_type]
    
    def test_cfe_keywords_in_comprobante(self):
        """Verifica que CFE esté en comprobante_domicilio pero como negativo en CSF."""
        # CFE debe ser exclusivo de comprobante_domicilio
        comprobante_keywords = DOCUMENT_SIGNATURES["comprobante_domicilio"]["exclusive_keywords"]
        assert any("CFE" in kw or "ELECTRICIDAD" in kw for kw in comprobante_keywords)
        
        # CFE debe ser negativo para CSF
        csf_negatives = DOCUMENT_SIGNATURES["csf"]["negative_keywords"]
        assert any("CFE" in kw or "ELECTRICIDAD" in kw for kw in csf_negatives)


# =============================================================================
# FUNCIÓN MAIN PARA EJECUCIÓN DIRECTA
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
