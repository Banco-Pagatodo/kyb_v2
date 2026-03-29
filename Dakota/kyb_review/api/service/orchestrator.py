"""
Orchestrator Service para flujo unificado de onboarding KYB.

Este servicio implementa el flujo completo de procesamiento:
1. Guardrails (validación de formato/tamaño)
2. Extracción OCR (datos de cada documento)
3. Validación individual (vigencia, protocolización, etc.)
4. Generación de veredicto final

El enfoque es "fail-fast": valida individualmente primero.
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from fastapi import UploadFile

from api.model.orchestrator import (
    OnboardingReviewResponse,
    DocumentResult,
    DocumentError,
    DocumentStage,
    ErrorSeverity,
    ReviewVerdict,
    ValidationDetail,
    REQUIRED_DOCUMENTS,
    CONDITIONAL_DOCUMENTS,
    DOCUMENT_NAMES
)
from api.model.DocFormat import DocFormat
from api.service.file_validator import (
    validate_upload_file,
    FileValidationError
)
from api.service.validator import validator_agent
from api.controller.docs import (
    analyze_csf,
    analyze_constitutiva,
    analyze_ine,
    analyze_poder,
    analyze_domicilio,
    analyze_fiel,
    analyze_estado_cuenta,
    analyze_reforma,
    get_docformat
)
from api.db import session as db_session
from api.db import repository as repo
from api.client.colorado_client import trigger_validacion_cruzada

logger = logging.getLogger(__name__)


class OrchestratorService:
    """
    Orquestador del flujo completo de onboarding KYB.
    
    Procesa documentos en el siguiente orden:
    1. Validación de guardrails (formato, tamaño, tipo MIME)
    2. Extracción OCR de datos estructurados
    3. Validación individual por documento (vigencia, campos required)
    4. Validación cruzada entre documentos (si todos pasan individuales)
    5. Generación de veredicto final
    """
    
    # Mapeo de tipo de documento a función extractora
    EXTRACTORS = {
        "csf": analyze_csf,
        "acta_constitutiva": analyze_constitutiva,
        "ine": lambda path: analyze_ine(path, get_docformat(path)),
        "poder": analyze_poder,
        "comprobante_domicilio": analyze_domicilio,
        "fiel": analyze_fiel,
        "estado_cuenta": analyze_estado_cuenta,
        "reforma": analyze_reforma
    }
    
    def __init__(self):
        """Inicializa el orquestador."""
        self.temp_dir = tempfile.gettempdir()
    
    async def process_review(
        self,
        expediente_id: str,
        files: Dict[str, UploadFile],
        fail_fast: bool = True,
        rfc: str | None = None,
    ) -> OnboardingReviewResponse:
        """
        Procesa una revisión completa de onboarding.
        
        Args:
            expediente_id: ID del expediente
            files: Diccionario {tipo_doc: UploadFile}
            fail_fast: Si True, detiene al primer error crítico
            rfc: RFC de la empresa. Si se proporciona, persiste docs y dispara Colorado.
            
        Returns:
            OnboardingReviewResponse con resultado completo
        """
        started_at = datetime.now()
        
        logger.info(f"[ORCHESTRATOR] Iniciando revisión de expediente {expediente_id}")
        logger.info(f"[ORCHESTRATOR] Documentos recibidos: {list(files.keys())}")
        
        # Inicializar estructuras de resultado
        document_results: List[DocumentResult] = []
        all_errors: List[DocumentError] = []
        extracted_data: Dict[str, Any] = {}
        critical_error_encountered = False
        
        # ═══════════════════════════════════════════════════════════════════
        # FASE 1: Guardrails + Extracción + Validación Individual
        # ═══════════════════════════════════════════════════════════════════
        logger.info("[ORCHESTRATOR] FASE 1: Procesando documentos...")
        
        for doc_type, upload_file in files.items():
            if critical_error_encountered and fail_fast:
                break
                
            doc_result, doc_errors, doc_data, validations = await self._process_single_document(
                doc_type=doc_type,
                upload_file=upload_file,
                fail_fast=fail_fast
            )
            
            document_results.append(doc_result)
            all_errors.extend(doc_errors)
            
            if doc_data:
                extracted_data[doc_type] = doc_data
            
            # Verificar si hay errores críticos
            critical_errors = [e for e in doc_errors if e.severity == ErrorSeverity.CRITICAL]
            if critical_errors and fail_fast:
                critical_error_encountered = True
                logger.warning(f"[ORCHESTRATOR] Error crítico en {doc_type}, deteniendo proceso")
        
        # ═══════════════════════════════════════════════════════════════════
        # FASE 2: Generar veredicto final
        # ═══════════════════════════════════════════════════════════════════
        completed_at = datetime.now()
        total_ms = int((completed_at - started_at).total_seconds() * 1000)
        
        # Calcular métricas
        docs_exitosos = sum(1 for d in document_results if d.validation_passed)
        docs_fallidos = sum(1 for d in document_results if d.stage == DocumentStage.FAILED)
        errores_criticos = sum(1 for e in all_errors if e.severity == ErrorSeverity.CRITICAL)
        
        # Determinar veredicto
        verdict, resumen, auto_aprobable = self._determine_verdict(
            document_results=document_results,
            all_errors=all_errors
        )
        
        # Generar recomendaciones
        recomendaciones = self._generate_recommendations(all_errors, document_results)
        
        logger.info(f"[ORCHESTRATOR] Revisión completada: {verdict.value} en {total_ms}ms")
        
        # ─────────────────────────────────────────────────────────────────
        # FASE 3: Persistir docs + disparar Colorado (si hay RFC)
        # ─────────────────────────────────────────────────────────────────
        empresa_id_str = None
        if rfc and extracted_data:
            empresa_id_str = await self._persist_and_trigger(
                rfc=rfc,
                extracted_data=extracted_data,
                document_results=document_results,
            )
        
        response = OnboardingReviewResponse(
            expediente_id=expediente_id,
            verdict=verdict,
            resumen=resumen,
            documentos_procesados=len(document_results),
            documentos_exitosos=docs_exitosos,
            documentos_fallidos=docs_fallidos,
            errores_criticos=errores_criticos,
            documentos=document_results,
            todos_errores=all_errors,
            recomendaciones=recomendaciones,
            auto_aprobable=auto_aprobable,
            started_at=started_at,
            completed_at=completed_at,
            total_processing_time_ms=total_ms
        )
        return response
    
    async def _process_single_document(
        self,
        doc_type: str,
        upload_file: UploadFile,
        fail_fast: bool
    ) -> Tuple[DocumentResult, List[DocumentError], Optional[Dict[str, Any]], List[ValidationDetail]]:
        """
        Procesa un documento individual: guardrails → OCR → validación.
        
        Returns:
            Tupla de (DocumentResult, errores, datos_extraidos, validaciones)
        """
        started_at = datetime.now()
        errors: List[DocumentError] = []
        extracted_data = None
        validations: List[ValidationDetail] = []
        
        doc_result = DocumentResult(
            documento_tipo=doc_type,
            archivo=upload_file.filename or "unknown",
            started_at=started_at,
            stage=DocumentStage.GUARDRAILS
        )
        
        doc_name = DOCUMENT_NAMES.get(doc_type, doc_type)
        logger.info(f"[ORCHESTRATOR] Procesando: {doc_name} ({upload_file.filename})")
        
        # ─────────────────────────────────────────────────────────────────
        # PASO 1: Guardrails
        # ─────────────────────────────────────────────────────────────────
        try:
            # Usar file_validator para validar (async)
            file_content, safe_filename = await validate_upload_file(
                file=upload_file,
                doc_type=doc_type,
                validate_mime=True
            )
            doc_result.guardrails_passed = True
            
            # Registrar validación de guardrails exitosa
            validations.append(ValidationDetail(
                tipo="guardrails",
                passed=True,
                mensaje=f"Archivo válido: formato correcto, tamaño {len(file_content)/1024:.1f}KB",
                datos={
                    "file_size_bytes": len(file_content),
                    "filename": safe_filename
                }
            ))
            
            logger.info(f"[ORCHESTRATOR] ✓ Guardrails OK para {doc_type}")
            
        except FileValidationError as e:
            doc_result.guardrails_passed = False
            doc_result.guardrails_error = str(e.detail)
            doc_result.stage = DocumentStage.FAILED
            
            # Registrar validación de guardrails fallida
            validations.append(ValidationDetail(
                tipo="guardrails",
                passed=False,
                mensaje=str(e.detail),
                datos={"error_type": e.__class__.__name__}
            ))
            
            errors.append(DocumentError(
                documento=doc_name,
                stage=DocumentStage.GUARDRAILS,
                severity=ErrorSeverity.CRITICAL,
                mensaje=str(e.detail),
                sugerencia="Verifique el formato y tamaño del archivo"
            ))
            
            logger.warning(f"[ORCHESTRATOR] ✗ Guardrails FAILED para {doc_type}: {e.detail}")
            
            completed_at = datetime.now()
            doc_result.completed_at = completed_at
            doc_result.processing_time_ms = int((completed_at - started_at).total_seconds() * 1000)
            doc_result.validaciones = validations
            
            return doc_result, errors, None, validations
        
        except Exception as e:
            doc_result.guardrails_passed = False
            doc_result.guardrails_error = str(e)
            doc_result.stage = DocumentStage.FAILED
            
            # Registrar error inesperado
            validations.append(ValidationDetail(
                tipo="guardrails",
                passed=False,
                mensaje=f"Error inesperado: {str(e)}",
                datos={"error_type": "unexpected"}
            ))
            
            errors.append(DocumentError(
                documento=doc_name,
                stage=DocumentStage.GUARDRAILS,
                severity=ErrorSeverity.CRITICAL,
                mensaje=f"Error inesperado en validación: {str(e)}"
            ))
            
            completed_at = datetime.now()
            doc_result.completed_at = completed_at
            doc_result.processing_time_ms = int((completed_at - started_at).total_seconds() * 1000)
            doc_result.validaciones = validations
            
            return doc_result, errors, None, validations
        
        # ─────────────────────────────────────────────────────────────────
        # PASO 2: Guardar archivo temporal y extraer datos
        # ─────────────────────────────────────────────────────────────────
        doc_result.stage = DocumentStage.EXTRACTING
        
        try:
            # Guardar archivo temporal
            temp_path = await self._save_temp_file(upload_file, doc_type)
            
            # Obtener extractor apropiado
            extractor = self.EXTRACTORS.get(doc_type)
            if not extractor:
                raise ValueError(f"No existe extractor para documento tipo: {doc_type}")
            
            # Ejecutar extracción (sync, envolver en thread)
            logger.info(f"[ORCHESTRATOR] Extrayendo datos de {doc_type}...")
            extracted_data = await asyncio.to_thread(extractor, temp_path)
            
            doc_result.datos_extraidos = extracted_data.get("datos_extraidos", {})
            doc_result.extraction_confidence = extracted_data.get("_confiabilidad_promedio")
            
            # Registrar extracción exitosa
            validations.append(ValidationDetail(
                tipo="extraccion",
                passed=True,
                mensaje=f"Datos extraídos exitosamente (confianza: {doc_result.extraction_confidence or 0:.0%})",
                datos={
                    "confidence": doc_result.extraction_confidence,
                    "fields_extracted": len(doc_result.datos_extraidos)
                }
            ))
            
            logger.info(f"[ORCHESTRATOR] ✓ Extracción OK para {doc_type}")
            
            # Limpiar archivo temporal
            try:
                os.remove(temp_path)
            except OSError:
                logger.debug("Could not remove temp file %s", temp_path)
                
        except Exception as e:
            doc_result.stage = DocumentStage.FAILED
            
            # Registrar extracción fallida
            validations.append(ValidationDetail(
                tipo="extraccion",
                passed=False,
                mensaje=f"Error extrayendo datos: {str(e)}",
                datos={"error": str(e)}
            ))
            
            errors.append(DocumentError(
                documento=doc_name,
                stage=DocumentStage.EXTRACTING,
                severity=ErrorSeverity.CRITICAL,
                mensaje=f"Error extrayendo datos: {str(e)}",
                sugerencia="Verifique que el documento sea legible y no esté dañado"
            ))
            
            logger.error(f"[ORCHESTRATOR] ✗ Extracción FAILED para {doc_type}: {e}")
            
            completed_at = datetime.now()
            doc_result.completed_at = completed_at
            doc_result.processing_time_ms = int((completed_at - started_at).total_seconds() * 1000)
            doc_result.validaciones = validations
            
            return doc_result, errors, None, validations
        
        # ─────────────────────────────────────────────────────────────────
        # PASO 3: Validación individual del documento
        # ─────────────────────────────────────────────────────────────────
        doc_result.stage = DocumentStage.VALIDATING
        
        try:
            # Usar el ValidatorAgent para validar este documento específico
            validation_errors, validation_details = await self._validate_single_document(
                doc_type=doc_type,
                doc_data=extracted_data
            )
            
            # Agregar detalles de validaciones
            validations.extend(validation_details)
            
            if validation_errors:
                for error_msg in validation_errors:
                    errors.append(DocumentError(
                        documento=doc_name,
                        stage=DocumentStage.VALIDATING,
                        severity=ErrorSeverity.CRITICAL if self._is_critical_error(error_msg) else ErrorSeverity.HIGH,
                        mensaje=error_msg
                    ))
                
                doc_result.validation_passed = False
                doc_result.stage = DocumentStage.FAILED
                doc_result.errores = errors
                logger.warning(f"[ORCHESTRATOR] ✗ Validación FAILED para {doc_type}: {len(validation_errors)} errores")
            else:
                doc_result.validation_passed = True
                doc_result.stage = DocumentStage.COMPLETED
                logger.info(f"[ORCHESTRATOR] ✓ Validación OK para {doc_type}")
                
        except Exception as e:
            doc_result.stage = DocumentStage.FAILED
            
            # Registrar error de validación
            validations.append(ValidationDetail(
                tipo="validacion",
                passed=False,
                mensaje=f"Error inesperado en validación: {str(e)}",
                datos={"error": str(e)}
            ))
            
            errors.append(DocumentError(
                documento=doc_name,
                stage=DocumentStage.VALIDATING,
                severity=ErrorSeverity.HIGH,
                mensaje=f"Error en validación: {str(e)}"
            ))
            
            logger.error(f"[ORCHESTRATOR] ✗ Validación ERROR para {doc_type}: {e}")
        
        completed_at = datetime.now()
        doc_result.completed_at = completed_at
        doc_result.processing_time_ms = int((completed_at - started_at).total_seconds() * 1000)
        doc_result.errores = errors
        doc_result.validaciones = validations
        
        return doc_result, errors, extracted_data, validations
    
    async def _persist_and_trigger(
        self,
        rfc: str,
        extracted_data: Dict[str, Any],
        document_results: List[DocumentResult],
    ) -> str | None:
        """
        Persiste los documentos extraídos en PostgreSQL y dispara Colorado.

        Returns:
            empresa_id (str) si se persistió correctamente, None si falló.
        """
        factory = db_session._session_factory
        if factory is None:
            logger.warning("[ORCHESTRATOR] No hay sesión de BD, no se puede persistir")
            return None

        empresa_id_str = None
        try:
            async with factory() as session:
                # Obtener o crear empresa
                empresa = await repo.get_or_create_empresa(session, rfc=rfc)

                # Persistir cada documento extraído
                for doc_type, doc_data in extracted_data.items():
                    try:
                        fields = repo.extract_fields_for_db(doc_data)
                        # Buscar el filename del DocumentResult correspondiente
                        file_name = "onboarding"
                        for dr in document_results:
                            if dr.documento_tipo == doc_type:
                                file_name = dr.archivo
                                break
                        await repo.save_documento(
                            session,
                            empresa_id=empresa.id,
                            doc_type=doc_type,
                            file_name=file_name,
                            **fields,
                        )
                    except Exception as e:
                        logger.warning(
                            "[ORCHESTRATOR] Error persistiendo %s: %s", doc_type, e
                        )

                await session.commit()
                empresa_id_str = str(empresa.id)
                logger.info(
                    "[ORCHESTRATOR] %d docs persistidos para %s (empresa=%s)",
                    len(extracted_data), rfc, empresa_id_str,
                )

        except Exception as e:
            logger.error("[ORCHESTRATOR] Error en persistencia: %s", e, exc_info=True)
            return None

        # Disparar Colorado en background (fire & forget)
        if empresa_id_str:
            asyncio.ensure_future(self._trigger_colorado(empresa_id_str, rfc))

        return empresa_id_str

    async def _trigger_colorado(self, empresa_id: str, rfc: str) -> None:
        """Wrapper seguro para llamar a Colorado en background."""
        try:
            resultado = await trigger_validacion_cruzada(empresa_id)
            if resultado:
                logger.info(
                    "[ORCHESTRATOR] Colorado completó: %s → %s",
                    rfc, resultado.get("dictamen", "?"),
                )
        except Exception as e:
            logger.warning("[ORCHESTRATOR] Error disparando Colorado: %s", e)

    async def _validate_single_document(
        self,
        doc_type: str,
        doc_data: Dict[str, Any]
    ) -> Tuple[List[str], List[ValidationDetail]]:
        """
        Ejecuta validaciones individuales para un documento.
        
        Valida:
        - Vigencia (para documentos con fecha de emisión/vencimiento)
        - Requisitos específicos del documento
        - Campos obligatorios
        
        Returns:
            Tupla de (lista de errores, lista de detalles de validación)
        """
        errors = []
        validations = []
        
        if doc_type not in validator_agent.DOCUMENT_REQUIREMENTS:
            return errors, validations
        
        requirement = validator_agent.DOCUMENT_REQUIREMENTS[doc_type]
        datos = doc_data.get("datos_extraidos", {})
        
        # 1. Validar vigencia
        vigencia_result = await validator_agent._validate_vigencia(
            doc_type=doc_type,
            vigencia_type=requirement.vigencia_maxima,
            datos=datos
        )
        
        vigencia_passed = vigencia_result.get("valid", True)
        validations.append(ValidationDetail(
            tipo="vigencia",
            passed=vigencia_passed,
            mensaje=vigencia_result.get("error", "Documento vigente") if not vigencia_passed else f"Documento vigente (tipo: {requirement.vigencia_maxima.value})",
            datos={
                "vigencia_type": requirement.vigencia_maxima.value,
                "fecha_emision": str(vigencia_result.get("fecha_emision")) if vigencia_result.get("fecha_emision") else None,
                "fecha_vencimiento": str(vigencia_result.get("fecha_vencimiento")) if vigencia_result.get("fecha_vencimiento") else None
            }
        ))
        
        if not vigencia_passed:
            errors.append(vigencia_result.get("error", "Error de vigencia"))
        
        # 2. Validar requisitos específicos (retorna errores + validaciones detalladas)
        specific_errors, specific_validations = await validator_agent._validate_specific_requirements(
            doc_type=doc_type,
            requisitos=requirement.requisitos_especificos,
            datos=datos
        )
        
        # Agregar validaciones específicas
        validations.extend(specific_validations)
        errors.extend(specific_errors)
        
        return errors, validations
    
    async def _save_temp_file(
        self,
        upload_file: UploadFile,
        doc_type: str
    ) -> str:
        """Guarda el UploadFile a un archivo temporal."""
        
        # Determinar extensión
        filename = upload_file.filename or "document.pdf"
        ext = os.path.splitext(filename)[1] or ".pdf"
        
        # Crear archivo temporal
        temp_path = os.path.join(
            self.temp_dir,
            f"kyb_{doc_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        )
        
        # Escribir contenido
        content = await upload_file.read()
        await upload_file.seek(0)
        
        with open(temp_path, "wb") as f:
            f.write(content)
        
        return temp_path
    
    def _is_critical_error(self, error_msg: str) -> bool:
        """Determina si un error es crítico basado en el mensaje."""
        critical_keywords = [
            "vencido",
            "vencida", 
            "antigüedad",
            "falta",
            "no está en estatus",
            "no muestra evidencia",
            "no coincide",
            "no proporcionado",
            "requerido"
        ]
        return any(kw in error_msg.lower() for kw in critical_keywords)
    
    def _determine_verdict(
        self,
        document_results: List[DocumentResult],
        all_errors: List[DocumentError]
    ) -> Tuple[ReviewVerdict, str, bool]:
        """
        Determina el veredicto final de la revisión.
        
        Returns:
            Tupla (verdict, resumen, auto_aprobable)
        """
        errores_criticos = [e for e in all_errors if e.severity == ErrorSeverity.CRITICAL]
        errores_altos = [e for e in all_errors if e.severity == ErrorSeverity.HIGH]
        
        docs_exitosos = sum(1 for d in document_results if d.validation_passed)
        docs_total = len(document_results)
        
        # REJECTED: Errores irrecuperables
        if len(errores_criticos) >= 3:
            return (
                ReviewVerdict.REJECTED,
                f"Expediente rechazado: {len(errores_criticos)} errores críticos encontrados. "
                f"Es necesario corregir múltiples documentos antes de volver a intentar.",
                False
            )
        
        # APPROVED: Todo bien
        if len(errores_criticos) == 0 and len(errores_altos) == 0:
            if docs_exitosos == docs_total:
                return (
                    ReviewVerdict.APPROVED,
                    f"Expediente aprobado automáticamente. "
                    f"{docs_exitosos}/{docs_total} documentos validados correctamente.",
                    True
                )
        
        # REVIEW_REQUIRED: Hay errores pero no son tantos
        resumen_parts = []
        
        if errores_criticos:
            resumen_parts.append(f"{len(errores_criticos)} error(es) crítico(s)")
        if errores_altos:
            resumen_parts.append(f"{len(errores_altos)} advertencia(s) importante(s)")
        
        return (
            ReviewVerdict.REVIEW_REQUIRED,
            f"Expediente requiere revisión manual: {', '.join(resumen_parts)}. "
            f"{docs_exitosos}/{docs_total} documentos pasaron validación individual.",
            False
        )
    
    def _generate_recommendations(
        self,
        all_errors: List[DocumentError],
        document_results: List[DocumentResult]
    ) -> List[str]:
        """Genera recomendaciones basadas en los errores."""
        recommendations = []
        
        # Errores de vigencia
        vigencia_errors = [e for e in all_errors if "antigüedad" in e.mensaje.lower() or "vencid" in e.mensaje.lower()]
        if vigencia_errors:
            recommendations.append(
                "Actualice los documentos con problemas de vigencia. Los documentos con vigencia de 3 meses "
                "(CSF, comprobante de domicilio) deben ser recientes."
            )
        
        # Errores de protocolización
        protocolo_errors = [e for e in all_errors if "protocoliz" in e.mensaje.lower()]
        if protocolo_errors:
            recommendations.append(
                "Verifique que los documentos notariales (Acta Constitutiva, Poder) estén debidamente "
                "protocolizados e inscritos en el Registro Público."
            )
        
        # Errores de extracción
        extraction_errors = [e for e in all_errors if e.stage == DocumentStage.EXTRACTING]
        if extraction_errors:
            recommendations.append(
                "Algunos documentos no pudieron ser procesados correctamente. Asegúrese de que los archivos "
                "sean legibles, no estén dañados y tengan buena calidad de imagen."
            )
        
        # Errores de cross-validation (datos no coinciden entre documentos)
        cross_errors = [e for e in all_errors if "coinc" in e.mensaje.lower() or "consistente" in e.mensaje.lower()]
        if cross_errors:
            recommendations.append(
                "Se detectaron inconsistencias entre documentos. Verifique que los datos (RFC, nombre, domicilio) "
                "sean consistentes y coincidan entre todos los documentos proporcionados."
            )
        
        return recommendations


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════

orchestrator_service = OrchestratorService()
