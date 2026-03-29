"""
BLOQUE 3: VIGENCIA DE DOCUMENTOS
V3.1 — FIEL vigente
V3.2 — INE del apoderado vigente
V3.3 — Antigüedad del comprobante de domicilio
V3.4 — Antigüedad de la CSF
V3.5 — Antigüedad del estado de cuenta
"""
from __future__ import annotations

from datetime import date

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor_str, parsear_fecha, es_vigente, meses_desde
from ...core.config import (
    MESES_VIGENCIA_DOMICILIO, MESES_VIGENCIA_CSF, MESES_VIGENCIA_EDO_CTA,
)
from .base import h, obtener_datos

_B = 3
_BN = "VIGENCIA DE DOCUMENTOS"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v3_1_fiel_vigente(exp))
    resultado.append(_v3_2_ine_vigente(exp))
    resultado.append(_v3_3_domicilio_reciente(exp))
    resultado.append(_v3_4_csf_reciente(exp))
    resultado.append(_v3_5_edo_cuenta_reciente(exp))
    return resultado


def _v3_1_fiel_vigente(exp: ExpedienteEmpresa) -> Hallazgo:
    """V3.1 — FIEL vigente."""
    fiel = obtener_datos(exp, "fiel")
    if not fiel:
        return h("V3.1", "FIEL vigente", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró documento de FIEL en el expediente")

    vigencia_str = get_valor_str(fiel, "vigencia_hasta")
    if not vigencia_str:
        # Intentar campo alternativo
        vigencia_str = get_valor_str(fiel, "fecha_vencimiento")
    if not vigencia_str:
        vigencia_str = get_valor_str(fiel, "vigencia")

    if not vigencia_str:
        return h("V3.1", "FIEL vigente", _B, _BN, None, Severidad.CRITICA,
                 "No se pudo extraer la fecha de vigencia de la FIEL")

    fecha = parsear_fecha(vigencia_str)
    if not fecha:
        return h("V3.1", "FIEL vigente", _B, _BN, None, Severidad.CRITICA,
                 f"No se pudo parsear la fecha de vigencia: '{vigencia_str}'",
                 valor_original=vigencia_str)

    hoy = date.today()
    if es_vigente(fecha, hoy):
        return h("V3.1", "FIEL vigente", _B, _BN, True, Severidad.CRITICA,
                 f"FIEL vigente hasta {fecha.isoformat()}",
                 vigencia_hasta=fecha.isoformat(), hoy=hoy.isoformat())

    return h("V3.1", "FIEL vigente", _B, _BN, False, Severidad.CRITICA,
             f"FIEL VENCIDA el {fecha.isoformat()}",
             vigencia_hasta=fecha.isoformat(), hoy=hoy.isoformat())


def _v3_2_ine_vigente(exp: ExpedienteEmpresa) -> Hallazgo:
    """V3.2 — INE del apoderado vigente."""
    ine = obtener_datos(exp, "ine")
    if not ine:
        return h("V3.2", "INE vigente", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró documento de INE en el expediente")

    # El campo puede ser DateOfExpiration, fecha_vencimiento, vigencia
    vigencia_str = (
        get_valor_str(ine, "DateOfExpiration")
        or get_valor_str(ine, "fecha_vencimiento")
        or get_valor_str(ine, "vigencia")
    )

    if not vigencia_str:
        return h("V3.2", "INE vigente", _B, _BN, None, Severidad.CRITICA,
                 "No se pudo extraer la fecha de vigencia de la INE")

    fecha = parsear_fecha(vigencia_str)
    if not fecha:
        return h("V3.2", "INE vigente", _B, _BN, None, Severidad.CRITICA,
                 f"No se pudo parsear la fecha de vigencia INE: '{vigencia_str}'",
                 valor_original=vigencia_str)

    hoy = date.today()
    if es_vigente(fecha, hoy):
        return h("V3.2", "INE vigente", _B, _BN, True, Severidad.CRITICA,
                 f"INE vigente hasta {fecha.isoformat()}",
                 vigencia_hasta=fecha.isoformat(), hoy=hoy.isoformat())

    return h("V3.2", "INE vigente", _B, _BN, False, Severidad.CRITICA,
             f"INE VENCIDA el {fecha.isoformat()}",
             vigencia_hasta=fecha.isoformat(), hoy=hoy.isoformat())


def _verificar_antiguedad(
    exp: ExpedienteEmpresa,
    doc_type: str,
    doc_nombre: str,
    campos_fecha: list[str],
    meses_maximo: int,
    codigo: str,
) -> Hallazgo:
    """Helper genérico para verificar antigüedad de un documento."""
    datos = obtener_datos(exp, doc_type)
    if not datos:
        return h(codigo, f"{doc_nombre} reciente", _B, _BN, None, Severidad.CRITICA,
                 f"No se encontró {doc_nombre} en el expediente")

    fecha_str = ""
    for campo in campos_fecha:
        fecha_str = get_valor_str(datos, campo)
        if fecha_str:
            break

    if not fecha_str:
        return h(codigo, f"{doc_nombre} reciente", _B, _BN, None, Severidad.CRITICA,
                 f"No se pudo extraer la fecha del {doc_nombre}")

    fecha = parsear_fecha(fecha_str)
    if not fecha:
        return h(codigo, f"{doc_nombre} reciente", _B, _BN, None, Severidad.CRITICA,
                 f"No se pudo parsear la fecha del {doc_nombre}: '{fecha_str}'",
                 valor_original=fecha_str)

    hoy = date.today()
    meses = meses_desde(fecha, hoy)

    if meses <= meses_maximo:
        return h(codigo, f"{doc_nombre} reciente", _B, _BN, True, Severidad.CRITICA,
                 f"{doc_nombre} emitido hace {meses} mes(es) ({fecha.isoformat()})",
                 fecha=fecha.isoformat(), meses=meses)

    return h(codigo, f"{doc_nombre} reciente", _B, _BN, False, Severidad.CRITICA,
             f"{doc_nombre} tiene {meses} meses de antigüedad (máximo {meses_maximo})",
             fecha=fecha.isoformat(), meses=meses, maximo=meses_maximo)


def _v3_3_domicilio_reciente(exp: ExpedienteEmpresa) -> Hallazgo:
    return _verificar_antiguedad(
        exp, "domicilio", "Comprobante de domicilio",
        ["fecha_emision", "fecha", "periodo"],
        MESES_VIGENCIA_DOMICILIO, "V3.3",
    )


def _v3_4_csf_reciente(exp: ExpedienteEmpresa) -> Hallazgo:
    return _verificar_antiguedad(
        exp, "csf", "Constancia de Situación Fiscal",
        ["fecha_emision", "fecha_impresion", "fecha"],
        MESES_VIGENCIA_CSF, "V3.4",
    )


def _v3_5_edo_cuenta_reciente(exp: ExpedienteEmpresa) -> Hallazgo:
    return _verificar_antiguedad(
        exp, "estado_cuenta", "Estado de cuenta",
        ["periodo", "fecha_emision", "fecha_corte"],
        MESES_VIGENCIA_EDO_CTA, "V3.5",
    )
