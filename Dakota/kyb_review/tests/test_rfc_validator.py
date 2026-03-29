"""
Tests para validación de RFC según SAT/CNBV.

Verifica:
- Formato RFC 12 chars (PM) y 13 chars (PF)
- Validación de dígito verificador
- RFCs genéricos para extranjeros
- Consistencia RFC vs tipo persona
"""

import pytest
from api.service.accionistas_validators.rfc_validator import (
    validar_rfc,
    normalizar_rfc,
    inferir_tipo_persona_por_rfc,
    detectar_tipo_persona,
    validar_consistencia_rfc_tipo,
    validar_rfcs_estructura,
    generar_alertas_rfc,
    es_rfc_generico,
    calcular_digito_verificador,
    validar_digito_verificador,
    TipoRFC,
    ResultadoValidacionRFC,
)


class TestNormalizarRFC:
    """Tests para normalización de RFC."""
    
    def test_normaliza_mayusculas(self):
        assert normalizar_rfc("abc123def456") == "ABC123DEF456"
    
    def test_remueve_espacios(self):
        assert normalizar_rfc("ABC 123 DEF 456") == "ABC123DEF456"
    
    def test_remueve_guiones(self):
        assert normalizar_rfc("ABC-123-DEF-456") == "ABC123DEF456"
    
    def test_rfc_vacio(self):
        assert normalizar_rfc("") == ""
        assert normalizar_rfc(None) == ""


class TestValidarRFC:
    """Tests para validación de formato RFC."""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RFC Persona Moral (12 caracteres)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def test_rfc_pm_valido(self):
        """RFC persona moral con formato correcto."""
        result = validar_rfc("AAA010101AAA", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_MORAL
        assert result.tipo_persona == "moral"
        assert result.formato_correcto is True
    
    def test_rfc_pm_fecha_invalida(self):
        """RFC PM con mes inválido (13)."""
        result = validar_rfc("AAA011301AAA", validar_checksum=False)
        assert result.es_valido is False
        assert result.formato_correcto is False
    
    def test_rfc_pm_fecha_dia_invalido(self):
        """RFC PM con día inválido (32)."""
        result = validar_rfc("AAA010132AAA", validar_checksum=False)
        assert result.es_valido is False
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RFC Persona Física (13 caracteres)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def test_rfc_pf_valido(self):
        """RFC persona física con formato correcto."""
        result = validar_rfc("AAAA010101AAA", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_FISICA
        assert result.tipo_persona == "fisica"
        assert result.formato_correcto is True
    
    def test_rfc_pf_con_ampersand(self):
        """RFC PF con ampersand en nombre (ej: García & Asociados)."""
        result = validar_rfc("GA&A010101AAA", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_FISICA
    
    def test_rfc_pf_con_enie(self):
        """RFC PF con Ñ en apellido."""
        result = validar_rfc("MUÑA010101AAA", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_FISICA
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RFCs Genéricos
    # ═══════════════════════════════════════════════════════════════════════════
    
    def test_rfc_generico_extranjero_pf(self):
        """RFC genérico para extranjero persona física."""
        result = validar_rfc("EXTF900101NI1")
        assert result.es_valido is True
        assert result.tipo == TipoRFC.GENERICO
        assert result.es_generico is True
        assert "extranjera" in result.descripcion_generico.lower()
    
    def test_rfc_generico_extranjero_pm(self):
        """RFC genérico para extranjero persona moral."""
        result = validar_rfc("EXT990101NI1")
        assert result.es_valido is True
        assert result.tipo == TipoRFC.GENERICO
        assert result.es_generico is True
    
    def test_rfc_generico_publico_general(self):
        """RFC genérico para público en general."""
        result = validar_rfc("XAXX010101000")
        assert result.es_valido is True
        assert result.tipo == TipoRFC.GENERICO
        assert result.es_generico is True
    
    def test_rfc_generico_residente_extranjero(self):
        """RFC genérico para residente extranjero."""
        result = validar_rfc("XEXX010101000")
        assert result.es_valido is True
        assert result.tipo == TipoRFC.GENERICO
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RFCs Inválidos
    # ═══════════════════════════════════════════════════════════════════════════
    
    def test_rfc_longitud_invalida_corto(self):
        """RFC con menos de 12 caracteres."""
        result = validar_rfc("AAA0101")
        assert result.es_valido is False
        assert result.tipo == TipoRFC.INVALIDO
        assert "longitud" in result.mensaje.lower()
    
    def test_rfc_longitud_invalida_largo(self):
        """RFC con más de 13 caracteres."""
        result = validar_rfc("AAAA01010101AAAA")
        assert result.es_valido is False
        assert result.tipo == TipoRFC.INVALIDO
    
    def test_rfc_vacio(self):
        """RFC vacío."""
        result = validar_rfc("")
        assert result.es_valido is False
        assert result.tipo == TipoRFC.INVALIDO


class TestEsRFCGenerico:
    """Tests para detección de RFCs genéricos."""
    
    def test_detecta_generico_extf(self):
        es_gen, desc = es_rfc_generico("EXTF900101NI1")
        assert es_gen is True
        assert desc is not None
    
    def test_detecta_generico_xaxx(self):
        es_gen, desc = es_rfc_generico("XAXX010101000")
        assert es_gen is True
    
    def test_rfc_normal_no_es_generico(self):
        es_gen, desc = es_rfc_generico("AAAA010101AAA")
        assert es_gen is False
        assert desc is None


class TestInferirTipoPersonaPorRFC:
    """Tests para inferir tipo de persona por RFC."""
    
    def test_infiere_pf_por_rfc_13(self):
        assert inferir_tipo_persona_por_rfc("AAAA010101AAA") == "fisica"
    
    def test_infiere_pm_por_rfc_12(self):
        assert inferir_tipo_persona_por_rfc("AAA010101AAA") == "moral"
    
    def test_infiere_generico(self):
        assert inferir_tipo_persona_por_rfc("EXTF900101NI1") == "generico"
    
    def test_infiere_desconocido_invalido(self):
        assert inferir_tipo_persona_por_rfc("INVALIDO") == "desconocido"


class TestDetectarTipoPersona:
    """Tests para detectar tipo persona usando RFC y nombre."""
    
    def test_detecta_por_rfc_pm(self):
        tipo, fuente = detectar_tipo_persona("EMPRESA SA", "AAA010101AAA")
        assert tipo == "moral"
        assert fuente == "rfc"
    
    def test_detecta_por_rfc_pf(self):
        tipo, fuente = detectar_tipo_persona("JUAN PEREZ", "AAAA010101AAA")
        assert tipo == "fisica"
        assert fuente == "rfc"
    
    def test_detecta_por_sufijo_sa_de_cv(self):
        tipo, fuente = detectar_tipo_persona("EMPRESA S.A. DE C.V.", None)
        assert tipo == "moral"
        assert fuente == "sufijo_corporativo"
    
    def test_detecta_por_sufijo_srl(self):
        tipo, fuente = detectar_tipo_persona("COMERCIALIZADORA S. DE R.L.", None)
        assert tipo == "moral"
        assert fuente == "sufijo_corporativo"
    
    def test_detecta_por_indicador_fideicomiso(self):
        tipo, fuente = detectar_tipo_persona("FIDEICOMISO BANCO XYZ", None)
        assert tipo == "moral"
        # FIDEICOMISO está en SUFIJOS_PERSONA_MORAL, se detecta como sufijo
        assert fuente == "sufijo_corporativo"
    
    def test_default_persona_fisica(self):
        tipo, fuente = detectar_tipo_persona("JUAN PEREZ GARCIA", None)
        assert tipo == "fisica"
        assert fuente == "default"


class TestValidarConsistenciaRFCTipo:
    """Tests para validar consistencia entre RFC y tipo declarado."""
    
    def test_consistente_pm(self):
        consistente, msg = validar_consistencia_rfc_tipo("AAA010101AAA", "moral")
        assert consistente is True
    
    def test_consistente_pf(self):
        consistente, msg = validar_consistencia_rfc_tipo("AAAA010101AAA", "fisica")
        assert consistente is True
    
    def test_inconsistente_rfc_pm_declarado_pf(self):
        """RFC de 12 chars (PM) declarado como física."""
        consistente, msg = validar_consistencia_rfc_tipo("AAA010101AAA", "fisica")
        assert consistente is False
        assert "inconsistencia" in msg.lower()
    
    def test_inconsistente_rfc_pf_declarado_pm(self):
        """RFC de 13 chars (PF) declarado como moral."""
        consistente, msg = validar_consistencia_rfc_tipo("AAAA010101AAA", "moral")
        assert consistente is False
    
    def test_generico_sin_validacion_consistencia(self):
        """RFC genérico no valida consistencia."""
        consistente, msg = validar_consistencia_rfc_tipo("EXTF900101NI1", "fisica")
        assert consistente is True


class TestValidarRFCsEstructura:
    """Tests para validación batch de RFCs en estructura accionaria."""
    
    def test_valida_estructura_simple(self):
        accionistas = [
            {"nombre": "JUAN PEREZ", "rfc": "AAAA010101AAA", "tipo": "fisica"},
            {"nombre": "EMPRESA SA DE CV", "rfc": "AAA010101AAA", "tipo": "moral"},
        ]
        resultado = validar_rfcs_estructura(accionistas)
        
        assert len(resultado) == 2
        assert resultado[0]["_rfc_valido"] is True
        assert resultado[0]["_rfc_tipo"] == "fisica"
        assert resultado[1]["_rfc_valido"] is True
        assert resultado[1]["_rfc_tipo"] == "moral"
    
    def test_detecta_inconsistencia(self):
        accionistas = [
            {"nombre": "JUAN PEREZ", "rfc": "AAA010101AAA", "tipo": "fisica"},  # Inconsistente!
        ]
        resultado = validar_rfcs_estructura(accionistas)
        
        assert resultado[0]["_rfc_consistente"] is False
    
    def test_asigna_tipo_si_no_declarado(self):
        accionistas = [
            {"nombre": "DESCONOCIDO", "rfc": "AAAA010101AAA"},  # Sin tipo
        ]
        resultado = validar_rfcs_estructura(accionistas)
        
        assert resultado[0]["tipo"] == "fisica"


class TestGenerarAlertasRFC:
    """Tests para generación de alertas de RFC."""
    
    def test_alerta_rfc_invalido(self):
        accionistas = [
            {"nombre": "JUAN PEREZ", "rfc": "INVALIDO", "_rfc_valido": False, "_rfc_mensaje": "formato incorrecto"},
        ]
        alertas = generar_alertas_rfc(accionistas)
        assert len(alertas) == 1
        assert "inválido" in alertas[0].lower()
    
    def test_alerta_rfc_inconsistente(self):
        accionistas = [
            {"nombre": "JUAN", "_rfc_consistente": False, "_alerta_rfc": "Inconsistencia detectada"},
        ]
        alertas = generar_alertas_rfc(accionistas)
        assert len(alertas) == 1
        assert "inconsistencia" in alertas[0].lower()
    
    def test_alerta_rfc_generico(self):
        accionistas = [
            {"nombre": "EXTRANJERO", "rfc": "EXTF900101NI1", "_rfc_es_generico": True, "_rfc_descripcion_generico": "Extranjero"},
        ]
        alertas = generar_alertas_rfc(accionistas)
        assert len(alertas) == 1
        assert "genérico" in alertas[0].lower()
    
    def test_alerta_pm_sin_rfc(self):
        accionistas = [
            {"nombre": "EMPRESA SA", "tipo": "moral", "rfc": None},
        ]
        alertas = generar_alertas_rfc(accionistas)
        assert len(alertas) == 1
        assert "sin rfc" in alertas[0].lower()
    
    def test_sin_alertas_estructura_correcta(self):
        accionistas = [
            {"nombre": "JUAN", "rfc": "AAAA010101AAA", "_rfc_valido": True, "_rfc_consistente": True, "tipo": "fisica"},
        ]
        alertas = generar_alertas_rfc(accionistas)
        assert len(alertas) == 0


class TestCalcularDigitoVerificador:
    """Tests para cálculo de dígito verificador."""
    
    def test_calcula_digito_pm(self):
        # RFC corto sin dígito
        rfc_sin_digito = "AAA010101AA"
        digito = calcular_digito_verificador(rfc_sin_digito)
        assert digito in "0123456789A"
    
    def test_calcula_digito_pf(self):
        rfc_sin_digito = "AAAA010101AA"
        digito = calcular_digito_verificador(rfc_sin_digito)
        assert digito in "0123456789A"


class TestValidarDigitoVerificador:
    """Tests para validación de dígito verificador."""
    
    def test_longitud_invalida(self):
        assert validar_digito_verificador("AAA") is False
        assert validar_digito_verificador("AAAA010101AAAAA") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de casos reales mexicanos
# ═══════════════════════════════════════════════════════════════════════════════

class TestCasosRealesRFC:
    """Tests con patrones de RFC comunes en México."""
    
    def test_rfc_banco(self):
        """RFC típico de banco mexicano."""
        result = validar_rfc("BBA830831LJ2", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_MORAL
    
    def test_rfc_empresa_comercial(self):
        """RFC típico de empresa comercial."""
        result = validar_rfc("RCA820101AB1", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_MORAL
    
    def test_rfc_persona_con_enie(self):
        """RFC con Ñ en apellido (Núñez, Muñoz, etc)."""
        result = validar_rfc("MUÑO800101ABC", validar_checksum=False)
        assert result.es_valido is True
        assert result.tipo == TipoRFC.PERSONA_FISICA
