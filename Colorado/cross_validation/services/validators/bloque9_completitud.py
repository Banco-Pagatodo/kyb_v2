"""
BLOQUE 9: COMPLETITUD DEL EXPEDIENTE
V9.1 — Documentos mínimos requeridos para KYB
V9.2 — Documentos complementarios deseables
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ...core.config import DOCS_MINIMOS, DOCS_COMPLEMENTARIOS
from .base import h

_B = 9
_BN = "COMPLETITUD DEL EXPEDIENTE"

# Nombres legibles para cada tipo de documento
_NOMBRES_DOC = {
    "csf": "Constancia de Situación Fiscal",
    "fiel": "Acuse de FIEL",
    "ine": "INE del apoderado legal",
    "ine_reverso": "INE reverso",
    "ine_propietario_real": "INE del propietario real",
    "estado_cuenta": "Estado de cuenta bancario",
    "domicilio": "Comprobante de domicilio (empresa)",
    "domicilio_rl": "Comprobante de domicilio (representante legal)",
    "domicilio_propietario_real": "Comprobante de domicilio (propietario real)",
    "acta_constitutiva": "Acta constitutiva",
    "poder": "Poder notarial",
    "reforma": "Reforma de estatutos",
    "reforma_estatutos": "Reforma de estatutos",
}


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.extend(_v9_1_docs_minimos(exp))
    resultado.extend(_v9_2_docs_complementarios(exp))
    return resultado


def _v9_1_docs_minimos(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """V9.1 — Documentos mínimos requeridos para KYB."""
    presentes: list[str] = []
    faltantes: list[str] = []

    for doc in DOCS_MINIMOS:
        if doc in exp.doc_types_presentes:
            presentes.append(doc)
        else:
            faltantes.append(doc)

    # ── Sustitución formal: estado de cuenta → comprobante de domicilio ──
    # El estado de cuenta bancario contiene la dirección fiscal del titular;
    # las DCG lo aceptan como comprobante de domicilio válido (≤3 meses).
    # Si «domicilio» falta pero «estado_cuenta» está presente, se acepta
    # la sustitución y no se marca como faltante.
    if "domicilio" in faltantes and "estado_cuenta" in presentes:
        faltantes.remove("domicilio")

    resultados = []

    if not faltantes:
        resultados.append(h(
            "V9.1", "Documentos mínimos", _B, _BN, True, Severidad.CRITICA,
            f"Todos los documentos mínimos presentes ({len(presentes)}/{len(DOCS_MINIMOS)})",
            presentes=presentes,
        ))
    else:
        # Un hallazgo por cada documento faltante
        for doc in faltantes:
            nombre_doc = _NOMBRES_DOC.get(doc, doc)
            resultados.append(h(
                "V9.1", f"Falta: {nombre_doc}", _B, _BN, False, Severidad.CRITICA,
                f"Documento FALTANTE: {nombre_doc} ({doc})",
                documento=doc, nombre_documento=nombre_doc,
            ))

        # Resumen
        nombres_faltantes = [_NOMBRES_DOC.get(d, d) for d in faltantes]
        resultados.append(h(
            "V9.1", "Documentos mínimos", _B, _BN, False, Severidad.CRITICA,
            f"Faltan {len(faltantes)}/{len(DOCS_MINIMOS)} documentos: "
            + ", ".join(nombres_faltantes),
            presentes=presentes, faltantes=faltantes,
        ))

    return resultados


def _v9_2_docs_complementarios(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """V9.2 — Documentos complementarios deseables."""
    presentes: list[str] = []
    faltantes: list[str] = []

    for doc in DOCS_COMPLEMENTARIOS:
        if doc in exp.doc_types_presentes:
            presentes.append(doc)
        else:
            faltantes.append(doc)

    # Si tiene reforma_estatutos, no contar reforma como faltante (y viceversa)
    if "reforma_estatutos" in presentes and "reforma" in faltantes:
        faltantes.remove("reforma")
    if "reforma" in presentes and "reforma_estatutos" in faltantes:
        faltantes.remove("reforma_estatutos")
    # Si ambas faltan, solo contar una (son equivalentes)
    if "reforma_estatutos" in faltantes and "reforma" in faltantes:
        faltantes.remove("reforma")

    if not faltantes:
        return [h("V9.2", "Documentos complementarios", _B, _BN, True,
                  Severidad.MEDIA,
                  f"Todos los documentos complementarios presentes",
                  presentes=presentes)]

    nombres = [_NOMBRES_DOC.get(d, d) for d in faltantes]
    return [h("V9.2", "Documentos complementarios", _B, _BN, False,
              Severidad.MEDIA,
              f"Documentos complementarios faltantes: {', '.join(nombres)}",
              presentes=presentes, faltantes=faltantes)]
