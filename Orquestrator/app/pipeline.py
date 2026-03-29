"""
Pipeline Service — Orquestación PagaTodo Hub → PostgreSQL → Colorado → Arizona → Nevada.

Dos fuentes de datos complementarias:
  - ``/prospects/data/`` — registro manual del cliente (datos declarados).
  - ``POST /ocr``        — extracción automática de documentos (OCR).

Ambas se persisten directamente en PostgreSQL (tablas empresas/documentos)
y alimentan el pipeline para dar un veredicto final.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .clients import (
    arizona_pld_analyze,
    colorado_validate,
    compliance_dictamen,
    nevada_dictamen_legal,
    pagatodo_ocr_result,
    pagatodo_prospect_data,
    transformar_datos_prospecto,
)
from .config import PAGATODO_DOCTYPE_MAP
from .persistence import (
    actualizar_arizona,
    actualizar_colorado,
    actualizar_dakota,
    actualizar_nevada,
    finalizar_pipeline,
    get_or_create_empresa,
    iniciar_pipeline,
    persist_documento,
)

logger = logging.getLogger("orquestrator.pipeline")


async def procesar_documento(
    prospect_id: str,
    document_type: str,
    rfc: str,
) -> dict[str, Any]:
    """
    Flujo completo para UN documento vía PagaTodo Hub.

    Obtiene DOS fuentes complementarias:
      - ``/prospects/data/``  → datos de registro manual del cliente
      - ``POST /ocr``         → extracción automática del documento

    Después: Persistencia directa en BD → Colorado → Arizona → Compliance → Nevada.

    Args:
        prospect_id: UUID del prospecto en PagaTodo Hub.
        document_type: Tipo de documento externo (e.g. "ActaCons", "Csf").
        rfc: RFC de la empresa.

    Returns:
        dict con datos_prospecto, extraccion, persistencia, validacion_cruzada, tiempos, etc.
    """
    rfc = rfc.strip().upper()
    started = datetime.now()
    tiempos: dict[str, int] = {}
    resultado: dict[str, Any] = {
        "rfc": rfc,
        "prospect_id": prospect_id,
        "document_type_externo": document_type,
        "datos_prospecto": None,
        "extraccion": None,
        "persistencia": None,
        "validacion_cruzada": None,
        "analisis_pld": None,
        "dictamen_pld": None,
        "dictamen_legal": None,
        "tiempos": tiempos,
    }

    # ── PASO 0: Datos del prospecto (registro manual) ────────────────────
    t0 = datetime.now()
    logger.info(
        "[PIPELINE-PT] Obteniendo datos del prospecto: prospect=%s",
        prospect_id,
    )
    raw_prospect = await pagatodo_prospect_data(prospect_id)
    tiempos["prospect_data_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    datos_prospecto = None
    if raw_prospect:
        datos_prospecto = transformar_datos_prospecto(raw_prospect)
        resultado["datos_prospecto"] = datos_prospecto
        logger.info(
            "[PIPELINE-PT] Datos del prospecto obtenidos: %s (%s)",
            datos_prospecto.get("persona_moral", {}).get("razon_social", "?"),
            datos_prospecto.get("persona_moral", {}).get("rfc", "?"),
        )
    else:
        logger.warning(
            "[PIPELINE-PT] Sin datos de registro manual para prospect %s — continuando con OCR",
            prospect_id,
        )

    # ── PASO 1a: PagaTodo Hub → obtener OCR ──────────────────────────────
    t0 = datetime.now()
    logger.info(
        "[PIPELINE-PT] Obteniendo OCR de PagaTodo: prospect=%s, type=%s",
        prospect_id, document_type,
    )

    ocr_data, doc_type_interno = await pagatodo_ocr_result(prospect_id, document_type)
    tiempos["pagatodo_ocr_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    if ocr_data is None or doc_type_interno is None:
        resultado["extraccion"] = {
            "error": f"PagaTodo no retornó OCR para {document_type}",
            "sugerencia": "Verificar prospect_id y DocumentType en PagaTodo Hub",
        }
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return resultado

    resultado["tipo_documento"] = doc_type_interno
    resultado["extraccion"] = ocr_data

    # ── PASO 1b: Persistir directamente en PostgreSQL ─────────────────────
    t0 = datetime.now()
    logger.info("[PIPELINE-PT] Persistiendo en BD: rfc=%s, doc=%s", rfc, doc_type_interno)

    try:
        # Determinar razón social (priorizar OCR CSF, fallback a datos manuales)
        razon_social = ""
        datos_ext = ocr_data.get("datos_extraidos", ocr_data)
        if isinstance(datos_ext, dict):
            rs_field = datos_ext.get("razon_social")
            if isinstance(rs_field, dict):
                razon_social = rs_field.get("valor", "")
            elif isinstance(rs_field, str):
                razon_social = rs_field
        if not razon_social and datos_prospecto:
            razon_social = datos_prospecto.get("persona_moral", {}).get("razon_social", "")

        empresa_id = await get_or_create_empresa(rfc, razon_social)

        # Persistir el documento OCR
        doc_id = await persist_documento(
            empresa_id, doc_type_interno,
            f"pagatodo_{prospect_id}_{document_type}",
            datos_ext,
        )

        # Persistir datos manuales como doc_type "formulario_manual"
        if raw_prospect:
            await persist_documento(
                empresa_id, "formulario_manual",
                f"pagatodo_manual_{prospect_id}",
                raw_prospect,
            )

        resultado["persistencia"] = {
            "guardado": True,
            "empresa_id": empresa_id,
            "documento_id": doc_id,
        }
    except Exception as e:
        logger.error("[PIPELINE-PT] Error persistiendo en BD: %s", e)
        resultado["persistencia"] = {"guardado": False, "error": str(e)}
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return resultado

    tiempos["persist_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    # Registrar pipeline en BD
    try:
        await iniciar_pipeline(empresa_id, rfc, razon_social or rfc)
        await actualizar_dakota(
            empresa_id, status="COMPLETADO",
            documentos_extraidos=1, tipos_documentos=[doc_type_interno],
        )
    except Exception as e:
        logger.warning("[PIPELINE-PT] No se pudo registrar en pipeline_resultados: %s", e)

    # ── PASO 2: Colorado → validación cruzada ─────────────────────────────
    t0 = datetime.now()
    logger.info("[PIPELINE-PT] Llamando a Colorado para empresa %s...", empresa_id)

    validacion = await colorado_validate(empresa_id)
    tiempos["validacion_cruzada_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    if validacion:
        resultado["validacion_cruzada"] = {
            "dictamen": validacion.get("dictamen"),
            "rfc": validacion.get("rfc"),
            "total_hallazgos": len(validacion.get("hallazgos", [])),
            "criticos": validacion.get("criticos", 0),
            "pasan": validacion.get("pasan", 0),
            "no_aplica": validacion.get("no_aplica", 0),
            "portales_ejecutados": validacion.get("portales_ejecutados", False),
        }
        try:
            await actualizar_colorado(
                empresa_id, status="COMPLETADO",
                dictamen=validacion.get("dictamen"),
                hallazgos=len(validacion.get("hallazgos", [])),
                criticos=validacion.get("criticos", 0),
            )
        except Exception as e:
            logger.warning("[PIPELINE-PT] Error actualizando Colorado en BD: %s", e)
    else:
        resultado["validacion_cruzada"] = {
            "error": "Colorado no disponible o no retornó resultado",
        }
        try:
            await actualizar_colorado(empresa_id, status="ERROR")
        except Exception:
            pass

    # ── Si Colorado RECHAZÓ, detener el pipeline ─────────────────────
    dictamen_colorado = (validacion or {}).get("dictamen") if validacion else None
    if dictamen_colorado == "RECHAZADO":
        logger.warning("[PIPELINE-PT] Colorado RECHAZÓ la empresa %s — deteniendo pipeline", empresa_id)
        resultado["pipeline_detenido"] = True
        resultado["motivo_detencion"] = "Dictamen Colorado: RECHAZADO — no se ejecutarán etapas posteriores"
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        try:
            await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
        except Exception:
            pass
        return resultado

    # ── PASO 3: Arizona → análisis PLD ─────────────────────────────────
    t0 = datetime.now()
    pld_result = await arizona_pld_analyze(empresa_id)
    tiempos["analisis_pld_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if pld_result:
        resultado["analisis_pld"] = {
            "resultado": pld_result.get("resultado"),
            "porcentaje_completitud": pld_result.get("porcentaje_completitud"),
        }
        try:
            await actualizar_arizona(
                empresa_id, status="COMPLETADO",
                resultado=pld_result.get("resultado"),
                completitud_pct=pld_result.get("porcentaje_completitud"),
            )
        except Exception:
            pass

    # ── PASO 4: Compliance → dictamen PLD/FT ──────────────────────────
    t0 = datetime.now()
    dictamen_result = await compliance_dictamen(empresa_id)
    tiempos["dictamen_pld_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if dictamen_result:
        score = dictamen_result.get("score", {})
        resultado["dictamen_pld"] = {
            "dictamen": dictamen_result.get("dictamen"),
            "riesgo_residual": score.get("riesgo_residual"),
            "nivel_residual": score.get("nivel_residual"),
        }
        try:
            await actualizar_nevada(
                empresa_id, status="COMPLETADO",
                dictamen=dictamen_result.get("dictamen"),
                nivel_riesgo=score.get("nivel_residual"),
                riesgo_residual=score.get("riesgo_residual"),
            )
        except Exception:
            pass

    # ── PASO 5: Nevada → dictamen jurídico ────────────────────────────
    t0 = datetime.now()
    legal_result = await nevada_dictamen_legal(empresa_id)
    tiempos["dictamen_legal_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if legal_result:
        resultado["dictamen_legal"] = {
            "dictamen": legal_result.get("dictamen"),
            "fundamento_legal": legal_result.get("fundamento_legal"),
        }

    tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
    logger.info("[PIPELINE-PT] Flujo completo para %s en %dms", rfc, tiempos["total_ms"])

    try:
        await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
    except Exception:
        pass

    return resultado


async def procesar_expediente(
    prospect_id: str,
    rfc: str,
    document_types: list[str],
) -> dict[str, Any]:
    """
    Flujo completo para un expediente multi-documento vía PagaTodo Hub.

    Obtiene DOS fuentes complementarias:
      0. ``/prospects/data/``  → datos de registro manual del cliente (una vez)
      1. ``POST /ocr``         → extracción OCR por cada documento

    Después persiste directamente en PostgreSQL y ejecuta:
      2. Colorado (una sola vez)
      3. Arizona PLD → Compliance → Nevada

    Args:
        prospect_id: UUID del prospecto en PagaTodo Hub.
        rfc: RFC de la empresa.
        document_types: Lista de tipos de documento externos (e.g. ["ActaCons", "Csf", ...]).
    """
    rfc = rfc.strip().upper()
    started = datetime.now()
    tiempos: dict[str, int] = {}
    docs_procesados: list[dict] = []
    empresa_id: str | None = None
    datos_prospecto: dict[str, Any] | None = None

    # ── PASO 0: Obtener datos del prospecto (registro manual) ─────────
    t0 = datetime.now()
    logger.info(
        "[PIPELINE-PT] Obteniendo datos del prospecto: prospect=%s",
        prospect_id,
    )
    raw_prospect = await pagatodo_prospect_data(prospect_id)
    tiempos["prospect_data_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    if raw_prospect:
        datos_prospecto = transformar_datos_prospecto(raw_prospect)
        logger.info(
            "[PIPELINE-PT] Datos del prospecto obtenidos: %s (%s)",
            datos_prospecto.get("persona_moral", {}).get("razon_social", "?"),
            datos_prospecto.get("persona_moral", {}).get("rfc", "?"),
        )
    else:
        logger.warning(
            "[PIPELINE-PT] Sin datos de registro manual para prospect %s — continuando con OCR",
            prospect_id,
        )

    # ── PASO 1: Crear empresa + Loop de documentos OCR ────────────────
    # Primero crear/obtener la empresa para poder persistir documentos
    razon_social = ""
    if datos_prospecto:
        razon_social = datos_prospecto.get("persona_moral", {}).get("razon_social", "")

    try:
        empresa_id = await get_or_create_empresa(rfc, razon_social)
    except Exception as e:
        logger.error("[PIPELINE-PT] Error creando empresa: %s", e)
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "rfc": rfc,
            "prospect_id": prospect_id,
            "error": f"No se pudo crear empresa en BD: {e}",
            "tiempos": tiempos,
        }

    # Persistir datos manuales como formulario_manual
    if raw_prospect:
        try:
            await persist_documento(
                empresa_id, "formulario_manual",
                f"pagatodo_manual_{prospect_id}",
                raw_prospect,
            )
        except Exception as e:
            logger.warning("[PIPELINE-PT] Error persistiendo formulario manual: %s", e)

    for document_type in document_types:
        t0 = datetime.now()
        logger.info(
            "[PIPELINE-PT] Obteniendo OCR: prospect=%s, type=%s",
            prospect_id, document_type,
        )

        # 1a. PagaTodo OCR
        ocr_data, doc_type_interno = await pagatodo_ocr_result(prospect_id, document_type)
        if ocr_data is None or doc_type_interno is None:
            docs_procesados.append({
                "tipo_externo": document_type,
                "tipo_interno": doc_type_interno,
                "status": "error",
                "error": f"PagaTodo no retornó OCR para {document_type}",
                "tiempo_ms": int((datetime.now() - t0).total_seconds() * 1000),
            })
            continue

        # 1b. Persistir directamente en PostgreSQL
        datos_ext = ocr_data.get("datos_extraidos", ocr_data)

        # Actualizar razón social si viene del CSF
        if doc_type_interno == "csf" and isinstance(datos_ext, dict):
            rs_field = datos_ext.get("razon_social")
            if isinstance(rs_field, dict) and rs_field.get("valor"):
                await get_or_create_empresa(rfc, rs_field["valor"])

        try:
            doc_id = await persist_documento(
                empresa_id, doc_type_interno,
                f"pagatodo_{prospect_id}_{document_type}",
                datos_ext,
            )
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            docs_procesados.append({
                "tipo_externo": document_type,
                "tipo_interno": doc_type_interno,
                "status": "ok",
                "documento_id": doc_id,
                "tiempo_ms": ms,
            })
        except Exception as e:
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            logger.error("[PIPELINE-PT] Error persistiendo %s: %s", doc_type_interno, e)
            docs_procesados.append({
                "tipo_externo": document_type,
                "tipo_interno": doc_type_interno,
                "status": "error",
                "error": str(e),
                "tiempo_ms": ms,
            })

    tiempos["extraccion_total_ms"] = int((datetime.now() - started).total_seconds() * 1000)

    # Registrar pipeline en BD
    try:
        await iniciar_pipeline(empresa_id, rfc, razon_social or rfc)
        tipos = [d["tipo_interno"] for d in docs_procesados if d["status"] == "ok"]
        await actualizar_dakota(
            empresa_id, status="COMPLETADO",
            documentos_extraidos=sum(1 for d in docs_procesados if d["status"] == "ok"),
            tipos_documentos=tipos,
        )
    except Exception as e:
        logger.warning("[PIPELINE-PT] Error registrando en pipeline_resultados: %s", e)

    # ── Colorado (una sola vez) ───────────────────────────────────────
    validacion_cruzada = None
    t0 = datetime.now()
    validacion = await colorado_validate(empresa_id)
    tiempos["validacion_cruzada_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if validacion:
        validacion_cruzada = {
            "dictamen": validacion.get("dictamen"),
            "total_hallazgos": len(validacion.get("hallazgos", [])),
            "criticos": validacion.get("criticos", 0),
            "pasan": validacion.get("pasan", 0),
            "portales_ejecutados": validacion.get("portales_ejecutados", False),
        }
        try:
            await actualizar_colorado(
                empresa_id, status="COMPLETADO",
                dictamen=validacion.get("dictamen"),
                hallazgos=len(validacion.get("hallazgos", [])),
                criticos=validacion.get("criticos", 0),
            )
        except Exception:
            pass

    # ── Si Colorado RECHAZÓ, detener ──────────────────────────────────
    dictamen_colorado = (validacion_cruzada or {}).get("dictamen")
    if dictamen_colorado == "RECHAZADO":
        logger.warning("[PIPELINE-PT] Colorado RECHAZÓ empresa %s — deteniendo", empresa_id)
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        try:
            await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
        except Exception:
            pass
        return {
            "rfc": rfc,
            "prospect_id": prospect_id,
            "datos_prospecto": datos_prospecto,
            "documentos_procesados": len(docs_procesados),
            "documentos_exitosos": sum(1 for d in docs_procesados if d["status"] == "ok"),
            "documentos": docs_procesados,
            "validacion_cruzada": validacion_cruzada,
            "analisis_pld": None,
            "dictamen_pld": None,
            "pipeline_detenido": True,
            "motivo_detencion": "Dictamen Colorado: RECHAZADO",
            "tiempos": tiempos,
        }

    # ── Arizona PLD ───────────────────────────────────────────────────
    analisis_pld = None
    t0 = datetime.now()
    pld_result = await arizona_pld_analyze(empresa_id)
    tiempos["analisis_pld_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if pld_result:
        analisis_pld = {
            "resultado": pld_result.get("resultado"),
            "porcentaje_completitud": pld_result.get("porcentaje_completitud"),
        }
        try:
            await actualizar_arizona(
                empresa_id, status="COMPLETADO",
                resultado=pld_result.get("resultado"),
                completitud_pct=pld_result.get("porcentaje_completitud"),
            )
        except Exception:
            pass

    # ── Compliance ────────────────────────────────────────────────────
    dictamen_pld = None
    t0 = datetime.now()
    dictamen_result = await compliance_dictamen(empresa_id)
    tiempos["dictamen_pld_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if dictamen_result:
        score = dictamen_result.get("score", {})
        dictamen_pld = {
            "dictamen": dictamen_result.get("dictamen"),
            "riesgo_residual": score.get("riesgo_residual"),
            "nivel_residual": score.get("nivel_residual"),
        }
        try:
            await actualizar_nevada(
                empresa_id, status="COMPLETADO",
                dictamen=dictamen_result.get("dictamen"),
                nivel_riesgo=score.get("nivel_residual"),
                riesgo_residual=score.get("riesgo_residual"),
            )
        except Exception:
            pass

    # ── Nevada → dictamen jurídico ────────────────────────────────────
    dictamen_legal = None
    t0 = datetime.now()
    legal_result = await nevada_dictamen_legal(empresa_id)
    tiempos["dictamen_legal_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
    if legal_result:
        dictamen_legal = {
            "dictamen": legal_result.get("dictamen"),
            "fundamento_legal": legal_result.get("fundamento_legal"),
        }

    tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)

    try:
        await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
    except Exception:
        pass

    return {
        "rfc": rfc,
        "prospect_id": prospect_id,
        "datos_prospecto": datos_prospecto,
        "documentos_procesados": len(docs_procesados),
        "documentos_exitosos": sum(1 for d in docs_procesados if d["status"] == "ok"),
        "documentos": docs_procesados,
        "validacion_cruzada": validacion_cruzada,
        "analisis_pld": analisis_pld,
        "dictamen_pld": dictamen_pld,
        "dictamen_legal": dictamen_legal,
        "tiempos": tiempos,
    }
