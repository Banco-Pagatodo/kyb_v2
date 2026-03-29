"""
Bloque 11 — Comparación de datos: Formulario Manual vs OCR.

Compara los datos capturados manualmente en el formulario de PagaTodo Hub
contra los datos extraídos por OCR de los documentos digitalizados.

Este bloque es CONDICIONAL: solo se ejecuta si existe el documento
``formulario_manual`` en el expediente.

Validaciones V11.1 – V11.10:
  V11.1  RFC de la persona moral          CRÍTICA
  V11.2  Razón social                     CRÍTICA
  V11.3  Nombre del representante legal   CRÍTICA
  V11.4  RFC del representante legal      MEDIA
  V11.5  Domicilio fiscal (calle)         MEDIA
  V11.6  Domicilio fiscal (CP)            MEDIA
  V11.7  No. de serie FIEL               MEDIA
  V11.8  Instrumento público (no. escritura) INFORMATIVA
  V11.9  Fecha de constitución            INFORMATIVA
  V11.10 Giro mercantil / actividad       INFORMATIVA
"""
from __future__ import annotations

from typing import Any

from ...models.schemas import (
    ComparacionCampo,
    ExpedienteEmpresa,
    Hallazgo,
    Severidad,
)
from ..text_utils import (
    comparar_nombres,
    comparar_razones_sociales,
    get_valor_str,
    normalizar_texto,
    similitud,
)
from ...core.config import (
    UMBRAL_SIMILITUD_MANUAL_OCR,
    UMBRAL_SIMILITUD_DIRECCION_MANUAL_OCR,
)
from .base import h, obtener_datos

_BLOQUE = 11
_BLOQUE_NOMBRE = "COMPARACIÓN MANUAL VS OCR"


# ── Helpers para extraer campos del formulario manual (camelCase) ──────────

def _get_manual(raw: dict, *keys: str) -> str:
    """Navega el dict camelCase del formulario manual tipo PagaTodo."""
    current: Any = raw
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if current is None:
        return ""
    return str(current).strip()


def _nombre_completo_rl(raw: dict) -> str:
    """Construye nombre completo del representante legal desde formulario."""
    rl = raw.get("representanteLegal") or {}
    partes = [
        (rl.get("nombres") or "").strip(),
        (rl.get("primerApellido") or "").strip(),
        (rl.get("segundoApellido") or "").strip(),
    ]
    return " ".join(p for p in partes if p)


def _nombre_completo_ine(ine: dict) -> str:
    """Extrae nombre completo de la INE OCR."""
    nc = get_valor_str(ine, "nombre_completo")
    if nc:
        return nc
    first = get_valor_str(ine, "FirstName")
    last = get_valor_str(ine, "LastName")
    if first or last:
        return f"{first} {last}".strip()
    nombre = get_valor_str(ine, "nombre")
    apellidos = get_valor_str(ine, "apellidos")
    if nombre or apellidos:
        return f"{nombre} {apellidos}".strip()
    return ""


# ── Validador principal ───────────────────────────────────────────────────

def validar(exp: ExpedienteEmpresa) -> tuple[list[Hallazgo], list[ComparacionCampo]]:
    """
    Compara datos del formulario manual contra datos OCR.

    Returns:
        Tupla (hallazgos, comparaciones).
    """
    raw = obtener_datos(exp, "formulario_manual")
    if not raw:
        return [], []

    hallazgos: list[Hallazgo] = []
    comparaciones: list[ComparacionCampo] = []

    csf = obtener_datos(exp, "csf")
    ine = obtener_datos(exp, "ine")
    fiel = obtener_datos(exp, "fiel")
    acta = obtener_datos(exp, "acta_constitutiva")

    # ── V11.1  RFC de la persona moral ─────────────────── CRÍTICA ──
    manual_rfc = normalizar_texto(_get_manual(raw, "personaMoral", "rfc"))
    ocr_rfc = normalizar_texto(get_valor_str(csf, "rfc")) if csf else ""
    if manual_rfc and ocr_rfc:
        coincide = manual_rfc == ocr_rfc
        comp = ComparacionCampo(
            campo="RFC Persona Moral",
            valor_manual=manual_rfc, valor_ocr=ocr_rfc,
            coincide=coincide, similitud=1.0 if coincide else 0.0,
            severidad=Severidad.CRITICA,
        )
        comparaciones.append(comp)
        hallazgos.append(h(
            "V11.1", "RFC PM: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide, severidad=Severidad.CRITICA,
            mensaje=f"Manual='{manual_rfc}' vs OCR='{ocr_rfc}'" + (
                " → COINCIDEN" if coincide else " → DISCREPANCIA"
            ),
        ))
    elif manual_rfc or ocr_rfc:
        comparaciones.append(ComparacionCampo(
            campo="RFC Persona Moral",
            valor_manual=manual_rfc, valor_ocr=ocr_rfc,
            coincide=None, severidad=Severidad.CRITICA,
        ))
        hallazgos.append(h(
            "V11.1", "RFC PM: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.CRITICA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.2  Razón social ───────────────────────────── CRÍTICA ──
    manual_rs = _get_manual(raw, "personaMoral", "razonSocial")
    ocr_rs = get_valor_str(csf, "razon_social") if csf else ""
    if manual_rs and ocr_rs:
        coincide_rs, sim_rs, desc_rs = comparar_razones_sociales(manual_rs, ocr_rs)
        comp = ComparacionCampo(
            campo="Razón Social",
            valor_manual=manual_rs, valor_ocr=ocr_rs,
            coincide=coincide_rs, similitud=sim_rs,
            severidad=Severidad.CRITICA,
        )
        comparaciones.append(comp)
        hallazgos.append(h(
            "V11.2", "Razón Social: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_rs, severidad=Severidad.CRITICA,
            mensaje=f"Manual='{manual_rs}' vs OCR='{ocr_rs}' — similitud={sim_rs:.2f} ({desc_rs})",
        ))
    elif manual_rs or ocr_rs:
        comparaciones.append(ComparacionCampo(
            campo="Razón Social",
            valor_manual=manual_rs, valor_ocr=ocr_rs,
            coincide=None, severidad=Severidad.CRITICA,
        ))
        hallazgos.append(h(
            "V11.2", "Razón Social: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.CRITICA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.3  Nombre del representante legal ─────────── CRÍTICA ──
    manual_nombre_rl = _nombre_completo_rl(raw)
    ocr_nombre_rl = _nombre_completo_ine(ine) if ine else ""
    if manual_nombre_rl and ocr_nombre_rl:
        coincide_n, sim_n = comparar_nombres(manual_nombre_rl, ocr_nombre_rl)
        comp = ComparacionCampo(
            campo="Nombre Rep. Legal",
            valor_manual=manual_nombre_rl, valor_ocr=ocr_nombre_rl,
            coincide=coincide_n, similitud=sim_n,
            severidad=Severidad.CRITICA,
        )
        comparaciones.append(comp)
        hallazgos.append(h(
            "V11.3", "Nombre R.L.: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_n, severidad=Severidad.CRITICA,
            mensaje=f"Manual='{manual_nombre_rl}' vs INE='{ocr_nombre_rl}' — similitud={sim_n:.2f}",
        ))
    elif manual_nombre_rl or ocr_nombre_rl:
        comparaciones.append(ComparacionCampo(
            campo="Nombre Rep. Legal",
            valor_manual=manual_nombre_rl, valor_ocr=ocr_nombre_rl,
            coincide=None, severidad=Severidad.CRITICA,
        ))
        hallazgos.append(h(
            "V11.3", "Nombre R.L.: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.CRITICA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.4  RFC del representante legal ─────────────── MEDIA ──
    manual_rfc_rl = normalizar_texto(_get_manual(raw, "representanteLegal", "rfc"))
    # OCR: intentar INE CURP → derivar RFC, o buscar en poder/acta
    ocr_rfc_rl = ""
    if ine:
        ocr_rfc_rl = normalizar_texto(get_valor_str(ine, "rfc"))
    if not ocr_rfc_rl:
        poder = obtener_datos(exp, "poder")
        if poder:
            ocr_rfc_rl = normalizar_texto(get_valor_str(poder, "rfc_apoderado"))
    if manual_rfc_rl and ocr_rfc_rl:
        coincide_rfc_rl = manual_rfc_rl == ocr_rfc_rl
        comparaciones.append(ComparacionCampo(
            campo="RFC Rep. Legal",
            valor_manual=manual_rfc_rl, valor_ocr=ocr_rfc_rl,
            coincide=coincide_rfc_rl, similitud=1.0 if coincide_rfc_rl else 0.0,
            severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.4", "RFC R.L.: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_rfc_rl, severidad=Severidad.MEDIA,
            mensaje=f"Manual='{manual_rfc_rl}' vs OCR='{ocr_rfc_rl}'" + (
                " → COINCIDEN" if coincide_rfc_rl else " → DISCREPANCIA"
            ),
        ))
    elif manual_rfc_rl or ocr_rfc_rl:
        comparaciones.append(ComparacionCampo(
            campo="RFC Rep. Legal",
            valor_manual=manual_rfc_rl, valor_ocr=ocr_rfc_rl,
            coincide=None, severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.4", "RFC R.L.: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.MEDIA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.5  Domicilio fiscal (calle) ────────────────── MEDIA ──
    manual_calle = _get_manual(raw, "domicilioFiscal", "calle")
    ocr_dom = {}
    if csf:
        dom_raw = get_valor_str(csf, "domicilio_fiscal")
        if not dom_raw:
            # domicilio puede ser sub-dict
            from ..text_utils import get_valor
            dom_obj = get_valor(csf, "domicilio_fiscal")
            if isinstance(dom_obj, dict):
                ocr_dom = dom_obj
        ocr_calle = get_valor_str(ocr_dom, "calle") if ocr_dom else get_valor_str(csf, "calle")
    else:
        ocr_calle = ""
    if manual_calle and ocr_calle:
        sim_calle = similitud(manual_calle, ocr_calle)
        coincide_calle = sim_calle >= UMBRAL_SIMILITUD_DIRECCION_MANUAL_OCR
        comparaciones.append(ComparacionCampo(
            campo="Domicilio (calle)",
            valor_manual=manual_calle, valor_ocr=ocr_calle,
            coincide=coincide_calle, similitud=sim_calle,
            severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.5", "Calle: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_calle, severidad=Severidad.MEDIA,
            mensaje=f"Manual='{manual_calle}' vs OCR='{ocr_calle}' — similitud={sim_calle:.2f}",
        ))
    elif manual_calle or ocr_calle:
        comparaciones.append(ComparacionCampo(
            campo="Domicilio (calle)",
            valor_manual=manual_calle, valor_ocr=ocr_calle,
            coincide=None, severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.5", "Calle: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.MEDIA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.6  Domicilio fiscal (CP) ───────────────────── MEDIA ──
    manual_cp = normalizar_texto(_get_manual(raw, "domicilioFiscal", "cp"))
    ocr_cp = ""
    if ocr_dom:
        ocr_cp = normalizar_texto(
            get_valor_str(ocr_dom, "codigo_postal") or get_valor_str(ocr_dom, "cp")
        )
    elif csf:
        ocr_cp = normalizar_texto(
            get_valor_str(csf, "codigo_postal") or get_valor_str(csf, "cp")
        )
    if manual_cp and ocr_cp:
        coincide_cp = manual_cp == ocr_cp
        comparaciones.append(ComparacionCampo(
            campo="Código Postal",
            valor_manual=manual_cp, valor_ocr=ocr_cp,
            coincide=coincide_cp, similitud=1.0 if coincide_cp else 0.0,
            severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.6", "CP: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_cp, severidad=Severidad.MEDIA,
            mensaje=f"Manual='{manual_cp}' vs OCR='{ocr_cp}'" + (
                " → COINCIDEN" if coincide_cp else " → DISCREPANCIA"
            ),
        ))
    elif manual_cp or ocr_cp:
        comparaciones.append(ComparacionCampo(
            campo="Código Postal",
            valor_manual=manual_cp, valor_ocr=ocr_cp,
            coincide=None, severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.6", "CP: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.MEDIA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.7  No. de serie FIEL ──────────────────────── MEDIA ──
    manual_fiel = normalizar_texto(_get_manual(raw, "personaMoral", "serieFEA"))
    ocr_fiel = ""
    if fiel:
        ocr_fiel = normalizar_texto(
            get_valor_str(fiel, "numero_serie_certificado") or get_valor_str(fiel, "no_serie")
        )
    if manual_fiel and ocr_fiel:
        coincide_fiel = manual_fiel == ocr_fiel
        comparaciones.append(ComparacionCampo(
            campo="No. Serie FIEL",
            valor_manual=manual_fiel, valor_ocr=ocr_fiel,
            coincide=coincide_fiel, similitud=1.0 if coincide_fiel else 0.0,
            severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.7", "FIEL: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_fiel, severidad=Severidad.MEDIA,
            mensaje=f"Manual='{manual_fiel}' vs OCR='{ocr_fiel}'" + (
                " → COINCIDEN" if coincide_fiel else " → DISCREPANCIA"
            ),
        ))
    elif manual_fiel or ocr_fiel:
        comparaciones.append(ComparacionCampo(
            campo="No. Serie FIEL",
            valor_manual=manual_fiel, valor_ocr=ocr_fiel,
            coincide=None, severidad=Severidad.MEDIA,
        ))
        hallazgos.append(h(
            "V11.7", "FIEL: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.MEDIA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.8  Instrumento público (no. escritura) ─── INFORMATIVA ──
    manual_instr = normalizar_texto(_get_manual(raw, "actaConstitutiva", "instrumentoPublico"))
    ocr_instr = ""
    if acta:
        ocr_instr = normalizar_texto(
            get_valor_str(acta, "numero_escritura") or get_valor_str(acta, "instrumento_publico")
        )
    if manual_instr and ocr_instr:
        coincide_instr = manual_instr == ocr_instr
        comparaciones.append(ComparacionCampo(
            campo="Instrumento Público",
            valor_manual=manual_instr, valor_ocr=ocr_instr,
            coincide=coincide_instr, similitud=1.0 if coincide_instr else 0.0,
            severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.8", "Instrumento: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_instr, severidad=Severidad.INFORMATIVA,
            mensaje=f"Manual='{manual_instr}' vs OCR='{ocr_instr}'" + (
                " → COINCIDEN" if coincide_instr else " → DISCREPANCIA"
            ),
        ))
    elif manual_instr or ocr_instr:
        comparaciones.append(ComparacionCampo(
            campo="Instrumento Público",
            valor_manual=manual_instr, valor_ocr=ocr_instr,
            coincide=None, severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.8", "Instrumento: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.INFORMATIVA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.9  Fecha de constitución ──────────────── INFORMATIVA ──
    manual_fecha = normalizar_texto(_get_manual(raw, "actaConstitutiva", "fechaConstitucion"))
    ocr_fecha = ""
    if acta:
        ocr_fecha = normalizar_texto(
            get_valor_str(acta, "fecha_constitucion") or get_valor_str(acta, "fecha_escritura")
        )
    if manual_fecha and ocr_fecha:
        coincide_f = manual_fecha == ocr_fecha
        # Intentar comparación parcial (solo año y mes si formatos difieren)
        if not coincide_f:
            # Limpiar separadores para comparar dígitos
            clean_m = "".join(c for c in manual_fecha if c.isdigit())
            clean_o = "".join(c for c in ocr_fecha if c.isdigit())
            if clean_m and clean_o and clean_m == clean_o:
                coincide_f = True
        comparaciones.append(ComparacionCampo(
            campo="Fecha Constitución",
            valor_manual=manual_fecha, valor_ocr=ocr_fecha,
            coincide=coincide_f, similitud=1.0 if coincide_f else 0.0,
            severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.9", "Fecha constitución: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_f, severidad=Severidad.INFORMATIVA,
            mensaje=f"Manual='{manual_fecha}' vs OCR='{ocr_fecha}'" + (
                " → COINCIDEN" if coincide_f else " → DISCREPANCIA"
            ),
        ))
    elif manual_fecha or ocr_fecha:
        comparaciones.append(ComparacionCampo(
            campo="Fecha Constitución",
            valor_manual=manual_fecha, valor_ocr=ocr_fecha,
            coincide=None, severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.9", "Fecha constitución: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.INFORMATIVA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    # ── V11.10 Giro mercantil / actividad ─────────── INFORMATIVA ──
    manual_giro = _get_manual(raw, "personaMoral", "giroMercantil")
    ocr_giro = ""
    if csf:
        ocr_giro = get_valor_str(csf, "giro_mercantil") or get_valor_str(csf, "actividad_economica")
    if manual_giro and ocr_giro:
        sim_giro = similitud(manual_giro, ocr_giro)
        coincide_g = sim_giro >= UMBRAL_SIMILITUD_MANUAL_OCR
        comparaciones.append(ComparacionCampo(
            campo="Giro Mercantil",
            valor_manual=manual_giro, valor_ocr=ocr_giro,
            coincide=coincide_g, similitud=sim_giro,
            severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.10", "Giro: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=coincide_g, severidad=Severidad.INFORMATIVA,
            mensaje=f"Manual='{manual_giro}' vs OCR='{ocr_giro}' — similitud={sim_giro:.2f}",
        ))
    elif manual_giro or ocr_giro:
        comparaciones.append(ComparacionCampo(
            campo="Giro Mercantil",
            valor_manual=manual_giro, valor_ocr=ocr_giro,
            coincide=None, severidad=Severidad.INFORMATIVA,
        ))
        hallazgos.append(h(
            "V11.10", "Giro: Manual vs OCR", _BLOQUE, _BLOQUE_NOMBRE,
            pasa=None, severidad=Severidad.INFORMATIVA,
            mensaje="Solo una fuente disponible — no se puede comparar",
        ))

    return hallazgos, comparaciones
