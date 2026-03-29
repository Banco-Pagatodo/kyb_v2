"""
Tests unitarios para persistence._construir_resumen_bloques — función pura.
"""
from __future__ import annotations

from cross_validation.models.schemas import Hallazgo, Severidad
from cross_validation.services.persistence import _construir_resumen_bloques


def _h(codigo: str, bloque: int, pasa: bool | None,
       severidad: Severidad = Severidad.CRITICA) -> Hallazgo:
    return Hallazgo(
        codigo=codigo, nombre=f"Test {codigo}", bloque=bloque,
        bloque_nombre=f"BLOQUE {bloque}", pasa=pasa,
        severidad=severidad, mensaje="msg",
    )


class TestConstruirResumenBloques:
    def test_vacio(self):
        assert _construir_resumen_bloques([]) == {}

    def test_un_bloque_todo_pasa(self):
        hallazgos = [
            _h("V1.1", 1, True),
            _h("V1.2", 1, True),
            _h("V1.3", 1, True),
        ]
        resumen = _construir_resumen_bloques(hallazgos)
        assert "1" in resumen
        b1 = resumen["1"]
        assert b1["total"] == 3
        assert b1["pasan"] == 3
        assert b1["fallan"] == 0
        assert b1["criticos"] == 0
        assert b1["codigos"] == ["V1.1", "V1.2", "V1.3"]

    def test_multiples_bloques(self):
        hallazgos = [
            _h("V1.1", 1, True),
            _h("V2.1", 2, False, Severidad.MEDIA),
            _h("V9.1", 9, False, Severidad.CRITICA),
        ]
        resumen = _construir_resumen_bloques(hallazgos)
        assert len(resumen) == 3
        assert resumen["1"]["pasan"] == 1
        assert resumen["2"]["fallan"] == 1
        assert resumen["2"]["medios"] == 1
        assert resumen["9"]["criticos"] == 1

    def test_na_cuenta_como_na(self):
        hallazgos = [_h("V10.1", 10, None, Severidad.INFORMATIVA)]
        resumen = _construir_resumen_bloques(hallazgos)
        b10 = resumen["10"]
        assert b10["na"] == 1
        assert b10["informativos"] == 1
        assert b10["pasan"] == 0
        assert b10["fallan"] == 0

    def test_nombre_bloque(self):
        hallazgos = [_h("V1.1", 1, True)]
        resumen = _construir_resumen_bloques(hallazgos)
        assert resumen["1"]["nombre"] == "IDENTIDAD CORPORATIVA"
