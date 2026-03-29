# api/service/validation_wrapper.py
"""
Wrapper para integrar validación automática a los endpoints del API.
Agrega scores de confianza y métricas a las respuestas.
"""

import time
import re
from datetime import date, datetime
from typing import Dict, Any, Callable, Optional
from functools import wraps

from .validators import validate_extraction
from .metrics import log_validation, metrics
from .name_parser import procesar_nombres_documento

DATE_PATTERN = re.compile(r"^\d{2}[/-]\d{2}[/-]\d{4}$")
MISSING_PATTERNS = ["no se encontró", "no encontrado", "no disponible"]


def _parse_date_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        raw_lower = raw.lower()
        if not raw or raw_lower in ["n/a", "pendiente", "pendiente de inscripción"]:
            return "" if not raw else value
        if any(pat in raw_lower for pat in MISSING_PATTERNS):
            return ""
        if DATE_PATTERN.match(raw):
            normalized = raw.replace("-", "/")
            try:
                dia, mes, anio = normalized.split("/")
                return date(int(anio), int(mes), int(dia))
            except ValueError:
                return value
    return value


def _coerce_dates_in_data(data: Any) -> Any:
    if isinstance(data, dict):
        # Convertir valores directos
        if "valor" in data:
            data["valor"] = _parse_date_value(data["valor"])
        if "content" in data:
            data["content"] = _parse_date_value(data["content"])
        # Recursivo para estructuras anidadas
        for key, value in list(data.items()):
            if isinstance(value, (dict, list)):
                data[key] = _coerce_dates_in_data(value)
        return data
    if isinstance(data, list):
        return [_coerce_dates_in_data(item) for item in data]
    return _parse_date_value(data)


def normalize_dates_in_result(result: Dict[str, Any]) -> Dict[str, Any]:
    datos = result.get("datos_extraidos")
    if datos is not None:
        result["datos_extraidos"] = _coerce_dates_in_data(datos)
    if "validacion" in result and isinstance(result["validacion"], dict):
        campos = result["validacion"].get("campos")
        if isinstance(campos, dict):
            result["validacion"]["campos"] = _coerce_dates_in_data(campos)
    return result


def with_validation(doc_type: str):
    """
    Decorador que agrega validación automática a funciones de análisis.

    Args:
        doc_type: Tipo de documento (csf, fiel, domicilio, etc.)

    Returns:
        Decorador que wrappea la función

    Example:
        @with_validation("csf")
        def analyze_csf(file_path):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            error = None

            try:
                # Ejecutar función original
                result = func(*args, **kwargs)

                # Extraer datos para validación
                datos = result.get("datos_extraidos", result)
                texto_ocr = result.get("texto_ocr", "")
                file_name = result.get("archivo_procesado", "unknown")

                # Validar extracción
                validation = validate_extraction(datos, doc_type, texto_ocr)

                # Agregar validación al resultado
                result["validacion"] = {
                    "score_global": validation["score_global"],
                    "nivel_confianza": validation["nivel_confianza"],
                    "requiere_revision": validation["requiere_revision"],
                    "campos": validation["campos"],
                }

                # Normalizar fechas en la respuesta
                result = normalize_dates_in_result(result)

                processing_time = time.time() - start_time

                # Registrar métricas
                log_validation(
                    doc_type=doc_type,
                    file_name=file_name,
                    validation_result=validation,
                    processing_time=processing_time
                )

                return result

            except Exception as e:
                error = str(e)
                processing_time = time.time() - start_time

                # Registrar error
                log_validation(
                    doc_type=doc_type,
                    file_name=kwargs.get("file_path", "unknown"),
                    validation_result={"score_global": 0, "campos": {}, "requiere_revision": True},
                    processing_time=processing_time,
                    error=error
                )
                raise

        return wrapper
    return decorator


def add_validation_to_response(
    result: Dict[str, Any],
    doc_type: str,
    file_name: str = "unknown",
    processing_time: float = 0.0
) -> Dict[str, Any]:
    """
    Función helper para agregar validación a una respuesta existente.
    Útil cuando no se puede usar el decorador.

    Args:
        result: Respuesta original del análisis
        doc_type: Tipo de documento
        file_name: Nombre del archivo procesado
        processing_time: Tiempo de procesamiento

    Returns:
        Respuesta con validación agregada
    """
    datos = result.get("datos_extraidos", result)
    texto_ocr = result.get("texto_ocr", "")

    validation = validate_extraction(datos, doc_type, texto_ocr)

    # Calcular confiabilidad por campo desde múltiples fuentes
    confiabilidad_por_campo = {}

    # 1. Primero, usar confiabilidad calculada por OpenAI (si existe)
    confiabilidad_openai = datos.get("_confiabilidad_campos", {})
    for campo, score in confiabilidad_openai.items():
        confiabilidad_por_campo[campo] = round(score * 100, 1)

    # 2. Agregar confiabilidad de Azure DI (campos con estructura {content, confidence})
    for campo, valor in datos.items():
        if isinstance(valor, dict) and "confidence" in valor:
            confiabilidad_por_campo[campo] = round(valor["confidence"] * 100, 1)

    # 3. Complementar con confiabilidad del validador
    for campo, campo_val in validation.get("campos", {}).items():
        if campo not in confiabilidad_por_campo:
            if isinstance(campo_val, dict) and "confianza" in campo_val:
                # Manejar confianza None (campos opcionales que no aplican)
                conf = campo_val["confianza"]
                if conf is not None:
                    confiabilidad_por_campo[campo] = round(conf * 100, 1)

    # Calcular promedio de confiabilidad considerando OpenAI si está disponible
    confiabilidad_promedio_openai = datos.get("_confiabilidad_promedio")
    score_final = validation["score_global"]
    if confiabilidad_promedio_openai is not None:
        # Asegurar que sea float (puede venir como string del LLM)
        try:
            confiabilidad_promedio_openai = float(confiabilidad_promedio_openai)
        except (ValueError, TypeError):
            confiabilidad_promedio_openai = 0.0
        # Promediar el score del validador con el de OpenAI
        score_final = (validation["score_global"] + confiabilidad_promedio_openai) / 2

    # ═══════════════════════════════════════════════════════════════════════════════
    # TRANSFORMAR datos_extraidos PARA INCLUIR CONFIABILIDAD, PÁGINA Y PÁRRAFO
    # ═══════════════════════════════════════════════════════════════════════════════
    datos_con_confiabilidad = {}
    campos_internos = ["_evidencia_extraccion", "_confiabilidad_campos", "_confiabilidad_promedio", "campos_no_encontrados"]

    # Obtener evidencia de extracción para página y párrafo
    evidencia = datos.get("_evidencia_extraccion", {})

    for campo, valor in datos.items():
        # Saltar campos internos/metadata
        if campo in campos_internos:
            continue

        # Obtener página y párrafo de la evidencia
        ev = evidencia.get(campo, {})
        pagina = ev.get("pagina")
        parrafo = ev.get("parrafo")

        # Si ya tiene estructura {content, confidence} (Azure DI), mantenerla
        if isinstance(valor, dict) and "content" in valor:
            datos_con_confiabilidad[campo] = {
                "valor": _parse_date_value(valor.get("content")),
                "confiabilidad": round(valor.get("confidence", 0) * 100, 1),
                "pagina": pagina,
                "parrafo": parrafo
            }
        # Si es una lista, mantenerla como está
        elif isinstance(valor, list):
            datos_con_confiabilidad[campo] = {
                "valor": _parse_date_value(valor),
                "confiabilidad": confiabilidad_por_campo.get(campo, 0),
                "pagina": pagina,
                "parrafo": parrafo
            }
        # Para valores simples, agregar confiabilidad
        else:
            conf = confiabilidad_por_campo.get(campo)
            # Si no tenemos confiabilidad específica, calcular basado en si tiene valor
            if conf is None:
                if valor and str(valor).upper() not in ["", "N/A", "PENDIENTE"]:
                    conf = 100.0  # Valor presente = 100%
                else:
                    conf = 0.0

            datos_con_confiabilidad[campo] = {
                "valor": _parse_date_value(valor),
                "confiabilidad": conf,
                "pagina": pagina,
                "parrafo": parrafo
            }

    # Agregar campos_no_encontrados si existe
    if "campos_no_encontrados" in datos:
        datos_con_confiabilidad["campos_no_encontrados"] = datos["campos_no_encontrados"]

    # ═══════════════════════════════════════════════════════════════════════════════
    # PARSEAR NOMBRES COMPLETOS EN SUS COMPONENTES
    # ═══════════════════════════════════════════════════════════════════════════════
    nombres_parseados = procesar_nombres_documento(datos_con_confiabilidad, doc_type)

    # Agregar nombres parseados al resultado
    if nombres_parseados:
        datos_con_confiabilidad["_nombres_parseados"] = nombres_parseados

    # Actualizar datos_extraidos con la nueva estructura
    result["datos_extraidos"] = _coerce_dates_in_data(datos_con_confiabilidad)

    # Agregar confiabilidad prominente al nivel superior
    result["confiabilidad"] = {
        "porcentaje_global": round(score_final * 100, 1),
        "nivel": validation["nivel_confianza"],
        "requiere_revision_manual": validation["requiere_revision"],
    }

    # Mantener validación detallada para compatibilidad
    result["validacion"] = {
        "score_global": validation["score_global"],
        "nivel_confianza": validation["nivel_confianza"],
        "requiere_revision": validation["requiere_revision"],
        "campos": _coerce_dates_in_data(validation["campos"]),
    }

    # Registrar métricas
    log_validation(
        doc_type=doc_type,
        file_name=file_name,
        validation_result=validation,
        processing_time=processing_time
    )

    # ═══════════════════════════════════════════════════════════════════════════════
    # VALIDACIÓN KYB (Usando ValidatorAgent para consistencia con Orchestrator)
    # ═══════════════════════════════════════════════════════════════════════════════
    try:
        from api.service.validator import validator_agent
        
        # Obtener datos planos para validación KYB
        datos_planos = {}
        for campo, valor_info in datos_con_confiabilidad.items():
            if isinstance(valor_info, dict) and "valor" in valor_info:
                datos_planos[campo] = valor_info["valor"]
            else:
                datos_planos[campo] = valor_info
        
        # Incluir document_identification del DocumentIdentifierAgent si está disponible
        if "document_identification" in result:
            datos_planos["document_identification"] = result["document_identification"]
        
        # Incluir texto_ocr para validación de keywords
        if "texto_ocr" in result:
            datos_planos["texto_ocr"] = result["texto_ocr"]
        
        kyb_validation = validator_agent.validate_single_document(
            doc_type=doc_type,
            extracted_data=datos_planos
        )
        
        result["kyb_compliance"] = {
            "status": kyb_validation.status.value,
            "compliance_score": kyb_validation.compliance_score,
            "vigente": kyb_validation.vigente,
            "es_requerido": kyb_validation.es_requerido,
            "documento_tipo_correcto": kyb_validation.documento_tipo_correcto,
            "confianza_tipo": kyb_validation.confianza_tipo,
            "errores": kyb_validation.errores,
            "warnings": kyb_validation.warnings,
            "campos_validados": kyb_validation.campos_validados,
            "recomendaciones": kyb_validation.recomendaciones,
        }
        
        # Si fecha de vencimiento disponible, incluirla
        if kyb_validation.fecha_vencimiento:
            result["kyb_compliance"]["fecha_vencimiento"] = kyb_validation.fecha_vencimiento.isoformat()
        
        # ═══════════════════════════════════════════════════════════════════════════
        # RESUMEN EJECUTIVO - Veredicto claro para el documento individual
        # ═══════════════════════════════════════════════════════════════════════════
        status = kyb_validation.status.value
        score = kyb_validation.compliance_score
        
        if status == "compliant" and score >= 0.8:
            verdict = "APROBADO"
            resumen_msg = "El documento cumple con todos los requisitos KYB."
        elif status == "warning" or (score >= 0.6 and score < 0.8):
            verdict = "REVISION_REQUERIDA"
            resumen_msg = f"El documento requiere revisión manual. Score: {score*100:.0f}%"
        else:
            verdict = "RECHAZADO"
            errores_str = ", ".join(kyb_validation.errores[:3]) if kyb_validation.errores else "requisitos faltantes"
            resumen_msg = f"El documento no cumple requisitos KYB: {errores_str}"
        
        result["resumen"] = {
            "verdict": verdict,
            "mensaje": resumen_msg,
            "score": round(score * 100, 1),
            "documento_valido": status == "compliant",
            "vigente": kyb_validation.vigente,
            "errores_count": len(kyb_validation.errores),
            "warnings_count": len(kyb_validation.warnings),
        }
        
    except Exception as e:
        # Si falla la validación KYB, incluir el error pero no fallar el request
        result["kyb_compliance"] = {
            "status": "error",
            "error": str(e),
            "message": "La validación KYB no pudo completarse, pero la extracción fue exitosa"
        }
        result["resumen"] = {
            "verdict": "ERROR",
            "mensaje": f"Error en validación KYB: {str(e)}",
            "score": 0,
            "documento_valido": False,
        }

    return normalize_dates_in_result(result)


def get_validation_status() -> Dict[str, Any]:
    """
    Obtiene estado actual de validaciones (para endpoint de monitoreo).

    Returns:
        Diccionario con métricas de la sesión actual
    """
    return {
        "session_id": metrics.session_id,
        "summary": metrics.get_summary(),
        "low_confidence_fields": metrics.get_low_confidence_fields(),
    }
