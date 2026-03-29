"""
Tests unitarios para la Etapa 1 PLD — Verificación de completitud documental.
No requieren conexión a BD; trabajan con ExpedientePLD mock.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from pld_agent.models.schemas import (
    EtapaPLD,
    ExpedientePLD,
    ItemCompletitud,
    PersonaIdentificada,
    ResultadoCompletitud,
    SeveridadPLD,
    VerificacionCompletitud,
)
from pld_agent.services.etapa1_completitud import (
    _campo_presente,
    _detectar_poder_bancario,
    _extraer_personas_de_documentos,
    _generar_recomendaciones_etapa1,
    _obtener_datos,
    _verificar_datos_obligatorios,
    _verificar_documentos,
    _verificar_domicilio,
    _verificar_poder_bancario,
    _verificar_validacion_cruzada,
    _identificar_personas,
    ejecutar_etapa1,
)
from pld_agent.services.report_generator import generar_reporte_etapa1


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _expediente_completo() -> ExpedientePLD:
    """Expediente con todos los documentos y datos completos."""
    return ExpedientePLD(
        empresa_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        rfc="ABC123456AB1",
        razon_social="Empresa Test SA de CV",
        documentos={
            "csf": {
                "denominacion_razon_social": "Empresa Test SA de CV",
                "rfc": "ABC123456AB1",
                "actividad_economica": "Comercio al por mayor",
                "domicilio": {
                    "calle": "Av. Reforma",
                    "numero_exterior": "123",
                    "colonia": "Juárez",
                    "codigo_postal": "06600",
                    "municipio_delegacion": "Cuauhtémoc",
                    "entidad_federativa": "CDMX",
                },
            },
            "fiel": {
                "no_serie": "30001000000500003416",
                "no_certificado": "30001000000500003416",
                "rfc": "ABC123456AB1",
            },
            "acta_constitutiva": {
                "denominacion_social": "Empresa Test SA de CV",
                "objeto_social": "Comercio en general",
                "fecha_constitucion": "2020-01-15",
                "lugar_otorgamiento": "Ciudad de México, México",
                "representante_legal": "Juan Pérez López",
                "estructura_accionaria": [
                    {"nombre": "Socio Uno SA", "porcentaje": 60.0, "tipo_persona": "moral"},
                    {"nombre": "María García", "porcentaje": 40.0, "tipo_persona": "fisica"},
                ],
                "administracion": "Administrador Único: Juan Pérez López",
            },
            "poder": {
                "nombre_apoderado": "Juan Pérez López",
                "tipo_poder": "General para actos de administración",
                "facultades": "Para abrir cuentas bancarias, contratar créditos y firmar contratos",
            },
            "ine": {
                "nombre": "Juan Pérez López",
                "clave_elector": "PRLPJN80010106H800",
                "vigencia": "2029",
            },
            "domicilio": {
                "calle": "Av. Reforma",
                "numero_exterior": "123",
                "colonia": "Juárez",
                "codigo_postal": "06600",
            },
        },
        doc_types_presentes=["acta_constitutiva", "csf", "domicilio", "fiel", "ine", "poder"],
        validacion_cruzada={
            "dictamen": "APROBADO",
            "hallazgos": [],
            "recomendaciones": [],
            "documentos_presentes": ["csf", "fiel", "ine", "acta_constitutiva", "poder", "domicilio"],
            "resumen_bloques": {"datos_clave": {}},
            "total_pasan": 20,
            "total_criticos": 0,
            "total_medios": 0,
            "total_informativos": 0,
            "created_at": "2025-01-01T00:00:00",
        },
        datos_clave={
            "razon_social": "Empresa Test SA de CV",
            "rfc": "ABC123456AB1",
            "apoderados": [
                {"nombre": "Juan Pérez López", "rol": "apoderado", "fuente": "poder", "tipo_persona": "fisica"},
            ],
            "representante_legal": {"nombre": "Juan Pérez López", "rol": "representante_legal", "fuente": "acta_constitutiva", "tipo_persona": "fisica"},
            "accionistas": [
                {"nombre": "Socio Uno SA", "rol": "accionista", "fuente": "acta_constitutiva", "tipo_persona": "moral", "porcentaje": 60.0},
                {"nombre": "María García", "rol": "accionista", "fuente": "acta_constitutiva", "tipo_persona": "fisica", "porcentaje": 40.0},
            ],
            "consejo_administracion": [],
            "poder_cuenta_bancaria": True,
        },
    )


def _expediente_vacio() -> ExpedientePLD:
    """Expediente sin documentos."""
    return ExpedientePLD(
        empresa_id="11111111-2222-3333-4444-555555555555",
        rfc="ZZZ999999ZZ9",
        razon_social="Sin Docs SA",
        documentos={},
        doc_types_presentes=[],
        validacion_cruzada=None,
        datos_clave=None,
    )


def _expediente_parcial() -> ExpedientePLD:
    """Expediente con algunos documentos pero sin poder ni FIEL."""
    return ExpedientePLD(
        empresa_id="22222222-3333-4444-5555-666666666666",
        rfc="PAR123456PA1",
        razon_social="Parcial SA de CV",
        documentos={
            "csf": {
                "denominacion_razon_social": "Parcial SA de CV",
                "rfc": "PAR123456PA1",
                "actividad_economica": "Servicios",
            },
            "acta_constitutiva": {
                "denominacion_social": "Parcial SA de CV",
                "objeto_social": "Servicios de consultoría",
                "fecha_constitucion": "2019-06-01",
                "representante_legal": "Ana Torres",
                "estructura_accionaria": [
                    {"nombre": "Pedro Ríos", "porcentaje": 100.0, "tipo_persona": "fisica"},
                ],
            },
            "ine": {
                "nombre": "Ana Torres",
                "vigencia": "2028",
            },
            "estado_cuenta": {
                "titular": "Parcial SA de CV",
                "banco": "BBVA",
            },
        },
        doc_types_presentes=["acta_constitutiva", "csf", "estado_cuenta", "ine"],
        validacion_cruzada=None,
        datos_clave=None,
    )


# ═══════════════════════════════════════════════════════════════════
#  Test helpers
# ═══════════════════════════════════════════════════════════════════

class TestHelpers:
    """Tests para funciones auxiliares."""

    def test_campo_presente_string(self):
        assert _campo_presente({"a": "hola"}, "a") is True

    def test_campo_presente_string_vacio(self):
        assert _campo_presente({"a": ""}, "a") is False

    def test_campo_presente_none(self):
        assert _campo_presente({"a": None}, "a") is False

    def test_campo_presente_no_existe(self):
        assert _campo_presente({"a": "x"}, "b") is False

    def test_campo_presente_lista(self):
        assert _campo_presente({"a": [1]}, "a") is True

    def test_campo_presente_lista_vacia(self):
        assert _campo_presente({"a": []}, "a") is False

    def test_campo_presente_dict(self):
        assert _campo_presente({"a": {"k": 1}}, "a") is True

    def test_campo_presente_dict_vacio(self):
        assert _campo_presente({"a": {}}, "a") is False

    def test_campo_presente_numero(self):
        assert _campo_presente({"a": 42}, "a") is True

    def test_obtener_datos_existente(self):
        exp = _expediente_completo()
        datos = _obtener_datos(exp, "csf")
        assert "rfc" in datos

    def test_obtener_datos_no_existe(self):
        exp = _expediente_completo()
        datos = _obtener_datos(exp, "inexistente")
        assert datos == {}


# ═══════════════════════════════════════════════════════════════════
#  Test verificación de documentos
# ═══════════════════════════════════════════════════════════════════

class TestVerificacionDocumentos:
    """Tests para _verificar_documentos."""

    def test_todos_presentes(self):
        exp = _expediente_completo()
        items = _verificar_documentos(exp)
        assert all(it.presente for it in items)
        assert all(it.categoria == "DOCUMENTO" for it in items)

    def test_sin_documentos(self):
        exp = _expediente_vacio()
        items = _verificar_documentos(exp)
        assert not any(it.presente for it in items)
        assert len(items) == 5  # 5 documentos obligatorios PLD

    def test_domicilio_alternativo_estado_cuenta(self):
        """estado_cuenta debe aceptarse como comprobante de domicilio."""
        exp = _expediente_parcial()
        items = _verificar_documentos(exp)
        dom_item = next(it for it in items if "domicilio" in it.elemento.lower())
        assert dom_item.presente is True
        assert dom_item.fuente == "estado_cuenta"

    def test_falta_poder_y_fiel(self):
        exp = _expediente_parcial()
        items = _verificar_documentos(exp)
        poder_item = next(it for it in items if "poder" in it.elemento.lower())
        assert poder_item.presente is False
        # FIEL no está en la lista obligatoria PLD explícita de 5 docs,
        # pero sí está en CAMPOS_OBLIGATORIOS como dato
        fiel_items = [it for it in items if "fiel" in it.elemento.lower()]
        # fiel no es un documento obligatorio PLD (es dato obligatorio)
        assert len(fiel_items) == 0

    def test_codigos_secuenciales(self):
        exp = _expediente_completo()
        items = _verificar_documentos(exp)
        for i, it in enumerate(items, 1):
            assert it.codigo == f"PLD1.{i:02d}"


# ═══════════════════════════════════════════════════════════════════
#  Test verificación de datos obligatorios
# ═══════════════════════════════════════════════════════════════════

class TestVerificacionDatosObligatorios:
    """Tests para _verificar_datos_obligatorios."""

    def test_datos_completos(self):
        exp = _expediente_completo()
        items = _verificar_datos_obligatorios(exp)
        assert all(it.presente for it in items)

    def test_datos_sin_csf(self):
        exp = _expediente_vacio()
        items = _verificar_datos_obligatorios(exp)
        # Sin docs → todos faltantes
        faltantes = [it for it in items if not it.presente]
        assert len(faltantes) == len(items)

    def test_categoria_correcta(self):
        exp = _expediente_completo()
        items = _verificar_datos_obligatorios(exp)
        assert all(it.categoria == "DATO_OBLIGATORIO" for it in items)

    def test_severidad_critica(self):
        exp = _expediente_completo()
        items = _verificar_datos_obligatorios(exp)
        # Los campos principales son CRITICA, actividad económica es ALTA
        criticos = [it for it in items if it.severidad == SeveridadPLD.CRITICA]
        assert len(criticos) >= 4


# ═══════════════════════════════════════════════════════════════════
#  Test verificación de domicilio
# ═══════════════════════════════════════════════════════════════════

class TestVerificacionDomicilio:
    """Tests para _verificar_domicilio."""

    def test_domicilio_completo_csf(self):
        exp = _expediente_completo()
        items = _verificar_domicilio(exp)
        assert all(it.presente for it in items)

    def test_domicilio_sin_datos(self):
        exp = _expediente_vacio()
        items = _verificar_domicilio(exp)
        assert not any(it.presente for it in items)

    def test_categoria_domicilio(self):
        exp = _expediente_completo()
        items = _verificar_domicilio(exp)
        assert all(it.categoria == "DOMICILIO" for it in items)

    def test_seis_campos_domicilio(self):
        exp = _expediente_completo()
        items = _verificar_domicilio(exp)
        assert len(items) == 6


# ═══════════════════════════════════════════════════════════════════
#  Test identificación de personas
# ═══════════════════════════════════════════════════════════════════

class TestIdentificacionPersonas:
    """Tests para _identificar_personas."""

    def test_con_datos_clave(self):
        exp = _expediente_completo()
        items, personas = _identificar_personas(exp)
        # Debe encontrar: apoderado, representante y 2 accionistas
        assert len(personas) >= 3
        roles = {p.rol for p in personas}
        assert "apoderado" in roles
        assert "representante_legal" in roles
        assert "accionista" in roles

    def test_sin_datos_clave_fallback_documentos(self):
        exp = _expediente_parcial()
        items, personas = _identificar_personas(exp)
        # Debe extraer del acta: representante + 1 accionista
        assert len(personas) >= 2

    def test_personas_requieren_screening(self):
        exp = _expediente_completo()
        _, personas = _identificar_personas(exp)
        assert all(p.requiere_screening for p in personas)

    def test_items_personas_categorias(self):
        exp = _expediente_completo()
        items, _ = _identificar_personas(exp)
        assert all(it.categoria == "PERSONAS" for it in items)
        assert len(items) == 3  # apoderado, accionistas, admin

    def test_sin_documentos_sin_personas(self):
        exp = _expediente_vacio()
        items, personas = _identificar_personas(exp)
        assert len(personas) == 0
        assert not any(it.presente for it in items)

    def test_accionista_porcentaje(self):
        exp = _expediente_completo()
        _, personas = _identificar_personas(exp)
        accionistas = [p for p in personas if p.rol == "accionista"]
        assert len(accionistas) == 2
        pcts = {p.nombre: p.porcentaje for p in accionistas}
        assert pcts["Socio Uno SA"] == 60.0
        assert pcts["María García"] == 40.0

    def test_tipo_persona_moral(self):
        exp = _expediente_completo()
        _, personas = _identificar_personas(exp)
        socio = next(p for p in personas if p.nombre == "Socio Uno SA")
        assert socio.tipo_persona == "moral"


# ═══════════════════════════════════════════════════════════════════
#  Test poder bancario
# ═══════════════════════════════════════════════════════════════════

class TestPoderBancario:
    """Tests para detección de poder para cuentas bancarias."""

    def test_detecta_desde_datos_clave(self):
        exp = _expediente_completo()
        result = _detectar_poder_bancario(exp)
        assert result is True

    def test_detecta_desde_facultades_poder(self):
        exp = ExpedientePLD(
            empresa_id="test",
            rfc="TEST",
            razon_social="Test",
            documentos={
                "poder": {"facultades": "Para abrir cuentas bancarias y firmar"},
            },
            doc_types_presentes=["poder"],
            datos_clave=None,
        )
        result = _detectar_poder_bancario(exp)
        assert result is True

    def test_no_detecta_sin_keywords(self):
        exp = ExpedientePLD(
            empresa_id="test",
            rfc="TEST",
            razon_social="Test",
            documentos={
                "poder": {"facultades": "Poder general para pleitos y cobranzas"},
            },
            doc_types_presentes=["poder"],
            datos_clave=None,
        )
        result = _detectar_poder_bancario(exp)
        assert result is False

    def test_none_sin_poder(self):
        exp = _expediente_vacio()
        result = _detectar_poder_bancario(exp)
        assert result is None

    def test_item_completitud_poder_presente(self):
        exp = _expediente_completo()
        item, poder_bc = _verificar_poder_bancario(exp)
        assert poder_bc is True
        assert item.presente is True
        assert item.severidad == SeveridadPLD.INFORMATIVA

    def test_item_completitud_poder_ausente(self):
        exp = ExpedientePLD(
            empresa_id="test",
            rfc="TEST",
            razon_social="Test",
            documentos={
                "poder": {"facultades": "Pleitos y cobranzas"},
            },
            doc_types_presentes=["poder"],
            datos_clave=None,
        )
        item, poder_bc = _verificar_poder_bancario(exp)
        assert poder_bc is False
        assert item.presente is False
        assert item.severidad == SeveridadPLD.ALTA

    def test_item_completitud_sin_poder(self):
        exp = _expediente_vacio()
        item, poder_bc = _verificar_poder_bancario(exp)
        assert poder_bc is None
        assert item.presente is False
        assert item.severidad == SeveridadPLD.CRITICA


# ═══════════════════════════════════════════════════════════════════
#  Test validación cruzada (Colorado — tabla validaciones_cruzadas)
# ═══════════════════════════════════════════════════════════════════

class TestValidacionCruzada:
    """Tests para _verificar_validacion_cruzada (lee datos de la BD)."""

    def test_vc_disponible(self):
        exp = _expediente_completo()
        items, hallazgos, resumen = _verificar_validacion_cruzada(exp)
        item_vc = next(it for it in items if it.codigo == "PLD1.50")
        assert item_vc.presente is True
        assert item_vc.categoria == "VALIDACION_CRUZADA"

    def test_vc_no_disponible(self):
        exp = _expediente_vacio()
        items, hallazgos, resumen = _verificar_validacion_cruzada(exp)
        assert len(items) == 1  # Solo PLD1.50
        assert items[0].presente is False
        assert items[0].severidad == SeveridadPLD.ALTA

    def test_dictamen_aprobado(self):
        exp = _expediente_completo()
        items, _, _ = _verificar_validacion_cruzada(exp)
        item_dict = next(it for it in items if it.codigo == "PLD1.51")
        assert item_dict.presente is True
        assert item_dict.severidad == SeveridadPLD.INFORMATIVA

    def test_dictamen_rechazado(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={}, doc_types_presentes=[],
            validacion_cruzada={
                "dictamen": "RECHAZADO",
                "hallazgos": [
                    {"codigo": "V1.1", "pasa": False, "severidad": "CRITICA",
                     "mensaje": "RFC no coincide"},
                ],
                "resumen_bloques": {
                    "1": {"nombre": "IDENTIDAD", "total": 3, "pasan": 2,
                           "fallan": 1, "na": 0, "criticos": 1,
                           "medios": 0, "informativos": 0},
                },
                "total_pasan": 15, "total_criticos": 1,
                "total_medios": 0, "total_informativos": 0,
            },
        )
        items, _, _ = _verificar_validacion_cruzada(exp)
        item_dict = next(it for it in items if it.codigo == "PLD1.51")
        assert item_dict.presente is False
        assert item_dict.severidad == SeveridadPLD.CRITICA

    def test_bloques_sin_criticos_todos_pasan(self):
        exp = _expediente_completo()
        items, _, _ = _verificar_validacion_cruzada(exp)
        bloque_items = [it for it in items if it.codigo not in ("PLD1.50", "PLD1.51")]
        assert len(bloque_items) == 10
        assert all(it.presente for it in bloque_items)

    def test_bloque_con_criticos_falla(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={}, doc_types_presentes=[],
            validacion_cruzada={
                "dictamen": "RECHAZADO",
                "hallazgos": [
                    {"codigo": "V1.1", "pasa": False, "severidad": "CRITICA",
                     "mensaje": "RFC no coincide"},
                ],
                "resumen_bloques": {
                    "1": {"nombre": "IDENTIDAD", "total": 3, "pasan": 2,
                           "fallan": 1, "na": 0, "criticos": 1,
                           "medios": 0, "informativos": 0},
                },
                "total_pasan": 15, "total_criticos": 1,
                "total_medios": 0, "total_informativos": 0,
            },
        )
        items, _, _ = _verificar_validacion_cruzada(exp)
        item_b1 = next(it for it in items if it.codigo == "PLD1.52")  # Bloque 1
        assert item_b1.presente is False
        assert "cr\u00edtico" in item_b1.detalle.lower()

    def test_hallazgos_criticos_recopilados(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={}, doc_types_presentes=[],
            validacion_cruzada={
                "dictamen": "RECHAZADO",
                "hallazgos": [
                    {"codigo": "V1.1", "pasa": False, "severidad": "CRITICA",
                     "mensaje": "Fallo"},
                    {"codigo": "V1.2", "pasa": True, "severidad": "CRITICA",
                     "mensaje": "OK"},
                    {"codigo": "V2.1", "pasa": False, "severidad": "MEDIA",
                     "mensaje": "Parcial"},
                ],
                "resumen_bloques": {},
                "total_pasan": 15, "total_criticos": 1,
                "total_medios": 1, "total_informativos": 0,
            },
        )
        _, hallazgos_criticos, _ = _verificar_validacion_cruzada(exp)
        # Solo V1.1 (CRITICA + pasa=False)
        assert len(hallazgos_criticos) == 1
        assert hallazgos_criticos[0]["codigo"] == "V1.1"

    def test_resumen_excluye_datos_clave(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={}, doc_types_presentes=[],
            validacion_cruzada={
                "dictamen": "APROBADO",
                "hallazgos": [],
                "resumen_bloques": {
                    "1": {"nombre": "IDENTIDAD", "total": 3, "pasan": 3,
                           "fallan": 0, "na": 0, "criticos": 0,
                           "medios": 0, "informativos": 0},
                    "datos_clave": {"rfc": "ABC"},
                },
                "total_pasan": 3, "total_criticos": 0,
                "total_medios": 0, "total_informativos": 0,
            },
        )
        _, _, resumen = _verificar_validacion_cruzada(exp)
        assert "1" in resumen
        assert "datos_clave" not in resumen

    def test_integracion_completo_con_colorado(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.hallazgos_colorado_criticos == []
        assert isinstance(vf.resumen_colorado, dict)
        # Items de Colorado deben estar en la lista total
        vc_items = [it for it in vf.items if it.categoria == "VALIDACION_CRUZADA"]
        assert len(vc_items) == 12  # 1 disponibilidad + 1 dictamen + 10 bloques

    def test_integracion_rechazado_afecta_resultado(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={
                "csf": {"denominacion_razon_social": "T", "rfc": "T",
                         "actividad_economica": "X",
                         "domicilio": {"calle": "A", "numero_exterior": "1",
                                       "colonia": "B", "codigo_postal": "0",
                                       "municipio_delegacion": "C",
                                       "entidad_federativa": "D"}},
                "fiel": {"no_serie": "123"},
                "acta_constitutiva": {"objeto_social": "X",
                                       "fecha_constitucion": "2020-01-01",
                                       "representante_legal": "Rep",
                                       "estructura_accionaria": [{"nombre": "Acc", "porcentaje": 100}]},
                "poder": {"nombre_apoderado": "Rep",
                          "facultades": "abrir cuentas bancarias"},
                "ine": {"nombre": "Rep"},
                "domicilio": {"calle": "A"},
            },
            doc_types_presentes=["acta_constitutiva", "csf", "domicilio", "fiel", "ine", "poder"],
            validacion_cruzada={
                "dictamen": "RECHAZADO",
                "hallazgos": [
                    {"codigo": "V1.1", "pasa": False, "severidad": "CRITICA",
                     "mensaje": "RFC no coincide"},
                ],
                "resumen_bloques": {
                    "1": {"nombre": "IDENTIDAD", "total": 3, "pasan": 2,
                           "fallan": 1, "na": 0, "criticos": 1,
                           "medios": 0, "informativos": 0},
                },
                "total_pasan": 15, "total_criticos": 1,
                "total_medios": 0, "total_informativos": 0,
            },
            datos_clave={
                "apoderados": [{"nombre": "Rep", "rol": "apoderado", "fuente": "poder"}],
                "representante_legal": {"nombre": "Rep", "fuente": "acta_constitutiva"},
                "accionistas": [{"nombre": "Acc", "porcentaje": 100, "fuente": "acta_constitutiva"}],
                "consejo_administracion": [],
                "poder_cuenta_bancaria": True,
            },
        )
        vf = ejecutar_etapa1(exp)
        # RECHAZADO genera item crítico faltante
        assert vf.items_criticos_faltantes > 0
        assert any("URGENTE" in r for r in vf.recomendaciones)
        assert len(vf.hallazgos_colorado_criticos) == 1

    def test_recomendacion_colorado_rechazado(self):
        recs = _generar_recomendaciones_etapa1(
            [], [], True,
            dictamen_colorado="RECHAZADO",
            hallazgos_colorado_criticos=[{"codigo": "V1.1"}],
        )
        assert any("URGENTE" in r for r in recs)
        assert any("V1.1" in r for r in recs)

    def test_recomendacion_colorado_con_observaciones(self):
        recs = _generar_recomendaciones_etapa1(
            [], [], True,
            dictamen_colorado="APROBADO_CON_OBSERVACIONES",
        )
        assert any("observacion" in r.lower() for r in recs)


# ═══════════════════════════════════════════════════════════════════
#  Test ejecutar_etapa1 (integración)
# ═══════════════════════════════════════════════════════════════════

class TestEjecutarEtapa1:
    """Tests de integración para ejecutar_etapa1."""

    def test_expediente_completo_resultado_completo(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.resultado == ResultadoCompletitud.COMPLETO
        assert vf.items_criticos_faltantes == 0
        assert vf.items_presentes == vf.total_items
        assert vf.etapa == EtapaPLD.ETAPA_1_COMPLETITUD

    def test_expediente_vacio_resultado_incompleto(self):
        exp = _expediente_vacio()
        vf = ejecutar_etapa1(exp)
        assert vf.resultado == ResultadoCompletitud.INCOMPLETO
        assert vf.items_criticos_faltantes > 0
        assert vf.items_presentes == 0

    def test_expediente_parcial(self):
        exp = _expediente_parcial()
        vf = ejecutar_etapa1(exp)
        # Tiene algunos docs pero le falta poder (CRITICO)
        assert vf.resultado == ResultadoCompletitud.INCOMPLETO
        assert "poder" in vf.documentos_faltantes

    def test_tiene_datos_empresa(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.rfc == "ABC123456AB1"
        assert vf.razon_social == "Empresa Test SA de CV"
        assert vf.empresa_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_personas_identificadas(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert len(vf.personas_identificadas) >= 3

    def test_poder_cuenta_bancaria(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.poder_cuenta_bancaria is True

    def test_validacion_cruzada_disponible(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.validacion_cruzada_disponible is True
        assert vf.dictamen_colorado == "APROBADO"

    def test_validacion_cruzada_no_disponible(self):
        exp = _expediente_vacio()
        vf = ejecutar_etapa1(exp)
        assert vf.validacion_cruzada_disponible is False
        assert vf.dictamen_colorado == ""

    def test_recomendaciones_expediente_vacio(self):
        exp = _expediente_vacio()
        vf = ejecutar_etapa1(exp)
        assert len(vf.recomendaciones) > 0
        # Debe recomendar solicitar documentos
        assert any("SOLICITAR" in r for r in vf.recomendaciones)

    def test_recomendaciones_expediente_completo(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        # Debe al menos recomendar screening
        assert any("ETAPA 2" in r for r in vf.recomendaciones)

    def test_documentos_presentes_listados(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert "csf" in vf.documentos_presentes
        assert "poder" in vf.documentos_presentes

    def test_documentos_faltantes_vacio_cuando_completo(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert len(vf.documentos_faltantes) == 0

    def test_contadores(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.total_items > 0
        assert vf.total_items == vf.items_presentes + vf.items_faltantes

    def test_fecha_analisis(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        assert vf.fecha_analisis is not None
        assert isinstance(vf.fecha_analisis, datetime)


# ═══════════════════════════════════════════════════════════════════
#  Test recomendaciones
# ═══════════════════════════════════════════════════════════════════

class TestRecomendaciones:
    """Tests para _generar_recomendaciones_etapa1."""

    def test_recomienda_solicitar_docs(self):
        items = [
            ItemCompletitud(
                codigo="PLD1.01", categoria="DOCUMENTO",
                elemento="CSF", presente=False,
                severidad=SeveridadPLD.CRITICA,
            ),
        ]
        recs = _generar_recomendaciones_etapa1(items, [], None)
        assert any("SOLICITAR" in r for r in recs)

    def test_recomienda_poder_bancario_false(self):
        recs = _generar_recomendaciones_etapa1([], [], False)
        assert any("poder" in r.lower() or "bancaria" in r.lower() for r in recs)

    def test_recomienda_poder_bancario_none(self):
        recs = _generar_recomendaciones_etapa1([], [], None)
        assert any("poder" in r.lower() for r in recs)

    def test_recomienda_screening(self):
        personas = [
            PersonaIdentificada(nombre="Test", rol="apoderado", requiere_screening=True),
        ]
        recs = _generar_recomendaciones_etapa1([], personas, True)
        assert any("ETAPA 2" in r for r in recs)

    def test_sin_apoderado_recomienda_identificar(self):
        recs = _generar_recomendaciones_etapa1([], [], True)
        assert any("apoderado" in r.lower() or "representante" in r.lower() for r in recs)


# ═══════════════════════════════════════════════════════════════════
#  Test reporte de texto
# ═══════════════════════════════════════════════════════════════════

class TestReporteTexto:
    """Tests para generar_reporte_etapa1."""

    def test_reporte_contiene_encabezado(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "ARIZONA" in texto
        assert "ETAPA 1" in texto
        assert "PLD" in texto

    def test_reporte_contiene_empresa(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "ABC123456AB1" in texto
        assert "Empresa Test SA de CV" in texto

    def test_reporte_contiene_resultado(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "COMPLETO" in texto

    def test_reporte_incompleto(self):
        exp = _expediente_vacio()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "INCOMPLETO" in texto
        assert "❌" in texto

    def test_reporte_personas(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "Juan Pérez López" in texto
        assert "apoderado" in texto.lower()

    def test_reporte_poder_bancario_si(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "CUENTAS BANCARIAS" in texto
        assert "✅" in texto

    def test_reporte_poder_bancario_no(self):
        exp = ExpedientePLD(
            empresa_id="test",
            rfc="TEST",
            razon_social="Test SA",
            documentos={"poder": {"facultades": "Pleitos y cobranzas"}},
            doc_types_presentes=["poder"],
            datos_clave=None,
        )
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "CUENTAS BANCARIAS" in texto

    def test_reporte_recomendaciones(self):
        exp = _expediente_vacio()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "RECOMENDACIONES" in texto

    def test_reporte_fin(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "Fin del reporte" in texto

    def test_reporte_seccion_colorado(self):
        exp = _expediente_completo()
        vf = ejecutar_etapa1(exp)
        texto = generar_reporte_etapa1(vf)
        assert "VALIDACI\u00d3N CRUZADA" in texto
        assert "COLORADO" in texto


# ═══════════════════════════════════════════════════════════════════
#  Test extraer personas de documentos (fallback sin datos_clave)
# ═══════════════════════════════════════════════════════════════════

class TestExtraerPersonasDocumentos:
    """Tests para _extraer_personas_de_documentos (fallback)."""

    def test_extrae_de_poder(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={"poder": {"nombre_apoderado": "Luis Martínez"}},
            doc_types_presentes=["poder"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        assert len(personas) == 1
        assert personas[0].nombre == "Luis Martínez"
        assert personas[0].rol == "apoderado"

    def test_extrae_de_acta_representante_string(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={"acta_constitutiva": {"representante_legal": "Ana López"}},
            doc_types_presentes=["acta_constitutiva"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        assert any(p.rol == "representante_legal" for p in personas)

    def test_extrae_de_acta_representante_dict(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={"acta_constitutiva": {"representante_legal": {"nombre": "Ana López"}}},
            doc_types_presentes=["acta_constitutiva"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        assert any(p.nombre == "Ana López" and p.rol == "representante_legal" for p in personas)

    def test_extrae_accionistas_de_acta(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={
                "acta_constitutiva": {
                    "estructura_accionaria": [
                        {"nombre": "Acc1", "porcentaje": 50.0},
                        {"nombre": "Acc2", "porcentaje": 50.0},
                    ],
                },
            },
            doc_types_presentes=["acta_constitutiva"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        accionistas = [p for p in personas if p.rol == "accionista"]
        assert len(accionistas) == 2

    def test_extrae_consejo_de_reforma_string(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={
                "reforma_estatutos": {
                    "consejo_administracion": ["Consejero A", "Consejero B"],
                },
            },
            doc_types_presentes=["reforma_estatutos"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        consejeros = [p for p in personas if p.rol == "consejero"]
        assert len(consejeros) == 2

    def test_extrae_consejo_de_reforma_dict(self):
        exp = ExpedientePLD(
            empresa_id="t", rfc="T", razon_social="T",
            documentos={
                "reforma_estatutos": {
                    "consejo_administracion": [
                        {"nombre": "Consejero C"},
                    ],
                },
            },
            doc_types_presentes=["reforma_estatutos"],
        )
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        assert len(personas) == 1
        assert personas[0].nombre == "Consejero C"

    def test_sin_documentos_sin_personas(self):
        exp = _expediente_vacio()
        personas: list[PersonaIdentificada] = []
        _extraer_personas_de_documentos(exp, personas)
        assert len(personas) == 0
