"""
BLOQUE 2: DOMICILIO (Consistencia geográfica)
V2.1 — Código postal consistente
V2.2 — Domicilio fiscal vs comprobante de domicilio
V2.3 — Domicilio en acta constitutiva vs domicilio actual
V2.4 — Domicilio campo por campo (calle, número, colonia, alcaldía)
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import (
    get_valor_str, comparar_codigos_postales,
    normalizar_direccion, similitud, normalizar_texto,
)
from .base import h, obtener_datos, obtener_reforma

_B = 2
_BN = "DOMICILIO"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v2_1_cp_consistente(exp))
    resultado.append(_v2_2_domicilio_fiscal_vs_comprobante(exp))
    resultado.append(_v2_3_domicilio_acta_vs_actual(exp))
    resultado.append(_v2_4_domicilio_campo_por_campo(exp))
    return resultado


def _v2_1_cp_consistente(exp: ExpedienteEmpresa) -> Hallazgo:
    """V2.1 — Código postal consistente."""
    cps: dict[str, str] = {}

    csf = obtener_datos(exp, "csf")
    if csf:
        cp = get_valor_str(csf, "codigo_postal")
        if cp:
            cps["csf"] = cp

    dom = obtener_datos(exp, "domicilio")
    if dom:
        cp = get_valor_str(dom, "codigo_postal")
        if cp:
            cps["domicilio"] = cp

    if len(cps) < 2:
        return h("V2.1", "CP consistente", _B, _BN, None, Severidad.MEDIA,
                 "No hay suficientes documentos para comparar CP",
                 valores=cps)

    if comparar_codigos_postales(cps.get("csf", ""), cps.get("domicilio", "")):
        return h("V2.1", "CP consistente", _B, _BN, True, Severidad.MEDIA,
                 f"CP {cps.get('csf', '')} coincide entre CSF y comprobante de domicilio",
                 valores=cps)

    return h("V2.1", "CP consistente", _B, _BN, False, Severidad.MEDIA,
             f"DISCREPANCIA: CSF ({cps.get('csf', 'N/A')}) vs Domicilio ({cps.get('domicilio', 'N/A')})",
             valores=cps)


def _construir_direccion(datos: dict, campos: list[str]) -> str:
    """Construye string de dirección a partir de campos individuales."""
    partes = []
    for campo in campos:
        val = get_valor_str(datos, campo)
        if val:
            partes.append(val)
    return " ".join(partes)


def _v2_2_domicilio_fiscal_vs_comprobante(exp: ExpedienteEmpresa) -> Hallazgo:
    """V2.2 — Domicilio fiscal vs comprobante de domicilio."""
    csf = obtener_datos(exp, "csf")
    dom = obtener_datos(exp, "domicilio")

    if not csf or not dom:
        return h("V2.2", "Domicilio fiscal vs comprobante", _B, _BN, None, Severidad.MEDIA,
                 "Faltan CSF o comprobante de domicilio para comparar")

    # Construir dirección de la CSF
    dir_csf = get_valor_str(csf, "domicilio_fiscal")
    if not dir_csf:
        dir_csf = _construir_direccion(csf, [
            "calle", "numero_exterior", "numero_interior",
            "colonia", "municipio", "estado",
        ])

    # Construir dirección del comprobante
    dir_dom = _construir_direccion(dom, [
        "calle", "numero_exterior", "numero_interior",
        "colonia", "ciudad", "estado",
    ])

    if not dir_csf or not dir_dom:
        return h("V2.2", "Domicilio fiscal vs comprobante", _B, _BN, None, Severidad.MEDIA,
                 "No se pudo extraer dirección de uno o ambos documentos",
                 csf=dir_csf, domicilio=dir_dom)

    # Normalizar y comparar
    norm_csf = normalizar_direccion(dir_csf)
    norm_dom = normalizar_direccion(dir_dom)
    sim = similitud(norm_csf, norm_dom)

    if sim >= 0.85:
        return h("V2.2", "Domicilio fiscal vs comprobante", _B, _BN, True, Severidad.MEDIA,
                 f"Domicilios coinciden ({sim:.0%})",
                 csf=dir_csf, domicilio=dir_dom, similitud=sim)
    elif sim >= 0.5:
        return h("V2.2", "Domicilio fiscal vs comprobante", _B, _BN, False, Severidad.MEDIA,
                 f"Domicilios difieren parcialmente ({sim:.0%})",
                 csf=dir_csf, domicilio=dir_dom, similitud=sim)
    else:
        # Discrepancia total — pero si existe documento válido el enfoque
        # basado en riesgo (DCG) mantiene MEDIA; solo CRITICA si el
        # documento está vencido o no corresponde al cliente.
        return h("V2.2", "Domicilio fiscal vs comprobante", _B, _BN, False, Severidad.MEDIA,
                 f"Domicilios completamente distintos ({sim:.0%}) — "
                 "verificar que el comprobante corresponda al domicilio fiscal vigente",
                 csf=dir_csf, domicilio=dir_dom, similitud=sim)


def _v2_3_domicilio_acta_vs_actual(exp: ExpedienteEmpresa) -> Hallazgo:
    """V2.3 — Domicilio en acta/reforma vs domicilio actual."""
    csf = obtener_datos(exp, "csf")
    reforma = obtener_reforma(exp)
    acta = obtener_datos(exp, "acta_constitutiva")

    dir_actual = ""
    if csf:
        dir_actual = get_valor_str(csf, "domicilio_fiscal")
        if not dir_actual:
            dir_actual = _construir_direccion(csf, [
                "calle", "numero_exterior", "colonia", "municipio", "estado",
            ])

    # Priorizar reforma sobre acta
    dir_constitutiva = ""
    fuente = ""
    if reforma:
        dir_constitutiva = get_valor_str(reforma, "domicilio_social")
        fuente = "reforma"
    if not dir_constitutiva and acta:
        dir_constitutiva = get_valor_str(acta, "domicilio_social")
        fuente = "acta_constitutiva"

    if not dir_actual or not dir_constitutiva:
        return h("V2.3", "Domicilio constitutivo vs actual", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay suficientes datos para comparar domicilio constitutivo vs fiscal")

    norm_actual = normalizar_direccion(dir_actual)
    norm_const = normalizar_direccion(dir_constitutiva)
    sim = similitud(norm_actual, norm_const)

    if sim >= 0.75:
        return h("V2.3", "Domicilio constitutivo vs actual", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"Domicilio constitutivo ({fuente}) coincide con el fiscal ({sim:.0%})",
                 fiscal=dir_actual, constitutivo=dir_constitutiva, fuente=fuente)

    return h("V2.3", "Domicilio constitutivo vs actual", _B, _BN, False,
             Severidad.INFORMATIVA,
             f"El domicilio constitutivo ({fuente}) difiere del fiscal ({sim:.0%}). "
             "Puede haberse cambiado legalmente.",
             fiscal=dir_actual, constitutivo=dir_constitutiva, fuente=fuente)


# ── Prefijos comunes de dirección que no son nombres del lugar ──────
_PREFIJOS_LUGAR = {
    "COLONIA", "FRACCIONAMIENTO", "CALLE", "AVENIDA", "BOULEVARD",
    "PRIVADA", "CIRCUITO", "ANDADOR", "CERRADA", "CALLEJON",
    "PROLONGACION", "CAMINO", "CARRETERA", "PASEO", "RINCONADA",
}


def _campo_en_direccion(valor: str, dir_norm: str) -> bool:
    """Verifica si el valor de un campo aparece en una dirección normalizada.

    Realiza 3 intentos:
    1. Substring directo.
    2. Sin prefijos de tipo (COLONIA → vacío).
    3. Todas las palabras significativas (>2 letras) presentes.
    """
    if not valor:
        return False
    norm = normalizar_direccion(valor)
    if not norm:
        return False

    # 1) Substring
    if norm in dir_norm:
        return True

    # 2) Sin prefijo de tipo
    stripped = norm
    for p in _PREFIJOS_LUGAR:
        if stripped.startswith(p + " "):
            stripped = stripped[len(p) + 1:]
            break
    if stripped and stripped in dir_norm:
        return True

    # 3) Palabras significativas
    words = (stripped or norm).split()
    sig = [w for w in words if len(w) > 2]
    if sig and all(w in dir_norm for w in sig):
        return True

    return False


def _v2_4_domicilio_campo_por_campo(exp: ExpedienteEmpresa) -> Hallazgo:
    """V2.4 — Comparación campo por campo del domicilio fiscal vs comprobante.

    Busca cada campo individual del comprobante de domicilio dentro del
    domicilio_fiscal concatenado de la CSF. Reporta qué campos coinciden
    y cuáles no.
    """
    csf = obtener_datos(exp, "csf")
    dom = obtener_datos(exp, "domicilio")

    if not csf or not dom:
        return h("V2.4", "Domicilio campo por campo", _B, _BN, None, Severidad.MEDIA,
                 "Faltan CSF o comprobante de domicilio para comparar")

    dir_csf = get_valor_str(csf, "domicilio_fiscal")
    if not dir_csf:
        return h("V2.4", "Domicilio campo por campo", _B, _BN, None, Severidad.MEDIA,
                 "La CSF no tiene domicilio fiscal para comparar")

    dir_norm = normalizar_direccion(dir_csf)

    # Campos del comprobante de domicilio a contrastar
    campos: list[tuple[str, str]] = [
        ("Calle", get_valor_str(dom, "calle")),
        ("Número exterior", get_valor_str(dom, "numero_exterior")),
        ("Número interior", get_valor_str(dom, "numero_interior")),
        ("Colonia", get_valor_str(dom, "colonia")),
        ("Alcaldía/Municipio",
         get_valor_str(dom, "alcaldia") or get_valor_str(dom, "ciudad")),
        ("Estado",
         get_valor_str(dom, "entidad_federativa") or get_valor_str(dom, "estado")),
    ]

    coinciden: list[str] = []
    no_coinciden: list[str] = []
    omitidos: list[str] = []

    for nombre, valor in campos:
        if not valor or normalizar_texto(valor) in ("NA", "N A", "NO APLICA", "0", ""):
            omitidos.append(nombre)
            continue

        if _campo_en_direccion(valor, dir_norm):
            coinciden.append(f"{nombre}: {valor}")
        else:
            no_coinciden.append(f"{nombre}: {valor}")

    total = len(coinciden) + len(no_coinciden)
    if total == 0:
        return h("V2.4", "Domicilio campo por campo", _B, _BN, None, Severidad.MEDIA,
                 "No hay campos individuales suficientes en el comprobante para comparar",
                 omitidos=omitidos)

    # ── Construir resultado ──
    detalles: dict = {
        "coinciden": coinciden,
        "no_coinciden": no_coinciden,
        "omitidos": omitidos,
        "total_comparados": total,
    }

    if not no_coinciden:
        return h("V2.4", "Domicilio campo por campo", _B, _BN, True, Severidad.MEDIA,
                 f"Todos los campos del comprobante coinciden con la CSF "
                 f"({total}/{total}): {', '.join(coinciden)}",
                 **detalles)

    tasa = len(coinciden) / total
    disc_txt = "; ".join(no_coinciden)

    if tasa >= 0.6:
        return h("V2.4", "Domicilio campo por campo", _B, _BN, False, Severidad.MEDIA,
                 f"Coinciden {len(coinciden)}/{total} campos. "
                 f"Discrepancias: {disc_txt}",
                 **detalles)

    return h("V2.4", "Domicilio campo por campo", _B, _BN, False, Severidad.MEDIA,
             f"Solo coinciden {len(coinciden)}/{total} campos. "
             f"Discrepancias: {disc_txt}. "
             "Verificar que el comprobante corresponda al domicilio fiscal vigente.",
             **detalles)
