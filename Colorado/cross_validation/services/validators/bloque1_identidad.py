"""
BLOQUE 1: IDENTIDAD CORPORATIVA
V1.1 — RFC consistente entre documentos
V1.2 — Razón social consistente
V1.3 — Estatus en el padrón fiscal
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor_str, comparar_razones_sociales, normalizar_texto, es_titular_corrupto
from .base import h, obtener_datos, obtener_reforma


_B = 1
_BN = "IDENTIDAD CORPORATIVA"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v1_1_rfc_consistente(exp))
    resultado.extend(_v1_2_razon_social_consistente(exp))
    resultado.append(_v1_3_estatus_padron(exp))
    return resultado


def _v1_1_rfc_consistente(exp: ExpedienteEmpresa) -> Hallazgo:
    """V1.1 — RFC consistente entre documentos."""
    rfcs: dict[str, str] = {}

    # Recolectar RFC de cada documento que lo tenga
    mapping = {
        "csf": "rfc",
        "fiel": "rfc",
        "acta_constitutiva": "rfc",
    }

    for doc_type, campo in mapping.items():
        datos = obtener_datos(exp, doc_type)
        if datos:
            val = get_valor_str(datos, campo)
            if val:
                rfcs[doc_type] = normalizar_texto(val)

    # Además, el RFC de la tabla empresas
    rfcs["BD (empresas)"] = normalizar_texto(exp.rfc)

    if not rfcs:
        return h("V1.1", "RFC consistente", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró RFC en ningún documento", valores={})

    valores_unicos = set(rfcs.values())

    if len(valores_unicos) == 1:
        return h("V1.1", "RFC consistente", _B, _BN, True, Severidad.CRITICA,
                 f"RFC {list(valores_unicos)[0]} coincide en todos los documentos",
                 valores=rfcs)
    else:
        return h("V1.1", "RFC consistente", _B, _BN, False, Severidad.CRITICA,
                 f"DISCREPANCIA: Se encontraron {len(valores_unicos)} RFC distintos",
                 valores=rfcs, valores_unicos=list(valores_unicos))


def _v1_2_razon_social_consistente(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """V1.2 — Razón social / Denominación social consistente."""
    nombres: dict[str, str] = {}

    # Recolectar razón social de cada documento
    campos_por_doc = {
        "csf": "razon_social",
        "fiel": "razon_social",
        "acta_constitutiva": "denominacion_social",
        "estado_cuenta": "titular",
        "poder": "nombre_poderdante",
    }

    for doc_type, campo in campos_por_doc.items():
        datos = obtener_datos(exp, doc_type)
        if datos:
            val = get_valor_str(datos, campo)
            if val:
                # Excluir titulares de estado de cuenta corruptos
                if doc_type == "estado_cuenta" and es_titular_corrupto(val):
                    continue
                nombres[doc_type] = val

    # Reforma
    reforma = obtener_reforma(exp)
    if reforma:
        val = get_valor_str(reforma, "razon_social")
        if val:
            nombres["reforma"] = val

    nombres["BD (empresas)"] = exp.razon_social

    if len(nombres) < 2:
        return [h("V1.2", "Razón social consistente", _B, _BN, None, Severidad.CRITICA,
                  "Solo se encontró razón social en un documento o ninguno",
                  valores=nombres)]

    # Comparar todos contra el de la CSF (o el primero disponible)
    referencia_key = "csf" if "csf" in nombres else list(nombres.keys())[0]
    referencia_val = nombres[referencia_key]
    resultados = []
    todas_coinciden = True

    for doc, nombre in nombres.items():
        if doc == referencia_key:
            continue
        coincide, sim, desc = comparar_razones_sociales(referencia_val, nombre)
        if not coincide:
            todas_coinciden = False

    if todas_coinciden:
        return [h("V1.2", "Razón social consistente", _B, _BN, True, Severidad.CRITICA,
                  "La razón social coincide en todos los documentos",
                  valores=nombres)]
    else:
        # Detallar las discrepancias
        detalles_comp: list[str] = []
        for doc, nombre in nombres.items():
            if doc == referencia_key:
                continue
            coincide, sim, desc = comparar_razones_sociales(referencia_val, nombre)
            if not coincide:
                detalles_comp.append(f"  {doc}: {nombre} → {desc}")

        return [h("V1.2", "Razón social consistente", _B, _BN, False, Severidad.CRITICA,
                  "DISCREPANCIA en razón social:\n" + "\n".join(detalles_comp),
                  valores=nombres, referencia=referencia_key)]


def _v1_3_estatus_padron(exp: ExpedienteEmpresa) -> Hallazgo:
    """V1.3 — Estatus en el padrón fiscal."""
    csf = obtener_datos(exp, "csf")
    if not csf:
        return h("V1.3", "Estatus padrón fiscal", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró CSF en el expediente")

    estatus = get_valor_str(csf, "estatus_padron")
    if not estatus:
        return h("V1.3", "Estatus padrón fiscal", _B, _BN, None, Severidad.CRITICA,
                 "No se pudo extraer el estatus del padrón fiscal de la CSF")

    estatus_norm = normalizar_texto(estatus)
    if estatus_norm == "ACTIVO":
        return h("V1.3", "Estatus padrón fiscal", _B, _BN, True, Severidad.CRITICA,
                 f"Estatus: {estatus} ✓", estatus=estatus)

    return h("V1.3", "Estatus padrón fiscal", _B, _BN, False, Severidad.CRITICA,
             f"ALERTA: Estatus '{estatus}' — NO es ACTIVO",
             estatus=estatus)
