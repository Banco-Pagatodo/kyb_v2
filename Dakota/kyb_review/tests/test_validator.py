"""
Tests para el Validator Agent.

Valida el funcionamiento del sistema de validación de requisitos documentales KYB.
"""

import pytest
from datetime import date, timedelta
from api.service.validator import ValidatorAgent
from api.model.validator import RequirementStatus, VigenciaType


class TestValidatorAgent:
    """Suite de tests para el agente de compliance."""
    
    def setup_method(self):
        """Inicializa el agente antes de cada test."""
        self.agent = ValidatorAgent()
    
    @pytest.mark.asyncio
    async def test_expediente_completo_auto_aprobable(self):
        """Test: Expediente completo con todos los requisitos debe ser auto-aprobable."""
        
        today = date.today()
        fecha_reciente = (today - timedelta(days=30)).strftime("%d/%m/%Y")
        fecha_futura = (today + timedelta(days=365)).strftime("%d/%m/%Y")
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "denominacion_razon_social": "EMPRESA TEST SA DE CV",
                    "domicilio_fiscal": "CALLE PRUEBA 123 COLONIA CENTRO",
                    "regimen_fiscal": "General",
                    "estatus_padron": "ACTIVO",
                    "fecha_emision": fecha_reciente
                }
            },
            "acta_constitutiva": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "numero_escritura_poliza": "12345",
                    "nombre_notario": "LIC. ROBERTO GARCIA MARTINEZ",
                    "numero_notaria": "49",
                    "folio_mercantil": "N-2024050847",
                    "fecha_constitucion": "15/03/2020",
                    "clausula_extranjeros": "EXCLUSION DE EXTRANJEROS",
                    "texto_completo": "ACTA PROTOCOLIZADA ANTE NOTARIO PUBLICO"
                }
            },
            "ine": {
                "datos_extraidos": {
                    "nombre_completo": "JUAN PEREZ LOPEZ",
                    "curp": "PELJ800101HDFRZN01",
                    "fecha_vencimiento": fecha_futura
                }
            },
            "poder": {
                "datos_extraidos": {
                    "nombre_apoderado": "JUAN PEREZ LOPEZ",
                    "numero_escritura": "12345",
                    "nombre_notario": "LIC. ROBERTO GARCIA",
                    "tipo_poder": "PODER GENERAL PARA ACTOS DE ADMINISTRACION",
                    "facultades": "Representar legalmente, celebrar contratos"
                }
            },
            "comprobante_domicilio": {
                "datos_extraidos": {
                    "calle": "CALLE PRUEBA",
                    "numero_exterior": "123",
                    "colonia": "CENTRO",
                    "codigo_postal": "06600",
                    "fecha_emision": fecha_reciente
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-001"
        )
        
        assert result.validation_score >= 0.95
        assert result.auto_aprobable is True
        assert len(result.errores_criticos) == 0
    
    @pytest.mark.asyncio
    async def test_csf_vencido_rechazado(self):
        """Test: CSF con más de 3 meses debe ser rechazado."""
        
        fecha_antigua = (date.today() - timedelta(days=120)).strftime("%d/%m/%Y")
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "denominacion_razon_social": "EMPRESA TEST SA DE CV",
                    "domicilio_fiscal": "CALLE PRUEBA 123",
                    "regimen_fiscal": "General",
                    "estatus_padron": "ACTIVO",
                    "fecha_emision": fecha_antigua
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-002"
        )
        
        assert result.auto_aprobable is False
        assert any("antigüedad" in error.lower() for error in result.errores_criticos)
    
    @pytest.mark.asyncio
    async def test_documento_requerido_faltante(self):
        """Test: Documento requerido faltante debe generar error."""
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789"
                }
            }
            # Faltan: acta_constitutiva, ine, poder, comprobante_domicilio
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-003"
        )
        
        assert result.auto_aprobable is False
        assert result.requisitos_fallidos > 0
        
        # Verificar que documentos requeridos faltantes estén identificados
        faltantes = [doc for doc in result.documentos 
                    if doc.status == RequirementStatus.NON_COMPLIANT 
                    and doc.requerimiento == "Requerido"]
        assert len(faltantes) > 0
    
    @pytest.mark.asyncio
    async def test_rfc_no_coincide_entre_documentos(self):
        """Test: RFC diferente entre documentos debe generar error."""
        
        today = date.today()
        fecha_reciente = (today - timedelta(days=30)).strftime("%d/%m/%Y")
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "denominacion_razon_social": "EMPRESA TEST SA DE CV",
                    "domicilio_fiscal": "CALLE PRUEBA 123",
                    "regimen_fiscal": "General",
                    "estatus_padron": "ACTIVO",
                    "fecha_emision": fecha_reciente
                }
            },
            "acta_constitutiva": {
                "datos_extraidos": {
                    "rfc": "XYZ987654321",  # RFC diferente
                    "denominacion_social": "EMPRESA TEST SA DE CV",
                    "texto_completo": "ACTA PROTOCOLIZADA ANTE NOTARIO",
                    "objeto_social": "Servicios",
                    "capital_social": "100000",
                    "domicilio": "CALLE PRUEBA 123"
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-004"
        )
        
        assert result.auto_aprobable is False
        assert any("rfc" in error.lower() and "no coincide" in error.lower() 
                  for error in result.errores_criticos)
    
    @pytest.mark.asyncio
    async def test_estatus_rfc_inactivo_rechazado(self):
        """Test: RFC con estatus diferente a ACTIVO debe ser rechazado."""
        
        today = date.today()
        fecha_reciente = (today - timedelta(days=30)).strftime("%d/%m/%Y")
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "denominacion_razon_social": "EMPRESA TEST SA DE CV",
                    "domicilio_fiscal": "CALLE PRUEBA 123",
                    "regimen_fiscal": "General",
                    "estatus_padron": "SUSPENDIDO",  # Estatus inválido
                    "fecha_emision": fecha_reciente
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-005"
        )
        
        assert result.auto_aprobable is False
        
        # Buscar el documento CSF
        csf_doc = next((doc for doc in result.documentos if doc.documento == "Constancia de Situación Fiscal (CSF)"), None)
        assert csf_doc is not None
        assert csf_doc.status == RequirementStatus.NON_COMPLIANT
        assert any("activo" in error.lower() for error in csf_doc.errores)
    
    @pytest.mark.asyncio
    async def test_acta_sin_protocolarizacion_rechazada(self):
        """Test: Acta sin evidencia de protocolización debe ser rechazada."""
        
        expediente_data = {
            "acta_constitutiva": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "denominacion_social": "EMPRESA TEST SA DE CV",
                    "texto_completo": "ACTA CONSTITUTIVA DE LA EMPRESA",  # Sin mención de notario
                    "objeto_social": "Servicios",
                    "capital_social": "100000",
                    "domicilio": "CALLE PRUEBA 123"
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-006"
        )
        
        acta_doc = next((doc for doc in result.documentos 
                        if doc.documento == "Acta Constitutiva"), None)
        assert acta_doc is not None
        assert acta_doc.status == RequirementStatus.NON_COMPLIANT
        assert any("protocolización" in error.lower() or "protocolizacion" in error.lower() 
                  for error in acta_doc.errores)
    
    @pytest.mark.asyncio
    async def test_poder_sin_facultades_suficientes(self):
        """Test: Poder sin facultades suficientes debe generar error."""
        
        expediente_data = {
            "poder": {
                "datos_extraidos": {
                    "nombre_apoderado": "JUAN PEREZ LOPEZ",
                    "texto_completo": "PODER LIMITADO PARA TRAMITES ESPECIFICOS"  # Sin facultades generales
                }
            }
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-007"
        )
        
        poder_doc = next((doc for doc in result.documentos 
                         if doc.documento == "Poder Notarial"), None)
        assert poder_doc is not None
        assert poder_doc.status == RequirementStatus.NON_COMPLIANT
        assert any("facultades" in error.lower() for error in poder_doc.errores)
    
    @pytest.mark.asyncio
    async def test_parse_date_multiples_formatos(self):
        """Test: El parser de fechas debe manejar múltiples formatos."""
        
        formatos = [
            "15/01/2024",
            "2024-01-15",
            "15-01-2024",
            "15.01.2024"
        ]
        
        for fecha_str in formatos:
            fecha = self.agent._parse_date(fecha_str)
            assert fecha is not None
            assert fecha.year == 2024
            assert fecha.month == 1
            assert fecha.day == 15
    
    @pytest.mark.asyncio
    async def test_address_similarity_calculation(self):
        """Test: Cálculo de similitud de direcciones."""
        
        # Direcciones muy similares
        addr1 = "CALLE REFORMA 123 COLONIA CENTRO"
        addr2 = "REFORMA 123 COL CENTRO"
        similarity = self.agent._calculate_address_similarity(addr1, addr2)
        assert similarity >= 0.7
        
        # Direcciones diferentes
        addr3 = "AVENIDA INSURGENTES 456"
        addr4 = "CALLE JUAREZ 789"
        similarity2 = self.agent._calculate_address_similarity(addr3, addr4)
        assert similarity2 < 0.5
    
    @pytest.mark.asyncio
    async def test_names_match(self):
        """Test: Coincidencia de nombres con variaciones."""
        
        # Nombres que deben coincidir
        assert self.agent._names_match("JUAN PEREZ LOPEZ", "JUAN PEREZ LOPEZ")
        assert self.agent._names_match("JUAN PEREZ LOPEZ", "PEREZ LOPEZ JUAN")
        assert self.agent._names_match("JUAN A PEREZ LOPEZ", "JUAN PEREZ LOPEZ")
        
        # Nombres que no deben coincidir
        assert not self.agent._names_match("JUAN PEREZ LOPEZ", "MARIA GARCIA RODRIGUEZ")
    
    @pytest.mark.asyncio
    async def test_documento_condicional_no_afecta_score(self):
        """Test: Documentos condicionales faltantes no deben afectar score crítico."""
        
        today = date.today()
        fecha_reciente = (today - timedelta(days=30)).strftime("%d/%m/%Y")
        fecha_futura = (today + timedelta(days=365)).strftime("%d/%m/%Y")
        
        expediente_data = {
            "csf": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "razon_social": "EMPRESA TEST SA DE CV",
                    "domicilio_fiscal": "CALLE PRUEBA 123",
                    "giro_mercantil": "General",
                    "estatus_padron": "ACTIVO",
                    "fecha_emision": fecha_reciente
                }
            },
            "acta_constitutiva": {
                "datos_extraidos": {
                    "rfc": "ABC123456789",
                    "numero_escritura_poliza": "12345",
                    "nombre_notario": "LIC. ROBERTO GARCIA",
                    "objeto_social": "Servicios",
                    "capital_social": "100000",
                    "domicilio": "CALLE PRUEBA 123"
                }
            },
            "ine": {
                "datos_extraidos": {
                    "nombre_completo": "JUAN PEREZ LOPEZ",
                    "curp": "PELJ800101HDFRZN01",
                    "clave_elector": "PRLJNN80010107H800",
                    "fecha_vencimiento": fecha_futura
                }
            },
            "poder": {
                "datos_extraidos": {
                    "nombre_apoderado": "JUAN PEREZ LOPEZ",
                    "numero_escritura": "12345",
                    "nombre_notario": "LIC. ROBERTO GARCIA",
                    "tipo_poder": "PODER GENERAL PARA ACTOS DE ADMINISTRACION"
                }
            },
            "comprobante_domicilio": {
                "datos_extraidos": {
                    "calle": "CALLE PRUEBA",
                    "numero_exterior": "123",
                    "colonia": "CENTRO",
                    "codigo_postal": "06600",
                    "fecha_emision": fecha_reciente
                }
            }
            # Faltan: fiel, estado_cuenta, reforma (todos condicionales)
        }
        
        result = await self.agent.validate_requirements(
            extracted_data=expediente_data,
            expediente_id="TEST-008"
        )
        
        # Debe tener score alto porque solo faltan condicionales
        assert result.validation_score >= 0.6
        
        # Verificar que condicionales estén marcados como NOT_APPLICABLE
        condicionales_faltantes = [
            doc for doc in result.documentos 
            if doc.requerimiento == "Condicional" and not doc.presente
        ]
        assert all(doc.status == RequirementStatus.NOT_APPLICABLE 
                  for doc in condicionales_faltantes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
