"""
Tests unitarios para text_utils — funciones puras de normalización,
comparación fuzzy y parsing de fechas.
"""
from __future__ import annotations

from datetime import date

from cross_validation.services.text_utils import (
    strip_accents,
    normalizar_texto,
    normalizar_razon_social,
    normalizar_direccion,
    similitud,
    es_similar,
    comparar_nombres,
    comparar_razones_sociales,
    comparar_codigos_postales,
    parsear_fecha,
    meses_desde,
    es_vigente,
    get_valor,
    get_confiabilidad,
    get_valor_str,
)


# ═══════════════════════════════════════════════════════════════════
#  strip_accents / normalizar_texto / normalizar_razon_social
# ═══════════════════════════════════════════════════════════════════


class TestStripAccents:
    def test_acentos_basicos(self):
        assert strip_accents("café") == "cafe"
        assert strip_accents("Ñandú") == "Nandu"
        assert strip_accents("MÉXICO") == "MEXICO"

    def test_string_vacio(self):
        assert strip_accents("") == ""
        assert strip_accents(None) == ""  # type: ignore[arg-type]

    def test_sin_acentos(self):
        assert strip_accents("ABC123") == "ABC123"


class TestNormalizarTexto:
    def test_normaliza_mayusculas_y_acentos(self):
        assert normalizar_texto("México, S.A.") == "MEXICO SA"

    def test_quita_caracteres_especiales(self):
        assert normalizar_texto("RFC: ACA-230223-IA7") == "RFC ACA230223IA7"

    def test_colapsa_espacios(self):
        assert normalizar_texto("  mi   texto  ") == "MI TEXTO"

    def test_vacio(self):
        assert normalizar_texto("") == ""
        assert normalizar_texto(None) == ""  # type: ignore[arg-type]


class TestNormalizarRazonSocial:
    def test_elimina_sa_de_cv(self):
        result = normalizar_razon_social("CAPITAL X SA DE CV")
        assert "SA DE CV" not in result
        assert "CAPITAL X" in result

    def test_elimina_sapi_de_cv(self):
        result = normalizar_razon_social("AVANZA SOLIDO SAPI DE CV")
        assert "SAPI" not in result
        assert "AVANZA SOLIDO" in result

    def test_sin_sufijo(self):
        result = normalizar_razon_social("ARENOSOS")
        assert result == "ARENOSOS"

    def test_vacio(self):
        assert normalizar_razon_social("") == ""


class TestNormalizarDireccion:
    def test_expande_abreviaturas(self):
        result = normalizar_direccion("AV REFORMA NUM 123 COL CENTRO")
        assert "AVENIDA" in result
        assert "NUMERO" in result
        assert "COLONIA" in result

    def test_vacio(self):
        assert normalizar_direccion("") == ""


# ═══════════════════════════════════════════════════════════════════
#  Comparación de textos
# ═══════════════════════════════════════════════════════════════════


class TestSimilitud:
    def test_identicos(self):
        assert similitud("HOLA", "HOLA") == 1.0

    def test_muy_similares(self):
        s = similitud("CAPITAL X", "CAPITAL Y")
        assert s > 0.7

    def test_vacios(self):
        assert similitud("", "ALGO") == 0.0
        assert similitud("ALGO", "") == 0.0


class TestEsSimilar:
    def test_similares(self):
        assert es_similar("CAPITAL X SA DE CV", "CAPITAL X S A DE C V") is True

    def test_no_similares(self):
        assert es_similar("ARENOSOS", "AVANZA SOLIDO") is False


class TestCompararNombres:
    def test_mismo_nombre(self):
        ok, sim = comparar_nombres("JUAN PEREZ LOPEZ", "JUAN PEREZ LOPEZ")
        assert ok is True
        assert sim == 1.0

    def test_orden_invertido(self):
        ok, sim = comparar_nombres("JUAN PEREZ LOPEZ", "PEREZ LOPEZ JUAN")
        assert ok is True
        assert sim >= 0.85

    def test_vacios(self):
        ok, sim = comparar_nombres("", "ALGO")
        assert ok is False
        assert sim == 0.0


class TestCompararRazonesSociales:
    def test_misma_con_distinto_sufijo(self):
        ok, sim, desc = comparar_razones_sociales(
            "CAPITAL X SA DE CV", "CAPITAL X SAPI DE CV"
        )
        assert ok is True
        assert sim >= 0.85

    def test_completamente_distintas(self):
        ok, sim, desc = comparar_razones_sociales("ARENOSOS", "AVANZA SOLIDO")
        assert ok is False

    def test_vacias(self):
        ok, sim, desc = comparar_razones_sociales("", "ALGO")
        assert ok is False


class TestCompararCodigosPostales:
    def test_iguales(self):
        assert comparar_codigos_postales("06600", "06600") is True

    def test_con_caracteres_extra(self):
        assert comparar_codigos_postales("C.P. 06600", "06600") is True

    def test_distintos(self):
        assert comparar_codigos_postales("06600", "11000") is False

    def test_vacios(self):
        assert comparar_codigos_postales("", "06600") is False


# ═══════════════════════════════════════════════════════════════════
#  Parsing de fechas
# ═══════════════════════════════════════════════════════════════════


class TestParsearFecha:
    def test_iso(self):
        assert parsear_fecha("2026-02-27") == date(2026, 2, 27)

    def test_dd_mm_yyyy(self):
        assert parsear_fecha("27/02/2026") == date(2026, 2, 27)

    def test_dd_mes_yyyy(self):
        assert parsear_fecha("27 De Febrero De 2026") == date(2026, 2, 27)

    def test_formato_bancario(self):
        assert parsear_fecha("31/JUL/2025") == date(2025, 7, 31)

    def test_mes_yyyy(self):
        assert parsear_fecha("Febrero 2026") == date(2026, 2, 1)

    def test_solo_anio(self):
        assert parsear_fecha("2030") == date(2030, 12, 31)

    def test_rango_toma_ultima(self):
        result = parsear_fecha("01/09/2025 - 30/09/2025")
        assert result == date(2025, 9, 30)

    def test_none_y_vacios(self):
        assert parsear_fecha(None) is None
        assert parsear_fecha("") is None
        assert parsear_fecha("N/A") is None

    def test_date_passthrough(self):
        d = date(2026, 1, 1)
        assert parsear_fecha(d) is d


class TestMesesDesde:
    def test_mismo_mes(self):
        ref = date(2026, 2, 27)
        assert meses_desde(date(2026, 2, 1), ref) == 0

    def test_meses_anteriores(self):
        ref = date(2026, 2, 27)
        assert meses_desde(date(2025, 11, 1), ref) == 3


class TestEsVigente:
    def test_vigente(self):
        ref = date(2026, 2, 27)
        assert es_vigente(date(2026, 12, 31), ref) is True

    def test_vencido(self):
        ref = date(2026, 2, 27)
        assert es_vigente(date(2025, 12, 31), ref) is False


# ═══════════════════════════════════════════════════════════════════
#  get_valor / get_confiabilidad / get_valor_str
# ═══════════════════════════════════════════════════════════════════


class TestGetValor:
    def test_campo_con_valor(self):
        datos = {"rfc": {"valor": "ACA230223IA7", "confiabilidad": 95.0}}
        assert get_valor(datos, "rfc") == "ACA230223IA7"

    def test_campo_none(self):
        assert get_valor({"rfc": None}, "rfc") is None

    def test_campo_na(self):
        assert get_valor({"rfc": {"valor": "N/A", "confiabilidad": 0}}, "rfc") is None

    def test_campo_inexistente(self):
        assert get_valor({"rfc": {"valor": "X"}}, "nombre") is None

    def test_datos_none(self):
        assert get_valor(None, "rfc") is None


class TestGetConfiabilidad:
    def test_con_valor(self):
        datos = {"rfc": {"valor": "X", "confiabilidad": 95.5}}
        assert get_confiabilidad(datos, "rfc") == 95.5

    def test_sin_campo(self):
        assert get_confiabilidad({}, "rfc") == 0.0


class TestGetValorStr:
    def test_valor_normal(self):
        datos = {"rfc": {"valor": "ACA230223IA7", "confiabilidad": 95.0}}
        assert get_valor_str(datos, "rfc") == "ACA230223IA7"

    def test_none_devuelve_vacio(self):
        assert get_valor_str(None, "rfc") == ""
