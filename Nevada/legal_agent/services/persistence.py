"""
Persistencia del Dictamen Jurídico en PostgreSQL.
Guarda resultados en la tabla dictamenes_legales.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from ..core.database import get_pool
from ..models.schemas import DictamenJuridico, ResultadoReglas

logger = logging.getLogger("nevada.persistence")


async def crear_tabla_si_no_existe() -> None:
    """Crea la tabla dictamenes_legales si no existe (idempotente)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dictamenes_legales (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                empresa_id      UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                rfc             VARCHAR(13) NOT NULL,
                razon_social    TEXT NOT NULL,

                dictamen        VARCHAR(40) NOT NULL,
                fundamento_legal TEXT,
                dictamen_json   JSONB NOT NULL,
                dictamen_texto  TEXT,

                datos_expediente JSONB,
                reglas_aplicadas JSONB,

                version         VARCHAR(20) DEFAULT 'Nevada v1.0.0',
                generado_por    VARCHAR(50) DEFAULT 'legal_agent',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dictamenes_legales_empresa
            ON dictamenes_legales(empresa_id)
        """)
    logger.info("Tabla dictamenes_legales verificada/creada")


async def guardar_dictamen(
    empresa_id: str,
    dictamen: DictamenJuridico,
    resultado_reglas: ResultadoReglas,
    datos_expediente: dict[str, Any] | None = None,
    documentos_ocr: dict[str, Any] | None = None,
) -> str:
    """
    Guarda el dictamen jurídico en la BD dentro de una transacción explícita.

    Returns:
        ID (UUID) del registro creado.
    """
    pool = await get_pool()
    uid = _uuid.UUID(empresa_id)

    dictamen_json = json.loads(dictamen.model_dump_json())
    reglas_json = json.loads(resultado_reglas.model_dump_json())

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO dictamenes_legales (
                    empresa_id, rfc, razon_social,
                    dictamen, fundamento_legal,
                    dictamen_json, dictamen_texto,
                    datos_expediente, reglas_aplicadas
                ) VALUES (
                    $1, $2, $3,
                    $4, $5,
                    $6::jsonb, $7,
                    $8::jsonb, $9::jsonb
                )
                RETURNING id
                """,
                uid,
                dictamen.rfc or "",
                dictamen.razon_social or "",
                dictamen.dictamen_resultado or "FAVORABLE",
                dictamen.fundamento_legal,
                json.dumps(dictamen_json, ensure_ascii=False),
                _generar_texto_plano(dictamen, resultado_reglas=resultado_reglas, documentos_ocr=documentos_ocr),
                json.dumps(datos_expediente or {}, ensure_ascii=False),
                json.dumps(reglas_json, ensure_ascii=False),
            )

    record_id = str(row["id"])
    logger.info(
        "Dictamen jurídico guardado: empresa=%s dictamen=%s id=%s",
        empresa_id, dictamen.dictamen_resultado, record_id,
    )
    return record_id


async def obtener_dictamen(empresa_id: str) -> dict[str, Any] | None:
    """Obtiene el último dictamen jurídico de una empresa."""
    pool = await get_pool()
    uid = _uuid.UUID(empresa_id)

    row = await pool.fetchrow(
        """
        SELECT id, empresa_id, rfc, razon_social,
               dictamen, fundamento_legal,
               dictamen_json, dictamen_texto,
               datos_expediente, reglas_aplicadas,
               version, generado_por,
               created_at, updated_at
        FROM dictamenes_legales
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        uid,
    )

    if not row:
        return None

    dj = row["dictamen_json"]
    if isinstance(dj, str):
        dj = json.loads(dj)

    reglas = row["reglas_aplicadas"]
    if isinstance(reglas, str):
        reglas = json.loads(reglas)

    datos_exp = row["datos_expediente"]
    if isinstance(datos_exp, str):
        datos_exp = json.loads(datos_exp)

    return {
        "id": str(row["id"]),
        "empresa_id": str(row["empresa_id"]),
        "rfc": row["rfc"],
        "razon_social": row["razon_social"],
        "dictamen": row["dictamen"],
        "fundamento_legal": row["fundamento_legal"],
        "dictamen_json": dj,
        "dictamen_texto": row["dictamen_texto"],
        "datos_expediente": datos_exp,
        "reglas_aplicadas": reglas,
        "version": row["version"],
        "generado_por": row["generado_por"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _generar_texto_plano(
    d: DictamenJuridico,
    resultado_reglas: ResultadoReglas | None = None,
    documentos_ocr: dict[str, Any] | None = None,
) -> str:
    """Genera texto plano del dictamen en formato DJ-1 estilo BPT (alineado con Colorado/Arizona)."""

    W = 100
    na = "N/A"

    def _v(val: object) -> str:
        return str(val) if val else na

    def _sn(val: object) -> str:
        if val is None:
            return na
        return "Sí" if val else "No"

    def _sec(num: str, title: str) -> str:
        label = f"  ──── {num}. {title} "
        return label + "─" * max(0, W - len(label))

    lines: list[str] = []

    # ═══════════ ENCABEZADO ═══════════
    lines.append("═" * W)
    lines.append(f"{'BANCO PAGATODO S.A., INSTITUCIÓN DE BANCA MÚLTIPLE':^{W}}")
    lines.append(f"{'DICTAMEN LEGAL — PERSONA MORAL':^{W}}")
    lines.append("═" * W)
    lines.append("")
    lines.append(f"  Dictamen ID:       {_v(d.numero_dictamen)}-{_v(d.rfc)}-{(_v(d.fecha)).replace('-','')}")
    lines.append(f"  Fecha elaboración: {_v(d.fecha)}")
    lines.append(f"  Razón Social:      {_v(d.razon_social)}")
    lines.append(f"  RFC:               {_v(d.rfc)}")
    lines.append("")
    lines.append("─" * W)

    # ──── 1. DENOMINACIÓN SOCIAL ─────
    lines.append("")
    lines.append(_sec("1", "DENOMINACIÓN SOCIAL"))
    lines.append("")
    lines.append(f"  Denominación (Acta Constitutiva):   {_v(d.denominacion_acta)}")
    lines.append(f"  Denominación (CSF):                 {_v(d.denominacion_csf)}")
    lines.append(f"  ¿Cambio de denominación?:           {_sn(d.cambio_denominacion)}")
    if d.cambio_denominacion and d.cambio_denominacion_detalle:
        lines.append(f"  Detalle del cambio:                 {d.cambio_denominacion_detalle}")

    # ──── 2. DATOS CORPORATIVOS ──────
    lines.append("")
    lines.append(_sec("2", "DATOS CORPORATIVOS"))
    lines.append("")
    lines.append(f"  Estatus en Padrón SAT:       {_v(d.estatus_padron)}")
    lines.append(f"  Giro Mercantil (CSF):        {_v(d.giro_mercantil_csf)}")
    lines.append(f"  Domicilio Fiscal:            {_v(d.domicilio_fiscal)}")
    lines.append(f"  Capital Social:              {_v(d.capital_social)} {_v(d.moneda_capital)}")
    lines.append(f"  Cláusula de Extranjeros:     {_v(d.clausula_extranjeros)}")

    # ──── 3. DATOS DE CONSTITUCIÓN ───
    lines.append("")
    lines.append(_sec("3", "DATOS DE CONSTITUCIÓN"))
    lines.append("")
    ct = d.constitucion
    lines.append(f"  No. de Escritura / Póliza:    {_v(ct.escritura_numero)}")
    lines.append(f"  Fecha de Escritura:           {_v(ct.escritura_fecha)}")
    lines.append(f"  Notario:                      {_v(ct.nombre_notario)} — Notaría {_v(ct.numero_notario)}, {_v(ct.residencia_notario)}")
    lines.append(f"  Folio Mercantil Electrónico:  {_v(ct.folio_mercantil)}")
    lines.append(f"  Fecha del Folio Mercantil:    {_v(ct.fecha_folio_mercantil)}")
    lines.append(f"  Lugar del Folio Mercantil:    {_v(ct.lugar_folio_mercantil)}")
    if ct.volumen_tomo:
        lines.append(f"  Volumen / Tomo:               {ct.volumen_tomo}")

    # ──── 4. ÚLTIMOS ESTATUTOS SOCIALES
    lines.append("")
    lines.append(_sec("4", "ÚLTIMOS ESTATUTOS SOCIALES"))
    lines.append("")
    ue = d.ultimos_estatutos
    lines.append(f"  No. de Escritura / Póliza:    {_v(ue.escritura_numero)}")
    lines.append(f"  Fecha de Escritura:           {_v(ue.escritura_fecha)}")
    lines.append(f"  Notario:                      {_v(ue.nombre_notario)} — Notaría {_v(ue.numero_notario)}, {_v(ue.residencia_notario)}")
    lines.append(f"  Folio Mercantil Electrónico:  {_v(ue.folio_mercantil)}")
    lines.append(f"  Fecha del Folio Mercantil:    {_v(ue.fecha_folio_mercantil)}")
    lines.append(f"  Lugar del Folio Mercantil:    {_v(ue.lugar_folio_mercantil)}")
    if ue.volumen_tomo:
        lines.append(f"  Volumen / Tomo:               {ue.volumen_tomo}")
    if ue.antecedentes_resumen:
        lines.append("")
        lines.append("  Resumen de Antecedentes:")
        for ln_a in ue.antecedentes_resumen.split("\n"):
            lines.append(f"    {ln_a}")
    if ue.orden_del_dia:
        lines.append("")
        lines.append("  Orden del Día:")
        for ln_o in ue.orden_del_dia.split("\n"):
            lines.append(f"    {ln_o}")
    if d.resumen_cambios_estatutos:
        lines.append("")
        lines.append(f"  Resumen de Cambios:           {d.resumen_cambios_estatutos}")

    # ──── 5. ACTIVIDAD / GIRO ────────
    lines.append("")
    lines.append(_sec("5", "ACTIVIDAD / GIRO"))
    lines.append("")
    act = d.actividad
    lines.append(f"  Actividad / Giro:             {_v(act.actividad_giro)}")
    lines.append(f"  ¿Sufrió modificaciones?:      {_sn(act.sufrio_modificaciones)}")
    lines.append(f"  Instrumento de cambio:        {_v(act.instrumento_cambio)}")
    lines.append(f"  Fuente del dato:              {_v(act.fuente_documento)}")
    lines.append(f"  Observaciones:                {_v(act.observaciones)}")

    # ──── 6. TENENCIA ACCIONARIA ─────
    lines.append("")
    lines.append(_sec("6", "TENENCIA ACCIONARIA"))
    lines.append("")
    lines.append("  ┌──────┬──────────────────────────────────────┬────────────┬──────────┬──────────────┐")
    lines.append("  │ #    │ Nombre / Razón social                │ %          │ Tipo     │ Extranjero   │")
    lines.append("  ├──────┼──────────────────────────────────────┼────────────┼──────────┼──────────────┤")
    for i, acc in enumerate(d.tenencia.accionistas, 1):
        tp = "P. Moral" if acc.tipo_persona and acc.tipo_persona.lower() == "moral" else "P. Física"
        ext = "SÍ" if acc.es_extranjero else "NO"
        lines.append(f"  │ {i:<4} │ {acc.nombre:<36s} │ {acc.porcentaje:>6.1f}%    │ {tp:<8s} │ {ext:<12s} │")
    lines.append("  └──────┴──────────────────────────────────────┴────────────┴──────────┴──────────────┘")
    lines.append("")
    lines.append(f"  Accionistas extranjeros:    {_sn(d.tenencia.hay_extranjeros)}")

    # ──── 7. RÉGIMEN DE ADMINISTRACIÓN
    lines.append("")
    lines.append(_sec("7", "RÉGIMEN DE ADMINISTRACIÓN"))
    lines.append("")
    if d.administracion.tipo == "consejo_administracion":
        tipo_adm = "Consejo de Administración"
    elif d.administracion.tipo == "administrador_unico":
        tipo_adm = "Administrador Único"
    else:
        tipo_adm = "No identificado"
    lines.append(f"  Tipo: {tipo_adm}")
    if d.administracion.miembros:
        for m in d.administracion.miembros:
            lines.append(f"    - {m.nombre:<38s} {m.cargo or ''}")
    else:
        lines.append("  No se identificaron administradores/consejeros.")

    # ──── 8. APODERADOS / REPRESENTANTES LEGALES ──────
    lines.append("")
    lines.append(_sec("8", "APODERADOS / REPRESENTANTES LEGALES"))
    lines.append("")
    # Tabla resumen
    lines.append("  ┌──────┬────────────────────────────────────────────────┬────────────────────┐")
    lines.append("  │ #    │ Nombre                                         │ Nacionalidad       │")
    lines.append("  ├──────┼────────────────────────────────────────────────┼────────────────────┤")
    for i, ap in enumerate(d.apoderados, 1):
        nac_d = _v(ap.nacionalidad).capitalize() if ap.nacionalidad else na
        lines.append(f"  │ {i:<4} │ {_v(ap.nombre):<46s} │ {nac_d:<18s} │")
    lines.append("  └──────┴────────────────────────────────────────────────┴────────────────────┘")

    # Detalle por apoderado
    for idx, ap in enumerate(d.apoderados, 1):
        lines.append("")
        if ap.poder_escritura_numero or ap.poderdante:
            lines.append(f"  Poder notarial (Apoderado {idx}):")
            lines.append(f"    Poderdante:      {_v(ap.poderdante)}")
            lines.append(f"    Tipo:            {_v(ap.tipo_poder_completo)}")
            lines.append(f"    Notario:         {_v(ap.poder_notario)} — Notaría {_v(ap.poder_notaria)}, {_v(ap.poder_estado)}")
            lines.append(f"    Escritura:       {_v(ap.poder_escritura_numero)}")
            lines.append(f"    Fecha:           {_v(ap.poder_fecha)}")
            lines.append("")

        lines.append(f"  Facultades (Apoderado {idx}):")
        lines.append(f"    Actos de Administración:       {_sn(ap.facultades.administracion)}")
        lines.append(f"    Actos de Dominio:              {_sn(ap.facultades.dominio)}")
        lines.append(f"    Títulos de Crédito:            {_sn(ap.facultades.titulos_credito)}")
        lines.append(f"    Apertura de Cuentas Bancarias: {_sn(ap.facultades.apertura_cuentas)}")
        lines.append(f"    Delegación / Sustitución:      {_sn(ap.facultades.delegacion_sustitucion)}")
        lines.append(f"    Especiales:                    {_v(ap.facultades.especiales)}")

        if ap.facultades.palabras_clave_encontradas:
            lines.append("    Palabras clave BPT detectadas:")
            for kw in ap.facultades.palabras_clave_encontradas:
                lines.append(f"      ✓ {kw}")

        lines.append(f"    Limitaciones:                  {_v(ap.limitaciones)}")
        lines.append(f"    Régimen de Firmas:             {_v(ap.regimen_firmas).capitalize()}")
        lines.append(f"    Vigencia:                      {_v(ap.vigencia)}")
        lines.append(f"    ¿Cuenta con FM3?:              {_sn(ap.cuenta_fm3)}")
        lines.append(f"    ¿Puede firmar contrato?:       {_sn(ap.puede_firmar_contrato)}")
        lines.append(f"    ¿Puede designar web banking?:  {_sn(ap.puede_designar_web_banking)}")

    # ──── 9. CONFIABILIDAD DE CAMPOS OCR ─────
    lines.append("")
    lines.append(_sec("9", "CONFIABILIDAD DE CAMPOS OCR"))
    lines.append("")
    cnf = d.confiabilidad
    if cnf.score_ocr is not None:
        lines.append(f"  Score OCR Global:    {cnf.score_ocr:.1f}%  ({cnf.campos_ocr_evaluados} campos evaluados)")
    else:
        lines.append("  Score OCR Global:    Sin datos de confiabilidad OCR")

    # Confiabilidad por campo
    campos_conf: list[tuple[str, str, float]] = []
    if documentos_ocr:
        for doc_type, doc_data in documentos_ocr.items():
            if not isinstance(doc_data, dict):
                continue
            for key, val in doc_data.items():
                if isinstance(val, dict) and "confiabilidad" in val:
                    try:
                        campos_conf.append((doc_type, key, float(val["confiabilidad"])))
                    except (TypeError, ValueError):
                        pass
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and "confiabilidad" in item:
                            try:
                                nombre_c = item.get("nombre", key)
                                campos_conf.append((doc_type, nombre_c, float(item["confiabilidad"])))
                            except (TypeError, ValueError):
                                pass

    if campos_conf:
        altos = [c for c in campos_conf if c[2] >= 90]
        medios_c = [c for c in campos_conf if 70 <= c[2] < 90]
        bajos = [c for c in campos_conf if c[2] < 70]

        lines.append("")
        lines.append(f"  ▸ Confiabilidad ≥ 90%:    {len(altos):>3} / {len(campos_conf)} campos")
        lines.append(f"  ▸ Confiabilidad 70-89%:   {len(medios_c):>3} / {len(campos_conf)} campos")
        lines.append(f"  ▸ Confiabilidad < 70%:    {len(bajos):>3} / {len(campos_conf)} campos")

        if bajos:
            lines.append("")
            lines.append("  Campos de baja confiabilidad (< 70%):")
            for doc, campo, score in sorted(bajos, key=lambda x: x[2]):
                lines.append(f"    - {doc}.{campo}: {score:.1f}%")

    lines.append("")
    lines.append(f"  Reglas:              {cnf.reglas_cumplidas}/{cnf.reglas_totales} cumplidas ({cnf.score_reglas:.1f}%)")
    lines.append(f"  Score Global:        {cnf.score_global:.1f}%  ({cnf.nivel})")
    lines.append(f"  Fuente:              {'LLM (GPT-4o) + motor de reglas' if cnf.usa_llm else 'Solo motor de reglas determinista'}")
    if not cnf.usa_llm:
        lines.append("  ⚠  El dictamen se generó sin análisis LLM.")

    # ════════════ CONCLUSIONES ════════════
    lines.append("")
    lines.append("═" * W)

    _ICONOS_DICTAMEN = {
        "FAVORABLE": "✅",
        "FAVORABLE_CON_CONDICIONES": "⚠️",
        "NO_FAVORABLE": "❌",
    }
    icono_dict = _ICONOS_DICTAMEN.get(d.dictamen_resultado or "", "")
    dictamen_display = (d.dictamen_resultado or na).replace("_", " ")

    if resultado_reglas:
        reglas = resultado_reglas.reglas
        total_pasan = sum(1 for r in reglas if r.cumple)
        total_criticos = sum(1 for r in reglas if not r.cumple and r.severidad == "CRITICA")
        total_medios_r = sum(1 for r in reglas if not r.cumple and r.severidad == "MEDIA")
        total_info = sum(1 for r in reglas if not r.cumple and r.severidad == "INFORMATIVA")

        lines.append(_sec("10", "CONCLUSIONES JURÍDICAS"))
        lines.append("")
        lines.append(f"  DICTAMEN:    {icono_dict} {dictamen_display}")
        lines.append(f"  FUNDAMENTO:  {_v(d.fundamento_legal)}")
        lines.append("")
        lines.append(f"  Validaciones que pasan (✅): {total_pasan}")
        lines.append(f"  Hallazgos Críticos  (🔴):     {total_criticos}")
        lines.append(f"  Hallazgos Medios    (🟡):     {total_medios_r}")
        lines.append(f"  Hallazgos Informativos (ℹ️):  {total_info}")

        # Detalle de reglas
        lines.append("")
        lines.append("─" * W)
        lines.append("  DETALLE DE REGLAS JURÍDICAS")
        lines.append("─" * W)
        lines.append("")

        _ICONOS_SEV = {"CRITICA": "🔴", "MEDIA": "🟡", "INFORMATIVA": "ℹ️"}
        for r in reglas:
            icono_p = "✅" if r.cumple else "❌"
            status = "CUMPLE" if r.cumple else "FALLA"
            sev = "" if r.cumple else f" {_ICONOS_SEV.get(r.severidad, '')}"
            lines.append(f"    {r.codigo} {r.nombre}: {icono_p} {status}{sev}")
            if r.detalle:
                lines.append(f"      {r.detalle}")
            if r.fuente_documento:
                lines.append(f"      Fuente: {r.fuente_documento}")
            lines.append("")

        # Alertas y riesgos
        criticos = [r for r in reglas if not r.cumple and r.severidad == "CRITICA"]
        medios_l = [r for r in reglas if not r.cumple and r.severidad == "MEDIA"]
        informativos = [r for r in reglas if not r.cumple and r.severidad == "INFORMATIVA"]

        lines.append("─" * W)
        lines.append("  ALERTAS Y RIESGOS")
        lines.append("─" * W)
        lines.append("")
        lines.append("  🔴 CRÍTICOS (requieren acción inmediata):")
        if criticos:
            for i, r in enumerate(criticos, 1):
                lines.append(f"    {i}. [{r.codigo}] {r.nombre} — {r.detalle}")
        else:
            lines.append("    Ninguno ✅")
        lines.append("")
        lines.append("  🟡 MEDIOS (requieren seguimiento):")
        if medios_l:
            for i, r in enumerate(medios_l, 1):
                lines.append(f"    {i}. [{r.codigo}] {r.nombre} — {r.detalle}")
        else:
            lines.append("    Ninguno ✅")
        lines.append("")
        lines.append("  ℹ️ INFORMATIVOS (para registro):")
        if informativos:
            for i, r in enumerate(informativos, 1):
                lines.append(f"    {i}. [{r.codigo}] {r.nombre} — {r.detalle}")
        else:
            lines.append("    Ninguno")

        # Observaciones
        if d.observaciones.observaciones:
            lines.append("")
            lines.append("─" * W)
            lines.append("  OBSERVACIONES ADICIONALES")
            lines.append("─" * W)
            lines.append("")
            for i, obs_t in enumerate(d.observaciones.observaciones, 1):
                lines.append(f"    {i}. {obs_t}")

        # Recomendaciones
        recomendaciones: list[str] = []
        for r in reglas:
            if not r.cumple:
                if r.severidad == "CRITICA":
                    recomendaciones.append(f"[URGENTE] Resolver {r.codigo} ({r.nombre}): {r.detalle}")
                elif r.severidad == "MEDIA":
                    recomendaciones.append(f"Subsanar {r.codigo} ({r.nombre}): {r.detalle}")

        lines.append("")
        lines.append("─" * W)
        lines.append("  RECOMENDACIONES")
        lines.append("─" * W)
        lines.append("")
        if recomendaciones:
            for i, rec in enumerate(recomendaciones, 1):
                lines.append(f"    {i}. {rec}")
        else:
            lines.append("    Sin recomendaciones adicionales.")

        # Siguiente paso
        lines.append("")
        lines.append("─" * W)
        lines.append("  SIGUIENTE PASO")
        lines.append("─" * W)
        lines.append("")
        if d.dictamen_resultado == "FAVORABLE":
            lines.append("    ✅ Dictamen jurídico favorable. Expediente listo para continuar.")
        elif d.dictamen_resultado == "FAVORABLE_CON_CONDICIONES":
            lines.append("    ⚠️ Dictamen favorable con condiciones.")
            lines.append("    Puntos a subsanar:")
            for r in medios_l:
                lines.append(f"      - {r.codigo}: {r.nombre}")
        else:
            lines.append("    ❌ Dictamen NO FAVORABLE.")
            lines.append("    Motivos principales:")
            for r in criticos:
                lines.append(f"      - {r.codigo}: {r.nombre}")

    # ──── PIE / ELABORACIÓN ──────
    lines.append("")
    lines.append("─" * W)
    lines.append("  ELABORÓ:")
    lines.append(f"    {_v(d.elaboracion.elaboro_nombre)}")
    lines.append(f"    Dictamen generado automáticamente por Agente Nevada — Dictamen Legal")
    lines.append("")
    lines.append(f"  Pipeline:  {_v(d.numero_dictamen)}-{_v(d.rfc)}")
    lines.append(f"  Versión:   1.1.0")
    lines.append(f"  Fuentes:   Dakota")
    lines.append(f"  Fecha:     {_v(d.elaboracion.elaboro_fecha)}")
    lines.append("")
    lines.append("═" * W)
    lines.append(f"{'FIN DEL DICTAMEN LEGAL':^{W}}")
    lines.append("═" * W)

    return "\n".join(lines)
