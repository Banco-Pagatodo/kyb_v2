"""
Tests para el sistema de guardrails.
"""

import pytest
from fastapi import UploadFile
from io import BytesIO
from api.service.guardrails import GuardrailService, GuardrailResult


class TestGuardrails:
    """Suite de tests para el servicio de guardrails."""
    
    def setup_method(self):
        """Inicializa el servicio antes de cada test."""
        self.service = GuardrailService()
    
    def test_valid_pdf_passes_format_validation(self):
        """Test: Un PDF válido pasa la validación de formato."""
        # Crear un PDF mínimo válido
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        file = UploadFile(
            filename="test.pdf",
            file=BytesIO(pdf_content)
        )
        
        result = self.service.validate_file_format(file)
        
        assert result.passed is True
        assert result.validation_type == "format"
        assert "mime_type" in result.details
    
    def test_invalid_extension_rejected(self):
        """Test: Archivo con extensión inválida es rechazado."""
        file = UploadFile(
            filename="test.exe",
            file=BytesIO(b"fake content")
        )
        
        result = self.service.validate_file_format(file)
        
        assert result.passed is False
        assert result.error_code == "INVALID_EXTENSION"
        assert self.service.rejection_count == 1
        assert self.service.rejection_reasons["invalid_format"] == 1
    
    def test_oversized_file_rejected(self):
        """Test: Archivo que excede límite de tamaño es rechazado."""
        # Crear archivo de 11MB (excede límite de 10MB para INE)
        large_content = b"x" * (11 * 1024 * 1024)
        file = UploadFile(
            filename="test.pdf",
            file=BytesIO(large_content)
        )
        
        result = self.service.validate_file_size(file, "ine")
        
        assert result.passed is False
        assert result.error_code == "FILE_TOO_LARGE"
        assert self.service.rejection_count == 1
        assert self.service.rejection_reasons["oversized"] == 1
    
    def test_path_traversal_detected(self):
        """Test: Path traversal es detectado y rechazado."""
        file = UploadFile(
            filename="../../../etc/passwd",
            file=BytesIO(b"fake")
        )
        
        result = self.service.validate_file_security(file)
        
        assert result.passed is False
        assert result.error_code == "PATH_TRAVERSAL_DETECTED"
        assert self.service.rejection_count == 1
        assert self.service.rejection_reasons["security_risk"] == 1
    
    def test_empty_file_rejected(self):
        """Test: Archivo vacío es rechazado."""
        file = UploadFile(
            filename="empty.pdf",
            file=BytesIO(b"")
        )
        
        result = self.service.validate_file_size(file, "ine")
        
        assert result.passed is False
        assert result.error_code == "EMPTY_FILE"
    
    def test_missing_required_fields_rejected(self):
        """Test: Documento con campos requeridos faltantes es rechazado."""
        extracted_data = {
            "nombre": "Juan",
            # Faltan: apellido_paterno, curp, fecha_nacimiento
        }
        
        result = self.service.validate_required_fields(extracted_data, "ine")
        
        assert result.passed is False
        assert result.error_code == "MISSING_REQUIRED_FIELDS"
        assert "apellido_paterno" in result.details["missing_fields"]
        assert "curp" in result.details["missing_fields"]
        assert self.service.rejection_count == 1
        assert self.service.rejection_reasons["missing_fields"] == 1
    
    def test_completeness_validation_soft(self):
        """Test: Validación de completitud no rechaza, solo advierte."""
        extracted_data = {
            "nombre": "Juan",
            "apellido_paterno": "Pérez"
            # Solo 2 de 4 campos requeridos
        }
        
        result = self.service.validate_completeness(extracted_data, "ine")
        
        # Debe pasar (soft validation)
        assert result.passed is True
        assert result.details["completeness"] == 50.0
        assert result.details["warning"] == "Low completeness"
    
    def test_metrics_tracking(self):
        """Test: Las métricas se trackean correctamente."""
        # Simular varios rechazos
        file1 = UploadFile(filename="test.exe", file=BytesIO(b"x"))
        file2 = UploadFile(filename="../bad.pdf", file=BytesIO(b"x"))
        
        self.service.validate_file_format(file1)
        self.service.validate_file_security(file2)
        
        metrics = self.service.get_metrics()
        
        assert metrics["total_rejections"] == 2
        assert metrics["rejection_reasons"]["invalid_format"] == 1
        assert metrics["rejection_reasons"]["security_risk"] == 1
    
    def test_metrics_reset(self):
        """Test: El reset de métricas funciona correctamente."""
        file = UploadFile(filename="test.exe", file=BytesIO(b"x"))
        self.service.validate_file_format(file)
        
        assert self.service.rejection_count == 1
        
        self.service.reset_metrics()
        
        assert self.service.rejection_count == 0
        assert all(count == 0 for count in self.service.rejection_reasons.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
