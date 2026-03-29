"""
Tests unitarios para validadores (bloques 1 y 9).
Usan ExpedienteEmpresa mock — no requieren BD.
"""
from __future__ import annotations

from cross_validation.models.schemas import ExpedienteEmpresa, Severidad
from cross_validation.services.validators.bloque1_identidad import validar as validar_b1
from cross_validation.services.validators.bloque9_completitud import validar as validar_b9


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
#  BLOQUE 1 — Identidad corporativa
# ═══════════════════════════════════════════════════════════════════


class TestBloque1:
    def test_rfc_consistente(self):
        """V1.1: RFC coincide en CSF, FIEL y BD → pasa."""
        exp = _exp(
            rfc="TST000101AA0",
            documentos={
                "csf": {"rfc": _dato("TST000101AA0")},
                "fiel": {"rfc": _dato("TST000101AA0")},
            },
        )
        hallazgos = validar_b1(exp)
        v11 = [h for h in hallazgos if h.codigo == "V1.1"]
        assert len(v11) == 1
        assert v11[0].pasa is True

    def test_rfc_discrepante(self):
        """V1.1: RFC distinto entre CSF y BD → falla."""
        exp = _exp(
            rfc="TST000101AA0",
            documentos={
                "csf": {"rfc": _dato("OTRO12345XX0")},
            },
        )
        hallazgos = validar_b1(exp)
        v11 = [h for h in hallazgos if h.codigo == "V1.1"]
        assert len(v11) == 1
        assert v11[0].pasa is False
        assert v11[0].severidad == Severidad.CRITICA

    def test_razon_social_consistente(self):
        """V1.2: Razón social coincide → pasa."""
        exp = _exp(
            rfc="TST000101AA0",
            razon_social="EMPRESA TEST SA DE CV",
            documentos={
                "csf": {"razon_social": _dato("EMPRESA TEST SA DE CV")},
                "acta_constitutiva": {"denominacion_social": _dato("EMPRESA TEST SA DE CV")},
            },
        )
        hallazgos = validar_b1(exp)
        v12 = [h for h in hallazgos if h.codigo == "V1.2"]
        assert len(v12) >= 1
        assert v12[0].pasa is True

    def test_estatus_activo(self):
        """V1.3: Estatus ACTIVO → pasa."""
        exp = _exp(documentos={"csf": {"estatus_padron": _dato("Activo")}})
        hallazgos = validar_b1(exp)
        v13 = [h for h in hallazgos if h.codigo == "V1.3"]
        assert len(v13) == 1
        assert v13[0].pasa is True

    def test_estatus_no_activo(self):
        """V1.3: Estatus diferente a ACTIVO → falla."""
        exp = _exp(documentos={"csf": {"estatus_padron": _dato("Suspendido")}})
        hallazgos = validar_b1(exp)
        v13 = [h for h in hallazgos if h.codigo == "V1.3"]
        assert len(v13) == 1
        assert v13[0].pasa is False

    def test_sin_csf_estatus_na(self):
        """V1.3: Sin CSF → N/A."""
        exp = _exp(documentos={})
        hallazgos = validar_b1(exp)
        v13 = [h for h in hallazgos if h.codigo == "V1.3"]
        assert len(v13) == 1
        assert v13[0].pasa is None


# ═══════════════════════════════════════════════════════════════════
#  BLOQUE 9 — Completitud del expediente
# ═══════════════════════════════════════════════════════════════════


class TestBloque9:
    def test_todos_minimos_presentes(self):
        """V9.1: Todos los docs mínimos → pasa."""
        docs = {d: {} for d in [
            "csf", "fiel", "ine", "estado_cuenta",
            "domicilio", "acta_constitutiva", "poder",
        ]}
        exp = _exp(documentos=docs)
        hallazgos = validar_b9(exp)
        v91 = [h for h in hallazgos if h.codigo == "V9.1"]
        # Al tener todos, debe haber exactamente 1 hallazgo V9.1 que pase
        pasan = [h for h in v91 if h.pasa is True]
        assert len(pasan) >= 1

    def test_faltan_documentos(self):
        """V9.1: Faltan docs → falla con un hallazgo por cada faltante."""
        docs = {"csf": {}, "ine": {}}  # faltan 5
        exp = _exp(documentos=docs)
        hallazgos = validar_b9(exp)
        v91_fail = [h for h in hallazgos if h.codigo == "V9.1" and h.pasa is False]
        assert len(v91_fail) >= 5  # 5 faltantes + 1 resumen

    def test_estado_cuenta_sustituye_domicilio(self):
        """V9.1: Con estado_cuenta pero sin domicilio → pasa (sustitución formal)."""
        docs = {d: {} for d in [
            "csf", "fiel", "ine", "estado_cuenta",
            "acta_constitutiva", "poder",
        ]}
        # No incluye "domicilio" — estado_cuenta lo sustituye
        exp = _exp(documentos=docs)
        hallazgos = validar_b9(exp)
        v91 = [h for h in hallazgos if h.codigo == "V9.1"]
        pasan = [h for h in v91 if h.pasa is True]
        assert len(pasan) >= 1, "estado_cuenta debe sustituir a domicilio"
        fallan = [h for h in v91 if h.pasa is False]
        assert len(fallan) == 0, "No debe haber faltantes si estado_cuenta sustituye domicilio"

    def test_sin_estado_cuenta_ni_domicilio_falla(self):
        """V9.1: Sin estado_cuenta ni domicilio → ambos faltan."""
        docs = {d: {} for d in [
            "csf", "fiel", "ine", "acta_constitutiva", "poder",
        ]}
        exp = _exp(documentos=docs)
        hallazgos = validar_b9(exp)
        v91_fail = [h for h in hallazgos if h.codigo == "V9.1" and h.pasa is False]
        # Deben faltar estado_cuenta y domicilio (2 faltantes + 1 resumen)
        assert len(v91_fail) >= 2

    def test_complementarios_presentes(self):
        """V9.2: Con reforma → complementarios OK."""
        minimos = {d: {} for d in [
            "csf", "fiel", "ine", "estado_cuenta",
            "domicilio", "acta_constitutiva", "poder",
        ]}
        minimos["reforma_estatutos"] = {}
        minimos["ine_reverso"] = {}
        exp = _exp(documentos=minimos)
        hallazgos = validar_b9(exp)
        v92 = [h for h in hallazgos if h.codigo == "V9.2"]
        assert len(v92) >= 1
        assert v92[0].pasa is True

    def test_complementarios_faltantes(self):
        """V9.2: Sin complementarios → falla (media)."""
        docs = {d: {} for d in [
            "csf", "fiel", "ine", "estado_cuenta",
            "domicilio", "acta_constitutiva", "poder",
        ]}
        exp = _exp(documentos=docs)
        hallazgos = validar_b9(exp)
        v92 = [h for h in hallazgos if h.codigo == "V9.2"]
        assert len(v92) >= 1
        assert v92[0].pasa is False
        assert v92[0].severidad == Severidad.MEDIA
