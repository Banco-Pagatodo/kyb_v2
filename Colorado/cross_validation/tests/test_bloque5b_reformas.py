"""
Tests unitarios para bloque5b_reformas.py
Valida cruce cronológico de reformas, consistencia RFC, cross-reference y alertas PLD.
"""
from __future__ import annotations

import pytest

from cross_validation.models.schemas import ExpedienteEmpresa, Severidad
from cross_validation.services.validators.bloque5b_reformas import (
    validar,
    determinar_estructura_vigente,
    EstructuraVigente,
    AlertaEstructura,
    UMBRAL_PROPIETARIO_REAL,
    UMBRAL_BENEFICIARIO_CONTROLADOR,
    _validar_formato_rfc,
    _detectar_tipo_persona_por_nombre,
    _inferir_tipo_persona,
    _cross_reference_accionistas,
    _detectar_estructura_multicapa,
    _detectar_jurisdiccion_riesgo,
    _detectar_rfc_inconsistente,
    _detectar_documentacion_incompleta,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _exp(
    rfc: str = "TST000101AA0",
    razon_social: str = "EMPRESA TEST SA DE CV",
    documentos: dict | None = None,
    doc_types: list[str] | None = None,
) -> ExpedienteEmpresa:
    docs = documentos or {}
    return ExpedienteEmpresa(
        empresa_id="00000000-0000-0000-0000-000000000001",
        rfc=rfc,
        razon_social=razon_social,
        documentos=docs,
        doc_types_presentes=doc_types or list(docs.keys()),
    )


def _dato(valor, confiabilidad: float = 95.0) -> dict:
    return {"valor": valor, "confiabilidad": confiabilidad}


# ═══════════════════════════════════════════════════════════════════
#  Tests de validación de RFC
# ═══════════════════════════════════════════════════════════════════

class TestValidarFormatoRFC:
    def test_rfc_pm_valido(self):
        """RFC PM 12 caracteres válido."""
        valido, tipo = _validar_formato_rfc("ABC120101AA0")
        assert valido is True
        assert tipo == "moral"
    
    def test_rfc_pf_valido(self):
        """RFC PF 13 caracteres válido."""
        valido, tipo = _validar_formato_rfc("GARC850101HDF")
        assert valido is True
        assert tipo == "fisica"
    
    def test_rfc_generico(self):
        """RFC genérico reconocido."""
        valido, tipo = _validar_formato_rfc("XAXX010101000")
        assert valido is True
        assert tipo == "generico"
    
    def test_rfc_invalido_corto(self):
        """RFC muy corto es inválido."""
        valido, tipo = _validar_formato_rfc("ABC")
        assert valido is False
        assert tipo == "invalido"
    
    def test_rfc_vacio(self):
        """RFC vacío es inválido."""
        valido, tipo = _validar_formato_rfc("")
        assert valido is False
        assert tipo == "invalido"
    
    def test_rfc_normaliza_espacios(self):
        """RFC con espacios se normaliza."""
        valido, tipo = _validar_formato_rfc("ABC 120101 AA0")
        assert valido is True
        assert tipo == "moral"


class TestDetectarTipoPersonaPorNombre:
    def test_detecta_sa_de_cv(self):
        """Detecta PM por sufijo S.A. de C.V."""
        assert _detectar_tipo_persona_por_nombre("EMPRESA XYZ SA DE CV") == "moral"
    
    def test_detecta_sapi(self):
        """Detecta PM por sufijo S.A.P.I."""
        assert _detectar_tipo_persona_por_nombre("HOLDING SAPI DE CV") == "moral"
    
    def test_detecta_fideicomiso(self):
        """Detecta PM por indicador FIDEICOMISO."""
        assert _detectar_tipo_persona_por_nombre("FIDEICOMISO BANCO XYZ") == "moral"
    
    def test_detecta_pf_por_default(self):
        """Sin sufijo corporativo retorna fisica."""
        assert _detectar_tipo_persona_por_nombre("JUAN PEREZ GONZALEZ") == "fisica"
    
    def test_nombre_vacio(self):
        """Nombre vacío retorna desconocido."""
        assert _detectar_tipo_persona_por_nombre("") == "desconocido"


class TestInferirTipoPersona:
    def test_prioriza_rfc(self):
        """RFC tiene prioridad sobre nombre."""
        accionista = {"rfc": "ABC120101AA0", "nombre": "JUAN PEREZ"}
        tipo, fuente = _inferir_tipo_persona(accionista)
        assert tipo == "moral"
        assert fuente == "rfc"
    
    def test_fallback_a_nombre(self):
        """Sin RFC, usa el nombre."""
        accionista = {"nombre": "EMPRESA SA DE CV"}
        tipo, fuente = _inferir_tipo_persona(accionista)
        assert tipo == "moral"
        assert fuente == "nombre"
    
    def test_usa_tipo_declarado(self):
        """Usa tipo declarado si no hay RFC."""
        accionista = {"nombre": "ALGO", "tipo_persona": "moral"}
        tipo, fuente = _inferir_tipo_persona(accionista)
        assert tipo == "moral"
        assert fuente == "declarado"


# ═══════════════════════════════════════════════════════════════════
#  Tests de estructura vigente
# ═══════════════════════════════════════════════════════════════════

class TestDeterminarEstructuraVigente:
    def test_sin_reformas(self):
        """Sin reformas, usa acta constitutiva."""
        acta = {
            "estructura_accionaria": [
                {"nombre": "SOCIO A", "porcentaje": 50},
                {"nombre": "SOCIO B", "porcentaje": 50},
            ],
            "fecha_constitucion": "2020-01-15",
        }
        resultado = determinar_estructura_vigente(acta, [])
        
        assert resultado.fuente_final == "acta_constitutiva"
        assert len(resultado.accionistas) == 2
        assert resultado.reformas_aplicadas == 0
    
    def test_con_reforma_inscrita(self):
        """Reforma inscrita actualiza la estructura."""
        acta = {
            "estructura_accionaria": [
                {"nombre": "SOCIO A", "porcentaje": 50},
                {"nombre": "SOCIO B", "porcentaje": 50},
            ],
        }
        reforma = {
            "estructura_accionaria": [
                {"nombre": "SOCIO A", "porcentaje": 60},
                {"nombre": "SOCIO B", "porcentaje": 30},
                {"nombre": "SOCIO C", "porcentaje": 10},
            ],
            "inscrita": True,
            "fecha_asamblea": "2023-06-01",
        }
        resultado = determinar_estructura_vigente(acta, [reforma])
        
        assert resultado.fuente_final == "reforma_estatutos"
        assert len(resultado.accionistas) == 3
        assert resultado.reformas_aplicadas == 1
    
    def test_reforma_no_inscrita_genera_alerta(self):
        """Reforma no inscrita genera alerta y no se aplica."""
        acta = {"estructura_accionaria": [{"nombre": "SOCIO A", "porcentaje": 100}]}
        reforma = {
            "estructura_accionaria": [{"nombre": "SOCIO B", "porcentaje": 100}],
            "inscrita": False,
            "fecha_asamblea": "2023-06-01",
        }
        resultado = determinar_estructura_vigente(acta, [reforma])
        
        assert resultado.fuente_final == "acta_constitutiva"
        assert resultado.reformas_no_inscritas == 1
        assert len(resultado.alertas) == 1
        assert resultado.alertas[0]["codigo"] == "REF001"


# ═══════════════════════════════════════════════════════════════════
#  Tests de cross-reference
# ═══════════════════════════════════════════════════════════════════

class TestCrossReferenceAccionistas:
    def test_detecta_nuevo_accionista(self):
        """Detecta accionista nuevo en reforma."""
        acta = [{"nombre": "JUAN PEREZ", "porcentaje": 100}]
        reforma = [
            {"nombre": "JUAN PEREZ", "porcentaje": 60},
            {"nombre": "MARIA LOPEZ", "porcentaje": 40},
        ]
        resultado = _cross_reference_accionistas(acta, reforma)
        
        assert len(resultado["permanecen"]) == 1
        assert len(resultado["nuevos"]) == 1
        assert "MARIA LOPEZ" in resultado["nuevos"][0].upper()
    
    def test_detecta_accionista_saliente(self):
        """Detecta accionista que salió."""
        acta = [
            {"nombre": "JUAN PEREZ", "porcentaje": 50},
            {"nombre": "PEDRO SANCHEZ", "porcentaje": 50},
        ]
        reforma = [{"nombre": "JUAN PEREZ", "porcentaje": 100}]
        resultado = _cross_reference_accionistas(acta, reforma)
        
        assert len(resultado["salieron"]) == 1
        assert "PEDRO SANCHEZ" in resultado["salieron"][0].upper()
    
    def test_detecta_cambio_porcentaje(self):
        """Detecta cambio de porcentaje."""
        acta = [{"nombre": "JUAN PEREZ", "porcentaje": 50}]
        reforma = [{"nombre": "JUAN PEREZ", "porcentaje": 80}]
        resultado = _cross_reference_accionistas(acta, reforma)
        
        assert len(resultado["discrepancias"]) == 1
        assert resultado["discrepancias"][0]["cambio"] == 30


# ═══════════════════════════════════════════════════════════════════
#  Tests de alertas PLD
# ═══════════════════════════════════════════════════════════════════

class TestDetectarEstructuraMulticapa:
    def test_detecta_multicapa(self):
        """Detecta 2+ PM con >25%."""
        accionistas = [
            {"nombre": "HOLDING A SA DE CV", "tipo_persona": "moral", "porcentaje": 40},
            {"nombre": "HOLDING B SA DE CV", "tipo_persona": "moral", "porcentaje": 35},
            {"nombre": "JUAN PEREZ", "tipo_persona": "fisica", "porcentaje": 25},
        ]
        alertas = _detectar_estructura_multicapa(accionistas)
        
        assert len(alertas) >= 1
        assert any(a.codigo == "EST001" for a in alertas)
    
    def test_no_alerta_single_pm(self):
        """Una sola PM >25% no genera alerta de multicapa."""
        accionistas = [
            {"nombre": "HOLDING SA DE CV", "tipo_persona": "moral", "porcentaje": 60},
            {"nombre": "JUAN PEREZ", "tipo_persona": "fisica", "porcentaje": 40},
        ]
        alertas = _detectar_estructura_multicapa(accionistas)
        
        # Genera alerta de perforación pero no de multicapa
        assert not any(a.codigo == "EST001" for a in alertas)


class TestDetectarJurisdiccionRiesgo:
    def test_detecta_pais_alto_riesgo(self):
        """Detecta accionista con nacionalidad de alto riesgo."""
        accionistas = [
            {"nombre": "EMPRESA IRANIANA", "nacionalidad": "IRAN", "porcentaje": 10},
        ]
        alertas = _detectar_jurisdiccion_riesgo(accionistas)
        
        assert len(alertas) == 1
        assert alertas[0].codigo == "EST004"
        assert alertas[0].severidad == "critica"
    
    def test_no_alerta_mexico(self):
        """No genera alerta para MEXICO."""
        accionistas = [
            {"nombre": "EMPRESA MEXICANA", "nacionalidad": "MEXICO", "porcentaje": 100},
        ]
        alertas = _detectar_jurisdiccion_riesgo(accionistas)
        
        assert len(alertas) == 0


class TestDetectarRFCInconsistente:
    def test_detecta_rfc_invalido(self):
        """Detecta RFC con formato inválido."""
        accionistas = [
            {"nombre": "EMPRESA X", "rfc": "ABC", "tipo_persona": "moral"},
        ]
        alertas = _detectar_rfc_inconsistente(accionistas)
        
        assert len(alertas) == 1
        assert alertas[0].codigo == "RFC001"
    
    def test_detecta_inconsistencia_tipo(self):
        """Detecta RFC PM pero declarado como PF."""
        accionistas = [
            {"nombre": "ALGO", "rfc": "ABC120101AA0", "tipo_persona": "fisica"},
        ]
        alertas = _detectar_rfc_inconsistente(accionistas)
        
        assert len(alertas) == 1
        assert alertas[0].codigo == "RFC002"
    
    def test_no_alerta_consistente(self):
        """No genera alerta cuando RFC es consistente."""
        accionistas = [
            {"nombre": "EMPRESA SA DE CV", "rfc": "EMP120101AA0", "tipo_persona": "moral"},
        ]
        alertas = _detectar_rfc_inconsistente(accionistas)
        
        assert len(alertas) == 0


class TestDetectarDocumentacionIncompleta:
    def test_detecta_sin_rfc(self):
        """Detecta accionista >10% sin RFC."""
        accionistas = [
            {"nombre": "JUAN PEREZ", "porcentaje": 30},
        ]
        alertas = _detectar_documentacion_incompleta(accionistas)
        
        assert len(alertas) == 1
        assert alertas[0].codigo == "EST005"
    
    def test_no_alerta_menor_umbral(self):
        """No alerta para accionista <10%."""
        accionistas = [
            {"nombre": "MARIA LOPEZ", "porcentaje": 5},
        ]
        alertas = _detectar_documentacion_incompleta(accionistas)
        
        assert len(alertas) == 0


# ═══════════════════════════════════════════════════════════════════
#  Tests de validaciones completas (V5.5 - V5.10)
# ═══════════════════════════════════════════════════════════════════

class TestV55CruceCronologico:
    def test_sin_reformas(self):
        """V5.5: Sin reformas retorna informativo."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [{"nombre": "SOCIO A", "porcentaje": 100}],
            }
        })
        hallazgos = validar(exp)
        v55 = [h for h in hallazgos if h.codigo == "V5.5"]
        
        assert len(v55) == 1
        assert v55[0].pasa is True
        assert "Sin reformas" in v55[0].mensaje


class TestV56ConsistenciaRFC:
    def test_rfcs_validos(self):
        """V5.6: RFCs válidos pasa."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "HOLDING SA DE CV", "rfc": "HOL120101AA0", "tipo_persona": "moral"},
                    {"nombre": "JUAN PEREZ", "rfc": "PEGJ850101HDG", "tipo_persona": "fisica"},
                ]
            }
        })
        hallazgos = validar(exp)
        v56 = [h for h in hallazgos if h.codigo == "V5.6"]
        
        assert len(v56) == 1
        assert v56[0].pasa is True


class TestV57CrossReference:
    def test_con_cambios(self):
        """V5.7: Detecta cambios entre acta y reforma."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "JUAN PEREZ", "porcentaje": 50},
                    {"nombre": "MARIA LOPEZ", "porcentaje": 50},
                ]
            },
            "reforma_estatutos": {
                "estructura_accionaria": [
                    {"nombre": "JUAN PEREZ", "porcentaje": 70},
                    {"nombre": "PEDRO SANCHEZ", "porcentaje": 30},
                ]
            }
        })
        hallazgos = validar(exp)
        v57 = [h for h in hallazgos if h.codigo == "V5.7"]
        
        assert len(v57) == 1
        assert "Nuevos" in v57[0].mensaje or "Salieron" in v57[0].mensaje


class TestV58InscripcionRPC:
    def test_con_folio(self):
        """V5.8: Con folio mercantil pasa."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "folio_mercantil": "12345",
            }
        })
        hallazgos = validar(exp)
        v58 = [h for h in hallazgos if h.codigo == "V5.8"]
        
        assert len(v58) == 1
        assert v58[0].pasa is True


class TestV59AlertasPLD:
    def test_detecta_alertas(self):
        """V5.9: Detecta alertas PLD."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "HOLDING A SA DE CV", "tipo_persona": "moral", "porcentaje": 40},
                    {"nombre": "HOLDING B SA DE CV", "tipo_persona": "moral", "porcentaje": 35},
                    {"nombre": "JUAN PEREZ", "porcentaje": 25},
                ]
            }
        })
        hallazgos = validar(exp)
        v59 = [h for h in hallazgos if h.codigo == "V5.9"]
        
        assert len(v59) == 1
        assert "alerta" in v59[0].mensaje.lower()


class TestV510EstructuraVigente:
    def test_resumen_estructura(self):
        """V5.10: Genera resumen de estructura vigente."""
        exp = _exp(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "HOLDING SA DE CV", "tipo_persona": "moral", "porcentaje": 60},
                    {"nombre": "JUAN PEREZ", "tipo_persona": "fisica", "porcentaje": 40},
                ]
            }
        })
        hallazgos = validar(exp)
        v510 = [h for h in hallazgos if h.codigo == "V5.10"]
        
        assert len(v510) == 1
        assert v510[0].pasa is True
        assert "2 accionistas" in v510[0].mensaje


# ═══════════════════════════════════════════════════════════════════
#  Tests de constantes
# ═══════════════════════════════════════════════════════════════════

class TestConstantes:
    def test_umbral_propietario_real(self):
        """Umbral propietario real es 25%."""
        assert UMBRAL_PROPIETARIO_REAL == 25.0
    
    def test_umbral_beneficiario_controlador(self):
        """Umbral beneficiario controlador es 15%."""
        assert UMBRAL_BENEFICIARIO_CONTROLADOR == 15.0
