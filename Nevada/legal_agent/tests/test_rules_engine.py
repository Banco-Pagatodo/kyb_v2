"""
Tests unitarios para el motor de reglas del Dictamen Jurídico (Nevada).

Cubre:
- Reglas R1-R9 con escenarios de éxito y fallo
- Lógica de dictamen (FAVORABLE, FAVORABLE_CON_CONDICIONES, NO_FAVORABLE)
- Helpers y extractores de datos
"""
from __future__ import annotations

import pytest

from ..models.schemas import ExpedienteLegal, ReglaEvaluada, ResultadoReglas
from ..services.rules_engine import (
    _es_extranjero_pm,
    _evaluar_actividad,
    _evaluar_administracion,
    _evaluar_apoderado,
    _evaluar_consistencia_pld,
    _evaluar_constitucion,
    _evaluar_denominacion,
    _evaluar_facultades_firma,
    _evaluar_folio_mercantil,
    _evaluar_tenencia,
    _get_doc,
    _safe_str,
    _unwrap,
    evaluar_reglas,
    extraer_actividad,
    extraer_administracion,
    extraer_apoderados,
    extraer_datos_constitucion,
    extraer_tenencia,
)

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _base_exp(**kwargs) -> ExpedienteLegal:
    """Crea un ExpedienteLegal mínimo para tests."""
    defaults = dict(
        empresa_id="00000000-0000-0000-0000-000000000001",
        rfc="ABC120101AAA",
        razon_social="EMPRESA TEST SA DE CV",
        documentos={},
    )
    defaults.update(kwargs)
    return ExpedienteLegal(**defaults)


def _exp_completa() -> ExpedienteLegal:
    """Expediente con todos los documentos necesarios para pasar las 9 reglas."""
    return _base_exp(
        documentos={
            "acta_constitutiva": {
                "denominacion_social": "EMPRESA TEST SA DE CV",
                "numero_escritura_poliza": "12345",
                "fecha_constitucion": "2020-01-15",
                "numero_notaria": "99",
                "nombre_notario": "LIC. JUAN PEREZ",
                "folio_mercantil": "N-2020-123456",
                "objeto_social": "Comercialización de productos diversos.",
                "estructura_accionaria": [
                    {"nombre": "SOCIO A", "porcentaje": 60},
                    {"nombre": "SOCIO B", "porcentaje": 40},
                ],
                "consejo_administracion": [
                    {"nombre": "DIRECTOR A", "cargo": "Presidente"},
                ],
            },
            "csf": {
                "razon_social": "EMPRESA TEST SA DE CV",
                "actividad_economica": "Comercio al por menor",
            },
            "poder": {
                "apoderado": "JUAN PEREZ LOPEZ",
                "facultades": "actos de administración y apertura de cuentas bancarias",
                "tipo_poder": "General",
                "numero_escritura": "67890",
                "fecha_otorgamiento": "2021-06-01",
                "nombre_notario": "LIC. MARIA GARCIA",
                "numero_notaria": "50",
                "estado_notaria": "CDMX",
            },
            "ine": {
                "nombre_completo": "JUAN PEREZ LOPEZ",
            },
        },
        analisis_pld={"resultado": "SIN_ALERTAS", "screening": {"resultado_global": "limpio"}},
    )


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_safe_str_none(self):
        assert _safe_str(None) == ""

    def test_safe_str_string(self):
        assert _safe_str("  hola  ") == "hola"

    def test_safe_str_dict_valor(self):
        assert _safe_str({"valor": "abc", "pagina": 1}) == "abc"

    def test_safe_str_dict_valor_none(self):
        assert _safe_str({"valor": None}) == ""

    def test_unwrap_plain(self):
        assert _unwrap("texto") == "texto"

    def test_unwrap_dict(self):
        assert _unwrap({"valor": [1, 2], "pagina": 3}) == [1, 2]

    def test_get_doc_existente(self):
        exp = _base_exp(documentos={"acta_constitutiva": {"campo": "x"}})
        assert _get_doc(exp, "acta_constitutiva") == {"campo": "x"}

    def test_get_doc_inexistente(self):
        exp = _base_exp()
        assert _get_doc(exp, "acta_constitutiva") == {}

    def test_es_extranjero_pm_ltd(self):
        assert _es_extranjero_pm("Acme Ltd") is True

    def test_es_extranjero_pm_sa_de_cv(self):
        assert _es_extranjero_pm("Empresa SA de CV") is False

    def test_es_extranjero_pm_llc(self):
        assert _es_extranjero_pm("Holdings LLC") is True

    def test_es_extranjero_pm_inc(self):
        assert _es_extranjero_pm("Tech Inc.") is True


# ═══════════════════════════════════════════════════════════════════
#  R1: Denominación Social
# ═══════════════════════════════════════════════════════════════════

class TestR1Denominacion:
    def test_cumple_con_acta(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"denominacion_social": "MI EMPRESA"},
        })
        r = _evaluar_denominacion(exp)
        assert r.cumple is True
        assert r.codigo == "R1"

    def test_cumple_con_csf(self):
        exp = _base_exp(documentos={
            "csf": {"razon_social": "MI EMPRESA"},
        })
        r = _evaluar_denominacion(exp)
        assert r.cumple is True

    def test_falla_sin_documentos(self):
        exp = _base_exp()
        r = _evaluar_denominacion(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"

    def test_cambio_denominacion_con_reforma(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"denominacion_social": "NOMBRE A"},
            "csf": {"razon_social": "NOMBRE B"},
            "reforma": {"algo": True},
        })
        r = _evaluar_denominacion(exp)
        assert r.cumple is True
        assert r.severidad == "INFORMATIVA"

    def test_cambio_denominacion_sin_reforma(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"denominacion_social": "NOMBRE A"},
            "csf": {"razon_social": "NOMBRE B"},
        })
        r = _evaluar_denominacion(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"


# ═══════════════════════════════════════════════════════════════════
#  R2: Datos de Constitución
# ═══════════════════════════════════════════════════════════════════

class TestR2Constitucion:
    def test_cumple_completo(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "numero_escritura_poliza": "123",
                "fecha_constitucion": "2020-01-01",
                "numero_notaria": "99",
                "nombre_notario": "Lic. Pérez",
            },
        })
        r = _evaluar_constitucion(exp)
        assert r.cumple is True

    def test_falla_sin_acta(self):
        exp = _base_exp()
        r = _evaluar_constitucion(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"

    def test_falla_campos_faltantes(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "numero_escritura_poliza": "123",
                # falta fecha, notario
            },
        })
        r = _evaluar_constitucion(exp)
        assert r.cumple is False
        assert "faltantes" in r.detalle.lower()


# ═══════════════════════════════════════════════════════════════════
#  R3: Folio Mercantil Electrónico
# ═══════════════════════════════════════════════════════════════════

class TestR3FolioMercantil:
    def test_cumple_con_fme(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"folio_mercantil": "N-2020-123"},
        })
        r = _evaluar_folio_mercantil(exp)
        assert r.cumple is True

    def test_falla_sin_fme(self):
        exp = _base_exp(documentos={"acta_constitutiva": {}})
        r = _evaluar_folio_mercantil(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"


# ═══════════════════════════════════════════════════════════════════
#  R4: Actividad / Giro
# ═══════════════════════════════════════════════════════════════════

class TestR4Actividad:
    def test_cumple_con_objeto_social(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"objeto_social": "Comercialización"},
        })
        r = _evaluar_actividad(exp)
        assert r.cumple is True

    def test_cumple_con_csf(self):
        exp = _base_exp(documentos={
            "csf": {"actividad_economica": "Comercio"},
        })
        r = _evaluar_actividad(exp)
        assert r.cumple is True

    def test_falla_sin_actividad(self):
        exp = _base_exp(documentos={"acta_constitutiva": {}, "csf": {}})
        r = _evaluar_actividad(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"


# ═══════════════════════════════════════════════════════════════════
#  R5: Tenencia Accionaria
# ═══════════════════════════════════════════════════════════════════

class TestR5Tenencia:
    def test_cumple_100_porciento(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "A", "porcentaje": 50},
                    {"nombre": "B", "porcentaje": 50},
                ],
            },
        })
        r = _evaluar_tenencia(exp)
        assert r.cumple is True

    def test_falla_sin_accionistas(self):
        exp = _base_exp(documentos={"acta_constitutiva": {}})
        r = _evaluar_tenencia(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"

    def test_falla_porcentaje_bajo(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "A", "porcentaje": 30},
                    {"nombre": "B", "porcentaje": 20},
                ],
            },
        })
        r = _evaluar_tenencia(exp)
        assert r.cumple is False
        assert "50.0%" in r.detalle


# ═══════════════════════════════════════════════════════════════════
#  R6: Régimen de Administración
# ═══════════════════════════════════════════════════════════════════

class TestR6Administracion:
    def test_cumple_con_consejo(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "consejo_administracion": [{"nombre": "Dir A", "cargo": "Presidente"}],
            },
        })
        r = _evaluar_administracion(exp)
        assert r.cumple is True

    def test_cumple_admin_unico(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"administrador_unico": "DIRECTOR X"},
        })
        r = _evaluar_administracion(exp)
        assert r.cumple is True

    def test_falla_sin_admin(self):
        exp = _base_exp(documentos={"acta_constitutiva": {}})
        r = _evaluar_administracion(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"


# ═══════════════════════════════════════════════════════════════════
#  R7: Representante Legal / Apoderado
# ═══════════════════════════════════════════════════════════════════

class TestR7Apoderado:
    def test_cumple_con_poder_e_ine(self):
        exp = _base_exp(documentos={
            "poder": {"apoderado": "JUAN PEREZ"},
            "ine": {"nombre_completo": "JUAN PEREZ"},
        })
        r = _evaluar_apoderado(exp)
        assert r.cumple is True

    def test_falla_sin_poder(self):
        exp = _base_exp(documentos={"ine": {"nombre_completo": "X"}})
        r = _evaluar_apoderado(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"

    def test_falla_sin_ine(self):
        exp = _base_exp(documentos={"poder": {"apoderado": "X"}})
        r = _evaluar_apoderado(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"

    def test_falla_sin_nombre_apoderado(self):
        exp = _base_exp(documentos={
            "poder": {"facultades": "algo"},
            "ine": {"nombre_completo": "X"},
        })
        r = _evaluar_apoderado(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"


# ═══════════════════════════════════════════════════════════════════
#  R8: Facultades para Firma
# ═══════════════════════════════════════════════════════════════════

class TestR8Facultades:
    def test_cumple_con_admin(self):
        exp = _base_exp(documentos={
            "poder": {
                "apoderado": "X",
                "facultades": "actos de administración",
                "tipo_poder": "General",
            },
        })
        r = _evaluar_facultades_firma(exp)
        assert r.cumple is True

    def test_cumple_con_apertura(self):
        exp = _base_exp(documentos={
            "poder": {
                "apoderado": "X",
                "facultades": "abrir y cancelar cuentas bancarias",
            },
        })
        r = _evaluar_facultades_firma(exp)
        assert r.cumple is True

    def test_falla_sin_poder(self):
        exp = _base_exp()
        r = _evaluar_facultades_firma(exp)
        assert r.cumple is False

    def test_falla_sin_facultades(self):
        exp = _base_exp(documentos={
            "poder": {"apoderado": "X", "facultades": "nada relevante"},
        })
        r = _evaluar_facultades_firma(exp)
        assert r.cumple is False


# ═══════════════════════════════════════════════════════════════════
#  R9: Consistencia PLD
# ═══════════════════════════════════════════════════════════════════

class TestR9ConsistenciaPLD:
    def test_cumple_con_pld_limpio(self):
        exp = _base_exp(analisis_pld={
            "resultado": "SIN_ALERTAS",
            "screening": {"resultado_global": "limpio"},
        })
        r = _evaluar_consistencia_pld(exp)
        assert r.cumple is True

    def test_falla_sin_pld(self):
        exp = _base_exp()
        r = _evaluar_consistencia_pld(exp)
        assert r.cumple is False
        assert r.severidad == "MEDIA"

    def test_falla_coincidencia_critica(self):
        exp = _base_exp(analisis_pld={
            "screening": {"resultado_global": "COINCIDENCIA_CRITICA"},
        })
        r = _evaluar_consistencia_pld(exp)
        assert r.cumple is False
        assert r.severidad == "CRITICA"


# ═══════════════════════════════════════════════════════════════════
#  evaluar_reglas — lógica de dictamen
# ═══════════════════════════════════════════════════════════════════

class TestEvaluarReglas:
    def test_favorable_completo(self):
        exp = _exp_completa()
        res = evaluar_reglas(exp)
        assert res.dictamen_sugerido == "FAVORABLE"
        assert res.total_criticas_fallidas == 0
        assert len(res.reglas) == 9

    def test_no_favorable_por_critica(self):
        """Una regla CRITICA fallida → NO_FAVORABLE."""
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "denominacion_social": "EMPRESA",
                "numero_escritura_poliza": "1",
                "fecha_constitucion": "2020-01-01",
                "numero_notaria": "1",
                "nombre_notario": "N",
                "folio_mercantil": "FM-1",
                "objeto_social": "Comercio",
                "estructura_accionaria": [{"nombre": "A", "porcentaje": 100}],
                "consejo_administracion": [{"nombre": "X"}],
            },
            # Sin poder ni INE → R7 CRITICA falla
        }, analisis_pld={"resultado": "ok", "screening": {"resultado_global": "limpio"}})
        res = evaluar_reglas(exp)
        assert res.dictamen_sugerido == "NO_FAVORABLE"
        assert res.total_criticas_fallidas >= 1

    def test_favorable_con_condiciones_por_medias(self):
        """3+ reglas MEDIA fallidas → FAVORABLE_CON_CONDICIONES."""
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "denominacion_social": "EMPRESA",
                # Falta numero_notario → R2 MEDIA
                "numero_escritura_poliza": "1",
                "fecha_constitucion": "2020-01-01",
                # Falta FME → R3 MEDIA
                # Falta objeto_social → R4 MEDIA
                "estructura_accionaria": [{"nombre": "A", "porcentaje": 100}],
                "consejo_administracion": [{"nombre": "X"}],
            },
            "poder": {
                "apoderado": "JUAN",
                "facultades": "actos de administración",
            },
            "ine": {"nombre_completo": "JUAN"},
        }, analisis_pld={"resultado": "ok", "screening": {"resultado_global": "limpio"}})
        res = evaluar_reglas(exp)
        assert res.total_medias_fallidas > 2
        assert res.total_criticas_fallidas == 0
        assert res.dictamen_sugerido == "FAVORABLE_CON_CONDICIONES"

    def test_resumen_contiene_info(self):
        exp = _exp_completa()
        res = evaluar_reglas(exp)
        assert "reglas cumplidas" in res.resumen
        assert "Dictamen sugerido" in res.resumen


# ═══════════════════════════════════════════════════════════════════
#  Extractores de datos
# ═══════════════════════════════════════════════════════════════════

class TestExtractores:
    def test_extraer_constitucion(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "numero_escritura_poliza": "12345",
                "fecha_constitucion": "2020-01-15",
                "numero_notaria": "99",
                "nombre_notario": "NOTARIO X",
                "folio_mercantil": "FM-123",
            },
        })
        datos = extraer_datos_constitucion(exp)
        assert datos.escritura_numero == "12345"
        assert datos.nombre_notario == "NOTARIO X"
        assert datos.folio_mercantil == "FM-123"

    def test_extraer_actividad_con_reforma(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"objeto_social": "Original"},
            "reforma": {
                "objeto_social": "Modificado",
                "numero_escritura": "999",
            },
        })
        act = extraer_actividad(exp)
        assert act.actividad_giro == "Modificado"
        assert act.sufrio_modificaciones is True
        assert act.fuente_documento == "reforma"

    def test_extraer_tenencia_con_extranjero(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "Empresa Nacional SA", "porcentaje": 60},
                    {"nombre": "Acme Ltd", "porcentaje": 40},
                ],
            },
        })
        ten = extraer_tenencia(exp)
        assert len(ten.accionistas) == 2
        assert ten.hay_extranjeros is True
        ext = [a for a in ten.accionistas if a.es_extranjero]
        assert len(ext) == 1
        assert "Acme" in ext[0].nombre

    def test_extraer_tenencia_exclusion_extranjeros(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "clausula_extranjeros": "Cláusula de Exclusión de extranjeros",
                "estructura_accionaria": [
                    {"nombre": "Foreign Ltd", "porcentaje": 100},
                ],
            },
        })
        ten = extraer_tenencia(exp)
        assert ten.hay_extranjeros is False

    def test_extraer_administracion_consejo(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {
                "consejo_administracion": [
                    {"nombre": "Director A", "cargo": "Presidente"},
                    {"nombre": "Director B", "cargo": "Secretario"},
                ],
            },
        })
        admin = extraer_administracion(exp)
        assert admin.tipo == "consejo_administracion"
        assert len(admin.miembros) == 2

    def test_extraer_administracion_unico(self):
        exp = _base_exp(documentos={
            "acta_constitutiva": {"administrador_unico": "DIRECTOR X"},
        })
        admin = extraer_administracion(exp)
        assert admin.tipo == "administrador_unico"
        assert admin.miembros[0].nombre == "DIRECTOR X"

    def test_extraer_apoderados_con_facultades(self):
        exp = _base_exp(documentos={
            "poder": {
                "apoderado": "REPRESENTANTE",
                "facultades": "actos de administración y apertura de cuentas bancarias",
                "tipo_poder": "General",
            },
            "ine": {"nombre_completo": "REPRESENTANTE"},
        })
        aps = extraer_apoderados(exp)
        assert len(aps) == 1
        assert aps[0].nombre == "REPRESENTANTE"
        assert aps[0].facultades.administracion is True
        assert aps[0].facultades.apertura_cuentas is True
        assert aps[0].puede_firmar_contrato is True

    def test_extraer_apoderados_sin_poder(self):
        exp = _base_exp()
        aps = extraer_apoderados(exp)
        assert aps == []
