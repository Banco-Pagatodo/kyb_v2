"""
BLOQUE 7: CONSISTENCIA NOTARIAL
V7.1 — Datos notariales de la constitutiva
V7.2 — Folio mercantil presente
V7.3 — Consistencia de folio entre documentos
V7.4 — Inscripción en Registro Público de Comercio (sello RPP/RPC)
"""
from __future__ import annotations

import re

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor_str, get_confiabilidad, normalizar_texto
from .base import h, obtener_datos, obtener_reforma

_B = 7
_BN = "CONSISTENCIA NOTARIAL"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v7_1_datos_notariales(exp))
    resultado.append(_v7_2_folio_mercantil(exp))
    resultado.append(_v7_3_consistencia_folio(exp))
    resultado.append(_v7_4_inscripcion_registro_publico(exp))
    return resultado


def _v7_1_datos_notariales(exp: ExpedienteEmpresa) -> Hallazgo:
    """V7.1 — Datos notariales de la constitutiva completos."""
    acta = obtener_datos(exp, "acta_constitutiva")
    if not acta:
        return h("V7.1", "Datos notariales", _B, _BN, None, Severidad.MEDIA,
                 "No se encontró Acta Constitutiva en el expediente")

    campos_requeridos = {
        "nombre_notario": "Nombre del notario",
        "numero_notaria": "Número de notaría",
        "estado_notaria": "Estado de la notaría",
        "numero_escritura_poliza": "Número de escritura/póliza",
    }

    faltantes: list[str] = []
    baja_confiabilidad: list[str] = []
    encontrados: dict[str, str] = {}

    for campo, desc in campos_requeridos.items():
        val = get_valor_str(acta, campo)
        conf = get_confiabilidad(acta, campo)

        if not val:
            faltantes.append(desc)
        else:
            encontrados[campo] = val
            if conf < 90.0:
                baja_confiabilidad.append(f"{desc}: {conf}%")

    if not faltantes and not baja_confiabilidad:
        return h("V7.1", "Datos notariales", _B, _BN, True, Severidad.MEDIA,
                 "Todos los datos notariales presentes con buena confiabilidad",
                 datos=encontrados)

    msg_parts = []
    if faltantes:
        msg_parts.append(f"Campos faltantes: {', '.join(faltantes)}")
    if baja_confiabilidad:
        msg_parts.append(f"Baja confiabilidad: {', '.join(baja_confiabilidad)}")

    # Faltantes en datos notariales impiden acreditar personalidad → CRITICA
    severidad = Severidad.CRITICA if faltantes else Severidad.MEDIA
    return h("V7.1", "Datos notariales", _B, _BN, False, severidad,
             " | ".join(msg_parts),
             encontrados=encontrados, faltantes=faltantes,
             baja_confiabilidad=baja_confiabilidad)


def _normalizar_folio(folio: str) -> str:
    """Normaliza un folio mercantil para comparación.
    Extrae el número base del folio antes de separadores de inscripción (*)
    Ej: '26728*16' → '26728', 'N-2019050847' → '2019050847'
    """
    if not folio:
        return ""
    # Si tiene '*' (folio*inscripción), tomar solo la parte base
    base = folio.split("*")[0].strip()
    # Remover prefijos no numéricos ("N-"), espacios, guiones
    norm = re.sub(r"[^0-9]", "", base)
    return norm


def _es_folio_pendiente(folio: str) -> bool:
    """Detecta si el folio indica que está pendiente."""
    if not folio:
        return True
    norm = normalizar_texto(folio)
    return any(kw in norm for kw in [
        "PENDIENTE", "INSCRIPCION", "TRAMITE", "NO DISPONIBLE",
    ])


def _v7_2_folio_mercantil(exp: ExpedienteEmpresa) -> Hallazgo:
    """V7.2 — Folio mercantil presente."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)

    folios: dict[str, str] = {}

    if acta:
        f = get_valor_str(acta, "folio_mercantil")
        if f:
            folios["acta_constitutiva"] = f
    if reforma:
        f = get_valor_str(reforma, "folio_mercantil")
        if f:
            folios["reforma"] = f

    if not folios:
        # Sin folio mercantil → imposible acreditar publicidad registral
        return h("V7.2", "Folio mercantil", _B, _BN, False, Severidad.CRITICA,
                 "No se encontró folio mercantil en ningún documento. "
                 "La falta de inscripción puede impedir la apertura de cuenta.")

    # Usar el más reciente (reforma > acta)
    folio_ref = folios.get("reforma", folios.get("acta_constitutiva", ""))

    if _es_folio_pendiente(folio_ref):
        return h("V7.2", "Folio mercantil", _B, _BN, False, Severidad.CRITICA,
                 f"Folio mercantil pendiente de inscripción: '{folio_ref}'. "
                 "La falta de inscripción vigente puede impedir la apertura.",
                 folios=folios)

    return h("V7.2", "Folio mercantil", _B, _BN, True, Severidad.MEDIA,
             f"Folio mercantil: {folio_ref}", folios=folios)


def _v7_3_consistencia_folio(exp: ExpedienteEmpresa) -> Hallazgo:
    """V7.3 — Consistencia de folio entre acta y reforma."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)

    if not acta or not reforma:
        return h("V7.3", "Consistencia folio", _B, _BN, None, Severidad.MEDIA,
                 "No hay acta y reforma para comparar folios")

    folio_acta = get_valor_str(acta, "folio_mercantil")
    folio_reforma = get_valor_str(reforma, "folio_mercantil")

    if not folio_acta or not folio_reforma:
        return h("V7.3", "Consistencia folio", _B, _BN, None, Severidad.MEDIA,
                 "Folio mercantil no disponible en uno de los documentos",
                 acta=folio_acta, reforma=folio_reforma)

    # Normalizar y comparar
    norm_acta = _normalizar_folio(folio_acta)
    norm_reforma = _normalizar_folio(folio_reforma)

    if norm_acta == norm_reforma:
        return h("V7.3", "Consistencia folio", _B, _BN, True, Severidad.MEDIA,
                 f"Folio mercantil consistente: acta '{folio_acta}' = reforma '{folio_reforma}'",
                 acta=folio_acta, reforma=folio_reforma)

    # Inconsistencia grave entre acta y reforma → CRITICA
    return h("V7.3", "Consistencia folio", _B, _BN, False, Severidad.CRITICA,
             f"INCONSISTENCIA GRAVE: folios mercantiles difieren entre acta "
             f"('{folio_acta}') y reforma ('{folio_reforma}'). "
             "Verificar que ambos documentos correspondan a la misma persona moral.",
             acta=folio_acta, reforma=folio_reforma)


def _v7_4_inscripcion_registro_publico(exp: ExpedienteEmpresa) -> Hallazgo:
    """V7.4 — Acta Constitutiva inscrita en el Registro Público de Comercio.

    El sello del Registro Público de la Propiedad / Comercio (RPP/RPC)
    se evidencia mediante el folio mercantil electrónico (FME). Si el
    folio existe y no está pendiente, la inscripción está verificada.
    """
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)

    if not acta and not reforma:
        return h("V7.4", "Inscripción Registro Público", _B, _BN, None,
                 Severidad.MEDIA,
                 "No se encontró Acta Constitutiva ni reforma para verificar "
                 "inscripción en el Registro Público")

    # Buscar folio en ambos documentos
    folio_acta = get_valor_str(acta, "folio_mercantil") if acta else ""
    folio_reforma = get_valor_str(reforma, "folio_mercantil") if reforma else ""
    folio_ref = folio_reforma or folio_acta

    if not folio_ref:
        return h("V7.4", "Inscripción Registro Público", _B, _BN, False,
                 Severidad.CRITICA,
                 "Sin evidencia de inscripción en el Registro Público de Comercio "
                 "(no se encontró folio mercantil). La falta de publicidad registral "
                 "impide acreditar personalidad y facultades.",
                 folio_acta=folio_acta, folio_reforma=folio_reforma)

    if _es_folio_pendiente(folio_ref):
        return h("V7.4", "Inscripción Registro Público", _B, _BN, False,
                 Severidad.CRITICA,
                 f"Inscripción en Registro Público de Comercio pendiente: '{folio_ref}'. "
                 "Sin inscripción vigente no se acredita personalidad jurídica.",
                 folio=folio_ref)

    return h("V7.4", "Inscripción Registro Público", _B, _BN, True,
             Severidad.MEDIA,
             f"Acta inscrita en el Registro Público de Comercio "
             f"(Folio mercantil: {folio_ref})",
             folio=folio_ref)
