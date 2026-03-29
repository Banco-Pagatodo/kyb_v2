"""
Tests unitarios para mer_calculator.py — Cálculo determinista MER PM.

Valida que el cálculo sea 100 % reproducible y correcto sin depender del LLM.
"""
import pytest
from datetime import date

from pld_agent.services.mer_calculator import (
    FactorCalc,
    ResultadoCalc,
    calcular_mer_pm,
    aplicar_resoluciones_llm,
    resultado_a_dict,
    _valor_tipo_persona,
    _valor_antiguedad,
    _valor_producto,
)


# ═══════════════════════════════════════════════════════════════════
#  Tests de funciones de valor individual
# ═══════════════════════════════════════════════════════════════════

class TestValorTipoPersona:
    def test_persona_moral(self):
        assert _valor_tipo_persona("PERSONA MORAL") == 3

    def test_sapi_de_cv(self):
        assert _valor_tipo_persona("SAPI DE CV") == 3

    def test_sa_de_cv(self):
        assert _valor_tipo_persona("SA DE CV") == 3

    def test_sofom(self):
        assert _valor_tipo_persona("SOFOM ENR") == 3

    def test_sindicato(self):
        assert _valor_tipo_persona("SINDICATO DE TRABAJADORES") == 3

    def test_pfae(self):
        assert _valor_tipo_persona("PFAE") == 2

    def test_persona_fisica(self):
        assert _valor_tipo_persona("PERSONA FÍSICA") == 1

    def test_default_pm(self):
        """Texto no reconocido → default 3 (flujo PM)."""
        assert _valor_tipo_persona("algo desconocido") == 3


class TestValorAntiguedad:
    def test_mas_de_3_anios(self):
        assert _valor_antiguedad(date(2019, 5, 22), date(2026, 3, 18)) == 1

    def test_entre_1_y_3(self):
        # 2024-01-01 to 2026-03-18 ≈ 2.2 years → between 1.1 and 3 → value 2
        assert _valor_antiguedad(date(2024, 1, 1), date(2026, 3, 18)) == 2

    def test_menos_de_1(self):
        assert _valor_antiguedad(date(2026, 1, 1), date(2026, 3, 18)) == 3


class TestValorProducto:
    def test_corporativa(self):
        assert _valor_producto("Corporativa N4") == 3

    def test_ya_ganaste(self):
        assert _valor_producto("Ya Ganaste") == 1

    def test_fundadores(self):
        assert _valor_producto("Fundadores") == 2

    def test_desconocido(self):
        assert _valor_producto("Premium Gold") is None


# ═══════════════════════════════════════════════════════════════════
#  Test caso SOLUCIONES CAPITAL X
# ═══════════════════════════════════════════════════════════════════

class TestCapitalX:
    """
    SOLUCIONES CAPITAL X, SAPI DE CV
    RFC: SCX190531824
    Constituida: 2019-05-22
    Actividad: intermediación crediticia (no está en catálogo → requiere_llm)
    Entidad: Jalisco (zona riesgo 1)
    Producto: Corporativa
    Sin datos transaccionales
    Sin coincidencias en listas
    """

    def test_calculo_sin_llm_tiene_pendientes(self):
        """Sin resolver Factor 4, el cálculo está incompleto."""
        r = calcular_mer_pm(
            tipo_societario="SAPI DE CV",
            pais_constitucion="México",
            fecha_constitucion="2019-05-22",
            actividad_economica="Servicios relacionados con la intermediación crediticia",
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        # Factor 4 debería requerir LLM (no está en catálogo literal)
        pendientes = [f for f in r.factores if f.requiere_llm]
        assert len(pendientes) >= 1
        assert any(f.numero == 4 for f in pendientes)
        assert not r.calculo_completo

    def test_calculo_con_resolucion_llm_grupo3(self):
        """Resolviendo Factor 4 como Grupo 3 → puntaje total = 150.0, MEDIO."""
        r = calcular_mer_pm(
            tipo_societario="SAPI DE CV",
            pais_constitucion="México",
            fecha_constitucion="2019-05-22",
            actividad_economica="Servicios relacionados con la intermediación crediticia",
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )

        # Resolver Factor 4 como Grupo 3
        r = aplicar_resoluciones_llm(r, {4: 3})

        assert r.calculo_completo
        assert r.puntaje_total == 150.0
        assert r.grado_riesgo == "MEDIO"

    def test_factores_deterministas_correctos(self):
        """Verifica cada factor individual del caso Capital X."""
        r = calcular_mer_pm(
            tipo_societario="SAPI DE CV",
            pais_constitucion="México",
            fecha_constitucion="2019-05-22",
            actividad_economica="Servicios relacionados con la intermediación crediticia",
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )

        # Resolver F4 para tener el resultado completo
        r = aplicar_resoluciones_llm(r, {4: 3})

        puntajes = {f.numero: f.puntaje for f in r.factores}

        # Factor 1: Tipo persona → PM=3, peso=0.10 → 30.0
        assert puntajes[1] == pytest.approx(30.0)
        # Factor 2: Nacionalidad → México=1, peso=0.05 → 5.0
        assert puntajes[2] == pytest.approx(5.0)
        # Factor 3: Antigüedad → ~6.8 años → val=1, peso=0.05 → 5.0
        assert puntajes[3] == pytest.approx(5.0)
        # Factor 4: Actividad → Grupo 3, peso=0.15 → 45.0
        assert puntajes[4] == pytest.approx(45.0)
        # Factor 5: Jalisco → zona 1, peso=0.10 → 10.0
        assert puntajes[5] == pytest.approx(10.0)
        # Factor 6: Corporativa → val=3, peso=0.05 → 15.0
        assert puntajes[6] == pytest.approx(15.0)
        # Factores 7-10: asumido val=1 → 5.0 c/u
        for n in (7, 8, 9, 10):
            assert puntajes[n] == pytest.approx(5.0)
        # Factores 11-12: asumido val=2 → 10.0 c/u
        assert puntajes[11] == pytest.approx(10.0)
        assert puntajes[12] == pytest.approx(10.0)
        # Factores 13-15: sin coincidencias → 0
        for n in (13, 14, 15):
            assert puntajes[n] == pytest.approx(0.0)

    def test_datos_asumidos_marcados(self):
        """Verifica que factores con datos asumidos estén correctamente marcados."""
        r = calcular_mer_pm(
            tipo_societario="SAPI DE CV",
            pais_constitucion="México",
            fecha_constitucion="2019-05-22",
            actividad_economica="Servicios relacionados con la intermediación crediticia",
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )

        asumidos = {f.numero for f in r.factores if f.dato_asumido}
        # Factores 7,8,9,10,11,12 → 6 factores asumidos
        assert asumidos == {7, 8, 9, 10, 11, 12}

    def test_alerta_sapi(self):
        """SAPI debe generar alerta estructural."""
        r = calcular_mer_pm(
            tipo_societario="SAPI DE CV",
            pais_constitucion="México",
            fecha_constitucion="2019-05-22",
            actividad_economica="Servicios relacionados con la intermediación crediticia",
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        assert any("SAPI" in a for a in r.alertas)


# ═══════════════════════════════════════════════════════════════════
#  Tests de clasificación de riesgo
# ═══════════════════════════════════════════════════════════════════

class TestClasificacion:
    def _crear_resultado_con_puntaje(self, puntaje_objetivo: float) -> ResultadoCalc:
        """Crea un resultado simple con un puntaje arbitrario para test."""
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,  # will require LLM
            entidad_federativa="Jalisco",
            producto="Ya Ganaste",
            fecha_evaluacion=date(2026, 3, 18),
        )
        # Resolver pendientes
        aplicar_resoluciones_llm(r, {4: 1})
        return r

    def test_bajo_142(self):
        """Puntaje ≤142 → BAJO."""
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,
            entidad_federativa="Jalisco",
            producto="Ya Ganaste",
            fecha_evaluacion=date(2026, 3, 18),
        )
        # Resolver Factor 4 como Grupo 1 (bajo)
        aplicar_resoluciones_llm(r, {4: 1})
        # F1=30, F2=5, F3=5, F4=15, F5=10, F6=5, F7-10=5*4=20, F11-12=10*2=20, F13-15=0
        # Total: 30+5+5+15+10+5+20+20=110
        assert r.grado_riesgo == "BAJO"

    def test_lpb_siempre_alto(self):
        """Coincidencia LPB → ALTO independientemente del puntaje."""
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,
            entidad_federativa="Jalisco",
            producto="Ya Ganaste",
            coincidencia_lpb=True,
            fecha_evaluacion=date(2026, 3, 18),
        )
        aplicar_resoluciones_llm(r, {4: 1})
        assert r.grado_riesgo == "ALTO"


# ═══════════════════════════════════════════════════════════════════
#  Tests de serialización
# ═══════════════════════════════════════════════════════════════════

class TestSerializacion:
    def test_resultado_a_dict_completo(self):
        r = calcular_mer_pm(
            tipo_societario="SA DE CV",
            pais_constitucion="México",
            fecha_constitucion="2018-06-15",
            actividad_economica=None,
            entidad_federativa="Nuevo León",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        d = resultado_a_dict(r)
        assert "factores" in d
        assert len(d["factores"]) == 15
        assert "factores_pendientes_llm" in d
        assert len(d["factores_pendientes_llm"]) >= 1

    def test_resultado_a_dict_con_opciones(self):
        r = calcular_mer_pm(
            tipo_societario="SA DE CV",
            pais_constitucion="México",
            fecha_constitucion="2018-06-15",
            actividad_economica=None,
            entidad_federativa="Nuevo León",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        d = resultado_a_dict(r)
        # Factor 4 pendiente debe tener opciones válidas
        f4_pendiente = next(
            (f for f in d["factores_pendientes_llm"] if f["numero"] == 4), None
        )
        assert f4_pendiente is not None
        assert len(f4_pendiente["opciones_validas"]) == 3


# ═══════════════════════════════════════════════════════════════════
#  Tests de resolución LLM
# ═══════════════════════════════════════════════════════════════════

class TestResolucionLLM:
    def test_resolver_un_factor(self):
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        assert not r.calculo_completo

        r = aplicar_resoluciones_llm(r, {4: 2})
        assert r.calculo_completo
        assert r.puntaje_total is not None

        f4 = next(f for f in r.factores if f.numero == 4)
        assert f4.valor == 2
        assert f4.puntaje == 2 * 0.15 * 100  # 30.0
        assert not f4.requiere_llm
        assert "Resuelto por LLM" in f4.nota

    def test_resolver_no_cambia_factores_fijos(self):
        """Aplicar resoluciones NO debe alterar factores ya calculados."""
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )

        puntajes_antes = {
            f.numero: f.puntaje for f in r.factores if not f.requiere_llm
        }

        r = aplicar_resoluciones_llm(r, {4: 3})

        for f in r.factores:
            if f.numero in puntajes_antes:
                assert f.puntaje == puntajes_antes[f.numero], (
                    f"Factor {f.numero} fue alterado: "
                    f"{puntajes_antes[f.numero]} → {f.puntaje}"
                )


# ═══════════════════════════════════════════════════════════════════
#  Tests de pesos
# ═══════════════════════════════════════════════════════════════════

class TestPesos:
    def test_pesos_suman_110(self):
        """Los pesos de los 15 factores deben sumar 1.10."""
        from pld_agent.services.mer_calculator import PESOS
        total = sum(PESOS.values())
        assert round(total, 2) == 1.10

    def test_15_factores(self):
        """Siempre se generan exactamente 15 factores."""
        r = calcular_mer_pm(
            tipo_societario="PERSONA MORAL",
            pais_constitucion="México",
            fecha_constitucion="2020-01-01",
            actividad_economica=None,
            entidad_federativa="Jalisco",
            producto="Corporativa",
            fecha_evaluacion=date(2026, 3, 18),
        )
        assert len(r.factores) == 15
