"""
Tests unitarios para report_generator — funciones puras de formato texto.
"""
from __future__ import annotations

from datetime import datetime

from cross_validation.models.schemas import (
    DatosClave,
    Dictamen,
    Hallazgo,
    PersonaClave,
    ReporteValidacion,
    ResumenGlobal,
    Severidad,
)
from cross_validation.services.report_generator import (
    generar_reporte_texto,
    generar_resumen_global_texto,
)


def _make_reporte(
    dictamen: Dictamen = Dictamen.APROBADO,
    hallazgos: list[Hallazgo] | None = None,
    recomendaciones: list[str] | None = None,
) -> ReporteValidacion:
    return ReporteValidacion(
        empresa_id="00000000-0000-0000-0000-000000000001",
        rfc="TST000101AA0",
        razon_social="EMPRESA TEST SA DE CV",
        fecha_analisis=datetime(2026, 2, 27, 10, 0),
        documentos_presentes=["csf", "ine", "acta_constitutiva"],
        hallazgos=hallazgos or [],
        dictamen=dictamen,
        total_criticos=0,
        total_medios=0,
        total_informativos=0,
        total_pasan=len(hallazgos or []),
        recomendaciones=recomendaciones or [],
    )


def _h(codigo: str = "V1.1", pasa: bool = True, bloque: int = 1,
       severidad: Severidad = Severidad.CRITICA) -> Hallazgo:
    return Hallazgo(
        codigo=codigo, nombre="Test hallazgo", bloque=bloque,
        bloque_nombre="IDENTIDAD CORPORATIVA", pasa=pasa,
        severidad=severidad, mensaje="Resultado de prueba",
    )


class TestGenerarReporteTexto:
    def test_contiene_encabezado(self):
        reporte = _make_reporte()
        texto = generar_reporte_texto(reporte)
        assert "REPORTE DE VALIDACIÓN CRUZADA KYB" in texto

    def test_contiene_datos_empresa(self):
        reporte = _make_reporte()
        texto = generar_reporte_texto(reporte)
        assert "TST000101AA0" in texto
        assert "EMPRESA TEST SA DE CV" in texto

    def test_dictamen_aprobado(self):
        reporte = _make_reporte(dictamen=Dictamen.APROBADO)
        texto = generar_reporte_texto(reporte)
        assert "APROBADO" in texto
        assert "listo para onboarding" in texto

    def test_dictamen_rechazado(self):
        reporte = _make_reporte(
            dictamen=Dictamen.RECHAZADO,
            hallazgos=[_h(pasa=False)],
        )
        reporte.total_criticos = 1
        reporte.total_pasan = 0
        texto = generar_reporte_texto(reporte)
        assert "RECHAZADO" in texto

    def test_con_hallazgos_por_bloque(self):
        hallazgos = [_h(bloque=1), _h(codigo="V9.1", bloque=9)]
        reporte = _make_reporte(hallazgos=hallazgos)
        texto = generar_reporte_texto(reporte)
        assert "BLOQUE 1" in texto
        assert "BLOQUE 9" in texto

    def test_recomendaciones(self):
        reporte = _make_reporte(recomendaciones=["Solicitar INE vigente"])
        texto = generar_reporte_texto(reporte)
        assert "Solicitar INE vigente" in texto

    def test_contiene_fin_reporte(self):
        reporte = _make_reporte()
        texto = generar_reporte_texto(reporte)
        assert "Fin del reporte" in texto

    def test_contiene_datos_clave_persona_moral(self):
        """Verifica que la sección DATOS CLAVE aparece con información completa."""
        dc = DatosClave(
            razon_social="EMPRESA PRUEBA SAPI DE CV",
            rfc="EPR123456AB1",
            apoderados=[PersonaClave(
                nombre="JUAN PEREZ", rol="apoderado",
                fuente="poder_notarial", facultades="General amplio",
            )],
            representante_legal=PersonaClave(
                nombre="JUAN PEREZ", rol="representante_legal",
                fuente="poder_notarial", facultades="General amplio",
            ),
            accionistas=[
                PersonaClave(nombre="SOCIO A", rol="accionista",
                             fuente="acta_constitutiva", porcentaje=60.0),
                PersonaClave(nombre="SOCIO B", rol="accionista",
                             fuente="acta_constitutiva", porcentaje=40.0),
            ],
            consejo_administracion=[PersonaClave(
                nombre="PRESIDENTE X", rol="consejero",
                fuente="reforma_estatutos", facultades="Presidente",
            )],
        )
        reporte = _make_reporte()
        reporte.datos_clave = dc
        texto = generar_reporte_texto(reporte)
        assert "DATOS CLAVE DE LA PERSONA MORAL" in texto
        assert "REPRESENTANTE LEGAL" in texto
        assert "JUAN PEREZ" in texto
        assert "APODERADO" in texto
        assert "ACCIONISTAS" in texto
        assert "SOCIO A" in texto
        assert "SOCIO B" in texto
        assert "CONSEJO DE ADMINISTRACIÓN" in texto
        assert "PRESIDENTE X" in texto

    def test_sin_datos_clave_no_aparece_seccion(self):
        """Sin datos_clave, la sección no se renderiza."""
        reporte = _make_reporte()
        texto = generar_reporte_texto(reporte)
        assert "DATOS CLAVE DE LA PERSONA MORAL" not in texto

    def test_poder_cuenta_bancaria_si(self):
        """Muestra '✅ SÍ' cuando poder_cuenta_bancaria es True."""
        dc = DatosClave(
            razon_social="TEST SA",
            poder_cuenta_bancaria=True,
        )
        reporte = _make_reporte()
        reporte.datos_clave = dc
        texto = generar_reporte_texto(reporte)
        assert "PODER PARA ABRIR CUENTAS BANCARIAS" in texto
        assert "SÍ" in texto

    def test_poder_cuenta_bancaria_no(self):
        """Muestra '❌ NO DETECTADO' cuando poder_cuenta_bancaria es False."""
        dc = DatosClave(
            razon_social="TEST SA",
            poder_cuenta_bancaria=False,
        )
        reporte = _make_reporte()
        reporte.datos_clave = dc
        texto = generar_reporte_texto(reporte)
        assert "PODER PARA ABRIR CUENTAS BANCARIAS" in texto
        assert "NO DETECTADO" in texto

    def test_poder_cuenta_bancaria_none(self):
        """Muestra '⚠ NO DETERMINADO' cuando poder_cuenta_bancaria es None."""
        dc = DatosClave(razon_social="TEST SA")
        reporte = _make_reporte()
        reporte.datos_clave = dc
        texto = generar_reporte_texto(reporte)
        assert "NO DETERMINADO" in texto


class TestGenerarResumenGlobalTexto:
    def test_resumen_basico(self):
        rep = _make_reporte()
        resumen = ResumenGlobal(
            fecha_analisis=datetime(2026, 2, 27, 10, 0),
            total_empresas=1,
            reportes=[rep],
            tabla_dictamenes=[{
                "rfc": "TST000101AA0",
                "razon_social": "EMPRESA TEST SA DE CV",
                "dictamen": "APROBADO",
                "criticos": 0, "medios": 0, "informativos": 0,
            }],
            hallazgos_frecuentes=[],
            recomendaciones_globales=["Todo en orden"],
        )
        texto = generar_resumen_global_texto(resumen)
        assert "RESUMEN GLOBAL" in texto
        assert "TST000101AA0" in texto
        assert "Todo en orden" in texto
