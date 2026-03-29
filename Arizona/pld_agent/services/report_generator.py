"""
Generador de reportes de texto para el análisis PLD — Etapa 1 + 2 integradas.

Formato visual inspirado en el reporte de Colorado (reporte.txt):
  ═══  separadores principales
  ───  subseparadores
  ··   separadores de bloque
  🔴🟡ℹ️  iconos de severidad
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models.schemas import (
    PersonaIdentificada,
    ResultadoCompletitud,
    SeveridadPLD,
    VerificacionCompletitud,
)
from ..models.mer_schemas import ResultadoMER


_CAT_BLOQUE: dict[str, tuple[int, str]] = {
    "DOCUMENTO": (1, "DOCUMENTOS OBLIGATORIOS"),
    "DATO_OBLIGATORIO": (2, "DATOS DE LA PERSONA MORAL"),
    "DOMICILIO": (3, "DOMICILIO COMPLETO"),
    "PERSONAS": (4, "PERSONAS IDENTIFICADAS"),
    "PODER_BANCARIO": (5, "PODER BANCARIO"),
    "VALIDACION_CRUZADA": (6, "VALIDACIÓN CRUZADA (COLORADO)"),
}


def _items_a_hallazgos(items: list) -> list[dict[str, Any]]:
    """Convierte ItemCompletitud → lista de hallazgos estilo Colorado."""
    hallazgos: list[dict[str, Any]] = []
    for it in items:
        bloque, bloque_nombre = _CAT_BLOQUE.get(it.categoria, (0, it.categoria))
        hallazgos.append({
            "codigo": it.codigo,
            "nombre": it.elemento,
            "bloque": bloque,
            "bloque_nombre": bloque_nombre,
            "pasa": it.presente,
            "severidad": it.severidad.value if hasattr(it.severidad, "value") else str(it.severidad),
            "mensaje": it.detalle,
            "detalles": {"fuente": it.fuente} if it.fuente else {},
        })
    return hallazgos


@dataclass
class ResultadoReporteUnificado:
    """Resultado de generar_reporte_unificado: texto + datos estructurados."""
    texto: str
    empresa_id: str
    rfc: str
    razon_social: str
    dictamen: str                          # APROBADO | APROBADO CON OBSERVACIONES | RECHAZADO
    total_pasan: int = 0
    total_criticos: int = 0
    total_altos: int = 0
    total_medios: int = 0
    total_informativos: int = 0
    hallazgos: list[dict[str, Any]] = field(default_factory=list)
    recomendaciones: list[str] = field(default_factory=list)
    documentos_presentes: list[str] = field(default_factory=list)
    screening_incompleto: bool = False


def generar_reporte_etapa1(vf: VerificacionCompletitud) -> str:
    """
    Genera un reporte de texto formateado para la Etapa 1 PLD.
    Formato visual idéntico al de Colorado (reporte.txt).
    """
    L: list[str] = []
    SEP = "═" * 60
    SUB = "─" * 60

    # ── ENCABEZADO ───────────────────────────────────────────────
    L.append(SEP)
    L.append("  REPORTE DE ANÁLISIS PLD / AML — ARIZONA")
    L.append(SEP)
    L.append("")
    L.append(f"  EMPRESA: {vf.razon_social}")
    L.append(f"  RFC: {vf.rfc}")
    L.append(f"  EMPRESA_ID: {vf.empresa_id}")
    L.append(f"  FECHA DE ANÁLISIS: {vf.fecha_analisis.strftime('%Y-%m-%d %H:%M')}")

    docs_str = ", ".join(vf.documentos_presentes) if vf.documentos_presentes else "N/D"
    L.append(f"  DOCUMENTOS EN EXPEDIENTE: {docs_str}")

    # ── DATOS CLAVE ──────────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  DATOS CLAVE DE LA PERSONA MORAL")
    L.append(SUB)
    L.append("")
    L.append(f"  Razón Social: {vf.razon_social}")
    L.append(f"  RFC:          {vf.rfc}")

    # Representante / apoderado
    apoderado = next((p for p in vf.personas_identificadas if p.rol in ("apoderado", "representante_legal")), None)
    if apoderado:
        L.append("")
        L.append("  ▸ REPRESENTANTE LEGAL")
        L.append(f"    Nombre:      {apoderado.nombre}")
        curp_rep = getattr(apoderado, '_curp_ine', None)
        if curp_rep:
            L.append(f"    CURP:        {curp_rep}")
        L.append(f"    Fuente:      {apoderado.fuente}")

    # Poder bancario
    poder_txt = "✅ SÍ" if vf.poder_cuenta_bancaria else ("❌ NO DETECTADO" if vf.poder_cuenta_bancaria is False else "⚠️ NO DETERMINADO")
    L.append("")
    L.append(f"  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: {poder_txt}")

    # Accionistas
    accionistas = [p for p in vf.personas_identificadas if p.rol == "accionista"]
    if accionistas:
        L.append("")
        L.append("  ▸ ACCIONISTAS / SOCIOS")
        L.append(f"    {'#':<5}{'Nombre':<40}{'Tipo':<18}{'%':>6}  Fuente")
        L.append("    " + "─" * 80)
        for i, a in enumerate(accionistas, 1):
            pct = f"{a.porcentaje:.1f}%" if a.porcentaje is not None else "N/D"
            tipo = "P. Física" if a.tipo_persona == "fisica" else "P. Moral"
            L.append(f"    {i:<5}{a.nombre:<40}{tipo:<18}{pct:>6}  {a.fuente}")

    # ── RESUMEN EJECUTIVO ────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  RESUMEN EJECUTIVO")
    L.append(SUB)
    L.append("")

    # Calcular conteos por severidad de items faltantes
    items_pasan = [it for it in vf.items if it.presente]
    items_criticos = [it for it in vf.items if not it.presente and it.severidad == SeveridadPLD.CRITICA]
    items_altos = [it for it in vf.items if not it.presente and it.severidad == SeveridadPLD.ALTA]
    items_medios = [it for it in vf.items if not it.presente and it.severidad == SeveridadPLD.MEDIA]
    items_info = [it for it in vf.items if not it.presente and it.severidad == SeveridadPLD.INFORMATIVA]

    # Dictamen PLD
    emoji_res = {"COMPLETO": "✅", "PARCIAL": "⚠️", "INCOMPLETO": "❌"}
    dictamen_map = {
        "COMPLETO": "COMPLETO",
        "PARCIAL": "APROBADO CON OBSERVACIONES",
        "INCOMPLETO": "INCOMPLETO — DOCUMENTACIÓN INSUFICIENTE",
    }
    res_val = vf.resultado.value
    L.append(f"  DICTAMEN: {emoji_res.get(res_val, '?')} {dictamen_map.get(res_val, res_val)}")
    L.append("")
    L.append(f"  Validaciones que pasan (✅): {len(items_pasan)}")
    L.append(f"  Hallazgos Críticos  (🔴): {len(items_criticos)}")
    L.append(f"  Hallazgos Altos     (🟠): {len(items_altos)}")
    L.append(f"  Hallazgos Medios    (🟡): {len(items_medios)}")
    L.append(f"  Hallazgos Informativos (ℹ️): {len(items_info)}")

    if vf.validacion_cruzada_disponible:
        L.append(f"\n  Validación cruzada (Colorado): {vf.dictamen_colorado}")

    # ── DETALLE DE VALIDACIONES ──────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  DETALLE DE VALIDACIONES")
    L.append(SUB)

    categorias = [
        ("DOCUMENTO", "BLOQUE 1: DOCUMENTOS OBLIGATORIOS"),
        ("DATO_OBLIGATORIO", "BLOQUE 2: DATOS DE LA PERSONA MORAL"),
        ("DOMICILIO", "BLOQUE 3: DOMICILIO"),
        ("PERSONAS", "BLOQUE 4: PERSONAS IDENTIFICADAS"),
        ("PODER_BANCARIO", "BLOQUE 5: PODER BANCARIO"),
        ("VALIDACION_CRUZADA", "BLOQUE 6: VALIDACIÓN CRUZADA (COLORADO)"),
    ]

    for cat_key, cat_label in categorias:
        cat_items = [it for it in vf.items if it.categoria == cat_key]
        if not cat_items:
            continue

        L.append("")
        L.append(f"  {cat_label}")
        L.append("  " + "·" * 50)

        for it in cat_items:
            if it.presente:
                icono = "✅ PASA"
            else:
                sev_icon = {
                    SeveridadPLD.CRITICA: "🔴",
                    SeveridadPLD.ALTA: "🟠",
                    SeveridadPLD.MEDIA: "🟡",
                    SeveridadPLD.INFORMATIVA: "ℹ️",
                }.get(it.severidad, "❌")
                icono = f"❌ FALLA {sev_icon}"

            L.append(f"    [{it.codigo}] {it.elemento}: {icono}")
            if it.detalle:
                L.append(f"      {it.detalle}")

    # ── ALERTAS Y RIESGOS ────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  ALERTAS Y RIESGOS")
    L.append(SUB)
    L.append("")

    # Críticos
    L.append("  🔴 CRÍTICOS (requieren acción inmediata):")
    if items_criticos:
        for i, it in enumerate(items_criticos, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}: {it.detalle}" if it.detalle else f"    {i}. [{it.codigo}] {it.elemento}")
    else:
        L.append("    Ninguno ✅")

    # Altos
    L.append("")
    L.append("  🟠 ALTOS (requieren acción antes de continuar):")
    if items_altos:
        for i, it in enumerate(items_altos, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}: {it.detalle}" if it.detalle else f"    {i}. [{it.codigo}] {it.elemento}")
    else:
        L.append("    Ninguno ✅")

    # Medios
    L.append("")
    L.append("  🟡 MEDIOS (requieren seguimiento):")
    if items_medios:
        for i, it in enumerate(items_medios, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}: {it.detalle}" if it.detalle else f"    {i}. [{it.codigo}] {it.elemento}")
    else:
        L.append("    Ninguno ✅")

    # Informativos
    L.append("")
    L.append("  ℹ️ INFORMATIVOS (para registro):")
    if items_info:
        for i, it in enumerate(items_info, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}: {it.detalle}" if it.detalle else f"    {i}. [{it.codigo}] {it.elemento}")
    else:
        L.append("    Ninguno")

    # ── RECOMENDACIONES ──────────────────────────────────────────
    if vf.recomendaciones:
        L.append("")
        L.append(SUB)
        L.append("  RECOMENDACIONES")
        L.append(SUB)
        L.append("")
        for i, rec in enumerate(vf.recomendaciones, 1):
            L.append(f"    {i}. {rec}")

    # ── SIGUIENTE PASO ───────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  SIGUIENTE PASO")
    L.append(SUB)
    L.append("")

    faltantes_no_info = [it for it in vf.items if not it.presente and it.severidad != SeveridadPLD.INFORMATIVA]
    if vf.resultado == ResultadoCompletitud.COMPLETO:
        L.append("    ✅ Documentación completa. Proceder a Etapa 2 — Screening PLD.")
    elif vf.resultado == ResultadoCompletitud.PARCIAL:
        L.append("    ⚠️ Expediente aprobado con observaciones.")
        L.append("    Documentos/datos a subsanar:")
        for it in faltantes_no_info:
            L.append(f"      - [{it.codigo}] {it.elemento}")
    else:
        L.append("    ❌ Expediente incompleto. No procede análisis PLD.")
        L.append("    Elementos faltantes críticos:")
        for it in items_criticos:
            L.append(f"      - [{it.codigo}] {it.elemento}")

    # ── CIERRE ───────────────────────────────────────────────────
    L.append("")
    L.append(SEP)
    L.append(f"  Fin del reporte — {vf.razon_social}")
    L.append(SEP)

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORTE COMPLETO: ETAPA 1 + ETAPA 2 + COLORADO
# ═══════════════════════════════════════════════════════════════════════════════

def generar_reporte_completo(
    etapa1: VerificacionCompletitud,
    screening_resumen: dict[str, Any] | None,
    colorado_detalle: dict[str, Any] | None = None,
    estructura_accionaria: dict[str, Any] | None = None,
) -> str:
    """
    Genera un reporte consolidado PLD estilo Colorado.
    Incluye: Etapa 1, Etapa 2 screening, estructura accionaria,
    validación Colorado y pre-dictamen.
    """
    L: list[str] = []
    SEP = "═" * 60
    SUB = "─" * 60
    ahora = datetime.now(timezone.utc)

    # ── ENCABEZADO ───────────────────────────────────────────────
    L.append(SEP)
    L.append("  REPORTE CONSOLIDADO PLD / AML — ARIZONA")
    L.append(SEP)
    L.append("")
    L.append(f"  EMPRESA: {etapa1.razon_social}")
    L.append(f"  RFC: {etapa1.rfc}")
    L.append(f"  EMPRESA_ID: {etapa1.empresa_id}")
    L.append(f"  FECHA DE ANÁLISIS: {ahora.strftime('%Y-%m-%d %H:%M')}")

    docs_str = ", ".join(etapa1.documentos_presentes) if etapa1.documentos_presentes else "N/D"
    L.append(f"  DOCUMENTOS EN EXPEDIENTE: {docs_str}")

    # ── DATOS CLAVE ──────────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  DATOS CLAVE DE LA PERSONA MORAL")
    L.append(SUB)
    L.append("")
    L.append(f"  Razón Social: {etapa1.razon_social}")
    L.append(f"  RFC:          {etapa1.rfc}")

    apoderado = next((p for p in etapa1.personas_identificadas if p.rol in ("apoderado", "representante_legal")), None)
    if apoderado:
        L.append("")
        L.append("  ▸ REPRESENTANTE LEGAL")
        L.append(f"    Nombre:      {apoderado.nombre}")
        curp_rep = getattr(apoderado, '_curp_ine', None)
        if curp_rep:
            L.append(f"    CURP:        {curp_rep}")
        L.append(f"    Fuente:      {apoderado.fuente}")

    poder_txt = "✅ SÍ" if etapa1.poder_cuenta_bancaria else ("❌ NO DETECTADO" if etapa1.poder_cuenta_bancaria is False else "⚠️ NO DETERMINADO")
    L.append("")
    L.append(f"  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: {poder_txt}")

    accionistas = [p for p in etapa1.personas_identificadas if p.rol == "accionista"]
    if accionistas:
        L.append("")
        L.append("  ▸ ACCIONISTAS / SOCIOS")
        L.append(f"    {'#':<5}{'Nombre':<40}{'Tipo':<18}{'%':>6}  Fuente")
        L.append("    " + "─" * 80)
        for i, a in enumerate(accionistas, 1):
            pct = f"{a.porcentaje:.1f}%" if a.porcentaje is not None else "N/D"
            tipo = "P. Física" if a.tipo_persona == "fisica" else "P. Moral"
            L.append(f"    {i:<5}{a.nombre:<40}{tipo:<18}{pct:>6}  {a.fuente}")

    # ── ESTRUCTURA ACCIONARIA Y PROPIETARIOS REALES ──────────────
    if estructura_accionaria:
        L.append("")
        L.append(SUB)
        L.append("  ESTRUCTURA ACCIONARIA Y PROPIETARIOS REALES")
        L.append(SUB)
        L.append("")

        acc_lista = estructura_accionaria.get("accionistas", [])
        prop_reales = estructura_accionaria.get("propietarios_reales", [])
        capital = estructura_accionaria.get("capital_social", {})

        if capital and isinstance(capital, dict):
            monto = capital.get("monto", "N/D")
            moneda = capital.get("moneda", "MXN")
            L.append(f"    Capital social: {monto:,.2f} {moneda}" if isinstance(monto, (int, float)) else f"    Capital social: {monto} {moneda}")
            L.append("")

        if acc_lista:
            L.append(f"    {'#':<4} {'Nombre':<35} {'RFC':<15} {'Tipo':<14} {'%':>7}  Fuente")
            L.append("    " + "═" * 82)
            for i, acc in enumerate(acc_lista, 1):
                nombre = acc.get("nombre", acc.get("nombre_completo", "N/D"))[:35]
                rfc = acc.get("rfc", "N/D")[:15]
                pct = float(acc.get("porcentaje", acc.get("porcentaje_directo", 0)) or 0)
                tipo = acc.get("tipo_persona", "N/D")[:14]
                fuente = acc.get("fuente", "N/D")
                L.append(f"    {i:<4} {nombre:<35} {rfc:<15} {tipo:<14} {pct:>6.2f}%  {fuente}")
            suma = sum(float(acc.get("porcentaje", acc.get("porcentaje_directo", 0)) or 0) for acc in acc_lista)
            L.append("    " + "═" * 82)
            if 99.0 <= suma <= 101.0:
                L.append(f"    ✅ Suma de participación: {suma:.2f}%")
            else:
                L.append(f"    ⚠️ Suma de participación: {suma:.2f}% (NO cuadra al 100%)")
            L.append("")

        if prop_reales:
            L.append("    PROPIETARIOS REALES (participación ≥25%):")
            L.append("    " + "─" * 50)
            for i, pr in enumerate(prop_reales, 1):
                pct = pr.get("porcentaje_efectivo", pr.get("porcentaje", 0))
                L.append(f"      {i}. {pr.get('nombre', 'N/D')} — {pct:.2f}%")
            L.append("")
        else:
            L.append("    ⚠️ No se identificaron Propietarios Reales (≥25%)")
            L.append("")

        alertas_est = estructura_accionaria.get("alertas", [])
        if alertas_est:
            L.append("    ALERTAS DE ESTRUCTURA:")
            for al in alertas_est:
                sev = al.get("severidad", "media")
                emoji = "🚨" if sev == "alta" else ("⚠️" if sev == "media" else "ℹ️")
                L.append(f"      {emoji} [{al.get('codigo', '?')}] {al.get('mensaje', '')}")

    # ── RESUMEN EJECUTIVO ────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  RESUMEN EJECUTIVO")
    L.append(SUB)
    L.append("")

    # Etapa 1 conteos
    items_pasan = [it for it in etapa1.items if it.presente]
    items_criticos = [it for it in etapa1.items if not it.presente and it.severidad == SeveridadPLD.CRITICA]
    items_altos = [it for it in etapa1.items if not it.presente and it.severidad == SeveridadPLD.ALTA]
    items_medios = [it for it in etapa1.items if not it.presente and it.severidad == SeveridadPLD.MEDIA]
    items_info = [it for it in etapa1.items if not it.presente and it.severidad == SeveridadPLD.INFORMATIVA]

    # Dictamen global
    problemas: list[str] = []
    advertencias: list[str] = []

    if etapa1.resultado == ResultadoCompletitud.INCOMPLETO:
        problemas.append("Documentación INCOMPLETA")
    elif etapa1.resultado == ResultadoCompletitud.PARCIAL:
        advertencias.append("Documentación parcial")

    if screening_resumen:
        if screening_resumen.get("tiene_coincidencias_criticas"):
            problemas.append("COINCIDENCIAS CRÍTICAS en listas negras")
        elif screening_resumen.get("coincidencias_confirmadas", 0) > 0:
            problemas.append("Coincidencias CONFIRMADAS en listas")
        elif screening_resumen.get("coincidencias_probables", 0) > 0:
            advertencias.append("Coincidencias probables en listas")
        elif screening_resumen.get("coincidencias_posibles", 0) > 0:
            advertencias.append("Coincidencias posibles (homónimos)")
    else:
        problemas.append("Screening Etapa 2 NO ejecutado — no se descarta presencia en listas")

    dictamen_co = etapa1.dictamen_colorado or ""
    if "RECHAZADO" in dictamen_co:
        problemas.append("Colorado: RECHAZADO")
    elif "OBSERVACIONES" in dictamen_co:
        advertencias.append(f"Colorado: {dictamen_co}")

    if problemas:
        dictamen = "❌ RECHAZADO / ESCALAR"
    elif advertencias:
        dictamen = "⚠️ APROBADO CON OBSERVACIONES"
    else:
        dictamen = "✅ APROBADO"

    L.append(f"  DICTAMEN: {dictamen}")
    L.append("")

    # Etapa 1
    emoji_e1 = {"COMPLETO": "✅", "PARCIAL": "⚠️", "INCOMPLETO": "❌"}
    L.append(f"  Etapa 1 — Completitud:  {emoji_e1.get(etapa1.resultado.value, '?')} {etapa1.resultado.value} ({etapa1.items_presentes}/{etapa1.total_items})")

    # Etapa 2
    if screening_resumen:
        tiene_criticas = screening_resumen.get("tiene_coincidencias_criticas", False)
        personas_match = screening_resumen.get("personas_con_coincidencias", 0)
        total_p = screening_resumen.get("total_personas", 0)
        if tiene_criticas:
            L.append(f"  Etapa 2 — Screening:    🚨 COINCIDENCIAS CRÍTICAS ({personas_match}/{total_p})")
        elif personas_match > 0:
            L.append(f"  Etapa 2 — Screening:    ⚠️ CON COINCIDENCIAS ({personas_match}/{total_p})")
        else:
            L.append(f"  Etapa 2 — Screening:    ✅ SIN COINCIDENCIAS ({total_p} personas)")
    else:
        L.append("  Etapa 2 — Screening:    🔴 NO EJECUTADO (CRÍTICO)")

    # Colorado
    if etapa1.validacion_cruzada_disponible:
        emoji_co = "✅" if dictamen_co == "APROBADO" else ("⚠️" if "OBSERVACIONES" in dictamen_co else "❌")
        L.append(f"  Colorado — Validación:  {emoji_co} {dictamen_co}")
    else:
        L.append("  Colorado — Validación:  ⏳ NO DISPONIBLE")

    L.append("")
    n_criticos = len(items_criticos) + (1 if not screening_resumen else 0)
    L.append(f"  Validaciones que pasan (✅): {len(items_pasan)}")
    L.append(f"  Hallazgos Críticos  (🔴): {n_criticos}")
    L.append(f"  Hallazgos Altos     (🟠): {len(items_altos)}")
    L.append(f"  Hallazgos Medios    (🟡): {len(items_medios)}")
    L.append(f"  Hallazgos Informativos (ℹ️): {len(items_info)}")

    # ── DETALLE DE VALIDACIONES — ETAPA 1 ────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  DETALLE DE VALIDACIONES — COMPLETITUD DOCUMENTAL")
    L.append(SUB)

    categorias = [
        ("DOCUMENTO", "BLOQUE 1: DOCUMENTOS OBLIGATORIOS"),
        ("DATO_OBLIGATORIO", "BLOQUE 2: DATOS DE LA PERSONA MORAL"),
        ("DOMICILIO", "BLOQUE 3: DOMICILIO"),
        ("PERSONAS", "BLOQUE 4: PERSONAS IDENTIFICADAS"),
        ("PODER_BANCARIO", "BLOQUE 5: PODER BANCARIO"),
        ("VALIDACION_CRUZADA", "BLOQUE 6: VALIDACIÓN CRUZADA (COLORADO)"),
    ]

    for cat_key, cat_label in categorias:
        cat_items = [it for it in etapa1.items if it.categoria == cat_key]
        if not cat_items:
            continue
        L.append("")
        L.append(f"  {cat_label}")
        L.append("  " + "·" * 50)
        for it in cat_items:
            if it.presente:
                icono = "✅ PASA"
            else:
                sev_icon = {
                    SeveridadPLD.CRITICA: "🔴",
                    SeveridadPLD.ALTA: "🟠",
                    SeveridadPLD.MEDIA: "🟡",
                    SeveridadPLD.INFORMATIVA: "ℹ️",
                }.get(it.severidad, "❌")
                icono = f"❌ FALLA {sev_icon}"
            L.append(f"    [{it.codigo}] {it.elemento}: {icono}")
            if it.detalle:
                L.append(f"      {it.detalle}")

    # ── ETAPA 2 — SCREENING ─────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 2: SCREENING CONTRA LISTAS NEGRAS / PEPs")
    L.append(SUB)
    L.append("")

    if screening_resumen:
        if screening_resumen.get("screening_incompleto"):
            L.append("    🚨 SCREENING INCOMPLETO — No se puede descartar presencia en listas.")
            L.append("")

        L.append(f"    Total personas verificadas   : {screening_resumen.get('total_personas', 0)}")
        L.append(f"    Personas con coincidencias   : {screening_resumen.get('personas_con_coincidencias', 0)}")
        L.append(f"    Coincidencias confirmadas    : {screening_resumen.get('coincidencias_confirmadas', 0)}")
        L.append(f"    Coincidencias probables      : {screening_resumen.get('coincidencias_probables', 0)}")
        L.append(f"    Coincidencias posibles       : {screening_resumen.get('coincidencias_posibles', 0)}")
        L.append(f"    Homónimos descartados        : {screening_resumen.get('homonimos_descartados', 0)}")
        L.append("")
        L.append("    Listas objetivo:")
        L.append("      • CatPLD69BPerson      — Lista 69-B SAT (EFOS/EDOS)")
        L.append("      • CatPLDLockedPerson   — Personas Bloqueadas UIF")
        L.append("      • TraPLDBlackListEntry — Lista Negra Consolidada (OFAC, PEP, SAT69)")

        # ── DETALLE POR PERSONA ──────────────────────────────────
        resultados = screening_resumen.get("resultados", [])
        if resultados:
            L.append("")
            PSEP = "─" * 60
            for i, res in enumerate(resultados, 1):
                persona = res.get("persona", {})
                nombre = persona.get("nombre", "N/D")
                curp = persona.get("curp", "N/D") or "N/D"
                rfc = persona.get("rfc", "N/D") or "N/D"
                tipo_p = persona.get("tipo_persona", "N/D") or "N/D"
                rol = persona.get("rol", "N/D") or "N/D"
                tiene_coinc = res.get("tiene_coincidencias", False)

                L.append("")
                L.append(f"  {PSEP}")
                L.append(f"    [{i}] {nombre}")
                L.append(f"  {PSEP}")
                L.append("")
                L.append(f"      CURP:  {curp}")
                L.append(f"      RFC:   {rfc}")
                L.append(f"      Tipo:  {tipo_p}")
                L.append(f"      Rol:   {rol}")

                # Listas consultadas con éxito
                listas_ok = res.get("listas_exitosas", [])
                listas_fail = res.get("listas_fallidas", [])

                if listas_ok:
                    L.append("")
                    L.append("      ✅ Listas consultadas con ÉXITO:")
                    for lst in listas_ok:
                        L.append(f"         • {lst}")

                if listas_fail:
                    L.append("")
                    L.append("      🚨 Listas FALLIDAS (no se pudo consultar):")
                    for lst in listas_fail:
                        L.append(f"         • {lst}")

                L.append("")
                if tiene_coinc:
                    nivel_riesgo = res.get("nivel_riesgo", "SIN_COINCIDENCIA")
                    L.append(f"      ⚠️ RESULTADO: {nivel_riesgo} | Score máximo: {res.get('score_maximo', 0)}")
                    for j, c in enumerate(res.get("coincidencias", []), 1):
                        L.append(f"      Coincidencia #{j}:")
                        L.append(f"        Tabla origen: {c.get('tabla_origen', 'N/D')}")
                        L.append(f"        Tipo lista:   {c.get('tipo_lista', 'N/D')}")
                        L.append(f"        Nombre lista: {c.get('nombre_en_lista', 'N/D')}")
                        L.append(f"        Score:        {c.get('score', 0)} ({c.get('nivel_coincidencia', 'N/D')})")
                        sim = c.get('match_nombre', 0)
                        L.append(f"        Similitud:    {sim * 100:.1f}%  RFC: {'SÍ' if c.get('match_rfc') else 'No'}  CURP: {'SÍ' if c.get('match_curp') else 'No'}")
                else:
                    if not res.get("screening_incompleto"):
                        L.append("      ✅ SIN COINCIDENCIAS en las listas consultadas exitosamente.")
                    else:
                        L.append("      ⛔ Screening incompleto — no se puede descartar presencia en listas.")

        # Resultado global screening
        L.append("")
        if screening_resumen.get("screening_incompleto"):
            L.append("    🚨 RESULTADO ETAPA 2: SCREENING INCOMPLETO")
        elif screening_resumen.get("tiene_coincidencias_criticas"):
            L.append("    🚨 RESULTADO ETAPA 2: COINCIDENCIAS CRÍTICAS — ESCALAR")
        elif screening_resumen.get("personas_con_coincidencias", 0) > 0:
            L.append("    ⚠️ RESULTADO ETAPA 2: COINCIDENCIAS — REVISIÓN MANUAL")
        else:
            L.append("    ✅ RESULTADO ETAPA 2: SIN COINCIDENCIAS EN LISTAS")
    else:
        L.append("    🔴 CRÍTICO: Screening NO ejecutado.")
        L.append("    No se puede descartar presencia en listas negras (LPB, OFAC, PEPs, 69-B).")
        L.append("    Se requiere ejecutar Etapa 2 antes de continuar con el proceso de onboarding.")

    # ── ALERTAS Y RIESGOS ────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  ALERTAS Y RIESGOS")
    L.append(SUB)
    L.append("")

    # Agregar screening no ejecutado como hallazgo crítico
    criticos_extra: list[str] = []
    if not screening_resumen:
        criticos_extra.append("[E2] Screening contra listas negras NO ejecutado — no se descarta presencia en LPB, OFAC, PEPs, 69-B")

    L.append("  🔴 CRÍTICOS (requieren acción inmediata):")
    if items_criticos or criticos_extra:
        idx = 1
        for it in items_criticos:
            L.append(f"    {idx}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
            idx += 1
        for extra in criticos_extra:
            L.append(f"    {idx}. {extra}")
            idx += 1
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  🟠 ALTOS (requieren acción antes de continuar):")
    if items_altos:
        for i, it in enumerate(items_altos, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  🟡 MEDIOS (requieren seguimiento):")
    if items_medios:
        for i, it in enumerate(items_medios, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  ℹ️ INFORMATIVOS (para registro):")
    if items_info:
        for i, it in enumerate(items_info, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
    else:
        L.append("    Ninguno")

    # ── RECOMENDACIONES ──────────────────────────────────────────
    all_recs = list(etapa1.recomendaciones)
    if not screening_resumen:
        n_personas = len(etapa1.personas_identificadas)
        all_recs.append(f"URGENTE: Ejecutar Etapa 2 — Screening de {n_personas} persona(s) contra listas negras (LPB, OFAC, PEP, 69-B)")
    if screening_resumen and screening_resumen.get("requiere_escalamiento"):
        all_recs.append("Escalar caso a Comité PLD")
    if screening_resumen and screening_resumen.get("personas_con_coincidencias", 0) > 0:
        all_recs.append("Revisión manual de coincidencias por analista PLD")
    if "OBSERVACIONES" in dictamen_co:
        all_recs.append("Documentar observaciones de Colorado en expediente")

    if all_recs:
        L.append("")
        L.append(SUB)
        L.append("  RECOMENDACIONES")
        L.append(SUB)
        L.append("")
        for i, rec in enumerate(all_recs, 1):
            L.append(f"    {i}. {rec}")

    # ── SIGUIENTE PASO ───────────────────────────────────────────
    L.append("")
    L.append(SUB)
    L.append("  SIGUIENTE PASO")
    L.append(SUB)
    L.append("")

    if problemas:
        L.append("    ❌ Expediente NO procede. Motivos:")
        for p in problemas:
            L.append(f"      • {p}")
        L.append("")
        L.append("    Acciones requeridas:")
        paso_num = 1
        if items_criticos:
            L.append(f"      {paso_num}. SUBSANAR documentos/datos críticos:")
            for it in items_criticos:
                L.append(f"         - [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
            paso_num += 1
        if screening_resumen and screening_resumen.get("tiene_coincidencias_criticas"):
            L.append(f"      {paso_num}. ESCALAR a Comité PLD — Coincidencias críticas en listas negras:")
            for res in screening_resumen.get("resultados", []):
                if res.get("tiene_coincidencias"):
                    persona = res.get("persona", {})
                    L.append(f"         - {persona.get('nombre', 'N/D')} ({res.get('nivel_riesgo', 'N/D')})")
            paso_num += 1
        elif screening_resumen and screening_resumen.get("personas_con_coincidencias", 0) > 0:
            L.append(f"      {paso_num}. REVISIÓN MANUAL de coincidencias en listas:")
            for res in screening_resumen.get("resultados", []):
                if res.get("tiene_coincidencias"):
                    persona = res.get("persona", {})
                    L.append(f"         - {persona.get('nombre', 'N/D')} — Score: {res.get('score_maximo', 0)}")
            paso_num += 1
        if screening_resumen and screening_resumen.get("screening_incompleto"):
            L.append(f"      {paso_num}. REINTENTAR screening de listas fallidas antes de continuar.")
            paso_num += 1
        if not screening_resumen:
            n_pers = len(etapa1.personas_identificadas)
            L.append(f"      {paso_num}. EJECUTAR Etapa 2 — Screening de {n_pers} persona(s) contra listas negras (LPB, OFAC, PEP, 69-B).")
            paso_num += 1
        if "RECHAZADO" in dictamen_co:
            L.append(f"      {paso_num}. RESOLVER hallazgos de validación cruzada (Colorado: RECHAZADO).")
            paso_num += 1
        L.append(f"      {paso_num}. Una vez resueltos los puntos anteriores, reprocesar expediente.")
    elif advertencias:
        L.append("    ⚠️ Expediente aprobado con observaciones.")
        L.append("")
        L.append("    Puntos a atender antes de continuar:")
        for a in advertencias:
            L.append(f"      • {a}")
        faltantes = [it for it in etapa1.items if not it.presente and it.severidad != SeveridadPLD.INFORMATIVA]
        if faltantes:
            L.append("")
            L.append("    Documentos/datos a subsanar:")
            for it in faltantes:
                L.append(f"      - [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
        if screening_resumen and screening_resumen.get("personas_con_coincidencias", 0) > 0:
            L.append("")
            L.append("    Personas con coincidencias que requieren revisión manual:")
            for res in screening_resumen.get("resultados", []):
                if res.get("tiene_coincidencias"):
                    persona = res.get("persona", {})
                    L.append(f"      - {persona.get('nombre', 'N/D')} ({res.get('nivel_riesgo', 'N/D')}, score: {res.get('score_maximo', 0)})")
        L.append("")
        L.append("    Siguiente acción: Documentar observaciones y proceder con onboarding condicionado.")
    else:
        L.append("    ✅ Expediente aprobado. Todas las validaciones superadas.")
        L.append("")
        L.append("    Las personas verificadas no presentan coincidencias en:")
        L.append("      • Lista 69-B del SAT (EFOS/EDOS)")
        L.append("      • Personas Bloqueadas por UIF/SHCP")
        L.append("      • Lista Negra Consolidada (OFAC, PEP, SAT69)")
        L.append("")
        L.append("    Siguiente acción: Proceder con onboarding.")

    # ── CIERRE ───────────────────────────────────────────────────
    L.append("")
    L.append(SEP)
    L.append(f"  Fin del reporte — {etapa1.razon_social}")
    L.append(SEP)

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS — Screening de Beneficiarios Controladores
# ═══════════════════════════════════════════════════════════════════════════════

def _mostrar_screening_bc_persona(
    L: list[str],
    nombre: str,
    screening_bc_resumen: dict[str, Any] | None,
    screening_resumen: dict[str, Any] | None,
) -> None:
    """
    Busca el resultado de screening del BC en screening_bc_resumen (prioritario)
    o en screening_resumen (fallback si ya fue screened en Etapa 2).
    Agrega líneas al buffer L.
    """
    nombre_up = nombre.upper().strip()

    # Buscar primero en screening de BCs (dedicado)
    for resumen in (screening_bc_resumen, screening_resumen):
        if not resumen:
            continue
        for res in resumen.get("resultados", []):
            persona = res.get("persona", {})
            if persona.get("nombre", "").upper().strip() == nombre_up:
                if res.get("tiene_coincidencias"):
                    nivel = res.get("nivel_riesgo", "N/D")
                    L.append(f"       ⚠️ SCREENING BC: {nivel}")
                    for coinc in res.get("coincidencias", []):
                        L.append(
                            f"          • {coinc.get('tipo_lista', 'N/D')} — "
                            f"{coinc.get('nombre_en_lista', '')} "
                            f"(score {coinc.get('score', 0)}, {coinc.get('nivel_coincidencia', 'N/D')})"
                        )
                elif res.get("screening_incompleto"):
                    L.append(f"       🚨 SCREENING BC: Incompleto — no se puede descartar presencia en listas")
                else:
                    L.append(f"       ✅ SCREENING BC: Sin coincidencias en listas")
                return

    # Si no se encontró en ningún resumen
    L.append(f"       ⏳ SCREENING BC: No ejecutado")


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORTE UNIFICADO PLD — Arizona
# ═══════════════════════════════════════════════════════════════════════════════

def generar_reporte_unificado(
    etapa1: VerificacionCompletitud,
    screening_resumen: dict[str, Any] | None,
    estructura_accionaria: dict[str, Any] | None = None,
    resultado_mer: ResultadoMER | None = None,
    screening_bc_resumen: dict[str, Any] | None = None,
) -> ResultadoReporteUnificado:
    """
    Genera el reporte PLD de Arizona organizado en las 4 primeras etapas del
    proceso de debida diligencia conforme a la Disposición 4ª de las DCG del
    artículo 115 de la Ley de Instituciones de Crédito.

    Estructura:
      ENCABEZADO
      DATOS CLAVE DE LA PERSONA MORAL
      ESTRUCTURA ACCIONARIA Y PROPIETARIOS REALES
      RESUMEN EJECUTIVO (dictamen + cuadro de etapas)
      ETAPA 1 — Completitud documental (Bloques 1-5 con veredicto)
      ETAPA 2 — Screening contra listas negras / PEPs
      ETAPA 3 — Verificación de datos y existencia legal (resumen Colorado)
      ETAPA 4 — Identificación del beneficiario controlador
      ALERTAS Y RIESGOS
      RECOMENDACIONES
      SIGUIENTE PASO
      CIERRE
    """
    L: list[str] = []
    SEP = "═" * 60
    SUB = "─" * 60
    ahora = datetime.now(timezone.utc)

    # ─── Clasificar items (sin VALIDACION_CRUZADA, eso va en Etapa 3) ────
    items_sin_colorado = [it for it in etapa1.items if it.categoria != "VALIDACION_CRUZADA"]
    items_pasan = [it for it in items_sin_colorado if it.presente]
    items_fallan = [it for it in items_sin_colorado if not it.presente]
    items_criticos = [it for it in items_fallan if it.severidad == SeveridadPLD.CRITICA]
    items_altos = [it for it in items_fallan if it.severidad == SeveridadPLD.ALTA]
    items_medios = [it for it in items_fallan if it.severidad == SeveridadPLD.MEDIA]
    items_info = [it for it in items_fallan if it.severidad == SeveridadPLD.INFORMATIVA]

    # ─── Evaluar estructura accionaria ───────────────────────────
    accionistas_e1 = [p for p in etapa1.personas_identificadas if p.rol == "accionista"]
    acc_est = estructura_accionaria.get("accionistas", []) if estructura_accionaria else []
    fuente_map = {a.nombre.upper().strip(): a.fuente for a in accionistas_e1}

    rows: list[tuple] = []
    if acc_est:
        for acc in acc_est:
            nombre = acc.get("nombre", acc.get("nombre_completo", "N/D"))
            tipo_raw = acc.get("tipo_persona", "N/D")
            tipo = "P. Física" if tipo_raw == "fisica" else ("P. Moral" if tipo_raw == "moral" else tipo_raw)
            pct = float(acc.get("porcentaje", acc.get("porcentaje_directo", 0)) or 0)
            fuente = acc.get("fuente") or fuente_map.get(nombre.upper().strip(), "N/D")
            rows.append((nombre, tipo, pct, fuente))
    elif accionistas_e1:
        for a in accionistas_e1:
            tipo = "P. Física" if a.tipo_persona == "fisica" else "P. Moral"
            pct = a.porcentaje if a.porcentaje is not None else 0.0
            rows.append((a.nombre, tipo, pct, a.fuente))

    suma_accionistas = sum(r[2] for r in rows) if rows else 0.0
    estructura_ok = 99.0 <= suma_accionistas <= 101.0

    # ─── Evaluar screening ───────────────────────────────────────
    screening_critico = False
    screening_observacion = False
    if screening_resumen:
        if screening_resumen.get("tiene_coincidencias_criticas") or screening_resumen.get("coincidencias_confirmadas", 0) > 0:
            screening_critico = True
        elif screening_resumen.get("coincidencias_probables", 0) > 0:
            screening_observacion = True

    # ─── Evaluar Colorado ────────────────────────────────────────
    dictamen_co = etapa1.dictamen_colorado or ""
    colorado_disponible = etapa1.validacion_cruzada_disponible
    colorado_obs = colorado_disponible and dictamen_co != "APROBADO"

    # Hallazgos de Colorado por bloque (from resumen_colorado)
    resumen_co = etapa1.resumen_colorado or {}
    hallazgos_co_criticos = etapa1.hallazgos_colorado_criticos or []

    # ─── Propietarios reales ─────────────────────────────────────
    prop_reales = estructura_accionaria.get("propietarios_reales", []) if estructura_accionaria else []

    # ─── Hallazgos adicionales (fuera de items) ──────────────────
    extra_criticos: list[str] = []
    extra_obs: list[str] = []

    if not estructura_ok and rows:
        extra_criticos.append(f"Estructura accionaria: suma de participación {suma_accionistas:.1f}% (no cuadra al 100%)")
    if screening_critico:
        extra_criticos.append("Coincidencias CRÍTICAS en listas negras — escalar a Comité PLD")
    if screening_resumen and screening_resumen.get("screening_incompleto"):
        extra_criticos.append("Screening INCOMPLETO — no se puede descartar presencia en listas")
    # Accionistas Persona Moral → hallazgo crítico (requieren look-through)
    if rows:
        pm_accionistas = [r for r in rows if r[1] == "P. Moral"]
        for pm_nombre, _, pm_pct, _ in pm_accionistas:
            extra_criticos.append(
                f"Accionista Persona Moral: {pm_nombre} ({pm_pct:.1f}%) — "
                "requiere perforación de cadena hasta persona física (DCG Art. 115)"
            )
    if screening_observacion:
        extra_obs.append("Coincidencias probables en listas negras — revisión manual requerida")
    if colorado_obs:
        extra_obs.append(f"Colorado — Validación cruzada: {dictamen_co}")

    # ─── Evaluar screening de beneficiarios controladores ────────
    screening_bc_critico = False
    screening_bc_observacion = False
    if screening_bc_resumen:
        if screening_bc_resumen.get("tiene_coincidencias_criticas") or screening_bc_resumen.get("coincidencias_confirmadas", 0) > 0:
            screening_bc_critico = True
            extra_criticos.append(
                "Beneficiario controlador con coincidencias CONFIRMADAS en listas negras — escalar a Comité PLD"
            )
        elif screening_bc_resumen.get("coincidencias_probables", 0) > 0:
            screening_bc_observacion = True
            extra_obs.append(
                "Beneficiario controlador con coincidencias PROBABLES en listas negras — revisión manual requerida"
            )
        if screening_bc_resumen.get("screening_incompleto"):
            extra_criticos.append(
                "Screening de beneficiarios controladores INCOMPLETO — no se puede descartar presencia en listas"
            )

    # ─── Dictamen final de Arizona ───────────────────────────────
    tiene_criticos = bool(items_criticos) or bool(extra_criticos)
    tiene_obs = bool(items_altos) or bool(items_medios) or bool(extra_obs)

    if tiene_criticos:
        dictamen_arizona = "RECHAZADO"
        emoji_dictamen = "❌"
    elif tiene_obs:
        dictamen_arizona = "APROBADO CON OBSERVACIONES"
        emoji_dictamen = "⚠️"
    else:
        dictamen_arizona = "APROBADO"
        emoji_dictamen = "✅"

    # ══════════════════════════════════════════════════════════════
    #  ENCABEZADO
    # ══════════════════════════════════════════════════════════════
    L.append(SEP)
    L.append("  REPORTE DE ANÁLISIS PLD / AML — ARIZONA")
    L.append(SEP)
    L.append("")
    L.append(f"  EMPRESA: {etapa1.razon_social}")
    L.append(f"  RFC: {etapa1.rfc}")
    L.append(f"  EMPRESA_ID: {etapa1.empresa_id}")
    L.append(f"  FECHA DE ANÁLISIS: {ahora.strftime('%Y-%m-%d %H:%M')}")
    docs_str = ", ".join(etapa1.documentos_presentes) if etapa1.documentos_presentes else "N/D"
    L.append(f"  DOCUMENTOS EN EXPEDIENTE: {docs_str}")
    L.append("")
    L.append("  Base legal: Disposición 4ª de las DCG del artículo 115")
    L.append("  de la Ley de Instituciones de Crédito.")
    L.append("  Reforma LFPIORPI julio 2025 — umbral beneficiario controlador: 25%.")

    # ══════════════════════════════════════════════════════════════
    #  DATOS CLAVE DE LA PERSONA MORAL
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  DATOS CLAVE DE LA PERSONA MORAL")
    L.append(SUB)
    L.append("")
    L.append(f"  Razón Social: {etapa1.razon_social}")
    L.append(f"  RFC:          {etapa1.rfc}")

    apoderado = next(
        (p for p in etapa1.personas_identificadas if p.rol in ("apoderado", "representante_legal")),
        None,
    )
    if apoderado:
        L.append("")
        L.append("  ▸ REPRESENTANTE LEGAL")
        L.append(f"    Nombre:      {apoderado.nombre}")
        curp_rep = getattr(apoderado, '_curp_ine', None)
        if curp_rep:
            L.append(f"    CURP:        {curp_rep}")
        L.append(f"    Fuente:      {apoderado.fuente}")

    poder_txt = (
        "✅ SÍ" if etapa1.poder_cuenta_bancaria
        else ("❌ NO DETECTADO" if etapa1.poder_cuenta_bancaria is False else "⚠️ NO DETERMINADO")
    )
    L.append("")
    L.append(f"  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: {poder_txt}")

    # ══════════════════════════════════════════════════════════════
    #  ESTRUCTURA ACCIONARIA Y PROPIETARIOS REALES
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ESTRUCTURA ACCIONARIA Y PROPIETARIOS REALES")
    L.append(SUB)
    L.append("")

    if estructura_accionaria:
        cap = estructura_accionaria.get("capital_social", {})
        if cap and isinstance(cap, dict):
            m = cap.get("monto", "N/D")
            mon = cap.get("moneda", "MXN")
            L.append(f"  Capital social: {m:,.2f} {mon}" if isinstance(m, (int, float)) else f"  Capital social: {m} {mon}")
            L.append("")

    if rows:
        L.append(f"    {'#':<4} {'Nombre':<35} {'Tipo':<14} {'%':>7}  Fuente")
        L.append("    " + "─" * 72)
        for i, (nombre, tipo, pct, fuente) in enumerate(rows, 1):
            L.append(f"    {i:<4} {nombre[:35]:<35} {tipo:<14} {pct:>6.1f}%  {fuente}")
        L.append("    " + "─" * 72)
        if estructura_ok:
            L.append(f"    ✅ Suma de participación: {suma_accionistas:.1f}%")
        else:
            L.append(f"    🔴 Suma de participación: {suma_accionistas:.1f}% — NO cuadra al 100%")
    else:
        L.append("    ⚠️ No se identificaron accionistas")

    L.append("")
    if prop_reales:
        L.append("  ▸ PROPIETARIOS REALES (participación ≥25%)")
        for i, pr in enumerate(prop_reales, 1):
            pct = pr.get("porcentaje_efectivo", pr.get("porcentaje", 0))
            L.append(f"    {i}. {pr.get('nombre', 'N/D')} — {pct:.1f}%")
    else:
        L.append("  ▸ PROPIETARIOS REALES: ⚠️ No se identificaron (≥25%)")

    # ══════════════════════════════════════════════════════════════
    #  RESUMEN EJECUTIVO
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  RESUMEN EJECUTIVO")
    L.append(SUB)
    L.append("")
    L.append(f"  DICTAMEN ARIZONA: {emoji_dictamen} {dictamen_arizona}")
    L.append("")

    # Cuadro de etapas
    emoji_e1 = {"COMPLETO": "✅", "PARCIAL": "⚠️", "INCOMPLETO": "❌"}
    L.append(f"  Etapa 1 — Completitud documental:   {emoji_e1.get(etapa1.resultado.value, '?')} {etapa1.resultado.value} ({etapa1.items_presentes}/{etapa1.total_items})")

    screening_incompleto = screening_resumen.get("screening_incompleto", False) if screening_resumen else False
    if screening_resumen:
        total_p = screening_resumen.get("total_personas", 0)
        if screening_critico:
            L.append(f"  Etapa 2 — Screening listas negras:  🔴 COINCIDENCIAS CRÍTICAS ({total_p} personas)")
        elif screening_incompleto:
            L.append(f"  Etapa 2 — Screening listas negras:  🔴 INCOMPLETO ({total_p} personas)")
        elif screening_observacion:
            L.append(f"  Etapa 2 — Screening listas negras:  ⚠️ COINCIDENCIAS PROBABLES ({total_p} personas)")
        else:
            L.append(f"  Etapa 2 — Screening listas negras:  ✅ SIN COINCIDENCIAS ({total_p} personas)")
    else:
        L.append("  Etapa 2 — Screening listas negras:  ⏳ PENDIENTE")

    if colorado_disponible:
        emoji_co = "✅" if dictamen_co == "APROBADO" else ("⚠️" if "OBSERVACIONES" in dictamen_co else "❌")
        L.append(f"  Etapa 3 — Verificación de datos:    {emoji_co} {dictamen_co} (Colorado)")
    else:
        L.append("  Etapa 3 — Verificación de datos:    ⏳ NO DISPONIBLE")

    if prop_reales:
        if screening_incompleto or screening_critico:
            L.append(f"  Etapa 4 — Beneficiario controlador: 🔴 {len(prop_reales)} identificado(s) — NO VALIDADOS (screening incompleto)")
        else:
            L.append(f"  Etapa 4 — Beneficiario controlador: ✅ {len(prop_reales)} identificado(s)")
    elif rows:
        L.append("  Etapa 4 — Beneficiario controlador: ⚠️ No se identificaron (≥25%)")
    else:
        L.append("  Etapa 4 — Beneficiario controlador: ⏳ Sin estructura accionaria")

    if rows:
        emoji_est = "✅" if estructura_ok else "🔴"
        L.append(f"  Estructura accionaria:              {emoji_est} Suma: {suma_accionistas:.1f}%")

    if resultado_mer:
        emoji_mer = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(resultado_mer.grado_riesgo.value, "⚪")
        L.append(f"  Etapa 5 — Matriz de riesgo MER:     {emoji_mer} {resultado_mer.grado_riesgo.value} ({resultado_mer.puntaje_total:.0f} pts)")
    else:
        L.append("  Etapa 5 — Matriz de riesgo MER:     ⏳ NO DISPONIBLE")

    L.append("")
    L.append(f"  Validaciones que pasan (✅): {len(items_pasan)}")
    L.append(f"  Hallazgos Críticos  (🔴): {len(items_criticos) + len(extra_criticos)}")
    L.append(f"  Hallazgos Altos     (🟠): {len(items_altos)}")
    L.append(f"  Hallazgos Medios    (🟡): {len(items_medios) + len(extra_obs)}")
    L.append(f"  Hallazgos Informativos (ℹ️): {len(items_info)}")

    # ══════════════════════════════════════════════════════════════
    #  ETAPA 1 — COMPLETITUD DOCUMENTAL
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 1 — RECEPCIÓN Y VERIFICACIÓN DE COMPLETITUD DOCUMENTAL")
    L.append(SUB)
    L.append("")
    L.append("  El analista PLD confirma la presencia de todos los elementos que exige")
    L.append("  la Disposición 4ª de las DCG del artículo 115 de la LIC: documentos")
    L.append("  soporte, datos de la persona moral, domicilio, personas y poder bancario.")

    categorias = [
        ("DOCUMENTO", "BLOQUE 1: DOCUMENTOS OBLIGATORIOS"),
        ("DATO_OBLIGATORIO", "BLOQUE 2: DATOS DE LA PERSONA MORAL"),
        ("DOMICILIO", "BLOQUE 3: DOMICILIO COMPLETO"),
        ("PERSONAS", "BLOQUE 4: PERSONAS IDENTIFICADAS"),
        ("PODER_BANCARIO", "BLOQUE 5: PODER BANCARIO"),
    ]
    for cat_key, cat_label in categorias:
        cat_items = [it for it in etapa1.items if it.categoria == cat_key]
        if not cat_items:
            continue

        cat_pasan = [it for it in cat_items if it.presente]
        cat_fallan = [it for it in cat_items if not it.presente]
        cat_fallan_no_info = [it for it in cat_fallan if it.severidad != SeveridadPLD.INFORMATIVA]

        L.append("")
        L.append(f"  {cat_label}")
        L.append("  " + "·" * 50)
        for it in cat_items:
            if it.presente:
                icono = "✅ PASA"
            else:
                sev_icon = {
                    SeveridadPLD.CRITICA: "🔴", SeveridadPLD.ALTA: "🟠",
                    SeveridadPLD.MEDIA: "🟡", SeveridadPLD.INFORMATIVA: "ℹ️",
                }.get(it.severidad, "❌")
                icono = f"❌ FALLA {sev_icon}"
            L.append(f"    [{it.codigo}] {it.elemento}: {icono}")
            if it.detalle:
                L.append(f"      {it.detalle}")

        # Detalle de personas identificadas (después de Bloque 4)
        if cat_key == "PERSONAS" and etapa1.personas_identificadas:
            L.append("")
            L.append("    Detalle de personas identificadas:")
            roles_agrupados: dict[str, list] = {}
            for p in etapa1.personas_identificadas:
                roles_agrupados.setdefault(p.rol, []).append(p)

            _ROL_LABELS = {
                "apoderado": "Apoderados",
                "representante_legal": "Representantes legales",
                "accionista": "Accionistas / Socios",
                "administrador": "Administradores",
                "consejero": "Consejeros",
                "director": "Directores",
            }
            for rol, personas_rol in roles_agrupados.items():
                label = _ROL_LABELS.get(rol, rol.replace("_", " ").title())
                L.append(f"      ▸ {label}:")
                for p in personas_rol:
                    tipo_str = "Física" if p.tipo_persona == "fisica" else "Moral"
                    pct_str = f" — {p.porcentaje:.1f}%" if p.porcentaje is not None else ""
                    L.append(f"        • {p.nombre} (P. {tipo_str}{pct_str}) [{p.fuente}]")

        # Veredicto del bloque
        L.append("")
        bloque_tag = cat_label.split(":")[0]
        if not cat_fallan_no_info:
            L.append(f"  → {bloque_tag}: ✅ PASA")
        else:
            criticos_bloque = [it for it in cat_fallan if it.severidad == SeveridadPLD.CRITICA]
            if criticos_bloque:
                L.append(f"  → {bloque_tag}: ❌ FALLA ({len(cat_pasan)}/{len(cat_items)})")
            else:
                L.append(f"  → {bloque_tag}: ⚠️ CON OBSERVACIONES ({len(cat_pasan)}/{len(cat_items)})")

    # ══════════════════════════════════════════════════════════════
    #  ETAPA 2 — SCREENING CONTRA LISTAS NEGRAS / PEPs
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 2 — SCREENING CONTRA LISTAS NEGRAS / PEPs")
    L.append(SUB)
    L.append("")
    L.append("  Cruce obligatorio de cada persona vinculada (razón social, apoderados,")
    L.append("  representantes legales, accionistas y beneficiarios controladores) contra")
    L.append("  las listas PLD/AML. Una coincidencia en la LPB (UIF) provoca suspensión")
    L.append("  inmediata y reporte de 24 horas. OFAC/ONU implica bloqueo. PEP activa")
    L.append("  debida diligencia reforzada. Lista 69-B SAT es alerta roja.")

    if screening_resumen:
        L.append("")
        if screening_resumen.get("screening_incompleto"):
            L.append("    🚨 SCREENING INCOMPLETO — No se puede descartar presencia en listas.")
            L.append("")

        L.append(f"    Total personas verificadas   : {screening_resumen.get('total_personas', 0)}")
        L.append(f"    Personas con coincidencias   : {screening_resumen.get('personas_con_coincidencias', 0)}")
        L.append(f"    Coincidencias confirmadas    : {screening_resumen.get('coincidencias_confirmadas', 0)}")
        L.append(f"    Coincidencias probables      : {screening_resumen.get('coincidencias_probables', 0)}")
        L.append(f"    Coincidencias posibles       : {screening_resumen.get('coincidencias_posibles', 0)}")
        L.append(f"    Homónimos descartados        : {screening_resumen.get('homonimos_descartados', 0)}")
        L.append("")
        L.append("    Listas consultadas:")
        L.append("      • CatPLD69BPerson      — Lista 69-B SAT (EFOS/EDOS)")
        L.append("      • CatPLDLockedPerson   — Personas Bloqueadas UIF (LPB)")
        L.append("      • TraPLDBlackListEntry — Lista Negra Consolidada (OFAC, PEP, SAT69)")

        resultados = screening_resumen.get("resultados", [])
        PSEP = "─" * 60
        for i, res in enumerate(resultados, 1):
            persona = res.get("persona", {})
            nombre = persona.get("nombre", "N/D")
            curp = persona.get("curp", "N/D") or "N/D"
            rfc_p = persona.get("rfc", "N/D") or "N/D"
            tipo_p = persona.get("tipo_persona", "N/D") or "N/D"
            rol = persona.get("rol", "N/D") or "N/D"
            tiene_coinc = res.get("tiene_coincidencias", False)

            L.append("")
            L.append(f"  {PSEP}")
            L.append(f"    [{i}] {nombre}")
            L.append(f"  {PSEP}")
            L.append("")
            L.append(f"      CURP:  {curp}")
            L.append(f"      RFC:   {rfc_p}")
            L.append(f"      Tipo:  {tipo_p}")
            L.append(f"      Rol:   {rol}")

            listas_ok = res.get("listas_exitosas", [])
            listas_fail = res.get("listas_fallidas", [])
            if listas_ok:
                L.append("")
                L.append("      ✅ Listas consultadas con ÉXITO:")
                for lst in listas_ok:
                    L.append(f"         • {lst}")
            if listas_fail:
                L.append("")
                L.append("      🚨 Listas FALLIDAS (no se pudo consultar):")
                for lst in listas_fail:
                    L.append(f"         • {lst}")

            L.append("")
            if tiene_coinc:
                nivel_riesgo = res.get("nivel_riesgo", "SIN_COINCIDENCIA")
                L.append(f"      ⚠️ RESULTADO: {nivel_riesgo} | Score máximo: {res.get('score_maximo', 0)}")
                for j, c in enumerate(res.get("coincidencias", []), 1):
                    L.append(f"      Coincidencia #{j}:")
                    L.append(f"        Tabla origen: {c.get('tabla_origen', 'N/D')}")
                    L.append(f"        Tipo lista:   {c.get('tipo_lista', 'N/D')}")
                    L.append(f"        Nombre lista: {c.get('nombre_en_lista', 'N/D')}")
                    L.append(f"        Score:        {c.get('score', 0)} ({c.get('nivel_coincidencia', 'N/D')})")
                    sim = c.get('match_nombre', 0)
                    L.append(f"        Similitud:    {sim * 100:.1f}%  RFC: {'SÍ' if c.get('match_rfc') else 'No'}  CURP: {'SÍ' if c.get('match_curp') else 'No'}")
            else:
                if not res.get("screening_incompleto"):
                    L.append("      ✅ SIN COINCIDENCIAS en las listas consultadas.")
                else:
                    L.append("      ⛔ Screening incompleto — no se puede descartar presencia en listas.")

        # Veredicto Etapa 2
        L.append("")
        if screening_critico:
            L.append("  → ETAPA 2: 🔴 COINCIDENCIAS CRÍTICAS — ESCALAR A COMITÉ PLD")
        elif screening_resumen.get("screening_incompleto"):
            L.append("  → ETAPA 2: 🔴 SCREENING INCOMPLETO — REINTENTAR")
        elif screening_observacion:
            L.append("  → ETAPA 2: ⚠️ COINCIDENCIAS PROBABLES — REVISIÓN MANUAL REQUERIDA")
        else:
            L.append("  → ETAPA 2: ✅ SIN COINCIDENCIAS EN LISTAS")
    else:
        L.append("")
        L.append("    ⏳ Screening no ejecutado aún.")

    # ══════════════════════════════════════════════════════════════
    #  ETAPA 3 — VERIFICACIÓN DE DATOS Y EXISTENCIA LEGAL
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 3 — VERIFICACIÓN DE DATOS Y EXISTENCIA LEGAL")
    L.append(SUB)
    L.append("")
    L.append("  Se valida RFC activo en SAT, consistencia entre razón social del RFC y")
    L.append("  acta constitutiva, existencia legal en Registro Público de Comercio,")
    L.append("  vigencia de documentos y consistencia cruzada de datos.")
    L.append("")
    L.append("  Esta etapa la ejecuta COLORADO (servicio de validación cruzada).")
    L.append("  A continuación se presenta el resumen de su análisis.")

    if colorado_disponible:
        L.append("")
        emoji_co = "✅" if dictamen_co == "APROBADO" else ("⚠️" if "OBSERVACIONES" in dictamen_co else "❌")
        L.append(f"  DICTAMEN COLORADO: {emoji_co} {dictamen_co}")
        L.append("")

        # Alertas y riesgos de Colorado (todos los hallazgos que no pasan)
        hallazgos_co_todos = etapa1.hallazgos_colorado or []
        h_co_criticos_alert = [h for h in hallazgos_co_todos if h.get("severidad") == "CRITICA" and h.get("pasa") is False]
        h_co_medios_alert = [h for h in hallazgos_co_todos if h.get("severidad") == "MEDIA" and h.get("pasa") is False]
        h_co_info_alert = [h for h in hallazgos_co_todos if h.get("severidad") == "INFORMATIVA" and h.get("pasa") is False]

        if h_co_criticos_alert or h_co_medios_alert or h_co_info_alert:
            L.append("")
            L.append("  ALERTAS Y RIESGOS DE COLORADO:")
            L.append("  " + "·" * 50)

            def _fmt_hallazgo(idx: int, h: dict) -> list[str]:
                cod = h.get("codigo", "?")
                msg = h.get("mensaje", h.get("nombre", ""))
                # Indentar líneas adicionales si el mensaje tiene saltos de línea
                lines = msg.split("\n")
                result = [f"    {idx}. [{cod}] {lines[0]}"]
                for extra in lines[1:]:
                    if extra.strip():
                        result.append(f"       {extra.strip()}")
                return result

            L.append("")
            L.append("  🔴 CRÍTICOS (requieren acción inmediata):")
            if h_co_criticos_alert:
                for i, h in enumerate(h_co_criticos_alert, 1):
                    L.extend(_fmt_hallazgo(i, h))
            else:
                L.append("    Ninguno ✅")

            L.append("")
            L.append("  🟡 MEDIOS (requieren seguimiento):")
            if h_co_medios_alert:
                for i, h in enumerate(h_co_medios_alert, 1):
                    L.extend(_fmt_hallazgo(i, h))
            else:
                L.append("    Ninguno ✅")

            L.append("")
            L.append("  ℹ️ INFORMATIVOS (para registro):")
            if h_co_info_alert:
                for i, h in enumerate(h_co_info_alert, 1):
                    L.extend(_fmt_hallazgo(i, h))
            else:
                L.append("    Ninguno")

        # ── Bloque 10: Validación en portales gubernamentales ──
        h_portales = [h for h in hallazgos_co_todos if str(h.get("bloque", "")) == "10" or str(h.get("codigo", "")).startswith("V10")]
        if h_portales:
            L.append("")
            L.append("  VALIDACIÓN EN PORTALES GUBERNAMENTALES")
            L.append("  " + "·" * 50)
            for h in h_portales:
                cod = h.get("codigo", "?")
                nombre = h.get("nombre", "")
                detalles = h.get("detalles", {})
                estado = detalles.get("estado_portal", "N/D")
                modulo = detalles.get("modulo_portal", "")
                ident = detalles.get("identificador", "")
                screenshot = detalles.get("screenshot", "")
                pasa = h.get("pasa")
                if pasa is True:
                    icono_p = "✅ PASA"
                elif pasa is False:
                    icono_p = "❌ FALLA"
                else:
                    icono_p = "⚪ N/A 🟡"
                L.append(f"    {cod} {nombre}: {icono_p}")
                msg = h.get("mensaje", "")
                if msg:
                    L.append(f"      {msg}")
                if modulo:
                    L.append(f"        Módulo: {modulo}")
                if ident:
                    L.append(f"        Identificador consultado: {ident}")
                if estado:
                    L.append(f"        Estado portal: {estado}")
                if screenshot:
                    L.append(f"        Screenshot: {screenshot}")
                L.append("")

        # Veredicto Etapa 3
        L.append("")
        if dictamen_co == "APROBADO":
            L.append("  → ETAPA 3: ✅ VERIFICACIÓN SUPERADA")
        elif "OBSERVACIONES" in dictamen_co:
            L.append("  → ETAPA 3: ⚠️ APROBADO CON OBSERVACIONES — Atender hallazgos de Colorado")
        elif dictamen_co == "RECHAZADO":
            L.append("  → ETAPA 3: ❌ RECHAZADO — Resolver hallazgos críticos de Colorado antes de continuar")
        else:
            L.append(f"  → ETAPA 3: ⚠️ {dictamen_co}")
    else:
        L.append("")
        L.append("    ⏳ Validación cruzada (Colorado) no disponible aún.")
        L.append("    No se puede verificar consistencia de datos ni existencia legal.")
        L.append("")
        L.append("  → ETAPA 3: ⏳ PENDIENTE")

    # ══════════════════════════════════════════════════════════════
    #  ETAPA 4 — IDENTIFICACIÓN DEL BENEFICIARIO CONTROLADOR
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 4 — IDENTIFICACIÓN DEL BENEFICIARIO CONTROLADOR")
    L.append(SUB)
    L.append("")
    L.append("  Se analiza la estructura accionaria para identificar a toda persona")
    L.append("  física que posea directa o indirectamente más del 25% del capital social")
    L.append("  o derechos de voto (umbral post-reforma LFPIORPI julio 2025).")
    L.append("  Si ningún accionista alcanza ≥25%, se designa al administrador o consejo")
    L.append("  de administración como beneficiario controlador.")

    L.append("")
    if rows:
        L.append(f"  Total accionistas identificados: {len(rows)}")
        L.append(f"  Suma de participación: {suma_accionistas:.1f}%")
        L.append("")

        if prop_reales:
            L.append("  BENEFICIARIOS CONTROLADORES IDENTIFICADOS (≥25%):")
            for i, pr in enumerate(prop_reales, 1):
                pct = pr.get("porcentaje_efectivo", pr.get("porcentaje", 0))
                nombre_pr = pr.get("nombre", "N/D")
                L.append(f"    {i}. {nombre_pr} — {pct:.1f}% del capital social")
                # Buscar resultado de screening BC para esta persona
                _mostrar_screening_bc_persona(L, nombre_pr, screening_bc_resumen, screening_resumen)
            L.append("")
            L.append("  Cada beneficiario controlador fue sometido a screening independiente")
            L.append("  contra las listas 69-B SAT, UIF y PEP (Etapa 2 aplicada a BCs).")
        else:
            L.append("  ⚠️ No se identificaron accionistas con participación ≥25%.")
            # Check for admin as fallback
            admins = [p for p in etapa1.personas_identificadas if p.rol in ("administrador", "consejero")]
            if admins:
                L.append("  Conforme a la normativa, se designa como beneficiario controlador:")
                for admin in admins:
                    L.append(f"    • {admin.nombre} (rol: {admin.rol})")
                    _mostrar_screening_bc_persona(L, admin.nombre, screening_bc_resumen, screening_resumen)
            else:
                apoderado_bc = next(
                    (p for p in etapa1.personas_identificadas if p.rol in ("apoderado", "representante_legal")),
                    None,
                )
                if apoderado_bc:
                    L.append("  Se designa al representante legal como beneficiario controlador:")
                    L.append(f"    • {apoderado_bc.nombre} (rol: {apoderado_bc.rol})")
                    _mostrar_screening_bc_persona(L, apoderado_bc.nombre, screening_bc_resumen, screening_resumen)

        # Personas morales en estructura (look-through)
        personas_morales = [r for r in rows if r[1] == "P. Moral"]
        if personas_morales:
            L.append("")
            L.append("  🔍 PERSONAS MORALES EN ESTRUCTURA — Requieren look-through:")
            for pm_nombre, _, pm_pct, pm_fuente in personas_morales:
                L.append(f"    • {pm_nombre} ({pm_pct:.1f}%) — perforar cadena hasta persona física")

        # Veredicto Etapa 4
        L.append("")
        if prop_reales and estructura_ok and not screening_incompleto and not screening_critico and not screening_bc_critico:
            L.append("  → ETAPA 4: ✅ BENEFICIARIOS CONTROLADORES IDENTIFICADOS Y VALIDADOS")
        elif prop_reales and estructura_ok and (screening_incompleto or screening_critico or screening_bc_critico):
            L.append("  → ETAPA 4: 🔴 BENEFICIARIOS IDENTIFICADOS — SCREENING CON ALERTAS")
        elif not rows:
            L.append("  → ETAPA 4: ❌ SIN ESTRUCTURA ACCIONARIA — No se puede identificar beneficiario controlador")
        elif not estructura_ok:
            L.append(f"  → ETAPA 4: 🔴 ESTRUCTURA ACCIONARIA INCONSISTENTE (suma: {suma_accionistas:.1f}%)")
        elif not prop_reales:
            L.append("  → ETAPA 4: ⚠️ SIN BENEFICIARIOS ≥25% — Designado administrador/representante")
        else:
            L.append("  → ETAPA 4: ⚠️ REQUIERE VERIFICACIÓN ADICIONAL")
    else:
        L.append("  ❌ No se dispone de estructura accionaria.")
        L.append("  No es posible identificar beneficiarios controladores sin esta información.")
        L.append("")
        L.append("  → ETAPA 4: ❌ NO DISPONIBLE")

    # ══════════════════════════════════════════════════════════════
    #  ETAPA 5 — MATRIZ DE RIESGO MER PLD/FT v7.0
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ETAPA 5 — EVALUACIÓN DE RIESGO MER PLD/FT v7.0")
    L.append(SUB)
    L.append("")
    L.append("  Conforme a la Metodología de Evaluación de Riesgos (MER) v7.0,")
    L.append("  se calcula el grado de riesgo de la Persona Moral considerando")
    L.append("  15 factores ponderados. Clasificación PM: BAJO 85-142 │ MEDIO 143-199 │ ALTO 200+")

    if resultado_mer:
        L.append("")
        # Tabla compacta de factores
        L.append(f"  {'#':<4} {'Factor':<44} {'Val':>4} {'Peso':>6} {'Pts':>8}")
        L.append("  " + "·" * 64)
        for f in resultado_mer.factores:
            L.append(f"  {f.numero:<4} {f.nombre:<44} {f.valor_riesgo:>4.0f} {f.peso:>6.2f} {f.puntaje:>8.1f}")
            L.append(f"      └─ {f.dato_cliente}")
            if getattr(f, "dato_asumido", False) and getattr(f, "nota", ""):
                L.append(f"         ⚠️ DATO ASUMIDO — {f.nota}")
            elif "Resuelto por LLM" in getattr(f, "nota", ""):
                L.append(f"         🤖 {f.nota}")
        L.append("  " + "·" * 64)
        L.append(f"  {'PUNTAJE TOTAL':<53} {resultado_mer.puntaje_total:>8.1f}")
        L.append("")

        emoji_mer = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(resultado_mer.grado_riesgo.value, "⚪")
        L.append(f"  {emoji_mer} GRADO DE RIESGO: {resultado_mer.grado_riesgo.value}  ({resultado_mer.puntaje_total:.1f} puntos)")
        L.append("")

        if resultado_mer.observaciones:
            L.append("  Observaciones MER:")
            for obs in resultado_mer.observaciones:
                L.append(f"    • {obs}")
            L.append("")

        # Datos asumidos — sección de pendientes
        factores_asumidos = [f for f in resultado_mer.factores if getattr(f, "dato_asumido", False)]
        if factores_asumidos:
            from datetime import date as _date, timedelta as _td
            fecha_limite = _date.today() + _td(days=90)
            L.append("  ⚠️ DATOS PENDIENTES DE CONFIRMACIÓN")
            L.append("  " + "·" * 64)
            L.append("  Los siguientes factores fueron evaluados con valores asumidos:")
            for fa in factores_asumidos:
                L.append(f"    • Factor {fa.numero}: {fa.nombre}")
            L.append(f"  FECHA LÍMITE DE RECALIFICACIÓN: {fecha_limite.isoformat()}")
            L.append("")

        if resultado_mer.recomendaciones:
            L.append("  Recomendaciones de debida diligencia:")
            for rec in resultado_mer.recomendaciones:
                L.append(f"    • {rec}")
            L.append("")

        # Alertas estructurales (SAPI, datos asumidos, etc.)
        if getattr(resultado_mer, "alertas", None):
            L.append("  Alertas estructurales:")
            for alerta in resultado_mer.alertas:
                L.append(f"    • ⚠️ {alerta}")
            L.append("")

        L.append(f"  → ETAPA 5: {emoji_mer} {resultado_mer.grado_riesgo.value} — Puntaje {resultado_mer.puntaje_total:.0f}")
    else:
        L.append("")
        L.append("  ⏳ Evaluación MER no disponible.")
        L.append("")
        L.append("  → ETAPA 5: ⏳ NO DISPONIBLE")

    # ══════════════════════════════════════════════════════════════
    #  ALERTAS Y RIESGOS
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  ALERTAS Y RIESGOS")
    L.append(SUB)
    L.append("")

    L.append("  🔴 CRÍTICOS (requieren acción inmediata):")
    all_criticos = [(f"[{it.codigo}] {it.elemento}", it.detalle) for it in items_criticos]
    all_criticos += [(ec, "") for ec in extra_criticos]
    if all_criticos:
        for i, (lbl, det) in enumerate(all_criticos, 1):
            L.append(f"    {i}. {lbl}" + (f": {det}" if det else ""))
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  🟠 ALTOS (requieren acción antes de continuar):")
    if items_altos:
        for i, it in enumerate(items_altos, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  🟡 MEDIOS / OBSERVACIONES (requieren seguimiento):")
    all_medios = [(f"[{it.codigo}] {it.elemento}", it.detalle) for it in items_medios]
    all_medios += [(eo, "") for eo in extra_obs]
    if all_medios:
        for i, (lbl, det) in enumerate(all_medios, 1):
            L.append(f"    {i}. {lbl}" + (f": {det}" if det else ""))
    else:
        L.append("    Ninguno ✅")

    L.append("")
    L.append("  ℹ️ INFORMATIVOS (para registro):")
    if items_info:
        for i, it in enumerate(items_info, 1):
            L.append(f"    {i}. [{it.codigo}] {it.elemento}" + (f": {it.detalle}" if it.detalle else ""))
    else:
        L.append("    Ninguno")

    # ══════════════════════════════════════════════════════════════
    #  RECOMENDACIONES
    # ══════════════════════════════════════════════════════════════
    # Build clean recomendaciones (avoid duplicates from etapa1.recomendaciones)
    recs_set: list[str] = []

    # From items
    docs_faltantes = [it for it in items_sin_colorado if it.categoria == "DOCUMENTO" and not it.presente]
    if docs_faltantes:
        nombres_docs = ", ".join(it.elemento for it in docs_faltantes)
        recs_set.append(f"Solicitar documentos faltantes: {nombres_docs}")

    datos_faltantes = [it for it in items_sin_colorado if it.categoria == "DATO_OBLIGATORIO" and not it.presente]
    if datos_faltantes:
        nombres_datos = ", ".join(it.elemento for it in datos_faltantes)
        recs_set.append(f"Verificar datos obligatorios faltantes: {nombres_datos}")

    dom_faltantes = [it for it in items_sin_colorado if it.categoria == "DOMICILIO" and not it.presente]
    if dom_faltantes:
        campos_dom = ", ".join(it.elemento.replace("Domicilio — ", "") for it in dom_faltantes)
        recs_set.append(f"Completar domicilio: campos faltantes — {campos_dom}")

    if etapa1.poder_cuenta_bancaria is False:
        recs_set.append("El poder no incluye facultad expresa para abrir cuentas bancarias. Solicitar poder específico o ampliación de facultades.")

    if screening_critico:
        recs_set.append("URGENTE: Escalar caso a Comité PLD — coincidencias críticas en listas negras.")
    if screening_observacion:
        recs_set.append("Revisión manual de coincidencias probables en listas negras por analista PLD.")

    if colorado_disponible and dictamen_co == "RECHAZADO":
        if hallazgos_co_criticos:
            codigos = ", ".join(h.get("codigo", "?") for h in hallazgos_co_criticos)
            recs_set.append(f"Resolver hallazgos de Colorado antes de continuar proceso PLD: {codigos}.")
        else:
            recs_set.append("Resolver hallazgos de validación cruzada (Colorado: RECHAZADO) antes de continuar.")
    elif colorado_disponible and "OBSERVACIONES" in dictamen_co:
        recs_set.append("Documentar observaciones de Colorado y atender hallazgos medios.")

    if not estructura_ok and rows:
        recs_set.append("Verificar estructura accionaria — los porcentajes de participación no suman 100%.")

    personas_morales_acc = [r for r in rows if r[1] == "P. Moral"]
    if personas_morales_acc:
        nombres_pm = ", ".join(r[0] for r in personas_morales_acc)
        recs_set.append(f"Ejecutar procedimiento de look-through para accionistas persona moral: {nombres_pm}.")

    if resultado_mer and resultado_mer.grado_riesgo.value == "ALTO":
        recs_set.append("MER ALTO: Aplicar debida diligencia reforzada (EDD) conforme MER v7.0.")
    elif resultado_mer and resultado_mer.grado_riesgo.value == "MEDIO":
        recs_set.append("MER MEDIO: Verificar documentación soporte y monitorear operaciones.")

    if recs_set:
        L.append("")
        L.append(SUB)
        L.append("  RECOMENDACIONES")
        L.append(SUB)
        L.append("")
        for i, rec in enumerate(recs_set, 1):
            L.append(f"    {i}. {rec}")

    # ══════════════════════════════════════════════════════════════
    #  SIGUIENTE PASO
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SUB)
    L.append("  SIGUIENTE PASO")
    L.append(SUB)
    L.append("")

    if dictamen_arizona == "RECHAZADO":
        L.append("    ❌ Expediente NO procede. Motivos:")
        for ec in extra_criticos:
            L.append(f"      • {ec}")
        for it in items_criticos:
            L.append(f"      • [{it.codigo}] {it.elemento}")
        L.append("")
        L.append("    Acciones requeridas:")
        paso = 1
        if items_criticos:
            L.append(f"      {paso}. Subsanar hallazgos críticos de completitud documental:")
            for it in items_criticos:
                L.append(f"         - [{it.codigo}] {it.elemento}")
            paso += 1
        if not estructura_ok and rows:
            L.append(f"      {paso}. Corregir estructura accionaria (suma actual: {suma_accionistas:.1f}%).")
            paso += 1
        if screening_critico:
            L.append(f"      {paso}. Escalar a Comité PLD — coincidencias en listas negras.")
            paso += 1
        if colorado_disponible and dictamen_co == "RECHAZADO":
            L.append(f"      {paso}. Resolver hallazgos de validación cruzada (Colorado: RECHAZADO).")
            paso += 1
        L.append(f"      {paso}. Reprocesar expediente una vez resueltos los puntos anteriores.")

    elif dictamen_arizona == "APROBADO CON OBSERVACIONES":
        L.append("    ⚠️ Expediente aprobado con observaciones.")
        L.append("")
        L.append("    Puntos a atender antes de formalizar la relación comercial:")
        for eo in extra_obs:
            L.append(f"      • {eo}")
        for it in items_altos + items_medios:
            L.append(f"      • [{it.codigo}] {it.elemento}")
        L.append("")
        L.append("    Siguiente acción: Documentar observaciones y proceder con")
        L.append("    onboarding condicionado. Aplicar monitoreo reforzado si corresponde.")

    else:
        L.append("    ✅ Expediente aprobado. Todas las validaciones superadas.")
        L.append("")
        L.append("    Las personas verificadas no presentan coincidencias en:")
        L.append("      • Lista de Personas Bloqueadas (LPB) de la UIF")
        L.append("      • Lista 69-B del SAT (EFOS/EDOS)")
        L.append("      • Lista Negra Consolidada (OFAC, PEP, ONU)")
        L.append("")
        L.append("    Siguiente acción: Proceder con onboarding estándar.")
        L.append("    Etapas 6 a 8 (adverse media, dictamen final y documentación)")
        L.append("    pendientes de implementación.")

    # ══════════════════════════════════════════════════════════════
    #  CIERRE
    # ══════════════════════════════════════════════════════════════
    L.append("")
    L.append(SEP)
    L.append(f"  Fin del reporte — {etapa1.razon_social}")
    L.append(SEP)

    # ── Construir hallazgos estructurados para persistencia (estilo Colorado) ──
    all_hallazgos = _items_a_hallazgos(etapa1.items)

    return ResultadoReporteUnificado(
        texto="\n".join(L),
        empresa_id=etapa1.empresa_id,
        rfc=etapa1.rfc,
        razon_social=etapa1.razon_social,
        dictamen=dictamen_arizona,
        total_pasan=len(items_pasan),
        total_criticos=len(items_criticos) + len(extra_criticos),
        total_altos=len(items_altos),
        total_medios=len(items_medios) + len(extra_obs),
        total_informativos=len(items_info),
        hallazgos=all_hallazgos,
        recomendaciones=recs_set,
        documentos_presentes=etapa1.documentos_presentes,
        screening_incompleto=bool(screening_resumen and screening_resumen.get("screening_incompleto")),
    )
