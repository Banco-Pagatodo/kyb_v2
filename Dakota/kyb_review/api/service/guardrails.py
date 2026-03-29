"""
Sistema de Guardrails para validación fail-fast de documentos KYB.

Este módulo implementa validaciones tempranas que previenen el procesamiento
costoso de archivos inválidos, mejorando la eficiencia y reduciendo costos.

NOTA: La detección MIME, extensiones permitidas y límites de tamaño se
delegan a ``file_validator`` para evitar duplicación.  Este módulo añade la
capa de seguridad (path-traversal, campos requeridos, completitud) y la
integración como middleware de FastAPI.
"""

import os
from pathlib import Path
from typing import Dict, List, Tuple, Any
from pydantic import BaseModel
from fastapi import UploadFile, HTTPException, status

from .file_validator import (
    get_real_mime_type,
    ALLOWED_MIME_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZES,
)


class GuardrailResult(BaseModel):
    """Resultado de una validación de guardrail."""
    passed: bool
    error_code: str | None = None
    error_message: str | None = None
    validation_type: str
    details: Dict[str, Any] = {}


class GuardrailService:
    """
    Servicio de validación temprana para documentos KYB.
    
    Implementa el patrón fail-fast para rechazar documentos inválidos
    antes de realizar llamadas costosas a Azure Document Intelligence.

    Los límites de tamaño, MIME types y extensiones se importan de
    ``file_validator`` (fuente única de verdad).
    """
    
    # Delegar a file_validator (single source of truth)
    FILE_SIZE_LIMITS = MAX_FILE_SIZES
    ALLOWED_MIME_TYPES = ALLOWED_MIME_TYPES
    ALLOWED_EXTENSIONS = ALLOWED_EXTENSIONS
    
    # Campos requeridos por tipo de documento
    REQUIRED_FIELDS = {
        "ine": ["nombre", "apellido_paterno", "curp", "fecha_nacimiento"],
        "csf": ["rfc", "nombre_razon_social", "regimen_fiscal"],
        "fiel": ["rfc", "fecha_inicio", "fecha_fin"],
        "domicilio": ["calle", "colonia", "ciudad", "estado", "codigo_postal"],
        "acta": ["folio", "fecha_constitucion", "notario"],
        "poder": ["poderdante", "apoderado", "fecha_otorgamiento"],
        "reforma": ["folio", "fecha_reforma"],
        "estado_cuenta": ["cuenta", "periodo", "saldo"]
    }
    
    @staticmethod
    def _detect_mime_from_buffer(buf: bytes) -> str:
        """Delega a file_validator.get_real_mime_type (single source of truth)."""
        return get_real_mime_type(buf)

    def __init__(self):
        """Inicializa el servicio de guardrails."""
        self.rejection_count = 0
        self.rejection_reasons: Dict[str, int] = {
            "invalid_format": 0,
            "oversized": 0,
            "security_risk": 0,
            "missing_fields": 0
        }
    
    def validate_file_format(self, file: UploadFile) -> GuardrailResult:
        """
        Valida el formato del archivo usando magic bytes.
        
        Args:
            file: Archivo subido por el usuario
            
        Returns:
            GuardrailResult con el resultado de la validación
        """
        try:
            # Leer los primeros bytes para validar magic bytes
            file.file.seek(0)
            file_content = file.file.read(2048)
            file.file.seek(0)
            
            # Detectar MIME type usando magic bytes (implementación pura en Python)
            detected_mime = self._detect_mime_from_buffer(file_content)
            
            # Validar extensión del archivo
            file_ext = Path(file.filename).suffix.lower()
            
            if file_ext not in self.ALLOWED_EXTENSIONS:
                self.rejection_count += 1
                self.rejection_reasons["invalid_format"] += 1
                return GuardrailResult(
                    passed=False,
                    error_code="INVALID_EXTENSION",
                    error_message=f"Extensión {file_ext} no permitida. Use: {', '.join(self.ALLOWED_EXTENSIONS)}",
                    validation_type="format",
                    details={"extension": file_ext, "allowed": list(self.ALLOWED_EXTENSIONS)}
                )
            
            # Validar MIME type
            if detected_mime not in self.ALLOWED_MIME_TYPES:
                self.rejection_count += 1
                self.rejection_reasons["invalid_format"] += 1
                return GuardrailResult(
                    passed=False,
                    error_code="INVALID_MIME_TYPE",
                    error_message=f"Tipo MIME {detected_mime} no permitido",
                    validation_type="format",
                    details={"detected_mime": detected_mime, "allowed": list(self.ALLOWED_MIME_TYPES)}
                )
            
            return GuardrailResult(
                passed=True,
                validation_type="format",
                details={"mime_type": detected_mime, "extension": file_ext}
            )
            
        except Exception as e:
            self.rejection_count += 1
            self.rejection_reasons["invalid_format"] += 1
            return GuardrailResult(
                passed=False,
                error_code="FORMAT_VALIDATION_ERROR",
                error_message=f"Error al validar formato: {str(e)}",
                validation_type="format",
                details={"error": str(e)}
            )
    
    def validate_file_size(self, file: UploadFile, doc_type: str) -> GuardrailResult:
        """
        Valida el tamaño del archivo según límites por tipo de documento.
        
        Args:
            file: Archivo subido
            doc_type: Tipo de documento (ine, csf, etc.)
            
        Returns:
            GuardrailResult con el resultado de la validación
        """
        try:
            # Obtener tamaño del archivo
            file.file.seek(0, 2)  # Ir al final del archivo
            file_size = file.file.tell()
            file.file.seek(0)  # Volver al inicio
            
            # Obtener límite para este tipo de documento
            size_limit = self.FILE_SIZE_LIMITS.get(doc_type, self.FILE_SIZE_LIMITS["default"])
            
            if file_size > size_limit:
                self.rejection_count += 1
                self.rejection_reasons["oversized"] += 1
                return GuardrailResult(
                    passed=False,
                    error_code="FILE_TOO_LARGE",
                    error_message=f"Archivo de {file_size / 1024 / 1024:.2f}MB excede el límite de {size_limit / 1024 / 1024:.0f}MB para {doc_type}",
                    validation_type="size",
                    details={
                        "file_size_bytes": file_size,
                        "file_size_mb": round(file_size / 1024 / 1024, 2),
                        "limit_mb": size_limit / 1024 / 1024,
                        "doc_type": doc_type
                    }
                )
            
            if file_size == 0:
                self.rejection_count += 1
                self.rejection_reasons["invalid_format"] += 1
                return GuardrailResult(
                    passed=False,
                    error_code="EMPTY_FILE",
                    error_message="El archivo está vacío",
                    validation_type="size",
                    details={"file_size_bytes": 0}
                )
            
            return GuardrailResult(
                passed=True,
                validation_type="size",
                details={
                    "file_size_bytes": file_size,
                    "file_size_mb": round(file_size / 1024 / 1024, 2),
                    "limit_mb": size_limit / 1024 / 1024
                }
            )
            
        except Exception as e:
            return GuardrailResult(
                passed=False,
                error_code="SIZE_VALIDATION_ERROR",
                error_message=f"Error al validar tamaño: {str(e)}",
                validation_type="size",
                details={"error": str(e)}
            )
    
    def validate_file_security(self, file: UploadFile) -> GuardrailResult:
        """
        Valida aspectos de seguridad del archivo.
        
        Detecta:
        - Path traversal attacks (../, ..)
        - Nombres de archivo maliciosos
        - Caracteres peligrosos
        
        Args:
            file: Archivo subido
            
        Returns:
            GuardrailResult con el resultado de la validación
        """
        filename = file.filename
        
        # Detectar path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            self.rejection_count += 1
            self.rejection_reasons["security_risk"] += 1
            return GuardrailResult(
                passed=False,
                error_code="PATH_TRAVERSAL_DETECTED",
                error_message="Nombre de archivo contiene caracteres peligrosos de path traversal",
                validation_type="security",
                details={"filename": filename}
            )
        
        # Detectar caracteres peligrosos
        dangerous_chars = ["<", ">", ":", '"', "|", "?", "*"]
        found_dangerous = [char for char in dangerous_chars if char in filename]
        if found_dangerous:
            self.rejection_count += 1
            self.rejection_reasons["security_risk"] += 1
            return GuardrailResult(
                passed=False,
                error_code="DANGEROUS_CHARACTERS",
                error_message=f"Nombre de archivo contiene caracteres peligrosos: {', '.join(found_dangerous)}",
                validation_type="security",
                details={"filename": filename, "dangerous_chars": found_dangerous}
            )
        
        # Validar longitud del nombre
        if len(filename) > 255:
            self.rejection_count += 1
            self.rejection_reasons["security_risk"] += 1
            return GuardrailResult(
                passed=False,
                error_code="FILENAME_TOO_LONG",
                error_message=f"Nombre de archivo demasiado largo ({len(filename)} caracteres, máximo 255)",
                validation_type="security",
                details={"filename_length": len(filename)}
            )
        
        return GuardrailResult(
            passed=True,
            validation_type="security",
            details={"filename": filename, "filename_length": len(filename)}
        )
    
    def validate_required_fields(self, extracted_data: Dict, doc_type: str) -> GuardrailResult:
        """
        Valida que los campos requeridos estén presentes en los datos extraídos.
        
        Args:
            extracted_data: Datos extraídos del documento
            doc_type: Tipo de documento
            
        Returns:
            GuardrailResult con el resultado de la validación
        """
        required_fields = self.REQUIRED_FIELDS.get(doc_type, [])
        
        if not required_fields:
            # Si no hay campos requeridos definidos para este tipo, pasar
            return GuardrailResult(
                passed=True,
                validation_type="required_fields",
                details={"doc_type": doc_type, "message": "No required fields defined"}
            )
        
        # Verificar campos faltantes
        missing_fields = []
        for field in required_fields:
            # Buscar en el diccionario de forma flexible
            if field not in extracted_data or not extracted_data[field]:
                missing_fields.append(field)
        
        if missing_fields:
            self.rejection_count += 1
            self.rejection_reasons["missing_fields"] += 1
            return GuardrailResult(
                passed=False,
                error_code="MISSING_REQUIRED_FIELDS",
                error_message=f"Faltan campos requeridos: {', '.join(missing_fields)}",
                validation_type="required_fields",
                details={
                    "missing_fields": missing_fields,
                    "required_fields": required_fields,
                    "doc_type": doc_type
                }
            )
        
        return GuardrailResult(
            passed=True,
            validation_type="required_fields",
            details={"all_required_fields_present": True, "doc_type": doc_type}
        )
    
    def validate_completeness(self, extracted_data: Dict, doc_type: str) -> GuardrailResult:
        """
        Validación suave de completitud del documento.
        
        No rechaza el documento, pero advierte si faltan muchos campos.
        
        Args:
            extracted_data: Datos extraídos
            doc_type: Tipo de documento
            
        Returns:
            GuardrailResult con advertencia si aplica
        """
        if not extracted_data:
            return GuardrailResult(
                passed=True,  # No rechazar, solo advertir
                validation_type="completeness",
                details={"warning": "No data extracted", "completeness": 0.0}
            )
        
        # Calcular completitud
        total_fields = len(self.REQUIRED_FIELDS.get(doc_type, []))
        if total_fields == 0:
            return GuardrailResult(
                passed=True,
                validation_type="completeness",
                details={"completeness": 100.0}
            )
        
        filled_fields = sum(1 for field in self.REQUIRED_FIELDS.get(doc_type, []) 
                          if field in extracted_data and extracted_data[field])
        
        completeness = (filled_fields / total_fields) * 100
        
        return GuardrailResult(
            passed=True,
            validation_type="completeness",
            details={
                "completeness": round(completeness, 2),
                "filled_fields": filled_fields,
                "total_fields": total_fields,
                "warning": "Low completeness" if completeness <= 50 else None
            }
        )
    
    def validate_all(
        self, 
        file: UploadFile, 
        doc_type: str,
        extracted_data: Dict = None
    ) -> Tuple[bool, List[GuardrailResult]]:
        """
        Ejecuta todas las validaciones de guardrail.
        
        Args:
            file: Archivo a validar
            doc_type: Tipo de documento
            extracted_data: Datos extraídos (opcional, para validaciones post-extracción)
            
        Returns:
            Tupla (todas_pasaron, lista_de_resultados)
            
        Raises:
            HTTPException: Si alguna validación crítica falla
        """
        results = []
        
        # Validación 1: Seguridad
        security_result = self.validate_file_security(file)
        results.append(security_result)
        if not security_result.passed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": security_result.error_code,
                    "message": security_result.error_message,
                    "details": security_result.details
                }
            )
        
        # Validación 2: Formato
        format_result = self.validate_file_format(file)
        results.append(format_result)
        if not format_result.passed:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={
                    "error": format_result.error_code,
                    "message": format_result.error_message,
                    "details": format_result.details
                }
            )
        
        # Validación 3: Tamaño - DESHABILITADA
        # La validación de tamaño se ha removido para permitir archivos de cualquier tamaño.
        # Azure Document Intelligence maneja archivos grandes internamente.
        size_result = GuardrailResult(
            passed=True,
            validation_type="size",
            details={"note": "Size validation disabled"}
        )
        results.append(size_result)
        
        # Validaciones post-extracción (si se proporcionan datos)
        if extracted_data is not None:
            # Validación 4: Campos requeridos
            fields_result = self.validate_required_fields(extracted_data, doc_type)
            results.append(fields_result)
            if not fields_result.passed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": fields_result.error_code,
                        "message": fields_result.error_message,
                        "details": fields_result.details
                    }
                )
            
            # Validación 5: Completitud (soft validation)
            completeness_result = self.validate_completeness(extracted_data, doc_type)
            results.append(completeness_result)
        
        all_passed = all(r.passed for r in results)
        return all_passed, results
    
    def get_metrics(self) -> Dict:
        """
        Obtiene métricas del sistema de guardrails.
        
        Returns:
            Diccionario con métricas de rechazo
        """
        return {
            "total_rejections": self.rejection_count,
            "rejection_reasons": self.rejection_reasons,
            "rejection_rate": self.rejection_count  # Se puede calcular % si se trackean aceptaciones
        }
    
    def reset_metrics(self):
        """Resetea las métricas de rechazo."""
        self.rejection_count = 0
        self.rejection_reasons = {
            "invalid_format": 0,
            "oversized": 0,
            "security_risk": 0,
            "missing_fields": 0
        }


# Instancia global del servicio
guardrail_service = GuardrailService()
