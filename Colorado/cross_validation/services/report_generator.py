"""
Generador de reportes en texto formateado.
Convierte ReporteValidacion y ResumenGlobal a texto legible.
"""
from __future__ import annotations

from ..models.schemas import (
    ComparacionCampo,
    DatosClave,
    Dictamen,
    Hallazgo,
    PersonaClave,
    ReporteValidacion,
    ResumenGlobal,
    Severidad,
)


_ICONOS_SEVERIDAD = {
    Severidad.CRITICA: "🔴",
    Severidad.MEDIA: "🟡",
    Severidad.INFORMATIVA: "ℹ️",
}

_ICONOS_PASA = {
    True: "✅",
    False: "❌",
    None: "⚪",
}

_ICONOS_DICTAMEN = {
    Dictamen.APROBADO: "✅",
    Dictamen.APROBADO_CON_OBSERVACIONES: "⚠️",
    Dictamen.RECHAZADO: "❌",
}

_NOMBRES_BLOQUE = {
    1: "IDENTIDAD CORPORATIVA",
    2: "DOMICILIO",
    3: "VIGENCIA DE DOCUMENTOS",
    4: "APODERADO LEGAL",
    5: "ESTRUCTURA SOCIETARIA",
    6: "DATOS BANCARIOS",
    7: "CONSISTENCIA NOTARIAL",
    8: "CALIDAD DE EXTRACCIÓN",
    9: "COMPLETITUD DEL EXPEDIENTE",
    10: "VALIDACIÓN EN PORTALES GUBERNAMENTALES",
    11: "COMPARACIÓN MANUAL VS OCR",
}


def _extraer_accionistas(hallazgos: list[Hallazgo]) -> list[dict]:
    """Extrae la lista de accionistas del hallazgo V5.1 si existe."""
    for haz in hallazgos:
        if haz.codigo == "V5.1" and haz.detalles:
            accionistas = haz.detalles.get("accionistas", [])
            if isinstance(accionistas, list) and accionistas:
                return accionistas
    return []


def _extraer_accionistas_reforma(hallazgos: list[Hallazgo]) -> tuple[list[dict], str]:
    """Extrae accionistas de la reforma (V5.2) y la fecha."""
    for haz in hallazgos:
        if haz.codigo == "V5.2" and haz.detalles:
            accionistas = haz.detalles.get("accionistas_reforma", [])
            fecha = haz.detalles.get("fecha_reforma", "")
            if isinstance(accionistas, list) and accionistas:
                return accionistas, fecha
    return [], ""


def _agregar_detalle_expandido(haz: Hallazgo, _l) -> None:
    """Agrega líneas de detalle extra para hallazgos específicos."""
    if not haz.detalles:
        return
    d = haz.detalles
    code = haz.codigo

    # V2.2 — Domicilio fiscal vs comprobante: mostrar ambos domicilios
    if code == "V2.2":
        if d.get("csf"):
            _l(f"        CSF:         {d['csf']}")
        if d.get("domicilio"):
            _l(f"        Comprobante: {d['domicilio']}")

    # V2.3 — Domicilio constitutivo vs actual: mostrar ambos + fuente
    elif code == "V2.3":
        if d.get("fiscal"):
            _l(f"        Fiscal:       {d['fiscal']}")
        if d.get("constitutivo"):
            _l(f"        Constitutivo: {d['constitutivo']}")

    # V7.3 — Consistencia folio: mostrar folios crudos
    elif code == "V7.3":
        if d.get("acta") and d.get("reforma"):
            _l(f"        Folio acta:    {d['acta']}")
            _l(f"        Folio reforma: {d['reforma']}")
            _l("        Nota: el folio base debe coincidir entre documentos.")

    # V8.1 — Confiabilidad baja: listar campos
    elif code == "V8.1":
        campos = d.get("campos", [])
        if isinstance(campos, list):
            for c in campos:
                _l(f"        - {c}")

    # V8.2 — Campos faltantes: listar campos
    elif code == "V8.2":
        campos = d.get("campos", [])
        if isinstance(campos, list):
            for c in campos:
                _l(f"        - {c}")

    # V8.4 — Titular corrupto: mostrar valor
    elif code == "V8.4":
        titular = d.get("titular", "")
        if titular:
            primera_linea = titular.split("\n")[0].split("\r")[0].strip()
            _l(f"        Valor extraído: \"{primera_linea}\"")
        problemas = d.get("problemas", [])
        if isinstance(problemas, list):
            for p in problemas:
                _l(f"        · {p}")

    # V10.x — Portales gubernamentales: mostrar error / estado / identificador
    elif code.startswith("V10."):
        modulo = d.get("modulo_portal", "")
        ident = d.get("identificador", "")
        estado = d.get("estado_portal", "")
        error = d.get("error", "")
        if modulo:
            _l(f"        Módulo: {modulo}")
        if ident:
            _l(f"        Identificador consultado: {ident}")
        if estado:
            _l(f"        Estado portal: {estado}")
        if error:
            _l(f"        Error: {error}")
        screenshot = d.get("screenshot", "")
        if screenshot:
            _l(f"        Screenshot: {screenshot}")


def generar_reporte_texto(reporte: ReporteValidacion) -> str:
    """Genera el reporte completo en texto formateado."""
    lines: list[str] = []
    _l = lines.append

    _l("═" * 60)
    _l("  REPORTE DE VALIDACIÓN CRUZADA KYB")
    _l("═" * 60)
    _l("")
    _l(f"  EMPRESA: {reporte.razon_social}")
    _l(f"  RFC: {reporte.rfc}")
    _l(f"  EMPRESA_ID: {reporte.empresa_id}")
    _l(f"  FECHA DE ANÁLISIS: {reporte.fecha_analisis.strftime('%Y-%m-%d %H:%M')}")
    _l(f"  DOCUMENTOS EN EXPEDIENTE: {', '.join(reporte.documentos_presentes)}")
    _l("")

    # ── DATOS CLAVE DE LA PERSONA MORAL ──
    if reporte.datos_clave:
        dc = reporte.datos_clave
        _l("─" * 60)
        _l("  DATOS CLAVE DE LA PERSONA MORAL")
        _l("─" * 60)
        _l("")
        _l(f"  Razón Social: {dc.razon_social}")
        _l(f"  RFC:          {dc.rfc}")
        _l("")

        # Representante Legal
        if dc.representante_legal:
            rl = dc.representante_legal
            _l(f"  ▸ REPRESENTANTE LEGAL")
            _l(f"    Nombre:      {rl.nombre}")
            if rl.facultades:
                _l(f"    Facultades:  {rl.facultades[:120]}")
            _l(f"    Fuente:      {rl.fuente}")
            _l("")

        # Poder para abrir cuentas bancarias
        if dc.poder_cuenta_bancaria is True:
            _l("  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: ✅ SÍ")
        elif dc.poder_cuenta_bancaria is False:
            _l("  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: ❌ NO DETECTADO")
            _l("    ⚠ No se encontró mención expresa de apertura/operación")
            _l("      de cuentas bancarias en las facultades del poder.")
        else:
            _l("  ▸ PODER PARA ABRIR CUENTAS BANCARIAS: ⚠ NO DETERMINADO")
            _l("    No se encontró Poder Notarial para evaluar.")
        _l("")

        # Apoderados
        if dc.apoderados:
            _l(f"  ▸ APODERADO(S) LEGAL(ES)")
            for i, ap in enumerate(dc.apoderados, 1):
                fac_txt = f" — {ap.facultades[:80]}" if ap.facultades else ""
                _l(f"    {i}. {ap.nombre} ({ap.fuente}){fac_txt}")
            _l("")

        # Accionistas
        if dc.accionistas:
            _l(f"  ▸ ACCIONISTAS / SOCIOS")
            _l(f"    {'#':<4} {'Nombre':<40} {'Tipo':<14} {'%':>8}  {'Fuente'}")
            _l("    " + "─" * 80)
            for i, acc in enumerate(dc.accionistas, 1):
                tipo_label = "P. Moral" if acc.tipo_persona == "moral" else "P. Física"
                pct_str = f"{acc.porcentaje:>7.1f}%" if acc.porcentaje else "     N/D"
                _l(f"    {i:<4} {acc.nombre[:38]:<40} {tipo_label:<14} {pct_str}  {acc.fuente}")
            _l("")

        # Consejo de Administración
        if dc.consejo_administracion:
            _l(f"  ▸ CONSEJO DE ADMINISTRACIÓN")
            for i, m in enumerate(dc.consejo_administracion, 1):
                cargo_txt = f" — {m.facultades}" if m.facultades else ""
                _l(f"    {i}. {m.nombre}{cargo_txt}")
            _l("")

    # ── RESUMEN EJECUTIVO ──
    _l("─" * 60)
    _l("  RESUMEN EJECUTIVO")
    _l("─" * 60)
    _l("")
    icono = _ICONOS_DICTAMEN[reporte.dictamen]
    dictamen_text = reporte.dictamen.value.replace("_", " ")
    _l(f"  DICTAMEN: {icono} {dictamen_text}")
    _l("")
    _l(f"  Validaciones que pasan (✅): {reporte.total_pasan}")
    _l(f"  Hallazgos Críticos  (🔴): {reporte.total_criticos}")
    _l(f"  Hallazgos Medios    (🟡): {reporte.total_medios}")
    _l(f"  Hallazgos Informativos (ℹ️): {reporte.total_informativos}")
    _l("")

    # ── DETALLE DE VALIDACIONES ──
    _l("─" * 60)
    _l("  DETALLE DE VALIDACIONES")
    _l("─" * 60)

    # Agrupar por bloque
    bloques: dict[int, list[Hallazgo]] = {}
    for haz in reporte.hallazgos:
        bloques.setdefault(haz.bloque, []).append(haz)

    for num_bloque in sorted(bloques.keys()):
        # Saltar Bloque 5 del detalle (la estructura accionaria se muestra aparte)
        if num_bloque == 5:
            continue

        nombre = _NOMBRES_BLOQUE.get(num_bloque, f"BLOQUE {num_bloque}")
        haz_bloque = bloques[num_bloque]
        _l("")
        _l(f"  BLOQUE {num_bloque}: {nombre}")
        _l("  " + "·" * 50)

        for haz in haz_bloque:
            icono_p = _ICONOS_PASA.get(haz.pasa, "⚪")
            status = "PASA" if haz.pasa else ("FALLA" if haz.pasa is False else "N/A")
            # Solo mostrar severidad en hallazgos (fallas / N/A), no en validaciones que pasan
            if haz.pasa is True:
                _l(f"    {haz.codigo} {haz.nombre}: {icono_p} {status}")
            else:
                icono_s = _ICONOS_SEVERIDAD.get(haz.severidad, "")
                _l(f"    {haz.codigo} {haz.nombre}: {icono_p} {status} {icono_s}")

            # Detallar el mensaje (indentado)
            for line in haz.mensaje.split("\n"):
                _l(f"      {line}")

            # ── Detalle expandido por hallazgo ──
            _agregar_detalle_expandido(haz, _l)

            # Mostrar detalles clave genéricos (valores, encontrados)
            if haz.detalles:
                for key, val in haz.detalles.items():
                    if key in ("valores", "encontrados") and isinstance(val, dict):
                        for k2, v2 in val.items():
                            _l(f"        - {k2}: {v2}")
            _l("")

    # ── COMPARACIÓN MANUAL VS OCR (Bloque 11 — si existe) ──
    if reporte.comparacion_fuentes:
        _l("─" * 60)
        _l("  BLOQUE 11: COMPARACIÓN MANUAL VS OCR")
        _l("─" * 60)
        _l("")
        _l(f"  {'Campo':<25} {'Manual':<25} {'OCR':<25} {'Resultado':<12} {'Severidad'}")
        _l("  " + "─" * 95)
        for comp in reporte.comparacion_fuentes:
            vm = (comp.valor_manual or "—")[:23]
            vo = (comp.valor_ocr or "—")[:23]
            if comp.coincide is True:
                resultado = "✅ Coincide"
            elif comp.coincide is False:
                resultado = "❌ Discrepa"
            else:
                resultado = "⚪ N/A"
            sev_icon = _ICONOS_SEVERIDAD.get(comp.severidad, "")
            _l(f"  {comp.campo:<25} {vm:<25} {vo:<25} {resultado:<12} {sev_icon}")
        _l("")
        # Resumen breve
        total = len(reporte.comparacion_fuentes)
        coinciden = sum(1 for c in reporte.comparacion_fuentes if c.coincide is True)
        discrepan = sum(1 for c in reporte.comparacion_fuentes if c.coincide is False)
        na = sum(1 for c in reporte.comparacion_fuentes if c.coincide is None)
        _l(f"  Resumen: {coinciden}/{total} coinciden, {discrepan} discrepan, {na} no evaluables")
        _l("")

    # ── ALERTAS Y RIESGOS ──
    _l("─" * 60)
    _l("  ALERTAS Y RIESGOS")
    _l("─" * 60)

    criticos = [h for h in reporte.hallazgos if h.pasa is False and h.severidad == Severidad.CRITICA]
    medios = [h for h in reporte.hallazgos if h.pasa is False and h.severidad == Severidad.MEDIA]
    informativos = [h for h in reporte.hallazgos if h.severidad == Severidad.INFORMATIVA and h.pasa is not True]

    _l("")
    _l("  🔴 CRÍTICOS (requieren acción inmediata):")
    if criticos:
        for i, haz in enumerate(criticos, 1):
            _l(f"    {i}. [{haz.codigo}] {haz.mensaje}")
    else:
        _l("    Ninguno ✅")

    _l("")
    _l("  🟡 MEDIOS (requieren seguimiento):")
    if medios:
        for i, haz in enumerate(medios, 1):
            _l(f"    {i}. [{haz.codigo}] {haz.mensaje}")
    else:
        _l("    Ninguno ✅")

    _l("")
    _l("  ℹ️ INFORMATIVOS (para registro):")
    if informativos:
        for i, haz in enumerate(informativos, 1):
            _l(f"    {i}. [{haz.codigo}] {haz.mensaje}")
    else:
        _l("    Ninguno")

    # ── RECOMENDACIONES ──
    _l("")
    _l("─" * 60)
    _l("  RECOMENDACIONES")
    _l("─" * 60)
    _l("")
    if reporte.recomendaciones:
        for i, rec in enumerate(reporte.recomendaciones, 1):
            _l(f"    {i}. {rec}")
    else:
        _l("    Sin recomendaciones adicionales.")

    # ── DICTAMEN FINAL ──
    _l("")
    _l("─" * 60)
    _l("  SIGUIENTE PASO")
    _l("─" * 60)
    _l("")
    if reporte.dictamen == Dictamen.APROBADO:
        _l("    ✅ Expediente listo para onboarding.")
    elif reporte.dictamen == Dictamen.APROBADO_CON_OBSERVACIONES:
        _l("    ⚠️ Expediente aprobado con observaciones.")
        _l("    Documentos/datos a subsanar:")
        for haz in medios:
            _l(f"      - {haz.codigo}: {haz.nombre}")
    else:
        _l("    ❌ Expediente RECHAZADO.")
        _l("    Motivos principales:")
        for haz in criticos:
            _l(f"      - {haz.codigo}: {haz.nombre}")
        _l("")
        _l("    Documentos requeridos para re-evaluación:")
        for rec in reporte.recomendaciones[:5]:
            _l(f"      - {rec}")

    _l("")
    _l("═" * 60)
    _l(f"  Fin del reporte — {reporte.razon_social}")
    _l("═" * 60)

    return "\n".join(lines)


def generar_resumen_global_texto(resumen: ResumenGlobal) -> str:
    """Genera el resumen global de todas las empresas."""
    lines: list[str] = []
    _l = lines.append

    _l("═" * 70)
    _l("  RESUMEN GLOBAL DE VALIDACIÓN CRUZADA KYB")
    _l("═" * 70)
    _l("")
    _l(f"  Fecha: {resumen.fecha_analisis.strftime('%Y-%m-%d %H:%M')}")
    _l(f"  Total empresas analizadas: {resumen.total_empresas}")
    _l("")

    # ── Tabla de dictámenes ──
    _l("─" * 70)
    _l("  TABLA DE DICTÁMENES")
    _l("─" * 70)
    _l("")
    _l(f"  {'RFC':<14} {'Razón Social':<30} {'Dictamen':<25} 🔴 🟡 ℹ️")
    _l("  " + "─" * 66)

    for row in resumen.tabla_dictamenes:
        icono = _ICONOS_DICTAMEN.get(Dictamen(row["dictamen"]), "")
        razon = row["razon_social"][:28]
        dictamen_short = row["dictamen"].replace("_", " ")[:23]
        _l(
            f"  {row['rfc']:<14} {razon:<30} {icono} {dictamen_short:<22} "
            f"{row['criticos']:>2} {row['medios']:>2} {row['informativos']:>2}"
        )

    # ── Top hallazgos ──
    _l("")
    _l("─" * 70)
    _l("  TOP HALLAZGOS MÁS FRECUENTES")
    _l("─" * 70)
    _l("")
    for i, hf in enumerate(resumen.hallazgos_frecuentes[:5], 1):
        _l(f"    {i}. {hf['hallazgo']} — en {hf['frecuencia']}/{resumen.total_empresas} empresas")

    # ── Recomendaciones globales ──
    _l("")
    _l("─" * 70)
    _l("  RECOMENDACIONES GLOBALES")
    _l("─" * 70)
    _l("")
    for i, rec in enumerate(resumen.recomendaciones_globales, 1):
        _l(f"    {i}. {rec}")

    # ── Reportes individuales ──
    _l("")
    _l("═" * 70)
    _l("  REPORTES INDIVIDUALES POR EMPRESA")
    _l("═" * 70)

    for reporte in resumen.reportes:
        _l("")
        _l(generar_reporte_texto(reporte))

    return "\n".join(lines)
