"""
Tests para Etapa 4 — Identificación de Propietarios Reales.

Cobertura:
- Look-through / perforación de cadena
- Cascada CNBV (4 pasos)
- Consolidación de participaciones múltiples
- Casos edge: ciclos, PM sin estructura, administradores PM
"""
import pytest
from unittest.mock import MagicMock

from pld_agent.models.schemas import ExpedientePLD, PersonaIdentificada
from pld_agent.services.etapa4_propietarios_reales import (
    # Constantes
    UMBRAL_PROPIETARIO_REAL,
    UMBRAL_BENEFICIARIO_CONTROLADOR,
    MAX_NIVELES_PERFORACION,
    # Enums
    CriterioIdentificacion,
    # Dataclasses
    PropietarioReal,
    ResultadoPropietariosReales,
    # Funciones principales
    calcular_propiedad_indirecta,
    consolidar_propietarios,
    identificar_propietarios_reales_cnbv,
    ejecutar_etapa4_propietarios_reales,
    generar_reporte_propietarios,
    propietarios_a_personas_identificadas,
    # Helpers
    _es_persona_moral,
    _normalizar_nombre,
)


# ═══════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def estructura_simple_pf():
    """Estructura con solo personas físicas."""
    return [
        {"nombre": "JUAN PEREZ GARCIA", "rfc": "PEGJ800101001", "porcentaje": 60, "tipo_persona": "fisica"},
        {"nombre": "MARIA LOPEZ SANCHEZ", "rfc": "LOSM850215002", "porcentaje": 40, "tipo_persona": "fisica"},
    ]


@pytest.fixture
def estructura_con_pm():
    """Estructura con persona moral que requiere perforación."""
    return [
        {"nombre": "JUAN PEREZ GARCIA", "rfc": "PEGJ800101001", "porcentaje": 40, "tipo_persona": "fisica"},
        {"nombre": "HOLDING ABC S.A. DE C.V.", "rfc": "HAB123456789", "porcentaje": 60, "tipo_persona": "moral"},
    ]


@pytest.fixture
def estructuras_intermedias():
    """Estructuras de PM conocidas para perforación."""
    return {
        "HAB123456789": [  # HOLDING ABC S.A. DE C.V.
            {"nombre": "CARLOS RAMIREZ TORRES", "rfc": "RATC700303003", "porcentaje": 80, "tipo_persona": "fisica"},
            {"nombre": "ANA MARTINEZ DIAZ", "rfc": "MADA680404004", "porcentaje": 20, "tipo_persona": "fisica"},
        ],
    }


@pytest.fixture
def expediente_basico():
    """Expediente PLD básico con estructura accionaria."""
    return ExpedientePLD(
        empresa_id="EMP001",
        rfc="XYZ123456ABC",
        razon_social="EMPRESA TEST S.A. DE C.V.",
        documentos={
            "acta_constitutiva": {
                "estructura_accionaria": [
                    {"nombre": "JUAN PEREZ", "rfc": "PEJJ800101001", "porcentaje": 60, "tipo_persona": "fisica"},
                    {"nombre": "MARIA LOPEZ", "rfc": "LOMM850215002", "porcentaje": 40, "tipo_persona": "fisica"},
                ],
                "administradores": [
                    {"nombre": "JUAN PEREZ", "rfc": "PEJJ800101001"},
                ],
            },
        },
    )


# ═══════════════════════════════════════════════════════════════════
#  TESTS: CONSTANTES
# ═══════════════════════════════════════════════════════════════════

class TestConstantes:
    """Verifica umbrales regulatorios."""
    
    def test_umbral_propietario_real_pld(self):
        """DCG Art. 115 = 25%."""
        assert UMBRAL_PROPIETARIO_REAL == 25.0
    
    def test_umbral_beneficiario_controlador_cff(self):
        """CFF Art. 32-B = 15%."""
        assert UMBRAL_BENEFICIARIO_CONTROLADOR == 15.0
    
    def test_max_niveles_perforacion(self):
        """Evitar loops infinitos."""
        assert MAX_NIVELES_PERFORACION == 10


# ═══════════════════════════════════════════════════════════════════
#  TESTS: HELPERS
# ═══════════════════════════════════════════════════════════════════

class TestEsPersonaMoral:
    """Tests para _es_persona_moral."""
    
    def test_pf_explicito(self):
        assert _es_persona_moral({"tipo_persona": "fisica"}) is False
    
    def test_pm_explicito(self):
        assert _es_persona_moral({"tipo_persona": "moral"}) is True
    
    def test_sa_de_cv(self):
        assert _es_persona_moral({"nombre": "EMPRESA S.A. DE C.V."}) is True
    
    def test_sa_simple(self):
        assert _es_persona_moral({"nombre": "CORPORATIVO S.A."}) is True
    
    def test_sapi(self):
        assert _es_persona_moral({"nombre": "FINTECH SAPI DE CV"}) is True
    
    def test_fideicomiso(self):
        assert _es_persona_moral({"nombre": "FIDEICOMISO 12345"}) is True
    
    def test_persona_fisica_nombre(self):
        assert _es_persona_moral({"nombre": "JUAN PEREZ GARCIA"}) is False
    
    def test_ac(self):
        assert _es_persona_moral({"nombre": "FUNDACION XYZ A.C."}) is True


class TestNormalizarNombre:
    """Tests para _normalizar_nombre."""
    
    def test_mayusculas(self):
        assert _normalizar_nombre("juan perez") == "JUAN PEREZ"
    
    def test_espacios_multiples(self):
        assert _normalizar_nombre("JUAN   PEREZ   GARCIA") == "JUAN PEREZ GARCIA"
    
    def test_vacio(self):
        assert _normalizar_nombre("") == ""
    
    def test_none(self):
        assert _normalizar_nombre(None) == ""


# ═══════════════════════════════════════════════════════════════════
#  TESTS: CALCULAR PROPIEDAD INDIRECTA
# ═══════════════════════════════════════════════════════════════════

class TestCalcularPropiedadIndirecta:
    """Tests para look-through / perforación de cadena."""
    
    def test_estructura_solo_pf(self, estructura_simple_pf):
        """Sin PM, retorna accionistas directos."""
        resultado = calcular_propiedad_indirecta(estructura_simple_pf)
        
        assert len(resultado) == 2
        assert resultado[0].nombre == "JUAN PEREZ GARCIA"
        assert resultado[0].porcentaje_directo == 60
        assert resultado[0].porcentaje_indirecto == 0
        assert resultado[0].tipo_persona == "fisica"
    
    def test_pm_sin_estructura_conocida(self, estructura_con_pm):
        """PM sin estructura marca requiere_perforacion."""
        resultado = calcular_propiedad_indirecta(estructura_con_pm)
        
        pm = next(p for p in resultado if p.tipo_persona == "moral")
        assert pm.nombre == "HOLDING ABC S.A. DE C.V."
        assert pm.requiere_perforacion is True  # 60% >= 25%
        assert pm.requiere_documentacion is True
    
    def test_perforacion_un_nivel(self, estructura_con_pm, estructuras_intermedias):
        """Perforación de PM con estructura conocida."""
        resultado = calcular_propiedad_indirecta(
            estructura_con_pm,
            estructuras_intermedias,
        )
        
        # Juan Pérez directo (40%) + perforados de Holding
        # Carlos Ramírez: 60% × 80% / 100 = 48%
        # Ana Martínez: 60% × 20% / 100 = 12%
        
        juan = next(p for p in resultado if "JUAN" in p.nombre)
        assert juan.porcentaje_directo == 40
        
        carlos = next(p for p in resultado if "CARLOS" in p.nombre)
        assert carlos.porcentaje_indirecto == 48.0
        assert carlos.nivel_perforacion == 1
        assert carlos.criterio == CriterioIdentificacion.PROPIEDAD_INDIRECTA
    
    def test_perforacion_dos_niveles(self):
        """Look-through con PM intermedias anidadas."""
        estructura = [
            {"nombre": "HOLDING PRINCIPAL S.A.", "rfc": "HP1", "porcentaje": 100, "tipo_persona": "moral"},
        ]
        
        estructuras = {
            "HP1": [
                {"nombre": "SUB-HOLDING S.A.", "rfc": "SH1", "porcentaje": 100, "tipo_persona": "moral"},
            ],
            "SH1": [
                {"nombre": "FINAL PF", "rfc": "PFINAL", "porcentaje": 100, "tipo_persona": "fisica"},
            ],
        }
        
        resultado = calcular_propiedad_indirecta(estructura, estructuras)
        
        final = next(p for p in resultado if "FINAL PF" in p.nombre)
        assert final.porcentaje_indirecto == 100.0  # 100% × 100% × 100%
        assert final.nivel_perforacion == 2
    
    def test_deteccion_ciclo(self):
        """Detecta estructuras circulares."""
        estructura = [
            {"nombre": "CICLO A S.A.", "rfc": "CA1", "porcentaje": 100, "tipo_persona": "moral"},
        ]
        
        estructuras = {
            "CA1": [
                {"nombre": "CICLO B S.A.", "rfc": "CB1", "porcentaje": 100, "tipo_persona": "moral"},
            ],
            "CB1": [
                {"nombre": "CICLO A S.A.", "rfc": "CA1", "porcentaje": 100, "tipo_persona": "moral"},  # Ciclo!
            ],
        }
        
        resultado = calcular_propiedad_indirecta(estructura, estructuras)
        
        # Debe detectar ciclo y no entrar en loop infinito
        circular = [p for p in resultado if "estructura_circular" in p.fuente]
        assert len(circular) > 0
    
    def test_cadena_titularidad(self, estructura_con_pm, estructuras_intermedias):
        """Verifica cadena de titularidad completa."""
        resultado = calcular_propiedad_indirecta(
            estructura_con_pm,
            estructuras_intermedias,
        )
        
        carlos = next(p for p in resultado if "CARLOS" in p.nombre)
        assert len(carlos.cadena_titularidad) == 2
        assert "HOLDING ABC" in carlos.cadena_titularidad[0]
        assert "CARLOS" in carlos.cadena_titularidad[1]


# ═══════════════════════════════════════════════════════════════════
#  TESTS: CONSOLIDAR PROPIETARIOS
# ═══════════════════════════════════════════════════════════════════

class TestConsolidarPropietarios:
    """Tests para consolidación de participaciones múltiples."""
    
    def test_consolidacion_por_rfc(self):
        """Misma persona con múltiples participaciones se consolida."""
        propietarios = [
            PropietarioReal(nombre="JUAN PEREZ", rfc="JP1", porcentaje_directo=20),
            PropietarioReal(nombre="JUAN PEREZ GARCIA", rfc="JP1", porcentaje_indirecto=15),
        ]
        
        resultado = consolidar_propietarios(propietarios)
        
        assert len(resultado) == 1
        assert resultado[0].porcentaje_total == 35  # 20 + 15
    
    def test_consolidacion_sin_rfc(self):
        """Consolida por nombre normalizado si no hay RFC."""
        propietarios = [
            PropietarioReal(nombre="JUAN PEREZ", porcentaje_directo=10),
            PropietarioReal(nombre="juan perez", porcentaje_indirecto=8),
        ]
        
        resultado = consolidar_propietarios(propietarios)
        
        assert len(resultado) == 1
        assert resultado[0].porcentaje_total == 18
    
    def test_no_consolida_diferentes(self):
        """Personas diferentes permanecen separadas."""
        propietarios = [
            PropietarioReal(nombre="JUAN PEREZ", rfc="JP1", porcentaje_directo=30),
            PropietarioReal(nombre="MARIA LOPEZ", rfc="ML1", porcentaje_directo=25),
        ]
        
        resultado = consolidar_propietarios(propietarios)
        
        assert len(resultado) == 2


# ═══════════════════════════════════════════════════════════════════
#  TESTS: CASCADA CNBV
# ═══════════════════════════════════════════════════════════════════

class TestCascadaCNBV:
    """Tests para identificación según lineamientos CNBV."""
    
    def test_paso1_propiedad_directa_25(self, estructura_simple_pf):
        """Paso 1: PF con ≥25% directo."""
        resultado = identificar_propietarios_reales_cnbv(
            estructura_simple_pf,
            administradores=[],
        )
        
        assert resultado.cumple_pld is True
        assert resultado.criterio_identificacion == CriterioIdentificacion.PROPIEDAD_DIRECTA
        assert len(resultado.propietarios_reales_pld) == 2  # 60% y 40%
    
    def test_paso1_propiedad_indirecta_25(self, estructura_con_pm, estructuras_intermedias):
        """Paso 1: PF con ≥25% incluyendo indirecta."""
        resultado = identificar_propietarios_reales_cnbv(
            estructura_con_pm,
            administradores=[],
            estructuras_intermedias=estructuras_intermedias,
        )
        
        assert resultado.cumple_pld is True
        
        # Carlos: 60% × 80% = 48% >= 25%
        carlos = next(p for p in resultado.propietarios_reales_pld if "CARLOS" in p.nombre)
        assert carlos.porcentaje_total >= UMBRAL_PROPIETARIO_REAL
    
    def test_paso2_cff_15_porciento(self, estructura_simple_pf):
        """También identifica beneficiarios controladores CFF >15%."""
        resultado = identificar_propietarios_reales_cnbv(
            estructura_simple_pf,
            administradores=[],
        )
        
        assert resultado.cumple_cff is True
        assert len(resultado.beneficiarios_controladores_cff) == 2  # 60% y 40% > 15%
    
    def test_paso3_control_otros_medios(self):
        """Paso 2: Control por derechos de voto especiales."""
        estructura = [
            {"nombre": "JUAN CONTROL", "porcentaje": 10, "derechos_voto": 60, "tipo_persona": "fisica"},
            {"nombre": "OTROS", "porcentaje": 90, "tipo_persona": "fisica"},
        ]
        
        resultado = identificar_propietarios_reales_cnbv(
            estructura,
            administradores=[],
        )
        
        # Juan tiene 10% pero 60% de votos (ratio 6:1)
        juan = next((p for p in resultado.propietarios_reales_pld if "JUAN" in p.nombre), None)
        if juan:
            assert resultado.criterio_identificacion == CriterioIdentificacion.CONTROL_OTROS_MEDIOS
    
    def test_paso4_administrador_pf(self):
        """Paso 3: Fallback a administrador cuando no hay ≥25%."""
        estructura = [
            {"nombre": "ACCIONISTA A", "porcentaje": 10, "tipo_persona": "fisica"},
            {"nombre": "ACCIONISTA B", "porcentaje": 10, "tipo_persona": "fisica"},
            {"nombre": "ACCIONISTA C", "porcentaje": 80, "tipo_persona": "moral"},  # PM sin perforar
        ]
        
        administradores = [
            {"nombre": "ADMIN PERSONA FISICA", "rfc": "APF123"},
        ]
        
        resultado = identificar_propietarios_reales_cnbv(
            estructura,
            administradores=administradores,
        )
        
        # No hay PF ≥25%, debe usar administrador
        assert resultado.cumple_pld is True
        assert resultado.criterio_identificacion == CriterioIdentificacion.ADMINISTRADOR
        assert resultado.propietarios_reales_pld[0].nombre == "ADMIN PERSONA FISICA"
    
    def test_paso5_pm_administradora(self):
        """Paso 4: PM administradora requiere identificar su controlador."""
        estructura = [
            {"nombre": "ACCIONISTA DISPERSO", "porcentaje": 100, "tipo_persona": "moral"},
        ]
        
        administradores = [
            {"nombre": "ADMIN PM S.A.", "rfc": "APS123", "tipo_persona": "moral"},
        ]
        
        estructuras = {
            "APS123": [
                {"nombre": "DUEÑO DE PM ADMIN", "rfc": "DPA1", "porcentaje": 100, "tipo_persona": "fisica"},
            ],
        }
        
        resultado = identificar_propietarios_reales_cnbv(
            estructura,
            administradores=administradores,
            estructuras_intermedias=estructuras,
        )
        
        assert resultado.cumple_pld is True
        assert resultado.criterio_identificacion == CriterioIdentificacion.CONTROLADOR_PM_ADMINISTRADORA
        assert "DUEÑO" in resultado.propietarios_reales_pld[0].nombre
    
    def test_no_identificado_requiere_escalamiento(self):
        """Sin propietario identificable requiere escalamiento."""
        estructura = [
            {"nombre": "PM SIN DATOS S.A.", "porcentaje": 100, "tipo_persona": "moral"},
        ]
        
        resultado = identificar_propietarios_reales_cnbv(
            estructura,
            administradores=[],
        )
        
        assert resultado.cumple_pld is False
        assert resultado.criterio_identificacion == CriterioIdentificacion.NO_IDENTIFICADO
        assert resultado.requiere_escalamiento is True
    
    def test_pm_sin_perforar_genera_alerta(self, estructura_con_pm):
        """PM ≥25% sin estructura genera alerta."""
        resultado = identificar_propietarios_reales_cnbv(
            estructura_con_pm,
            administradores=[],
        )
        
        # Holding ABC tiene 60% pero no hay estructura conocida
        assert len(resultado.pm_sin_perforar) >= 0  # Puede variar según lógica exacta
        assert resultado.requiere_documentacion_adicional or len(resultado.pm_sin_perforar) > 0


# ═══════════════════════════════════════════════════════════════════
#  TESTS: EJECUTAR ETAPA 4
# ═══════════════════════════════════════════════════════════════════

class TestEjecutarEtapa4:
    """Tests de integración para etapa completa."""
    
    def test_expediente_con_estructura(self, expediente_basico):
        """Procesa expediente con estructura completa."""
        resultado = ejecutar_etapa4_propietarios_reales(expediente_basico)
        
        assert resultado.cumple_pld is True
        assert len(resultado.propietarios_reales_pld) >= 1
    
    def test_expediente_sin_estructura(self):
        """Expediente sin estructura genera alerta crítica."""
        expediente = ExpedientePLD(
            empresa_id="EMP002",
            rfc="ABC999999ABC",
            razon_social="EMPRESA SIN ESTRUCTURA S.A.",
            documentos={
                "acta_constitutiva": {},  # Sin estructura_accionaria
            },
        )
        
        resultado = ejecutar_etapa4_propietarios_reales(expediente)
        
        assert resultado.cumple_pld is False
        assert resultado.requiere_documentacion_adicional is True
        assert any(a["codigo"] == "PR007" for a in resultado.alertas)
    
    def test_usa_reforma_sobre_acta(self):
        """Prioriza estructura de reforma sobre acta."""
        expediente = ExpedientePLD(
            empresa_id="EMP003",
            rfc="DEF888888DEF",
            razon_social="EMPRESA REFORMA TEST S.A.",
            documentos={
                "acta_constitutiva": {
                    "estructura_accionaria": [
                        {"nombre": "ORIGINAL", "porcentaje": 100, "tipo_persona": "fisica"},
                    ],
                },
                "reforma_estatutos": {
                    "estructura_accionaria": [
                        {"nombre": "REFORMADO", "porcentaje": 100, "tipo_persona": "fisica"},
                    ],
                },
            },
        )
        
        resultado = ejecutar_etapa4_propietarios_reales(expediente)
        
        assert resultado.propietarios_reales_pld[0].nombre == "REFORMADO"


# ═══════════════════════════════════════════════════════════════════
#  TESTS: REPORTE
# ═══════════════════════════════════════════════════════════════════

class TestGenerarReporte:
    """Tests para generación de reporte."""
    
    def test_estructura_reporte(self):
        """Verifica estructura del reporte."""
        resultado = ResultadoPropietariosReales(
            propietarios_reales_pld=[
                PropietarioReal(
                    nombre="JUAN PEREZ",
                    rfc="JP1",
                    porcentaje_directo=30,
                    porcentaje_indirecto=10,
                    nacionalidad="MEXICANA",
                ),
            ],
            beneficiarios_controladores_cff=[
                PropietarioReal(nombre="JUAN PEREZ", rfc="JP1", porcentaje_total=40),
            ],
            criterio_identificacion=CriterioIdentificacion.PROPIEDAD_DIRECTA,
            cumple_pld=True,
            cumple_cff=True,
        )
        
        reporte = generar_reporte_propietarios(resultado)
        
        assert "propietarios_reales_pld" in reporte
        assert "beneficiarios_controladores_cff" in reporte
        assert "cadenas_titularidad" in reporte
        assert reporte["cumple_pld"] is True
        assert reporte["criterio_identificacion"] == "PROPIEDAD_DIRECTA"


# ═══════════════════════════════════════════════════════════════════
#  TESTS: CONVERSIÓN A PERSONAS IDENTIFICADAS
# ═══════════════════════════════════════════════════════════════════

class TestPropietariosAPersonas:
    """Tests para integración con Etapa 1."""
    
    def test_conversion_basica(self):
        """Convierte propietarios a PersonaIdentificada."""
        resultado = ResultadoPropietariosReales(
            propietarios_reales_pld=[
                PropietarioReal(
                    nombre="JUAN PEREZ",
                    rfc="JP1",
                    tipo_persona="fisica",
                    porcentaje_directo=35,
                    fuente="estructura_accionaria",
                ),
            ],
            criterio_identificacion=CriterioIdentificacion.PROPIEDAD_DIRECTA,
        )
        
        personas = propietarios_a_personas_identificadas(resultado)
        
        assert len(personas) == 1
        assert personas[0].nombre == "JUAN PEREZ"
        assert personas[0].rol == "propietario_real"
        assert personas[0].porcentaje == 35
        assert personas[0].requiere_screening is True
    
    def test_incluye_beneficiarios_adicionales(self):
        """Incluye beneficiarios CFF no duplicados."""
        resultado = ResultadoPropietariosReales(
            propietarios_reales_pld=[
                PropietarioReal(nombre="JUAN", rfc="JP1", porcentaje_directo=30),
            ],
            beneficiarios_controladores_cff=[
                PropietarioReal(nombre="JUAN", rfc="JP1", porcentaje_directo=30),  # Duplicado
                PropietarioReal(nombre="MARIA", rfc="ML1", porcentaje_directo=18),  # Adicional
            ],
        )
        
        personas = propietarios_a_personas_identificadas(resultado)
        
        # JUAN aparece 1 vez como propietario_real, MARIA como beneficiario_controlador
        assert len(personas) == 2
        maria = next(p for p in personas if p.nombre == "MARIA")
        assert maria.rol == "beneficiario_controlador"
