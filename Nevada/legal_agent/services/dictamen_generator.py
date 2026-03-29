"""
Generador de Dictamen Jurídico con Azure OpenAI GPT-4o.

Toma los datos del expediente (extraídos determinísticamente) y
las reglas evaluadas para generar la narrativa del dictamen jurídico
según el template DJ-1 de Banco PagaTodo.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from openai import AsyncAzureOpenAI

from ..core.config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
    KNOWLEDGE_DIR,
)
from ..models.schemas import (
    ConfiabilidadDictamen,
    DictamenJuridico,
    ElaboracionRevision,
    ExpedienteLegal,
    ObservacionesAdicionales,
    ResultadoReglas,
)
from .rules_engine import (
    extraer_actividad,
    extraer_administracion,
    extraer_apoderados,
    extraer_datos_constitucion,
    extraer_datos_ultimos_estatutos,
    extraer_tenencia,
)

logger = logging.getLogger("nevada.generator")


# ── Calcular confiabilidad ────────────────────────────────────────

def _calcular_confiabilidad(
    exp: ExpedienteLegal,
    resultado_reglas: ResultadoReglas,
    uso_llm: bool,
) -> ConfiabilidadDictamen:
    """
    Calcula la confiabilidad global del dictamen a partir de:
      * Promedio de los scores ``confiabilidad`` de los campos OCR (0-100).
      * Porcentaje de reglas cumplidas.
      * Si se usó LLM o solo motor determinista.
    """
    # ── 1. Confiabilidad OCR ──
    confiabilidades: list[float] = []
    for _doc_type, doc_data in exp.documentos.items():
        if not isinstance(doc_data, dict):
            continue
        for _key, val in doc_data.items():
            if isinstance(val, dict) and "confiabilidad" in val:
                try:
                    confiabilidades.append(float(val["confiabilidad"]))
                except (TypeError, ValueError):
                    pass
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and "confiabilidad" in item:
                        try:
                            confiabilidades.append(float(item["confiabilidad"]))
                        except (TypeError, ValueError):
                            pass

    score_ocr = (sum(confiabilidades) / len(confiabilidades)) if confiabilidades else 0.0

    # ── 2. Completitud de reglas ──
    total_reglas = len(resultado_reglas.reglas)
    cumplidas = sum(1 for r in resultado_reglas.reglas if r.cumple)
    score_reglas = (cumplidas / total_reglas * 100) if total_reglas else 0.0

    # ── 3. Score global ponderado ──
    #   50 % OCR  +  40 % reglas  +  10 % fuente análisis
    bonus_llm = 100.0 if uso_llm else 60.0
    if confiabilidades:
        score_global = score_ocr * 0.50 + score_reglas * 0.40 + bonus_llm * 0.10
    else:
        # Sin datos OCR, basar en reglas + fuente
        score_global = score_reglas * 0.80 + bonus_llm * 0.20

    score_global = round(min(score_global, 100.0), 1)

    if score_global >= 80:
        nivel = "ALTA"
    elif score_global >= 55:
        nivel = "MEDIA"
    else:
        nivel = "BAJA"

    partes: list[str] = []
    if confiabilidades:
        partes.append(f"OCR {score_ocr:.0f}% ({len(confiabilidades)} campos)")
    else:
        partes.append("Sin scores OCR disponibles")
    partes.append(f"Reglas {cumplidas}/{total_reglas}")
    partes.append(f"Fuente: {'LLM + reglas' if uso_llm else 'Solo reglas deterministas'}")

    return ConfiabilidadDictamen(
        score_global=score_global,
        nivel=nivel,
        score_ocr=round(score_ocr, 1) if confiabilidades else None,
        score_reglas=round(score_reglas, 1),
        campos_ocr_evaluados=len(confiabilidades),
        reglas_cumplidas=cumplidas,
        reglas_totales=total_reglas,
        usa_llm=uso_llm,
        detalle="; ".join(partes),
    )


# ── Cargar knowledge base ─────────────────────────────────────────

def _load_knowledge() -> str:
    """Carga las reglas del dictamen como contexto para el LLM."""
    reglas_path = KNOWLEDGE_DIR / "reglas_dictamen.md"
    if reglas_path.exists():
        return reglas_path.read_text(encoding="utf-8")
    return ""


SYSTEM_PROMPT = """\
Eres un abogado corporativo especialista en derecho bancario y mercantil \
mexicano. Tu trabajo es elaborar el Dictamen Jurídico (DJ-1) para el \
área legal de Banco PagaTodo, S.A., Institución de Banca Múltiple.

Tu rol es analizar la documentación legal de personas morales que aperturan \
cuentas bancarias y determinar si la documentación es suficiente y correcta.

REGLAS QUE DEBES SEGUIR:
{reglas}

INSTRUCCIONES DE RESPUESTA:
1. Responde SOLO con un JSON válido.
2. El JSON debe contener las secciones del dictamen DJ-1.
3. Para las observaciones, genera texto claro, profesional y jurídico.
4. Basa tu análisis EXCLUSIVAMENTE en los datos proporcionados.
5. No inventes datos que no estén en el expediente.
6. Si falta información, indícalo en las observaciones.
7. Determina el dictamen: FAVORABLE, FAVORABLE_CON_CONDICIONES, o NO_FAVORABLE.
8. Explica el fundamento legal de tu dictamen.
"""


def _build_user_prompt(
    exp: ExpedienteLegal,
    resultado_reglas: ResultadoReglas,
    constitucion: dict,
    ultimos_estatutos: dict,
    actividad: dict,
    tenencia: dict,
    administracion: dict,
    apoderados: list[dict],
) -> str:
    """Construye el prompt de usuario con los datos del expediente."""
    return f"""Elabora el Dictamen Jurídico DJ-1 para la siguiente empresa:

## Datos de la Empresa
- RFC: {exp.rfc}
- Razón Social: {exp.razon_social}
- Documentos disponibles: {', '.join(exp.tipos_documento)}

## Datos de Constitución (extraídos del acta constitutiva)
{json.dumps(constitucion, ensure_ascii=False, indent=2)}

## Últimos Estatutos Sociales
{json.dumps(ultimos_estatutos, ensure_ascii=False, indent=2)}

## Actividad / Giro
{json.dumps(actividad, ensure_ascii=False, indent=2)}

## Tenencia Accionaria
{json.dumps(tenencia, ensure_ascii=False, indent=2)}

## Régimen de Administración
{json.dumps(administracion, ensure_ascii=False, indent=2)}

## Apoderado(s)
{json.dumps(apoderados, ensure_ascii=False, indent=2)}

## Resultado de Validación de Reglas
{resultado_reglas.resumen}

Detalle de reglas:
{json.dumps([r.model_dump() for r in resultado_reglas.reglas], ensure_ascii=False, indent=2)}

## Validación Cruzada (Colorado)
{json.dumps(exp.validacion_cruzada, ensure_ascii=False, indent=2) if exp.validacion_cruzada else "No disponible"}

## Análisis PLD – Screening (Arizona)
{json.dumps(exp.analisis_pld, ensure_ascii=False, indent=2) if exp.analisis_pld else "No disponible"}

## Dictamen PLD (Arizona)
{json.dumps(exp.dictamen_pld, ensure_ascii=False, indent=2) if exp.dictamen_pld else "No disponible"}

NOTA IMPORTANTE: Las secciones de Constitución, Tenencia Accionaria, Apoderado(s) y Actividad son \
los datos AUTORITATIVOS porque fueron extraídos directamente de los documentos fuente (OCR). \
Los datos de Arizona (PLD) y Colorado (validación cruzada) son complementarios para la evaluación \
de riesgo y compliance. NO marques inconsistencias entre estas fuentes; prioriza siempre los datos OCR.

Responde con un JSON con esta estructura exacta:
{{
  "observaciones": ["obs1", "obs2", ...],
  "dictamen_resultado": "FAVORABLE | FAVORABLE_CON_CONDICIONES | NO_FAVORABLE",
  "fundamento_legal": "Texto con el fundamento jurídico del dictamen",
  "resumen_cambios_estatutos": "Resumen de los cambios detectados en los estatutos o null"
}}
"""


async def generar_dictamen(
    exp: ExpedienteLegal,
    resultado_reglas: ResultadoReglas,
) -> DictamenJuridico:
    """
    Genera el Dictamen Jurídico completo combinando:
    1. Datos extraídos determinísticamente (rules_engine)
    2. Análisis narrativo del LLM (observaciones, fundamento, dictamen)
    """
    # ── Paso 1: Extracción determinista ──
    constitucion = extraer_datos_constitucion(exp)
    ultimos_estatutos = extraer_datos_ultimos_estatutos(exp)
    actividad = extraer_actividad(exp)
    tenencia = extraer_tenencia(exp)
    administracion = extraer_administracion(exp)
    apoderados_list = extraer_apoderados(exp)

    # ── Paso 2: Llamar al LLM para narrativa ──
    llm_result = await _llamar_llm(
        exp, resultado_reglas,
        constitucion.model_dump(),
        ultimos_estatutos.model_dump(),
        actividad.model_dump(),
        tenencia.model_dump(),
        administracion.model_dump(),
        [a.model_dump() for a in apoderados_list],
    )

    uso_llm = llm_result.get("_uso_llm", False)

    # ── Paso 3: Calcular confiabilidad ──
    confiabilidad = _calcular_confiabilidad(exp, resultado_reglas, uso_llm)

    # ── Paso 4: Ensamblar dictamen ──
    # Extraer datos adicionales directamente de Dakota (BD independiente)
    acta = exp.documentos.get("acta_constitutiva", {})
    csf = exp.documentos.get("csf", {})
    from .rules_engine import _safe_str

    denom_acta = _safe_str(
        acta.get("denominacion_social") or acta.get("denominacion_razon_social") or acta.get("razon_social")
    )
    denom_csf = _safe_str(csf.get("razon_social") or csf.get("denominacion_razon_social"))

    import re as _re
    cambio_denom = False
    cambio_denom_det = None
    if denom_acta and denom_csf:
        norm_a = _re.sub(r"\s+", " ", denom_acta.upper())
        norm_c = _re.sub(r"\s+", " ", denom_csf.upper())
        if norm_a != norm_c:
            cambio_denom = True
            cambio_denom_det = f"Acta: '{denom_acta}' vs CSF: '{denom_csf}'"

    dictamen = DictamenJuridico(
        fecha=date.today().isoformat(),
        razon_social=exp.razon_social,
        rfc=exp.rfc,
        denominacion_acta=denom_acta or None,
        denominacion_csf=denom_csf or None,
        cambio_denominacion=cambio_denom,
        cambio_denominacion_detalle=cambio_denom_det,
        estatus_padron=_safe_str(csf.get("estatus_padron")) or None,
        giro_mercantil_csf=_safe_str(csf.get("giro_mercantil") or csf.get("actividad_economica")) or None,
        domicilio_fiscal=_safe_str(csf.get("domicilio_fiscal")) or None,
        capital_social=_safe_str(acta.get("capital_social")) or None,
        moneda_capital=_safe_str(acta.get("moneda_capital")) or None,
        clausula_extranjeros=_safe_str(acta.get("clausula_extranjeros")) or None,
        constitucion=constitucion,
        ultimos_estatutos=ultimos_estatutos,
        resumen_cambios_estatutos=llm_result.get("resumen_cambios_estatutos"),
        actividad=actividad,
        tenencia=tenencia,
        administracion=administracion,
        apoderados=apoderados_list,
        observaciones=ObservacionesAdicionales(
            observaciones=llm_result.get("observaciones", []),
        ),
        elaboracion=ElaboracionRevision(
            elaboro_fecha=date.today().isoformat(),
            elaboro_nombre="Nevada v1.1.0 — Agente IA Legal",
        ),
        confiabilidad=confiabilidad,
        dictamen_resultado=llm_result.get("dictamen_resultado", resultado_reglas.dictamen_sugerido),
        fundamento_legal=llm_result.get("fundamento_legal"),
    )

    logger.info(
        "[GENERATOR] Dictamen generado: %s → %s",
        exp.razon_social, dictamen.dictamen_resultado,
    )

    return dictamen


async def _llamar_llm(
    exp: ExpedienteLegal,
    resultado_reglas: ResultadoReglas,
    constitucion: dict,
    ultimos_estatutos: dict,
    actividad: dict,
    tenencia: dict,
    administracion: dict,
    apoderados: list[dict],
) -> dict[str, Any]:
    """Llama a Azure OpenAI GPT-4o para generar la narrativa."""
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_KEY:
        logger.warning("[GENERATOR] Azure OpenAI no configurado — usando dictamen sugerido por reglas")
        return {
            "observaciones": [
                "Dictamen generado sin análisis LLM (credenciales Azure OpenAI no configuradas).",
                f"Resultado basado en evaluación determinista de {len(resultado_reglas.reglas)} reglas.",
            ],
            "dictamen_resultado": resultado_reglas.dictamen_sugerido,
            "fundamento_legal": "Evaluación determinista basada en las Reglas de Elaboración de Dictamen de BPT.",
            "resumen_cambios_estatutos": None,
            "_uso_llm": False,
        }

    reglas_text = _load_knowledge()
    system = SYSTEM_PROMPT.format(reglas=reglas_text)
    user = _build_user_prompt(
        exp, resultado_reglas,
        constitucion, ultimos_estatutos, actividad,
        tenencia, administracion, apoderados,
    )

    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )

    try:
        response = await client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        result = json.loads(content)
        result["_uso_llm"] = True
        logger.info("[GENERATOR] LLM respondió exitosamente")
        return result

    except Exception as e:
        logger.error("[GENERATOR] Error llamando a Azure OpenAI: %s", e)
        return {
            "observaciones": [
                f"Error al generar análisis LLM: {e}",
                f"Resultado basado en evaluación determinista de {len(resultado_reglas.reglas)} reglas.",
            ],
            "dictamen_resultado": resultado_reglas.dictamen_sugerido,
            "fundamento_legal": "Evaluación determinista (LLM no disponible).",
            "resumen_cambios_estatutos": None,
            "_uso_llm": False,
        }
