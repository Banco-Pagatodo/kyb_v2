"""
Formateador de Dictamen PLD/FT a texto plano (.txt).

Genera un documento de ~6 páginas con formato tabular fijo
siguiendo la plantilla de Banco PagaTodo S.A., Institución de Banca Múltiple.
"""
from __future__ import annotations

import textwrap
from datetime import date
from typing import Any

from ..models.dictamen_schemas import (
    AccionistaDictamen,
    AdministradorDictamen,
    DictamenPLDFT,
    PropietarioRealDictamen,
    RepresentanteLegalDictamen,
    ScreeningSeccion,
)

_W = 100  # Ancho estándar del documento


def generar_txt_dictamen(dictamen: DictamenPLDFT) -> str:
    """Genera el texto completo del dictamen."""
    secciones = [
        _encabezado(dictamen),
        _seccion_persona_moral(dictamen),
        _seccion_screening_pm(dictamen),
        _seccion_actividad(dictamen),
        _seccion_domicilio(dictamen),
        _seccion_estructura_accionaria(dictamen),
        _seccion_propietarios(dictamen),
        _seccion_representantes(dictamen),
        _seccion_administracion(dictamen),
        _seccion_perfil_transaccional(dictamen),
        _seccion_vigencia_documentos(dictamen),
        _seccion_conclusiones(dictamen),
        _seccion_elaboro(dictamen),
    ]
    return "\n".join(secciones)


# ═══════════════════════════════════════════════════════════════════
#  SECCIONES
# ═══════════════════════════════════════════════════════════════════

def _encabezado(d: DictamenPLDFT) -> str:
    fecha_str = d.fecha_elaboracion.strftime("%d/%m/%Y")
    pm = d.persona_moral
    return "\n".join([
        _linea("═"),
        _centrar("BANCO PAGATODO S.A., INSTITUCIÓN DE BANCA MÚLTIPLE"),
        _centrar("DICTAMEN PLD/FT — PERSONA MORAL"),
        _linea("═"),
        "",
        f"  Dictamen ID:       {d.dictamen_id}",
        f"  Fecha elaboración: {fecha_str}",
        f"  Tipo producto:     {d.tipo_producto}",
        f"  Grado riesgo:      {d.grado_riesgo_inicial.upper()}",
        "",
        _linea("─"),
    ])


def _seccion_persona_moral(d: DictamenPLDFT) -> str:
    pm = d.persona_moral
    lines = [
        "",
        _titulo("1. DATOS GENERALES DE LA PERSONA MORAL"),
        "",
        f"  Razón social:           {pm.get('razon_social', 'N/D')}",
        f"  RFC:                    {pm.get('rfc', 'N/D')}",
        f"  Fecha constitución:     {pm.get('fecha_constitucion', 'N/D')}",
        f"  Actividad económica:    {pm.get('actividad_economica', 'N/D')}",
        f"  Domicilio:              {pm.get('domicilio', 'N/D')}",
        f"  Uso de cuenta:          {pm.get('uso_cuenta', 'N/D')}",
    ]
    # BUG-17: folio mercantil
    if pm.get("folio_mercantil"):
        lines.append(f"  Folio mercantil:        {pm['folio_mercantil']}")
    # BUG-13: cláusula de extranjeros
    if pm.get("clausula_extranjeros"):
        lines.append(f"  Cláusula extranjeros:   {pm['clausula_extranjeros']}")
    # BUG-18: datos notariales del acta
    dn = pm.get("datos_notariales_acta", {})
    if dn:
        notario = dn.get("nombre_notario", "")
        num_not = dn.get("numero_notaria", "")
        estado = dn.get("estado_notaria", "")
        num_esc = dn.get("numero_escritura_poliza", "")
        fecha_c = dn.get("fecha_constitucion", dn.get("fecha_expedicion", ""))
        lines.append(f"  Notario acta:           {notario} — Notaría {num_not}, {estado}")
        lines.append(f"  Escritura N°:           {num_esc}")
        if fecha_c:
            lines.append(f"  Fecha escritura acta:   {fecha_c}")
    lines.append("")
    return "\n".join(lines)


def _seccion_screening_pm(d: DictamenPLDFT) -> str:
    return "\n".join([
        _titulo("2. SCREENING — PERSONA MORAL (RAZÓN SOCIAL)"),
        "",
        _screening_block(d.screening_persona_moral),
        "",
    ])


def _seccion_actividad(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("3. ACTIVIDAD ECONÓMICA"),
        "",
        f"  Actividad declarada:            {d.actividad_economica or 'N/D'}",
        f"  Congruencia con documentos:     {'SÍ' if d.congruencia_info_docs else 'NO'}",
        f"  Actividades no declaradas:      {'SÍ' if d.actividades_no_declaradas else 'NO'}",
        f"  Actividades de mayor riesgo:    {'SÍ' if d.actividades_mayor_riesgo else 'NO'}",
    ]
    if d.detalle_act_mayor_riesgo:
        lines.append(f"  Detalle:                        {d.detalle_act_mayor_riesgo}")
    lines.append("")
    return "\n".join(lines)


def _seccion_domicilio(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("4. DOMICILIO"),
        "",
        f"  Domicilio registrado:           {d.domicilio or 'N/D'}",
        f"  Concuerda con documentos:       {'SÍ' if d.concuerda_domicilio_docs else 'NO'}",
        f"  Concuerda con actividad:        {'SÍ' if d.concuerda_domicilio_actividad else 'NO'}",
        f"  Vínculo con otra PM:            {'SÍ' if d.vinculo_otra_pm else 'NO'}",
        f"  País sancionado:                {'SÍ' if d.vinculos_paises_sancionados else 'NO'}",
        f"  Observaciones:                  {d.observaciones_domicilio}",
        "",
    ]
    return "\n".join(lines)


def _seccion_estructura_accionaria(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("5. ESTRUCTURA ACCIONARIA VIGENTE"),
        "",
    ]
    if d.estructura_accionaria:
        lines.append(_tabla_accionistas(d.estructura_accionaria))
    else:
        lines.append("  No se identificaron accionistas en la documentación.")
    lines += [
        "",
        "  Screening accionistas:",
        _screening_block(d.screening_accionistas, indent=4),
        "",
    ]
    return "\n".join(lines)


def _seccion_propietarios(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("6. PROPIETARIOS REALES / BENEFICIARIOS CONTROLADORES"),
        "",
    ]
    if d.propietarios_reales:
        lines.append(_tabla_propietarios(d.propietarios_reales))
    else:
        lines.append("  No se identificaron propietarios reales (≥25%).")
    lines += [
        "",
        "  Screening propietarios:",
        _screening_block(d.screening_propietarios, indent=4),
        f"  Señales de alerta:  {d.senales_alerta_propietarios}",
        "",
    ]
    return "\n".join(lines)


def _seccion_representantes(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("7. REPRESENTANTES LEGALES"),
        "",
    ]
    if d.representantes_legales:
        lines.append(_tabla_representantes(d.representantes_legales))
    else:
        lines.append("  No se identificaron representantes legales.")
    # BUG-14: detalle del poder notarial
    dp = d.detalle_poder_notarial or {}
    if dp:
        lines.append("")
        lines.append("  Poder notarial:")
        if dp.get("tipo_poder"):
            lines.append(f"    Tipo:        {dp['tipo_poder']}")
        if dp.get("nombre_notario"):
            lines.append(f"    Notario:     {dp['nombre_notario']} — Notaría {dp.get('numero_notaria', 'N/D')}, {dp.get('estado_notaria', '')}")
        if dp.get("numero_escritura"):
            lines.append(f"    Escritura:   {dp['numero_escritura']}")
        if dp.get("fecha_otorgamiento"):
            lines.append(f"    Fecha:       {dp['fecha_otorgamiento']}")
        if dp.get("facultades"):
            wrapped = textwrap.fill(
                dp["facultades"],
                width=_W - 6,
                initial_indent="    Facultades:  ",
                subsequent_indent="                 ",
            )
            lines.append(wrapped)
    lines += [
        "",
        "  Screening representantes:",
        _screening_block(d.screening_representantes, indent=4),
        "",
    ]
    return "\n".join(lines)


def _seccion_administracion(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("8. ADMINISTRACIÓN / CONSEJO"),
        "",
    ]
    if d.administracion:
        lines.append(_tabla_admin(d.administracion))
    else:
        lines.append("  No se identificaron administradores/consejeros.")
    lines += [
        "",
        "  Screening administración:",
        _screening_block(d.screening_administracion, indent=4),
        f"  Señales de alerta:  {d.senales_alerta_admin or 'Sin señales de alerta'}",
        "",
    ]
    return "\n".join(lines)


def _seccion_perfil_transaccional(d: DictamenPLDFT) -> str:
    lines = [
        _titulo("9. PERFIL TRANSACCIONAL"),
        "",
        f"  Uso de cuenta:                  {d.uso_cuenta or 'N/D'}",
        f"  Congruencia perfil/actividad:   {'SÍ' if d.congruencia_perfil_actividad else 'NO'}",
        f"  Observaciones:                  {d.observaciones_perfil or 'Sin observaciones'}",
    ]
    # BUG-09: datos del estado de cuenta
    pt = d.perfil_transaccional or {}
    if pt:
        lines.append("")
        lines.append("  Estado de cuenta:")
        if pt.get("banco"):
            lines.append(f"    Banco:            {pt['banco']}")
        if pt.get("numero_cuenta"):
            lines.append(f"    Cuenta:           {pt['numero_cuenta']}")
        if pt.get("clabe"):
            lines.append(f"    CLABE:            {pt['clabe']}")
        if pt.get("periodo"):
            lines.append(f"    Período:          {pt['periodo']}")
        if pt.get("saldo_inicial"):
            lines.append(f"    Saldo inicial:    ${_fmt_monto(pt['saldo_inicial'])}")
        if pt.get("saldo_final"):
            lines.append(f"    Saldo final:      ${_fmt_monto(pt['saldo_final'])}")
        if pt.get("total_depositos"):
            lines.append(f"    Total depósitos:  ${_fmt_monto(pt['total_depositos'])}")
        if pt.get("total_retiros"):
            lines.append(f"    Total retiros:    ${_fmt_monto(pt['total_retiros'])}")
    lines.append("")
    return "\n".join(lines)


def _seccion_vigencia_documentos(d: DictamenPLDFT) -> str:
    """BUG-11: Muestra vigencia de documentos presentados."""
    vigencias = d.vigencia_documentos or []
    if not vigencias:
        return ""
    lines = [
        _titulo("9-B. VIGENCIA DE DOCUMENTOS"),
        "",
    ]
    for v in vigencias:
        estado = "✓ Vigente" if v.get("vigente") is True else (
            "✗ No vigente" if v.get("vigente") is False else "? Sin verificar"
        )
        lines.append(f"  {v.get('documento', 'N/D'):40s} {estado}  — {v.get('detalle', '')}")
    lines.append("")
    return "\n".join(lines)


def _seccion_conclusiones(d: DictamenPLDFT) -> str:
    c = d.conclusiones
    lines = [
        _linea("═"),
        _titulo("10. CONCLUSIONES PLD/FT"),
        "",
        f"  Señales de alerta:              {'SÍ' if c.get('senales_alerta') else 'NO'}",
    ]
    if c.get("detalle_senales"):
        lines.append(f"  Detalle:                        {c['detalle_senales']}")
    lines += [
        f"  Grado riesgo confirmado:        {c.get('grado_riesgo_final', d.grado_riesgo_inicial).upper()}",
        f"  Debida diligencia reforzada:    {'SÍ' if c.get('debida_diligencia_reforzada') else 'NO'}",
    ]
    if c.get("detalle_edd"):
        lines.append(f"  Medidas EDD:                    {c['detalle_edd']}")
    lines += [
        f"  Presentar a CCC:               {'SÍ' if c.get('presentar_ccc') else 'NO'}",
    ]
    if c.get("observaciones_oficial"):
        lines.append(f"  Observaciones:                  {c['observaciones_oficial']}")
    lines.append("")
    return "\n".join(lines)


def _seccion_elaboro(d: DictamenPLDFT) -> str:
    elaboro = d.elaboro
    meta = d.metadata
    return "\n".join([
        _linea("─"),
        "  ELABORÓ:",
        f"    {elaboro.get('nombre', 'Agente Arizona')}",
        f"    {elaboro.get('firma', '')}",
        "",
        f"  Pipeline:  {meta.get('pipeline_id', 'N/D')}",
        f"  Versión:   {meta.get('agente_version', 'N/D')}",
        f"  Fuentes:   {', '.join(meta.get('fuentes_datos', []))}",
        f"  MER:       puntaje={meta.get('puntaje_mer', 'N/D')}, grado={meta.get('grado_mer', 'N/D')}",
        f"  Personas screened: {meta.get('total_personas_screened', 0)}",
        f"  Coincidencias:     {meta.get('total_coincidencias', 0)}",
        f"  Tiempo:    {meta.get('tiempo_procesamiento_ms', 0)} ms",
        "",
        _linea("═"),
        _centrar("FIN DEL DICTAMEN PLD/FT"),
        _linea("═"),
    ])


# ═══════════════════════════════════════════════════════════════════
#  HELPERS DE FORMATO
# ═══════════════════════════════════════════════════════════════════

def _linea(char: str = "─") -> str:
    return char * _W


def _centrar(texto: str) -> str:
    return texto.center(_W)


def _titulo(texto: str) -> str:
    return f"  {'─' * 4} {texto} {'─' * max(0, _W - len(texto) - 9)}"


def _screening_block(s: ScreeningSeccion, indent: int = 2) -> str:
    pad = " " * indent
    lines = [
        f"{pad}  Coincidencia en listas:   {'SÍ' if s.coincidencia_listas else 'NO'}",
    ]
    if s.datos_lista:
        lines.append(f"{pad}  Datos de lista:           {s.datos_lista}")
    lines.append(f"{pad}  Confirma coincidencia:    {'SÍ' if s.confirma_coincidencia else 'NO'}")
    if s.justificacion_descarte:
        # Envolver texto largo
        wrapped = textwrap.fill(
            s.justificacion_descarte,
            width=_W - indent - 4,
            initial_indent=f"{pad}  Justificación descarte:   ",
            subsequent_indent=f"{pad}                            ",
        )
        lines.append(wrapped)
    if s.fuentes_negativas:
        lines.append(f"{pad}  Fuentes negativas:        SÍ")
        if s.detalle_fuentes:
            lines.append(f"{pad}  Detalle fuentes:          {s.detalle_fuentes}")
    return "\n".join(lines)


def _tabla_accionistas(accionistas: list[AccionistaDictamen]) -> str:
    """Tabla de accionistas con box-drawing."""
    col_w = [4, 36, 10, 18, 6, 20]
    headers = ["#", "Nombre / Razón social", "%", "RFC / CURP", "Tipo", "Coincidencia listas"]
    return _tabla(col_w, headers, [
        [
            str(a.numero),
            a.nombre_razon_social[:36],
            a.porcentaje_accionario,
            a.rfc_curp or "N/D",
            a.tipo_persona,
            a.coincidencia_listas[:20],
        ]
        for a in accionistas
    ])


def _tabla_propietarios(propietarios: list[PropietarioRealDictamen]) -> str:
    # BUG-05: ampliar columna Tipo control de 18→22 para "Tenencia Accionaria" (20 chars)
    col_w = [4, 34, 22, 18, 20]
    headers = ["#", "Nombre", "Tipo control", "RFC / CURP", "Coincidencia listas"]
    return _tabla(col_w, headers, [
        [
            str(p.numero),
            p.nombre[:34],
            p.tipo_control[:22],
            p.rfc_curp or "N/D",
            p.coincidencia_listas[:20],
        ]
        for p in propietarios
    ])


def _tabla_representantes(reps: list[RepresentanteLegalDictamen]) -> str:
    col_w = [4, 46, 18, 26]
    headers = ["#", "Nombre", "RFC / CURP", "Coincidencia listas"]
    return _tabla(col_w, headers, [
        [str(r.numero), r.nombre[:46], r.rfc_curp or "N/D", r.coincidencia_listas[:26]]
        for r in reps
    ])


def _tabla_admin(admins: list[AdministradorDictamen]) -> str:
    col_w = [4, 36, 22, 18, 14]
    headers = ["#", "Nombre", "Puesto", "RFC / CURP", "Coin. listas"]
    return _tabla(col_w, headers, [
        [
            str(a.numero),
            a.nombre[:36],
            a.puesto[:22],
            a.rfc_curp or "N/D",
            a.coincidencia_listas[:14],
        ]
        for a in admins
    ])


def _tabla(col_widths: list[int], headers: list[str], rows: list[list[str]]) -> str:
    """Genera una tabla con bordes usando box-drawing chars."""
    def fila(vals: list[str]) -> str:
        celdas = [v.ljust(w)[:w] for v, w in zip(vals, col_widths)]
        return "  │ " + " │ ".join(celdas) + " │"

    sep_top = "  ┌─" + "─┬─".join("─" * w for w in col_widths) + "─┐"
    sep_mid = "  ├─" + "─┼─".join("─" * w for w in col_widths) + "─┤"
    sep_bot = "  └─" + "─┴─".join("─" * w for w in col_widths) + "─┘"

    lines = [sep_top, fila(headers), sep_mid]
    for row in rows:
        lines.append(fila(row))
    lines.append(sep_bot)
    return "\n".join(lines)


def _fmt_monto(valor: str | int | float) -> str:
    """Formatea un monto numérico con separadores de miles."""
    try:
        return f"{float(valor):,.2f}"
    except (ValueError, TypeError):
        return str(valor)
