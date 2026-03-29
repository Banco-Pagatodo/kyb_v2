"""
Tests unitarios para engine.py — _calcular_dictamen y _generar_recomendaciones.
Funciones puras que no requieren BD.
"""
from __future__ import annotations

from cross_validation.models.schemas import Hallazgo, Severidad, Dictamen, ExpedienteEmpresa
from cross_validation.services.engine import _calcular_dictamen, _generar_recomendaciones, _extraer_datos_clave


# ═══════════════════════════════════════════════════════════════════
#  Helpers para crear hallazgos rápidamente
# ═══════════════════════════════════════════════════════════════════

def _h(codigo: str = "V1.1", pasa: bool | None = True,
       severidad: Severidad = Severidad.CRITICA,
       nombre: str = "Test", bloque: int = 1,
       mensaje: str = "ok") -> Hallazgo:
    return Hallazgo(
        codigo=codigo, nombre=nombre, bloque=bloque,
        bloque_nombre="TEST", pasa=pasa, severidad=severidad,
        mensaje=mensaje,
    )


# ═══════════════════════════════════════════════════════════════════
#  _calcular_dictamen
# ═══════════════════════════════════════════════════════════════════


class TestCalcularDictamen:
    def test_todo_pasa_aprobado(self):
        """Si todos los hallazgos pasan → APROBADO."""
        hallazgos = [_h(pasa=True) for _ in range(10)]
        dictamen, crit, med, info, pasan = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.APROBADO
        assert crit == 0
        assert med == 0
        assert pasan == 10

    def test_un_critico_falla_rechazado(self):
        """1+ criticos fallidos → RECHAZADO."""
        hallazgos = [
            _h(pasa=True),
            _h(pasa=False, severidad=Severidad.CRITICA),
            _h(pasa=True),
        ]
        dictamen, crit, med, info, pasan = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.RECHAZADO
        assert crit == 1
        assert pasan == 2

    def test_varios_criticos_rechazado(self):
        hallazgos = [
            _h(pasa=False, severidad=Severidad.CRITICA),
            _h(pasa=False, severidad=Severidad.CRITICA),
        ]
        dictamen, crit, *_ = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.RECHAZADO
        assert crit == 2

    def test_muchos_medios_aprobado_con_obs(self):
        """0 criticos + >2 medios fallidos → APROBADO_CON_OBSERVACIONES."""
        hallazgos = [
            _h(pasa=True),
            _h(pasa=False, severidad=Severidad.MEDIA),
            _h(pasa=False, severidad=Severidad.MEDIA),
            _h(pasa=False, severidad=Severidad.MEDIA),
        ]
        dictamen, crit, med, info, pasan = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.APROBADO_CON_OBSERVACIONES
        assert crit == 0
        assert med == 3

    def test_dos_medios_aprobado(self):
        """0 criticos + exactamente 2 medios fallidos → APROBADO (no >2)."""
        hallazgos = [
            _h(pasa=True),
            _h(pasa=False, severidad=Severidad.MEDIA),
            _h(pasa=False, severidad=Severidad.MEDIA),
        ]
        dictamen, *_ = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.APROBADO

    def test_informativos_no_afectan_dictamen(self):
        hallazgos = [
            _h(pasa=True),
            _h(pasa=None, severidad=Severidad.INFORMATIVA),
        ]
        dictamen, crit, med, info, pasan = _calcular_dictamen(hallazgos)
        assert dictamen == Dictamen.APROBADO
        assert info == 1
        assert pasan == 1

    def test_lista_vacia(self):
        dictamen, crit, med, info, pasan = _calcular_dictamen([])
        assert dictamen == Dictamen.APROBADO
        assert pasan == 0


# ═══════════════════════════════════════════════════════════════════
#  _generar_recomendaciones
# ═══════════════════════════════════════════════════════════════════


class TestGenerarRecomendaciones:
    def test_sin_fallas_sin_recomendaciones(self):
        hallazgos = [_h(pasa=True)]
        recs = _generar_recomendaciones(hallazgos)
        assert recs == []

    def test_rfc_discrepancia(self):
        hallazgos = [
            _h(codigo="V1.1", pasa=False, nombre="RFC inconsistente",
               severidad=Severidad.CRITICA, mensaje="Discrepancia de RFC"),
        ]
        recs = _generar_recomendaciones(hallazgos)
        assert any("RFC" in r for r in recs)

    def test_documento_faltante(self):
        hallazgos = [
            _h(codigo="V9.1", pasa=False, nombre="Falta: INE del apoderado legal",
               severidad=Severidad.CRITICA, mensaje="Documento FALTANTE: INE"),
        ]
        recs = _generar_recomendaciones(hallazgos)
        assert any("faltante" in r.lower() or "INE" in r for r in recs)

    def test_deduplicacion(self):
        """Las recomendaciones no se repiten."""
        hallazgos = [
            _h(codigo="V1.1", pasa=False, nombre="RFC inconsistente",
               severidad=Severidad.CRITICA, mensaje="A"),
            _h(codigo="V1.1", pasa=False, nombre="RFC inconsistente",
               severidad=Severidad.CRITICA, mensaje="B"),
        ]
        recs = _generar_recomendaciones(hallazgos)
        assert len(recs) == len(set(recs))

    def test_medios_limitados(self):
        """Se limitan a 5 recomendaciones por medios."""
        hallazgos = [
            _h(pasa=False, severidad=Severidad.MEDIA, nombre=f"CP discrepante {i}",
               mensaje=f"msg {i}")
            for i in range(10)
        ]
        recs = _generar_recomendaciones(hallazgos)
        assert len(recs) <= 5


# ═══════════════════════════════════════════════════════════════════
#  _extraer_datos_clave
# ═══════════════════════════════════════════════════════════════════

def _dato(val):
    """Envuelve un valor como {valor, confiabilidad}."""
    return {"valor": val, "confiabilidad": "high"}


def _make_expediente(**kwargs) -> ExpedienteEmpresa:
    """Crea un ExpedienteEmpresa con valores por defecto."""
    defaults = dict(
        empresa_id="00000000-0000-0000-0000-000000000001",
        rfc="ABC123456XX1",
        razon_social="EMPRESA TEST SA DE CV",
        documentos={},
        doc_types_presentes=[],
    )
    defaults.update(kwargs)
    return ExpedienteEmpresa(**defaults)


class TestExtraerDatosClave:

    def test_razon_social_desde_csf(self):
        """Prioriza razón social de la CSF sobre la del registro empresa."""
        exp = _make_expediente(
            razon_social="EMPRESA VIEJA",
            documentos={
                "csf": {"razon_social": _dato("EMPRESA ACTUALIZADA SA DE CV")},
            },
        )
        dc = _extraer_datos_clave(exp)
        assert dc.razon_social == "EMPRESA ACTUALIZADA SA DE CV"

    def test_razon_social_fallback_acta(self):
        """Sin CSF, usa denominación del Acta Constitutiva."""
        exp = _make_expediente(
            razon_social="EMPRESA REG",
            documentos={
                "acta_constitutiva": {"denominacion_social": _dato("EMPRESA ACTA SC")},
            },
        )
        dc = _extraer_datos_clave(exp)
        assert dc.razon_social == "EMPRESA ACTA SC"

    def test_razon_social_fallback_empresa(self):
        """Sin CSF ni Acta, usa la razón social del registro empresa."""
        exp = _make_expediente(razon_social="EMPRESA REGISTRO")
        dc = _extraer_datos_clave(exp)
        assert dc.razon_social == "EMPRESA REGISTRO"

    def test_apoderado_desde_poder(self):
        """Extrae apoderado del Poder Notarial."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("JUAN PEREZ LOPEZ"),
                "tipo_poder": _dato("General para actos de administración"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert len(dc.apoderados) == 1
        assert dc.apoderados[0].nombre == "JUAN PEREZ LOPEZ"
        assert dc.apoderados[0].rol == "apoderado"
        assert dc.apoderados[0].fuente == "poder_notarial"
        assert "administración" in dc.apoderados[0].facultades

    def test_representante_legal_es_primer_apoderado(self):
        """El representante legal se extrae del primer apoderado."""
        exp = _make_expediente(documentos={
            "poder": {"nombre_apoderado": _dato("MARIA GARCIA RUIZ")},
        })
        dc = _extraer_datos_clave(exp)
        assert dc.representante_legal is not None
        assert dc.representante_legal.nombre == "MARIA GARCIA RUIZ"
        assert dc.representante_legal.rol == "representante_legal"

    def test_apoderado_fallback_ine(self):
        """Sin Poder, extrae nombre del apoderado de la INE."""
        exp = _make_expediente(documentos={
            "ine": {
                "nombre_completo": _dato("CARLOS MARTINEZ SOTO"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert len(dc.apoderados) == 1
        assert dc.apoderados[0].nombre == "CARLOS MARTINEZ SOTO"
        assert dc.apoderados[0].fuente == "ine"

    def test_accionistas_desde_acta(self):
        """Extrae accionistas desde Acta Constitutiva."""
        exp = _make_expediente(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": _dato([
                    {"nombre": "SOCIO UNO", "tipo": "Persona Física", "porcentaje": 60},
                    {"nombre": "SOCIO DOS", "tipo": "Persona Física", "porcentaje": 40},
                ]),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert len(dc.accionistas) == 2
        assert dc.accionistas[0].nombre == "SOCIO UNO"
        assert dc.accionistas[0].porcentaje == 60.0
        assert dc.accionistas[0].tipo_persona == "fisica"
        assert dc.accionistas[1].nombre == "SOCIO DOS"

    def test_accionistas_persona_moral(self):
        """Detecta personas morales en la estructura accionaria."""
        exp = _make_expediente(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": _dato([
                    {"nombre": "HOLDING SA DE CV", "tipo": "Persona Moral", "porcentaje": 100},
                ]),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.accionistas[0].tipo_persona == "moral"

    def test_accionistas_reforma_prioridad(self):
        """Reforma tiene prioridad; nombres duplicados no se repiten."""
        exp = _make_expediente(documentos={
            "acta_constitutiva": {
                "estructura_accionaria": _dato([
                    {"nombre": "ANA LOPEZ", "tipo": "PF", "porcentaje": 50},
                    {"nombre": "PEDRO GOMEZ", "tipo": "PF", "porcentaje": 50},
                ]),
            },
            "reforma_estatutos": {
                "estructura_accionaria": _dato([
                    {"nombre": "ANA LOPEZ", "tipo": "PF", "porcentaje": 70},
                    {"nombre": "NUEVO SOCIO", "tipo": "PF", "porcentaje": 30},
                ]),
            },
        })
        dc = _extraer_datos_clave(exp)
        nombres = [a.nombre for a in dc.accionistas]
        assert "ANA LOPEZ" in nombres
        assert "NUEVO SOCIO" in nombres
        assert "PEDRO GOMEZ" in nombres
        # ANA LOPEZ viene de reforma (70%), no duplicada
        ana = next(a for a in dc.accionistas if a.nombre == "ANA LOPEZ")
        assert ana.porcentaje == 70.0
        assert ana.fuente == "reforma_estatutos"

    def test_consejo_administracion(self):
        """Extrae consejo de administración de la reforma."""
        exp = _make_expediente(documentos={
            "reforma_estatutos": {
                "consejo_administracion": _dato([
                    {"nombre": "PRESIDENTE CONSEJO", "cargo": "Presidente"},
                    {"nombre": "SECRETARIO CONSEJO", "cargo": "Secretario"},
                ]),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert len(dc.consejo_administracion) == 2
        assert dc.consejo_administracion[0].nombre == "PRESIDENTE CONSEJO"
        assert dc.consejo_administracion[0].facultades == "Presidente"

    def test_expediente_vacio(self):
        """Sin documentos, datos_clave solo tiene la info del registro."""
        exp = _make_expediente()
        dc = _extraer_datos_clave(exp)
        assert dc.razon_social == "EMPRESA TEST SA DE CV"
        assert dc.rfc == "ABC123456XX1"
        assert dc.apoderados == []
        assert dc.representante_legal is None
        assert dc.accionistas == []
        assert dc.consejo_administracion == []

    def test_datos_clave_completo(self):
        """Caso completo con todos los documentos."""
        exp = _make_expediente(documentos={
            "csf": {
                "razon_social": _dato("EMPRESA COMPLETA SAPI DE CV"),
                "rfc": _dato("ECP123456AB1"),
            },
            "poder": {
                "nombre_apoderado": _dato("REPRESENTANTE PEREZ"),
                "tipo_poder": _dato("General amplio"),
            },
            "ine": {
                "nombre_completo": _dato("REPRESENTANTE PEREZ"),
            },
            "acta_constitutiva": {
                "estructura_accionaria": _dato([
                    {"nombre": "SOCIO A", "tipo": "PF", "porcentaje": 50},
                    {"nombre": "SOCIO B", "tipo": "PF", "porcentaje": 50},
                ]),
            },
            "reforma_estatutos": {
                "consejo_administracion": _dato([
                    {"nombre": "CONSEJERO X", "cargo": "Presidente"},
                ]),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.razon_social == "EMPRESA COMPLETA SAPI DE CV"
        assert dc.rfc == "ECP123456AB1"
        assert len(dc.apoderados) == 1
        assert dc.representante_legal is not None
        assert dc.representante_legal.nombre == "REPRESENTANTE PEREZ"
        assert len(dc.accionistas) == 2
        assert len(dc.consejo_administracion) == 1

    # ── Tests: Poder para abrir cuentas bancarias ──

    def test_poder_bancario_detectado_abrir_cuentas(self):
        """Detecta 'abrir cuentas' en las facultades del poder."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("APODERADO TEST"),
                "tipo_poder": _dato("General para actos de administración"),
                "facultades": _dato("Abrir cuentas bancarias e invertir fondos"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is True

    def test_poder_bancario_detectado_tipo_poder(self):
        """Detecta keywords bancarias en tipo_poder."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("APODERADO TEST"),
                "tipo_poder": _dato("General para apertura de cuentas y operaciones bancarias"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is True

    def test_poder_bancario_detectado_instituciones_credito(self):
        """Detecta 'instituciones de crédito' como facultad bancaria."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("APODERADO TEST"),
                "facultades": _dato("Operaciones ante instituciones de crédito y banca múltiple"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is True

    def test_poder_bancario_no_detectado(self):
        """No detecta poder bancario si solo hay administración."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("APODERADO TEST"),
                "tipo_poder": _dato("General para actos de administración"),
                "facultades": _dato("Pleitos y cobranzas, actos de dominio"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is False

    def test_poder_bancario_none_sin_poder(self):
        """Sin Poder Notarial, poder_cuenta_bancaria es None."""
        exp = _make_expediente()
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is None

    def test_poder_bancario_servicios_financieros(self):
        """Detecta 'servicios financieros' como facultad bancaria."""
        exp = _make_expediente(documentos={
            "poder": {
                "nombre_apoderado": _dato("APODERADO TEST"),
                "tipo_poder": _dato("General"),
                "facultades": _dato("Contratar servicios financieros y celebrar convenios"),
            },
        })
        dc = _extraer_datos_clave(exp)
        assert dc.poder_cuenta_bancaria is True
