"""
Pipeline Service — Orquestación Dakota → Colorado → Arizona → Nevada.

Flujo Dakota (sin PagaTodo Hub):
  1. Recibe archivos (PDF/imagen) desde el router.
  2. Envía cada archivo a Dakota para OCR + persistencia en PostgreSQL.
  3. Dakota retorna datos_extraidos + empresa_id.
  4. Colorado valida cruzado → Arizona PLD → Compliance → Nevada dictamen.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .clients import (
    arizona_pld_analyze,
    colorado_validate,
    compliance_dictamen,
    dakota_get_empresa,
    dakota_upload_document,
    nevada_dictamen_legal,
)
from .persistence import (
    actualizar_arizona,
    actualizar_colorado,
    actualizar_dakota,
    actualizar_nevada,
    finalizar_pipeline,
    iniciar_pipeline,
)

logger = logging.getLogger("orquestrator.pipeline")


async def procesar_documento(
    doc_type: str,
    file_content: bytes,
    file_name: str,
    rfc: str,
) -> dict[str, Any]:
    """
    Flujo completo para UN documento vía Dakota.

    1. Envía el archivo a Dakota para OCR + persistencia.
    2. Colorado valida cruzado.
    3. Arizona PLD.
    4. Compliance dictamen PLD/FT.
    5. Nevada dictamen jurídico.

    Args:
        doc_type: Tipo de documento (csf, ine, acta_constitutiva, etc.)
        file_content: Contenido del archivo en bytes.
        file_name: Nombre del archivo original.
        rfc: RFC de la empresa.

    Returns:
        dict con extraccion, persistencia, validacion_cruzada, tiempos, etc.
    """
    rfc = rfc.strip().upper()
    started = datetime.now()
    tiempos: dict[str, int] = {}
    resultado: dict[str, Any] = {
        "rfc": rfc,
        "tipo_documento": doc_type,
        "archivo": file_name,
        "extraccion": None,
        "persistencia": None,
        "validacion_cruzada": None,
        "analisis_pld": None,
        "dictamen_pld": None,
        "dictamen_legal": None,
        "tiempos": tiempos,
    }

    # ── PASO 1: Dakota → OCR + Persistencia ───────────────────────────
    t0 = datetime.now()
    logger.info(
        "[PIPELINE-DK] Enviando a Dakota: doc=%s, file=%s, rfc=%s",
        doc_type, file_name, rfc,
    )

    dakota_result = await dakota_upload_document(
        doc_type=doc_type,
        file_content=file_content,
        file_name=file_name,
        rfc=rfc,
        skip_colorado=True,  # El Orquestrador controla Colorado
    )
    tiempos["dakota_ocr_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

    if dakota_result is None:
        resultado["extraccion"] = {
            "error": f"Dakota no retornó resultado para {doc_type}",
            "sugerencia": "Verificar que Dakota esté activo en puerto 8010",
        }
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return resultado

    resultado["extraccion"] = dakota_result

    # Obtener empresa_id de la respuesta de Dakota o por consulta
    empresa_id = (dakota_result.get("persistencia") or {}).get("empresa_id")
    razon_social = ""

    if not empresa_id:
        # Buscar por RFC en Dakota
        empresa_data = await dakota_get_empresa(rfc)
        if empresa_data:
            empresa_id = str(empresa_data.get("id", ""))
            razon_social = empresa_data.get("razon_social", "")

    if not empresa_id:
        resultado["persistencia"] = {
            "guardado": False,
            "error": "No se pudo determinar empresa_id desde Dakota",
        }
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return resultado

    # Extraer razón social del resultado OCR si es CSF
    if not razon_social:
        datos_ext = dakota_result.get("datos_extraidos", {})
        if isinstance(datos_ext, dict):
            rs_field = datos_ext.get("razon_social")
            if isinstance(rs_field, dict):
                razon_social = rs_field.get("valor", "")
            elif isinstance(rs_field, str):
                razon_social = rs_field

    resultado["persistencia"] = {
        "guardado": True,
        "empresa_id": empresa_id,
        "persistido_por": "Dakota",
    }

    # Registrar pipeline en BD
    try:
        await iniciar_pipeline(empresa_id, rfc, razon_social or rfc)
        await actualizar_dakota(
            empresa_id, status="COMPLETADO",
            documentos_extraidos=1, tipos_documentos=[doc_type],
        )
    except Exception as e:
        logger.warning("[PIPELINE-DK] No se pudo registrar en pipeline_resultados: %s", e)

    # ── PASO 2: Colorado → validación cruzada ─────────────────────────
    t0 = datetime.now()
    logger.info("[PIPELINE-DK] Llamando a Colorado para empresa %s...", empresa_id)

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
            logger.warning("[PIPELINE-DK] Error actualizando Colorado en BD: %s", e)
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
        logger.warning("[PIPELINE-DK] Colorado RECHAZÓ la empresa %s — deteniendo pipeline", empresa_id)
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
    logger.info("[PIPELINE-DK] Flujo completo para %s en %dms", rfc, tiempos["total_ms"])

    try:
        await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
    except Exception:
        pass

    return resultado


async def procesar_expediente(
    rfc: str,
    archivos: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Flujo completo para un expediente multi-documento vía Dakota.

    1. Envía cada archivo a Dakota para OCR + persistencia.
    2. Colorado valida cruzado (una sola vez).
    3. Arizona PLD → Compliance → Nevada.

    Args:
        rfc: RFC de la empresa.
        archivos: Lista de dicts con:
            - doc_type: Tipo de documento.
            - file_content: bytes del archivo.
            - file_name: Nombre del archivo.
    """
    rfc = rfc.strip().upper()
    started = datetime.now()
    tiempos: dict[str, int] = {}
    docs_procesados: list[dict] = []
    empresa_id: str | None = None
    razon_social: str = ""

    # ── PASO 1: Loop de documentos → Dakota ───────────────────────────
    for archivo in archivos:
        doc_type = archivo["doc_type"]
        file_content = archivo["file_content"]
        file_name = archivo["file_name"]

        t0 = datetime.now()
        logger.info(
            "[PIPELINE-DK] Enviando a Dakota: doc=%s, file=%s, rfc=%s",
            doc_type, file_name, rfc,
        )

        dakota_result = await dakota_upload_document(
            doc_type=doc_type,
            file_content=file_content,
            file_name=file_name,
            rfc=rfc,
            skip_colorado=True,
        )

        ms = int((datetime.now() - t0).total_seconds() * 1000)

        if dakota_result is None:
            docs_procesados.append({
                "tipo_documento": doc_type,
                "archivo": file_name,
                "status": "error",
                "error": f"Dakota no retornó resultado para {doc_type}",
                "tiempo_ms": ms,
            })
            continue

        # Obtener empresa_id de la primera respuesta exitosa
        if not empresa_id:
            empresa_id = (dakota_result.get("persistencia") or {}).get("empresa_id")

        # Extraer razón social del CSF
        if doc_type == "csf" and not razon_social:
            datos_ext = dakota_result.get("datos_extraidos", {})
            if isinstance(datos_ext, dict):
                rs_field = datos_ext.get("razon_social")
                if isinstance(rs_field, dict):
                    razon_social = rs_field.get("valor", "")
                elif isinstance(rs_field, str):
                    razon_social = rs_field

        docs_procesados.append({
            "tipo_documento": doc_type,
            "archivo": file_name,
            "status": "ok",
            "tiempo_ms": ms,
        })

    tiempos["extraccion_total_ms"] = int((datetime.now() - started).total_seconds() * 1000)

    # Si no obtuvimos empresa_id de las respuestas, buscar por RFC
    if not empresa_id:
        empresa_data = await dakota_get_empresa(rfc)
        if empresa_data:
            empresa_id = str(empresa_data.get("id", ""))
            razon_social = razon_social or empresa_data.get("razon_social", "")

    if not empresa_id:
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "rfc": rfc,
            "error": "No se pudo determinar empresa_id. Verificar que Dakota persistió correctamente.",
            "documentos": docs_procesados,
            "tiempos": tiempos,
        }

    # Registrar pipeline en BD
    try:
        await iniciar_pipeline(empresa_id, rfc, razon_social or rfc)
        tipos = [d["tipo_documento"] for d in docs_procesados if d["status"] == "ok"]
        await actualizar_dakota(
            empresa_id, status="COMPLETADO",
            documentos_extraidos=sum(1 for d in docs_procesados if d["status"] == "ok"),
            tipos_documentos=tipos,
        )
    except Exception as e:
        logger.warning("[PIPELINE-DK] Error registrando en pipeline_resultados: %s", e)

    # ── PASO 2: Colorado (una sola vez) ───────────────────────────────
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
        logger.warning("[PIPELINE-DK] Colorado RECHAZÓ empresa %s — deteniendo", empresa_id)
        tiempos["total_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        try:
            await finalizar_pipeline(empresa_id, tiempos_ms=tiempos)
        except Exception:
            pass
        return {
            "rfc": rfc,
            "empresa_id": empresa_id,
            "documentos_procesados": len(docs_procesados),
            "documentos_exitosos": sum(1 for d in docs_procesados if d["status"] == "ok"),
            "documentos": docs_procesados,
            "validacion_cruzada": validacion_cruzada,
            "analisis_pld": None,
            "dictamen_pld": None,
            "dictamen_legal": None,
            "pipeline_detenido": True,
            "motivo_detencion": "Dictamen Colorado: RECHAZADO",
            "tiempos": tiempos,
        }

    # ── PASO 3: Arizona PLD ───────────────────────────────────────────
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

    # ── PASO 4: Compliance ────────────────────────────────────────────
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

    # ── PASO 5: Nevada → dictamen jurídico ────────────────────────────
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
        "empresa_id": empresa_id,
        "documentos_procesados": len(docs_procesados),
        "documentos_exitosos": sum(1 for d in docs_procesados if d["status"] == "ok"),
        "documentos": docs_procesados,
        "validacion_cruzada": validacion_cruzada,
        "analisis_pld": analisis_pld,
        "dictamen_pld": dictamen_pld,
        "dictamen_legal": dictamen_legal,
        "tiempos": tiempos,
    }
