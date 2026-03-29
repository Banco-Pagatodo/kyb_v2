"""
Agente de Validación para requisitos documentales KYB.

Este módulo implementa el sistema de validación automática de requisitos
según la Matriz de Requisitos Documentales KYB — México (Personas Morales).
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, date
from api.model.validator import (
    ValidationResult,
    DocumentRequirement,
    RequirementStatus,
    VigenciaType,
    ValidationRule
)
import logging
import re

logger = logging.getLogger(__name__)


class ValidatorAgent:
    """
    Agente especializado en validación de requisitos documentales KYB
    según normativa mexicana para personas morales.
    
    Valida:
    - Vigencias de documentos
    - Protocolización ante notario
    - Coincidencia de datos entre documentos (cross-validation)
    - Facultades suficientes en poderes
    - Certificados vigentes (FIEL)
    - Identidad de representantes legales
    - Requisitos específicos por tipo de documento
    
    El agente genera un score de compliance y determina si el expediente
    es auto-aprobable o requiere revisión manual.
    """
    
    # Matriz de requisitos según normativa KYB México
    DOCUMENT_REQUIREMENTS = {
        "acta_constitutiva": DocumentRequirement(
            documento="Acta Constitutiva",
            requerimiento="Requerido",
            vigencia_maxima=VigenciaType.SIN_VENCIMIENTO,
            requisitos_especificos=[
                "Protocolizada ante Notario Público",
                "Inscrita en el Registro Público de la Propiedad (RPP)",
                "Debe incluir: denominación social",
                "Debe incluir: objeto social",
                "Debe incluir: capital social",
                "Debe incluir: domicilio",
                "Debe incluir: duración",
                "Debe incluir: datos de los socios fundadores"
            ]
        ),
        "comprobante_domicilio": DocumentRequirement(
            documento="Comprobante de Domicilio",
            requerimiento="Requerido",
            vigencia_maxima=VigenciaType.TRES_MESES,
            requisitos_especificos=[
                "Recibo de CFE, Telmex, agua, gas, o predial",
                "A nombre de la persona moral o del representante legal",
                "Debe coincidir con el domicilio fiscal registrado ante el SAT"
            ]
        ),
        "csf": DocumentRequirement(
            documento="Constancia de Situación Fiscal (CSF)",
            requerimiento="Requerido",
            vigencia_maxima=VigenciaType.TRES_MESES,
            requisitos_especificos=[
                "Emitida por el SAT",
                "Debe mostrar: RFC",
                "Debe mostrar: denominación/razón social",
                "Debe mostrar: domicilio fiscal",
                "Debe mostrar: régimen fiscal vigente",
                "Estatus 'Activo' en el padrón de contribuyentes"
            ]
        ),
        "estado_cuenta": DocumentRequirement(
            documento="Estado de Cuenta Bancario",
            requerimiento="Condicional",
            vigencia_maxima=VigenciaType.TRES_MESES,
            requisitos_especificos=[
                "A nombre de la persona moral",
                "Debe mostrar: denominación social",
                "Debe mostrar: número de cuenta/CLABE",
                "Debe mostrar: domicilio"
            ]
        ),
        "fiel": DocumentRequirement(
            documento="FIEL (Firma Electrónica Avanzada)",
            requerimiento="Condicional",
            vigencia_maxima=VigenciaType.VIGENTE,
            requisitos_especificos=[
                "Certificado digital (.cer) emitido por el SAT",
                "Verificar vigencia del certificado",
                "No debe estar revocada",
                "Se requiere para trámites electrónicos"
            ]
        ),
        "ine": DocumentRequirement(
            documento="INE del Representante Legal",
            requerimiento="Requerido",
            vigencia_maxima=VigenciaType.VIGENTE,
            requisitos_especificos=[
                "Credencial para Votar vigente",
                "Verificar que los datos coincidan con el poder notarial",
                "Aceptable también: Pasaporte mexicano vigente o Cédula Profesional"
            ]
        ),
        "ine_reverso": DocumentRequirement(
            documento="INE Reverso del Representante Legal",
            requerimiento="Condicional",
            vigencia_maxima=VigenciaType.VIGENTE,
            requisitos_especificos=[
                "Complementa la INE anverso",
                "Debe contener código MRZ legible",
                "Verificar que los datos coincidan con el anverso"
            ]
        ),
        "poder": DocumentRequirement(
            documento="Poder Notarial",
            requerimiento="Requerido",
            vigencia_maxima=VigenciaType.VIGENTE,
            requisitos_especificos=[
                "Protocolizado ante Notario Público",
                "Debe otorgar facultades suficientes: actos de administración",
                "Debe otorgar facultades suficientes: pleitos y cobranzas",
                "Debe otorgar facultades suficientes: actos de dominio según tipo de relación",
                "Verificar que no haya sido revocado"
            ]
        ),
        "reforma": DocumentRequirement(
            documento="Reforma de Estatutos",
            requerimiento="Condicional",
            vigencia_maxima=VigenciaType.VARIABLE,
            requisitos_especificos=[
                "Requerido solo si hubo modificaciones posteriores al acta constitutiva",
                "Debe estar protocolizada",
                "Debe estar inscrita en el RPP",
                "Incluye cambios a: denominación, objeto social, capital, administración"
            ]
        )
    }
    
    def __init__(self):
        """Inicializa el agente de compliance con reglas de validación."""
        self.validation_rules = self._initialize_rules()
    
    def _initialize_rules(self) -> List[ValidationRule]:
        """Inicializa las reglas de validación de compliance."""
        return [
            ValidationRule(
                rule_id="VIGENCIA_CSF",
                documento_tipo="csf",
                severity="critical",
                description="CSF debe tener vigencia máxima de 3 meses",
                validation_logic="fecha_emision <= today - 90 days",
                error_message="La Constancia de Situación Fiscal tiene más de 3 meses de antigüedad"
            ),
            ValidationRule(
                rule_id="PROTOCOLARIZACION_ACTA",
                documento_tipo="acta_constitutiva",
                severity="critical",
                description="Acta Constitutiva debe estar protocolizada",
                validation_logic="contains 'NOTARIO' or 'NOTARÍA' or 'PROTOCOLIZADA'",
                error_message="El Acta Constitutiva no muestra evidencia de protocolización ante notario"
            ),
            ValidationRule(
                rule_id="RFC_ACTIVO",
                documento_tipo="csf",
                severity="critical",
                description="RFC debe estar en estatus Activo",
                validation_logic="datos_extraidos['estatus_padron'] == 'ACTIVO'",
                error_message="El RFC no está en estatus 'Activo' en el padrón del SAT"
            ),
            ValidationRule(
                rule_id="COINCIDENCIA_RFC",
                documento_tipo="cross_document",
                severity="critical",
                description="RFC debe coincidir en todos los documentos",
                validation_logic="all_rfcs_match()",
                error_message="El RFC no coincide entre los documentos presentados"
            ),
            ValidationRule(
                rule_id="VIGENCIA_INE",
                documento_tipo="ine",
                severity="critical",
                description="INE debe estar vigente",
                validation_logic="fecha_vencimiento >= today",
                error_message="La credencial INE del representante legal está vencida"
            ),
            ValidationRule(
                rule_id="FACULTADES_PODER",
                documento_tipo="poder",
                severity="high",
                description="Poder debe otorgar facultades suficientes",
                validation_logic="has_authority_keywords()",
                error_message="El Poder Notarial no muestra facultades suficientes para actos bancarios"
            ),
            ValidationRule(
                rule_id="VIGENCIA_FIEL",
                documento_tipo="fiel",
                severity="high",
                description="FIEL debe estar vigente y no revocada",
                validation_logic="not_revoked and vigente",
                error_message="La FIEL está vencida o ha sido revocada"
            ),
            ValidationRule(
                rule_id="DOMICILIO_COINCIDE",
                documento_tipo="cross_document",
                severity="high",
                description="Domicilio debe coincidir entre CSF y comprobante",
                validation_logic="addresses_match()",
                error_message="El domicilio fiscal en la CSF no coincide con el comprobante de domicilio"
            )
        ]
    
    async def validate_requirements(
        self,
        extracted_data: Dict[str, Any],
        expediente_id: str
    ) -> ValidationResult:
        """
        Valida cumplimiento de requisitos documentales.
        
        Args:
            extracted_data: Diccionario con datos extraídos de todos los documentos
                           Formato: {"csf": {"datos_extraidos": {...}}, "acta": {...}}
            expediente_id: ID del expediente
            
        Returns:
            ValidationResult con análisis completo del expediente
        """
        
        logger.info(f"Iniciando validación de compliance para expediente {expediente_id}")
        
        documentos = []
        errores_criticos = []
        
        # 1. Validar cada documento individual
        for doc_type, requirement in self.DOCUMENT_REQUIREMENTS.items():
            doc_data = extracted_data.get(doc_type, {})
            
            validated_req = await self._validate_document(
                requirement=requirement,
                doc_type=doc_type,
                doc_data=doc_data
            )
            
            documentos.append(validated_req)
            
            if validated_req.status == RequirementStatus.NON_COMPLIANT:
                errores_criticos.extend(validated_req.errores)
        
        # 2. Validar coincidencias entre documentos
        cross_validation_errors = await self._validate_cross_document(extracted_data)
        errores_criticos.extend(cross_validation_errors)
        
        # 3. Calcular score de compliance (excluir documentos condicionales no aplicables)
        total_requisitos = sum(
            1 for doc in documentos 
            if doc.status != RequirementStatus.NOT_APPLICABLE
        )
        requisitos_cumplidos = sum(
            1 for doc in documentos 
            if doc.status == RequirementStatus.COMPLIANT
        )
        requisitos_fallidos = sum(
            1 for doc in documentos 
            if doc.status == RequirementStatus.NON_COMPLIANT
        )
        requisitos_warning = sum(
            1 for doc in documentos 
            if doc.status == RequirementStatus.WARNING
        )
        
        validation_score = requisitos_cumplidos / total_requisitos if total_requisitos > 0 else 0.0
        
        # 4. Determinar si es auto-aprobable
        auto_aprobable = validation_score >= 0.95 and len(errores_criticos) == 0
        requiere_revision_manual = not auto_aprobable
        
        # 5. Generar recomendaciones
        recomendaciones = self._generate_recommendations(documentos, errores_criticos)
        
        result = ValidationResult(
            expediente_id=expediente_id,
            validation_score=validation_score,
            total_requisitos=total_requisitos,
            requisitos_cumplidos=requisitos_cumplidos,
            requisitos_fallidos=requisitos_fallidos,
            requisitos_warning=requisitos_warning,
            documentos=documentos,
            auto_aprobable=auto_aprobable,
            requiere_revision_manual=requiere_revision_manual,
            errores_criticos=errores_criticos,
            recomendaciones=recomendaciones
        )
        
        logger.info(
            f"Validation complete. Score: {validation_score:.2%}, "
            f"Auto-aprobable: {auto_aprobable}"
        )
        
        return result
    
    async def _validate_document(
        self,
        requirement: DocumentRequirement,
        doc_type: str,
        doc_data: Dict[str, Any]
    ) -> DocumentRequirement:
        """Valida un documento individual según sus requisitos."""
        
        req = requirement.model_copy()
        
        # Verificar si el documento está presente
        if not doc_data or not doc_data.get("datos_extraidos"):
            if requirement.requerimiento == "Requerido":
                req.status = RequirementStatus.NON_COMPLIANT
                req.errores.append(f"{requirement.documento} es requerido pero no fue proporcionado")
            else:
                req.status = RequirementStatus.NOT_APPLICABLE
            return req
        
        req.presente = True
        datos = doc_data.get("datos_extraidos", {})
        
        # Validar vigencia
        vigencia_valid = await self._validate_vigencia(
            doc_type=doc_type,
            vigencia_type=requirement.vigencia_maxima,
            datos=datos
        )
        
        if not vigencia_valid["valid"]:
            req.errores.append(vigencia_valid["error"])
            req.status = RequirementStatus.NON_COMPLIANT
            return req
        
        req.vigente = True
        req.fecha_emision = vigencia_valid.get("fecha_emision")
        req.fecha_vencimiento = vigencia_valid.get("fecha_vencimiento")
        
        # Validar requisitos específicos
        specific_errors, validations = await self._validate_specific_requirements(
            doc_type=doc_type,
            requisitos=requirement.requisitos_especificos,
            datos=datos
        )
        
        if specific_errors:
            req.errores.extend(specific_errors)
            req.status = RequirementStatus.NON_COMPLIANT
        else:
            req.status = RequirementStatus.COMPLIANT
        
        return req
    
    async def _validate_vigencia(
        self,
        doc_type: str,
        vigencia_type: VigenciaType,
        datos: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Valida la vigencia de un documento."""
        
        today = date.today()
        
        # Documentos sin vencimiento o con vigencia variable (ej: Acta Constitutiva, Reforma de Estatutos)
        if vigencia_type in (VigenciaType.SIN_VENCIMIENTO, VigenciaType.VARIABLE):
            return {"valid": True}
        
        # Intentar extraer fechas - soportar múltiples nombres de campo
        # Normalizar valores que pueden venir anidados ({"valor": "...", ...})
        fecha_emision_raw = (
            datos.get("fecha_emision") or 
            datos.get("fecha") or 
            datos.get("vigencia_desde") or 
            datos.get("fecha_corte") or
            datos.get("fecha_otorgamiento")  # Para Reforma de Estatutos, Poder Notarial, Acta
        )
        fecha_vencimiento_raw = datos.get("fecha_vencimiento") or datos.get("vigencia") or datos.get("vigencia_hasta")
        fecha_emision_str = self._extract_field_value(fecha_emision_raw)
        fecha_vencimiento_str = self._extract_field_value(fecha_vencimiento_raw)
        
        # Para estado de cuenta: extraer fecha final del período (ej: "01/08/2025 - 31/08/2025")
        if not fecha_emision_str:
            periodo_raw = datos.get("periodo")
            periodo_str = self._extract_field_value(periodo_raw)
            if periodo_str and " - " in str(periodo_str):
                # Tomar la fecha final del período como fecha de emisión
                fecha_emision_str = str(periodo_str).split(" - ")[-1].strip()
        
        # Para documentos tipo VIGENTE (INE, Poder, FIEL), solo necesitamos fecha_vencimiento
        if vigencia_type == VigenciaType.VIGENTE:
            if fecha_vencimiento_str:
                fecha_vencimiento = self._parse_date(fecha_vencimiento_str)
                if fecha_vencimiento:
                    if fecha_vencimiento < today:
                        return {
                            "valid": False,
                            "error": f"El documento venció el {fecha_vencimiento}",
                            "fecha_vencimiento": fecha_vencimiento
                        }
                    return {
                        "valid": True,
                        "fecha_vencimiento": fecha_vencimiento
                    }
            # Si no hay fecha_vencimiento, asumimos que está vigente
            return {"valid": True}
        
        # Para otros tipos (TRES_MESES), requiere fecha_emision
        if not fecha_emision_str:
            return {
                "valid": False,
                "error": f"No se pudo determinar la fecha de emisión del documento"
            }
        
        # Parsear fecha
        fecha_emision = self._parse_date(fecha_emision_str)
        if not fecha_emision:
            return {
                "valid": False,
                "error": f"Formato de fecha inválido: {fecha_emision_str}"
            }
        
        # Validar tipo TRES_MESES (CSF, Comprobante Domicilio, Estado Cuenta)
        if vigencia_type == VigenciaType.TRES_MESES:
            max_age = timedelta(days=90)
            edad_documento = today - fecha_emision
            
            if edad_documento > max_age:
                return {
                    "valid": False,
                    "error": f"El documento tiene {edad_documento.days} días de antigüedad (máximo 90 días)",
                    "fecha_emision": fecha_emision
                }
        
        # Documento válido
        return {
            "valid": True,
            "fecha_emision": fecha_emision,
            "fecha_vencimiento": self._parse_date(fecha_vencimiento_str) if fecha_vencimiento_str else None
        }
    
    def _validate_document_type_match(
        self,
        expected_type: str,
        datos: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Valida que el documento extraído sea realmente del tipo esperado.
        
        Verifica la presencia de campos clave únicos de cada tipo de documento
        para detectar si se subió un documento incorrecto.
        
        Args:
            expected_type: Tipo de documento esperado (csf, acta, poder, etc.)
            datos: Datos extraídos del documento
            
        Returns:
            Dict con keys:
                - is_correct (bool): True si el documento parece ser del tipo correcto
                - detected_type (str): Tipo detectado más probable
                - confidence (float): Confianza de la detección (0.0 - 1.0)
        """
        
        # Campos clave únicos por tipo de documento
        KEY_FIELDS = {
            "csf": {
                "required": ["rfc", "regimen_fiscal"],
                "optional": ["denominacion_razon_social", "domicilio_fiscal", "estatus"],
                "keywords": ["CONSTANCIA", "SITUACIÓN FISCAL", "SAT", "RÉGIMEN"]
            },
            "acta_constitutiva": {
                "required": ["folio_mercantil", "numero_escritura"],
                "optional": ["nombre_notario", "numero_notaria", "denominacion_social"],
                "keywords": ["ACTA CONSTITUTIVA", "ESCRITURA PÚBLICA", "NOTARIO", "PROTOCOLIZACIÓN"]
            },
            "poder": {
                "required": ["poderdante", "apoderado"],
                "optional": ["facultades", "nombre_notario", "numero_escritura"],
                "keywords": ["PODER", "OTORGA", "APODERADO", "FACULTADES"]
            },
            "ine": {
                "required": ["curp"],
                "optional": ["clave_elector", "nombre", "fecha_nacimiento", "vigencia"],
                "keywords": ["CREDENCIAL", "VOTAR", "ELECTORAL", "CURP", "ELECTOR"]
            },
            "ine_reverso": {
                "required": ["mrz"],
                "optional": ["fecha_nacimiento", "vigencia"],
                "keywords": ["MRZ", "CREDENCIAL", "REVERSO"]
            },
            "fiel": {
                "required": ["numero_serie_certificado"],
                "optional": ["rfc", "vigencia_certificado", "razon_social"],
                "keywords": ["CERTIFICADO", "FIEL", "FIRMA ELECTRÓNICA", "SAT"]
            },
            "comprobante_domicilio": {
                "required": ["domicilio"],
                "optional": ["fecha_emision", "titular"],
                "keywords": ["CFE", "TELMEX", "AGUA", "RECIBO", "DOMICILIO"]
            },
            "estado_cuenta": {
                "required": ["numero_cuenta"],
                "optional": ["titular", "periodo", "saldo", "clabe"],
                "keywords": ["ESTADO DE CUENTA", "BANCO", "SALDO", "MOVIMIENTOS"]
            },
            "reforma": {
                "required": ["reforma_numero_escritura"],
                "optional": ["reforma_folio_mercantil", "reforma_nombre_notario"],
                "keywords": ["REFORMA", "ESTATUTOS", "MODIFICACIÓN", "PROTOCOLIZACIÓN"]
            }
        }
        
        if expected_type not in KEY_FIELDS:
            return {
                "is_correct": True,
                "detected_type": expected_type,
                "confidence": 1.0
            }
        
        # Preparar texto para búsqueda de keywords (priorizar texto_ocr)
        texto_ocr = str(datos.get("texto_ocr", "")).upper()
        texto_completo = str(datos.get("texto_completo", "")).upper()
        texto_busqueda = texto_ocr if texto_ocr else texto_completo
        
        # Verificar campos del tipo esperado
        expected_fields = KEY_FIELDS[expected_type]
        required_found = 0
        optional_found = 0
        keywords_found = 0
        
        # Contar campos requeridos presentes
        for field in expected_fields["required"]:
            value = self._extract_field_value(datos.get(field))
            if value:
                required_found += 1
        
        # Contar campos opcionales presentes
        for field in expected_fields["optional"]:
            value = self._extract_field_value(datos.get(field))
            if value:
                optional_found += 1
        
        # Buscar keywords en texto de búsqueda
        for keyword in expected_fields["keywords"]:
            if keyword in texto_busqueda:
                keywords_found += 1
        
        # Calcular score para tipo esperado
        total_required = len(expected_fields["required"])
        total_optional = len(expected_fields["optional"])
        total_keywords = len(expected_fields["keywords"])
        
        required_score = required_found / total_required if total_required > 0 else 0
        optional_score = optional_found / total_optional if total_optional > 0 else 0
        keyword_score = keywords_found / total_keywords if total_keywords > 0 else 0
        
        # Score ponderado adaptativo:
        # - Si NO hay campos extraídos: keywords tienen 100% peso (caso documento del tipo incorrecto)
        # - Si hay campos: requeridos 50%, opcionales 30%, keywords 20%
        if required_score == 0 and optional_score == 0:
            # Sin campos extraídos - confiar solo en keywords
            expected_score = keyword_score
        else:
            # Con campos extraídos - ponderación normal
            expected_score = (required_score * 0.5) + (optional_score * 0.3) + (keyword_score * 0.2)
        
        # Si el score es muy bajo (<30%), verificar si parece otro tipo
        if expected_score < 0.3:
            # Calcular scores para otros tipos
            best_match = expected_type
            best_score = expected_score
            
            for doc_type, fields in KEY_FIELDS.items():
                if doc_type == expected_type:
                    continue
                
                type_required = 0
                type_optional = 0
                type_keywords = 0
                
                for field in fields["required"]:
                    if self._extract_field_value(datos.get(field)):
                        type_required += 1
                
                for field in fields["optional"]:
                    if self._extract_field_value(datos.get(field)):
                        type_optional += 1
                
                for keyword in fields["keywords"]:
                    if keyword in texto_busqueda:
                        type_keywords += 1
                
                # Calcular score con ponderación adaptativa
                type_required_score = (type_required / len(fields["required"])) if len(fields["required"]) > 0 else 0
                type_optional_score = (type_optional / len(fields["optional"])) if len(fields["optional"]) > 0 else 0
                type_keyword_score = (type_keywords / len(fields["keywords"])) if len(fields["keywords"]) > 0 else 0
                
                if type_required_score == 0 and type_optional_score == 0:
                    # Sin campos - confiar solo en keywords
                    type_score = type_keyword_score
                else:
                    # Con campos - ponderación normal
                    type_score = (type_required_score * 0.5) + (type_optional_score * 0.3) + (type_keyword_score * 0.2)
                
                if type_score > best_score:
                    best_match = doc_type
                    best_score = type_score
            
            # Si encontramos mejor match en otro tipo
            if best_match != expected_type and best_score > 0.4:
                return {
                    "is_correct": False,
                    "detected_type": best_match,
                    "confidence": best_score
                }
        
        # El documento parece ser del tipo correcto
        return {
            "is_correct": expected_score >= 0.3,
            "detected_type": expected_type if expected_score >= 0.3 else "desconocido",
            "confidence": expected_score
        }
    
    async def _validate_specific_requirements(
        self,
        doc_type: str,
        requisitos: List[str],
        datos: Dict[str, Any]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """
        Valida requisitos específicos por tipo de documento.
        
        Returns:
            Tupla de (lista_errores, lista_validaciones_detalladas)
        """
        from api.model.orchestrator import ValidationDetail
        
        # Mapeo de validadores por tipo de documento
        validators = {
            "acta_constitutiva": self._validate_acta_constitutiva,
            "csf": self._validate_csf,
            "poder": self._validate_poder_notarial,
            "fiel": self._validate_fiel,
            "ine": self._validate_ine,
            "ine_reverso": self._validate_ine_reverso,
            "comprobante_domicilio": self._validate_comprobante_domicilio,
            "estado_cuenta": self._validate_estado_cuenta,
            "reforma": self._validate_reforma
        }
        
        validator = validators.get(doc_type)
        if validator:
            return validator(datos, requisitos)
        
        return [], []
    
    def _validate_acta_constitutiva(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Acta Constitutiva."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Verificar protocolización - puede venir en texto_completo o como campo nombre_notario
        texto_completo = datos.get("texto_completo", "").upper()
        nombre_notario = datos.get("nombre_notario", "")
        numero_notaria = datos.get("numero_notaria", "")
        
        tiene_evidencia_notarial = bool(
            nombre_notario or 
            numero_notaria or
            any(keyword in texto_completo for keyword in ["NOTARIO", "NOTARÍA", "PROTOCOLIZADA"])
        )
        if not tiene_evidencia_notarial:
            errors.append("El Acta Constitutiva no muestra evidencia de protocolización ante notario")
        
        # Verificar campos obligatorios según lo que extrae el servicio
        # Campo: numero_escritura_poliza
        if not datos.get("numero_escritura_poliza") and not datos.get("numero_escritura"):
            errors.append("Falta número de escritura/póliza en el Acta Constitutiva")
        
        # Campo: fecha_constitucion o fecha_expedicion
        has_fecha = (
            datos.get("fecha_constitucion") or 
            datos.get("fecha_expedicion") or
            datos.get("fecha")
        )
        if not has_fecha:
            errors.append("Falta fecha de constitución/expedición en el Acta Constitutiva")
        
        # Campo: folio_mercantil (puede estar pendiente de inscripción)
        folio = datos.get("folio_mercantil", "")
        if folio and "PENDIENTE" in str(folio).upper():
            # Warning, no error - es válido que esté pendiente
            pass
        elif not folio:
            errors.append("Falta folio mercantil en el Acta Constitutiva (puede indicar que no está inscrita)")
        
        # Campo: nombre_notario
        if not nombre_notario:
            errors.append("Falta nombre del notario en el Acta Constitutiva")
        
        # Campo: clausula_extranjeros - debe estar presente
        clausula = datos.get("clausula_extranjeros", "")
        if not clausula:
            errors.append("Falta cláusula de admisión/exclusión de extranjeros")
        
        # Campos adicionales de la matriz de validación
        denominacion_social = datos.get("denominacion_social", "") or datos.get("razon_social", "")
        
        # Crear validaciones detalladas
        validations.append(ValidationDetail(
            tipo="acta_protocolizacion",
            passed=tiene_evidencia_notarial,
            mensaje="Acta protocolizada ante notario" if tiene_evidencia_notarial else "Sin evidencia de protocolización",
            datos={"notario": nombre_notario, "notaria": numero_notaria}
        ))
        
        validations.append(ValidationDetail(
            tipo="acta_folio_mercantil",
            passed=bool(folio),
            mensaje=f"Folio mercantil: {folio}" if folio else "Folio mercantil no disponible",
            datos={"folio": folio}
        ))
        
        validations.append(ValidationDetail(
            tipo="acta_fecha_constitucion",
            passed=bool(has_fecha),
            mensaje="Fecha de constitución presente" if has_fecha else "Fecha de constitución no disponible",
            datos={"fecha": datos.get("fecha_constitucion") or datos.get("fecha_expedicion")}
        ))
        
        validations.append(ValidationDetail(
            tipo="acta_notario",
            passed=bool(nombre_notario),
            mensaje=f"Notario: {nombre_notario}" if nombre_notario else "Notario no disponible",
            datos={"notario": nombre_notario, "numero_notaria": numero_notaria}
        ))
        
        validations.append(ValidationDetail(
            tipo="acta_denominacion_social",
            passed=bool(denominacion_social),
            mensaje=f"Denominación social: {denominacion_social}" if denominacion_social else "Denominación social no disponible",
            datos={"denominacion_social": denominacion_social}
        ))
        
        return errors, validations
    
    def _validate_csf(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Constancia de Situación Fiscal."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # 1. Verificar RFC presente
        rfc = datos.get("rfc")
        rfc_presente = bool(rfc and str(rfc).strip())
        validations.append(ValidationDetail(
            tipo="campo_rfc",
            passed=rfc_presente,
            mensaje=f"RFC presente: {rfc}" if rfc_presente else "Falta RFC",
            datos={"rfc": rfc if rfc_presente else None}
        ))
        if not rfc_presente:
            errors.append("Falta RFC en la Constancia de Situación Fiscal")
        
        # 2. Verificar formato RFC (12-13 caracteres alfanuméricos)
        rfc_formato_valido = False
        if rfc_presente:
            rfc_str = str(rfc).strip().upper()
            rfc_formato_valido = len(rfc_str) in [12, 13] and rfc_str.isalnum()
            validations.append(ValidationDetail(
                tipo="campo_rfc_formato",
                passed=rfc_formato_valido,
                mensaje=f"RFC formato válido: {rfc_str}" if rfc_formato_valido else f"RFC formato inválido: {rfc_str} (debe ser 12-13 caracteres alfanuméricos)",
                datos={"rfc": rfc_str, "longitud": len(rfc_str)}
            ))
            if not rfc_formato_valido:
                errors.append(f"RFC con formato inválido: {rfc_str} (debe tener 12-13 caracteres alfanuméricos)")
        
        # 3. Verificar estatus activo
        estatus = datos.get("estatus_padron", "").upper()
        estatus_activo = estatus == "ACTIVO"
        validations.append(ValidationDetail(
            tipo="campo_estatus",
            passed=estatus_activo,
            mensaje=f"Estatus 'ACTIVO'" if estatus_activo else f"Estatus: {estatus}" if estatus else "Estatus no disponible",
            datos={"estatus_padron": estatus}
        ))
        if estatus and not estatus_activo:
            errors.append(f"El RFC no está en estatus 'Activo' (estatus actual: {estatus})")
        
        # 4. Razón social - múltiples nombres posibles de campo
        has_razon_social = (
            datos.get("denominacion_razon_social") or 
            datos.get("nombre_razon_social") or
            datos.get("razon_social")
        )
        razon_social_presente = bool(has_razon_social and str(has_razon_social).strip())
        validations.append(ValidationDetail(
            tipo="campo_denominacion_razon_social",
            passed=razon_social_presente,
            mensaje=f"Denominación/razón social presente: {has_razon_social}" if razon_social_presente else "Falta denominación/razón social",
            datos={"razon_social": has_razon_social if razon_social_presente else None}
        ))
        if not razon_social_presente:
            errors.append("Falta denominación/razón social en la CSF")
        
        # 5. Domicilio fiscal - múltiples nombres posibles
        has_domicilio = (
            datos.get("domicilio_fiscal") or 
            datos.get("domicilio") or
            datos.get("direccion") or
            datos.get("codigo_postal")
        )
        domicilio_presente = bool(has_domicilio and str(has_domicilio).strip())
        validations.append(ValidationDetail(
            tipo="campo_domicilio_fiscal",
            passed=domicilio_presente,
            mensaje=f"Domicilio fiscal presente" if domicilio_presente else "Falta domicilio fiscal",
            datos={"domicilio": has_domicilio if domicilio_presente else None}
        ))
        if not domicilio_presente:
            errors.append("Falta domicilio fiscal en la CSF")
        
        # 6. Régimen fiscal / giro mercantil
        has_regimen = (
            datos.get("regimen_fiscal") or 
            datos.get("regimen") or
            datos.get("giro_mercantil") or
            datos.get("actividad_preponderante")
        )
        regimen_presente = bool(has_regimen and str(has_regimen).strip())
        validations.append(ValidationDetail(
            tipo="campo_regimen_fiscal",
            passed=regimen_presente,
            mensaje=f"Régimen fiscal presente: {has_regimen}" if regimen_presente else "Falta régimen fiscal",
            datos={"regimen_fiscal": has_regimen if regimen_presente else None}
        ))
        if not regimen_presente:
            errors.append("Falta régimen fiscal en la CSF")
        
        return errors, validations
    
    def _validate_poder_notarial(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Poder Notarial."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Extraer valores (pueden venir anidados con "valor")
        numero_escritura = self._extract_field_value(datos.get("numero_escritura"))
        nombre_notario = self._extract_field_value(datos.get("nombre_notario"))
        tipo_poder = self._extract_field_value(datos.get("tipo_poder")) or ""
        facultades = self._extract_field_value(datos.get("facultades")) or ""
        
        # Verificar protocolización: debe tener número de escritura y nombre del notario
        tiene_escritura = bool(numero_escritura and str(numero_escritura).strip() and str(numero_escritura).lower() not in ['n/a', 'pendiente'])
        tiene_notario = bool(nombre_notario and str(nombre_notario).strip() and str(nombre_notario).lower() not in ['n/a', 'pendiente'])
        
        if not tiene_escritura or not tiene_notario:
            # Solo marcar error si faltan ambos
            if not tiene_escritura and not tiene_notario:
                errors.append("El Poder Notarial no muestra evidencia de protocolización")
        
        # Verificar facultades suficientes buscando en tipo_poder y facultades
        texto_facultades = f"{tipo_poder} {facultades}".upper()
        
        facultades_keywords = [
            "ADMINISTRACIÓN", "ADMINISTRACION",
            "PLEITOS", "COBRANZAS",
            "DOMINIO",
            "GENERALES",
            "REPRESENTAR", "CONTRATAR",
            "CELEBRAR CONTRATOS"
        ]
        
        tiene_facultades = any(keyword in texto_facultades for keyword in facultades_keywords)
        if not tiene_facultades:
            errors.append("El Poder Notarial no contiene las facultades suficientes requeridas para operaciones bancarias")
        
        # Extraer campos adicionales de la matriz
        poderdante = (
            self._extract_field_value(datos.get("nombre_poderdante")) or 
            self._extract_field_value(datos.get("poderdante")) or 
            self._extract_field_value(datos.get("otorgante"))
        )
        apoderado = (
            self._extract_field_value(datos.get("nombre_apoderado")) or 
            self._extract_field_value(datos.get("apoderado")) or 
            self._extract_field_value(datos.get("representante"))
        )
        fecha_otorgamiento = (
            self._extract_field_value(datos.get("fecha_otorgamiento")) or 
            self._extract_field_value(datos.get("fecha_expedicion"))
        )
        
        validations.append(ValidationDetail(
            tipo="poder_protocolizacion",
            passed=tiene_escritura and tiene_notario,
            mensaje="Poder protocolizado" if (tiene_escritura and tiene_notario) else "Sin evidencia de protocolización",
            datos={"escritura": numero_escritura, "notario": nombre_notario}
        ))
        
        validations.append(ValidationDetail(
            tipo="poder_facultades",
            passed=tiene_facultades,
            mensaje="Facultades suficientes presentes" if tiene_facultades else "Faltan facultades suficientes",
            datos={"tipo_poder": tipo_poder, "facultades": facultades}
        ))
        
        validations.append(ValidationDetail(
            tipo="poder_poderdante",
            passed=bool(poderdante),
            mensaje=f"Poderdante: {poderdante}" if poderdante else "Poderdante no disponible",
            datos={"poderdante": poderdante}
        ))
        
        validations.append(ValidationDetail(
            tipo="poder_apoderado",
            passed=bool(apoderado),
            mensaje=f"Apoderado: {apoderado}" if apoderado else "Apoderado no disponible",
            datos={"apoderado": apoderado}
        ))
        
        validations.append(ValidationDetail(
            tipo="poder_fecha_otorgamiento",
            passed=bool(fecha_otorgamiento),
            mensaje=f"Fecha de otorgamiento: {fecha_otorgamiento}" if fecha_otorgamiento else "Fecha de otorgamiento no disponible",
            datos={"fecha_otorgamiento": fecha_otorgamiento}
        ))
        
        return errors, validations
    
    def _validate_fiel(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para FIEL."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # 1. Verificar RFC del certificado
        rfc = datos.get("rfc")
        rfc_presente = bool(rfc and str(rfc).strip())
        validations.append(ValidationDetail(
            tipo="fiel_rfc",
            passed=rfc_presente,
            mensaje=f"RFC en certificado FIEL: {rfc}" if rfc_presente else "RFC no disponible",
            datos={"rfc": rfc}
        ))
        if not rfc_presente:
            errors.append("No se pudo extraer el RFC del certificado FIEL")
        
        # 2. Verificar número de serie del certificado
        numero_serie = datos.get("numero_serie_certificado")
        numero_serie_presente = bool(numero_serie and str(numero_serie).strip())
        validations.append(ValidationDetail(
            tipo="fiel_numero_serie",
            passed=numero_serie_presente,
            mensaje=f"Número de serie: {numero_serie}" if numero_serie_presente else "Número de serie no disponible",
            datos={"numero_serie_certificado": numero_serie}
        ))
        if not numero_serie_presente:
            errors.append("No se pudo extraer el número de serie del certificado FIEL")
        
        # 3. Verificar razón social
        razon_social = datos.get("razon_social")
        razon_social_presente = bool(razon_social and str(razon_social).strip())
        validations.append(ValidationDetail(
            tipo="fiel_razon_social",
            passed=razon_social_presente,
            mensaje=f"Razón social: {razon_social}" if razon_social_presente else "Razón social no disponible",
            datos={"razon_social": razon_social}
        ))
        if not razon_social_presente:
            errors.append("No se pudo extraer la razón social del certificado FIEL")
        
        return errors, validations
    
    def _validate_ine(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para INE."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Extraer valores (pueden venir anidados con "valor")
        nombre_completo = self._extract_field_value(datos.get("nombre_completo")) or self._extract_field_value(datos.get("nombre"))
        curp = self._extract_field_value(datos.get("curp"))
        # El extractor de INE devuelve DocumentNumber para la clave de elector
        clave_elector = self._extract_field_value(datos.get("clave_elector")) or self._extract_field_value(datos.get("DocumentNumber"))
        fecha_nacimiento = self._extract_field_value(datos.get("fecha_nacimiento")) or self._extract_field_value(datos.get("DateOfBirth"))
        
        # Verificar campos obligatorios - al menos nombre
        tiene_nombre = nombre_completo and str(nombre_completo).strip() and str(nombre_completo).lower() not in ['n/a', 'pendiente']
        if not tiene_nombre:
            errors.append("No se pudo extraer el nombre completo de la INE")
        
        # CURP o clave de elector deben existir
        tiene_identificador = (curp and str(curp).strip() and len(str(curp).strip()) >= 10) or \
                              (clave_elector and str(clave_elector).strip() and len(str(clave_elector).strip()) >= 10)
        if not tiene_identificador:
            errors.append("No se pudo extraer el CURP o clave de elector de la INE")
        
        # Validar formato CURP (18 caracteres)
        curp_formato_valido = False
        if curp:
            curp_str = str(curp).strip().upper()
            curp_formato_valido = len(curp_str) == 18 and curp_str.isalnum()
        
        validations.append(ValidationDetail(
            tipo="ine_nombre",
            passed=tiene_nombre,
            mensaje=f"Nombre completo: {nombre_completo}" if tiene_nombre else "Nombre no disponible",
            datos={"nombre": nombre_completo}
        ))
        
        validations.append(ValidationDetail(
            tipo="ine_curp",
            passed=bool(curp),
            mensaje=f"CURP: {curp}" if curp else "CURP no disponible",
            datos={"curp": curp}
        ))
        
        validations.append(ValidationDetail(
            tipo="ine_curp_formato",
            passed=curp_formato_valido,
            mensaje=f"CURP formato válido (18 caracteres)" if curp_formato_valido else "CURP formato inválido o no disponible",
            datos={"curp": curp, "longitud": len(str(curp)) if curp else 0}
        ))
        
        validations.append(ValidationDetail(
            tipo="ine_fecha_nacimiento",
            passed=bool(fecha_nacimiento),
            mensaje=f"Fecha de nacimiento: {fecha_nacimiento}" if fecha_nacimiento else "Fecha de nacimiento no disponible",
            datos={"fecha_nacimiento": fecha_nacimiento}
        ))
        
        validations.append(ValidationDetail(
            tipo="ine_clave_elector",
            passed=bool(clave_elector),
            mensaje=f"Clave de elector presente" if clave_elector else "Clave de elector no disponible",
            datos={"clave_elector": clave_elector}
        ))
        
        return errors, validations
    
    def _validate_ine_reverso(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para INE reverso.
        
        Nota: El reverso del INE contiene:
        - MRZ (Machine Readable Zone): 3 líneas con formato IDMEX...
        - Información electoral
        - Código QR
        
        NO contiene domicilio (eso está en el frente).
        """
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Extraer valores (pueden venir anidados con "valor")
        nombre_completo = (
            self._extract_field_value(datos.get("nombre_completo")) or 
            self._extract_field_value(datos.get("nombre")) or
            self._extract_field_value(datos.get("FirstName"))
        )
        
        # El reverso debe tener al menos el código MRZ o nombre
        idmex = self._extract_field_value(datos.get("IdMex"))
        tiene_mrz = idmex and str(idmex).strip() and len(str(idmex).strip()) > 20
        
        tiene_nombre = nombre_completo and str(nombre_completo).strip() and str(nombre_completo).lower() not in ['n/a', 'pendiente']
        
        if not tiene_mrz and not tiene_nombre:
            errors.append("El reverso de la INE no contiene código MRZ legible ni nombre")
        
        validations.append(ValidationDetail(
            tipo="ine_reverso_mrz",
            passed=tiene_mrz or tiene_nombre,
            mensaje="Código MRZ legible" if tiene_mrz else ("Nombre presente" if tiene_nombre else "MRZ y nombre no disponibles"),
            datos={"idmex": idmex, "nombre": nombre_completo}
        ))
        
        # El reverso no contiene domicilio - validar fecha de nacimiento y vigencia desde MRZ
        fecha_nacimiento = self._extract_field_value(datos.get("DateOfBirth")) or self._extract_field_value(datos.get("fecha_nacimiento"))
        fecha_expiracion = self._extract_field_value(datos.get("DateOfExpiration")) or self._extract_field_value(datos.get("vigencia"))
        
        validations.append(ValidationDetail(
            tipo="ine_reverso_fecha_nacimiento",
            passed=bool(fecha_nacimiento),
            mensaje=f"Fecha de nacimiento: {fecha_nacimiento}" if fecha_nacimiento else "Fecha de nacimiento no disponible",
            datos={"fecha_nacimiento": fecha_nacimiento}
        ))
        
        validations.append(ValidationDetail(
            tipo="ine_reverso_vigencia",
            passed=bool(fecha_expiracion),
            mensaje=f"Vigencia: {fecha_expiracion}" if fecha_expiracion else "Vigencia no disponible",
            datos={"vigencia": fecha_expiracion}
        ))
        
        return errors, validations
    
    def _validate_comprobante_domicilio(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Comprobante de Domicilio."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Verificar que tenga calle o dirección
        calle = self._extract_field_value(datos.get("calle"))
        colonia = self._extract_field_value(datos.get("colonia"))
        codigo_postal = self._extract_field_value(datos.get("codigo_postal"))
        
        tiene_direccion = (calle and str(calle).strip() and str(calle).lower() not in ['n/a', 'pendiente']) or \
                          (colonia and str(colonia).strip() and str(colonia).lower() not in ['n/a', 'pendiente']) or \
                          (codigo_postal and str(codigo_postal).strip())
        
        if not tiene_direccion:
            errors.append("No se pudo extraer el domicilio del comprobante")
        
        validations.append(ValidationDetail(
            tipo="comprobante_domicilio",
            passed=tiene_direccion,
            mensaje="Domicilio presente" if tiene_direccion else "Domicilio no disponible",
            datos={"calle": calle, "colonia": colonia, "codigo_postal": codigo_postal}
        ))
        
        return errors, validations
    
    def _validate_estado_cuenta(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Estado de Cuenta."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Verificar campos obligatorios
        cuenta_presente = bool(datos.get("cuenta") or datos.get("clabe"))
        validations.append(ValidationDetail(
            tipo="estado_cuenta_numero",
            passed=cuenta_presente,
            mensaje=f"Número de cuenta presente: {datos.get('cuenta') or datos.get('clabe')}" if cuenta_presente else "Número de cuenta no disponible",
            datos={"cuenta": datos.get("cuenta"), "clabe": datos.get("clabe")}
        ))
        if not cuenta_presente:
            errors.append("No se pudo extraer el número de cuenta o CLABE")
        
        titular_presente = bool(datos.get("denominacion_social") or datos.get("titular"))
        validations.append(ValidationDetail(
            tipo="estado_cuenta_titular",
            passed=titular_presente,
            mensaje=f"Titular presente: {datos.get('denominacion_social') or datos.get('titular')}" if titular_presente else "Titular no disponible",
            datos={"titular": datos.get("denominacion_social") or datos.get("titular")}
        ))
        if not titular_presente:
            errors.append("No se pudo extraer la denominación social del titular")
        
        # Verificar período
        periodo = datos.get("periodo") or datos.get("fecha_corte")
        saldo = datos.get("saldo") or datos.get("saldo_final")
        
        validations.append(ValidationDetail(
            tipo="estado_cuenta_periodo",
            passed=bool(periodo),
            mensaje=f"Período: {periodo}" if periodo else "Período no disponible",
            datos={"periodo": periodo}
        ))
        
        validations.append(ValidationDetail(
            tipo="estado_cuenta_saldo",
            passed=bool(saldo),
            mensaje=f"Saldo presente" if saldo else "Saldo no disponible",
            datos={"saldo": saldo}
        ))
        
        return errors, validations
    
    def _validate_reforma(
        self,
        datos: Dict[str, Any],
        requisitos: List[str]
    ) -> Tuple[List[str], List["ValidationDetail"]]:
        """Validaciones específicas para Reforma de Estatutos."""
        from api.model.orchestrator import ValidationDetail
        
        errors = []
        validations = []
        
        # Campo: numero_escritura
        numero_escritura = datos.get("numero_escritura", "")
        numero_escritura_valido = bool(numero_escritura and str(numero_escritura).strip())
        validations.append(ValidationDetail(
            tipo="reforma_numero_escritura",
            passed=numero_escritura_valido,
            mensaje=f"Número de escritura: {numero_escritura}" if numero_escritura_valido else "Número de escritura no disponible",
            datos={"numero_escritura": numero_escritura}
        ))
        if not numero_escritura_valido:
            errors.append("Falta número de escritura en la Reforma de Estatutos")
        
        # Campo: razon_social
        razon_social = datos.get("razon_social", "")
        razon_social_valida = bool(razon_social and len(str(razon_social)) > 3)
        validations.append(ValidationDetail(
            tipo="reforma_razon_social",
            passed=razon_social_valida,
            mensaje=f"Razón social: {razon_social}" if razon_social_valida else "Razón social no disponible",
            datos={"razon_social": razon_social}
        ))
        if not razon_social_valida:
            errors.append("Falta razón social en la Reforma de Estatutos")
        
        # Campo: fecha_otorgamiento
        fecha_otorgamiento = datos.get("fecha_otorgamiento", "")
        fecha_valida = bool(fecha_otorgamiento)
        validations.append(ValidationDetail(
            tipo="reforma_fecha_otorgamiento",
            passed=fecha_valida,
            mensaje=f"Fecha de otorgamiento: {fecha_otorgamiento}" if fecha_valida else "Fecha de otorgamiento no disponible",
            datos={"fecha_otorgamiento": fecha_otorgamiento}
        ))
        if not fecha_valida:
            errors.append("Falta fecha de otorgamiento en la Reforma de Estatutos")
        
        # Campo: nombre_notario
        nombre_notario = datos.get("nombre_notario", "")
        notario_valido = bool(nombre_notario and len(str(nombre_notario).split()) >= 2)
        validations.append(ValidationDetail(
            tipo="reforma_nombre_notario",
            passed=notario_valido,
            mensaje=f"Notario: {nombre_notario}" if notario_valido else "Nombre del notario no disponible",
            datos={"nombre_notario": nombre_notario}
        ))
        if not notario_valido:
            errors.append("Falta nombre del notario en la Reforma de Estatutos")
        
        # Campo: numero_notaria
        numero_notaria = datos.get("numero_notaria", "")
        numero_notaria_valido = bool(numero_notaria and str(numero_notaria).strip())
        validations.append(ValidationDetail(
            tipo="reforma_numero_notaria",
            passed=numero_notaria_valido,
            mensaje=f"Número de notaría: {numero_notaria}" if numero_notaria_valido else "Número de notaría no disponible",
            datos={"numero_notaria": numero_notaria}
        ))
        if not numero_notaria_valido:
            errors.append("Falta número de notaría en la Reforma de Estatutos")
        
        # Campo: folio_mercantil
        folio_mercantil = datos.get("folio_mercantil", "")
        folio_valido = bool(folio_mercantil and len(str(folio_mercantil)) >= 4)
        validations.append(ValidationDetail(
            tipo="reforma_folio_mercantil",
            passed=folio_valido,
            mensaje=f"Folio mercantil: {folio_mercantil}" if folio_valido else "Folio mercantil no disponible",
            datos={"folio_mercantil": folio_mercantil}
        ))
        if not folio_valido:
            errors.append("Falta folio mercantil en la Reforma de Estatutos")
        
        # Campo: estructura_accionaria
        estructura = datos.get("estructura_accionaria", "")
        estructura_valida = False
        if isinstance(estructura, list) and len(estructura) > 0:
            estructura_valida = True
            estructura_desc = f"{len(estructura)} accionistas"
        elif estructura and len(str(estructura)) > 10:
            estructura_valida = True
            estructura_desc = "Estructura accionaria presente"
        else:
            estructura_desc = "Estructura accionaria no disponible"
        
        validations.append(ValidationDetail(
            tipo="reforma_estructura_accionaria",
            passed=estructura_valida,
            mensaje=estructura_desc,
            datos={"estructura_accionaria": estructura}
        ))
        if not estructura_valida:
            errors.append("Falta estructura accionaria en la Reforma de Estatutos")
        
        return errors, validations
    
    async def _validate_cross_document(
        self,
        extracted_data: Dict[str, Any]
    ) -> List[str]:
        """Valida coincidencias entre documentos (cross-validation)."""
        
        errors = []
        
        # 1. Validar coincidencia de RFC
        rfcs = {}
        for doc_type in ["csf", "fiel", "acta_constitutiva"]:
            doc_data = extracted_data.get(doc_type, {})
            rfc = doc_data.get("datos_extraidos", {}).get("rfc")
            if rfc:
                rfcs[doc_type] = rfc.upper().strip()
        
        if len(set(rfcs.values())) > 1:
            errors.append(
                f"El RFC no coincide entre documentos: {', '.join(f'{doc}: {rfc}' for doc, rfc in rfcs.items())}"
            )
        
        # 2. Validar coincidencia de denominación social
        denominaciones = {}
        for doc_type in ["csf", "acta_constitutiva"]:
            doc_data = extracted_data.get(doc_type, {})
            datos = doc_data.get("datos_extraidos", {})
            denom = datos.get("denominacion_social") or datos.get("denominacion_razon_social") or datos.get("nombre_razon_social")
            if denom:
                denominaciones[doc_type] = denom.upper().strip()
        
        if len(denominaciones) > 1:
            valores_unicos = set(denominaciones.values())
            if len(valores_unicos) > 1:
                errors.append(
                    f"La denominación social no coincide entre documentos: "
                    f"{', '.join(f'{doc}: {denom}' for doc, denom in denominaciones.items())}"
                )
        
        # 3. Validar coincidencia de domicilio
        domicilio_csf = extracted_data.get("csf", {}).get("datos_extraidos", {}).get("domicilio_fiscal")
        domicilio_comprobante = extracted_data.get("comprobante_domicilio", {}).get("datos_extraidos", {}).get("domicilio")
        
        if domicilio_csf and domicilio_comprobante:
            similarity = self._calculate_address_similarity(domicilio_csf, domicilio_comprobante)
            if similarity < 0.7:
                errors.append(
                    f"El domicilio fiscal en la CSF no coincide suficientemente con el comprobante de domicilio "
                    f"(similitud: {similarity:.0%})"
                )
        
        # 4. Validar que representante legal en INE coincida con poder
        nombre_ine = extracted_data.get("ine", {}).get("datos_extraidos", {}).get("nombre_completo") or \
                     extracted_data.get("ine", {}).get("datos_extraidos", {}).get("nombre")
        nombre_poder = extracted_data.get("poder", {}).get("datos_extraidos", {}).get("nombre_apoderado") or \
                       extracted_data.get("poder", {}).get("datos_extraidos", {}).get("apoderado")
        
        if nombre_ine and nombre_poder:
            if not self._names_match(nombre_ine, nombre_poder):
                errors.append(
                    f"El nombre en la INE no coincide con el nombre del apoderado en el Poder Notarial"
                )
        
        return errors
    
    def _generate_recommendations(
        self,
        documentos: List[DocumentRequirement],
        errores_criticos: List[str]
    ) -> List[str]:
        """Genera recomendaciones basadas en los errores encontrados."""
        
        recomendaciones = []
        
        # Documentos faltantes
        faltantes = [doc.documento for doc in documentos 
                    if doc.status == RequirementStatus.MISSING and doc.requerimiento == "Requerido"]
        if faltantes:
            recomendaciones.append(
                f"Documentos requeridos faltantes: {', '.join(faltantes)}. Deben ser proporcionados para continuar."
            )
        
        # Documentos vencidos
        vencidos = [doc.documento for doc in documentos if not doc.vigente and doc.presente]
        if vencidos:
            recomendaciones.append(
                f"Documentos vencidos: {', '.join(vencidos)}. Deben actualizarse a versiones vigentes."
            )
        
        # Errores de protocolización
        if any("protocolización" in error.lower() or "protocolizacion" in error.lower() for error in errores_criticos):
            recomendaciones.append(
                "Verificar que los documentos notariales estén debidamente protocolizados e inscritos en el RPP."
            )
        
        # Errores de coincidencia
        if any("no coincide" in error.lower() for error in errores_criticos):
            recomendaciones.append(
                "Revisar que los datos (RFC, denominación, domicilio) sean consistentes entre todos los documentos."
            )
        
        # Errores de estatus
        if any("estatus" in error.lower() or "activo" in error.lower() for error in errores_criticos):
            recomendaciones.append(
                "Verificar estatus del RFC ante el SAT. Debe estar en estatus 'Activo'."
            )
        
        return recomendaciones
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parsea una fecha en múltiples formatos comunes."""
        
        if not date_str:
            return None
        
        # Limpiar string
        date_str = str(date_str).strip()
        
        # Mapeo de meses en español (mayúsculas y minúsculas)
        meses_es = {
            "ENE": "01", "ENERO": "01",
            "FEB": "02", "FEBRERO": "02",
            "MAR": "03", "MARZO": "03",
            "ABR": "04", "ABRIL": "04",
            "MAY": "05", "MAYO": "05",
            "JUN": "06", "JUNIO": "06",
            "JUL": "07", "JULIO": "07",
            "AGO": "08", "AGOSTO": "08",
            "SEP": "09", "SEPTIEMBRE": "09", "SEPT": "09",
            "OCT": "10", "OCTUBRE": "10",
            "NOV": "11", "NOVIEMBRE": "11",
            "DIC": "12", "DICIEMBRE": "12"
        }
        
        # Intentar convertir meses en español a números
        # Ejemplo: "31/JUL/2025" -> "31/07/2025"
        date_str_upper = date_str.upper()
        for mes_nombre, mes_num in meses_es.items():
            if mes_nombre in date_str_upper:
                date_str = date_str_upper.replace(mes_nombre, mes_num)
                break
        
        formats = [
            "%d/%m/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%Y/%m/%d",
            "%d %b %Y",
            "%d %B %Y",
            "%d/%b/%Y",  # 31/Jul/2025
            "%d-%b-%Y",  # 31-Jul-2025
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        return None
    
    def _calculate_address_similarity(self, addr1: str, addr2: str) -> float:
        """Calcula similitud entre dos direcciones usando fuzzy matching (Levenshtein)."""
        from thefuzz import fuzz
        
        # Normalizar
        a1 = self._normalize_address(addr1)
        a2 = self._normalize_address(addr2)
        
        # Usar token_sort_ratio para manejar orden diferente de palabras
        # y partial_ratio para substrings
        token_sort = fuzz.token_sort_ratio(a1, a2)
        partial = fuzz.partial_ratio(a1, a2)
        
        # Promedio ponderado: token_sort es mejor para direcciones
        # porque maneja "CALLE 5 NUM 10" vs "NUM 10 CALLE 5"
        return (token_sort * 0.7 + partial * 0.3) / 100.0
    
    def _normalize_address(self, addr: str) -> str:
        """Normaliza una dirección para comparación."""
        import re
        import unicodedata
        
        # Uppercase y strip
        result = addr.upper().strip()
        
        # Remover acentos
        result = unicodedata.normalize('NFKD', result)
        result = ''.join(c for c in result if not unicodedata.combining(c))
        
        # Expandir abreviaciones comunes
        replacements = {
            r'\bAV\.?\b': 'AVENIDA',
            r'\bCOL\.?\b': 'COLONIA',
            r'\bNUM\.?\b': 'NUMERO',
            r'\bNO\.?\b': 'NUMERO',
            r'\bC\.?P\.?\b': 'CP',
            r'\bEDIF\.?\b': 'EDIFICIO',
            r'\bDEPTO?\.?\b': 'DEPARTAMENTO',
            r'\bINT\.?\b': 'INTERIOR',
            r'\bPISO\b': 'PISO',
            r'\bMZA?\.?\b': 'MANZANA',
            r'\bLTE?\.?\b': 'LOTE',
        }
        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result)
        
        # Remover caracteres especiales excepto alfanuméricos y espacios
        result = re.sub(r'[^A-Z0-9\s]', ' ', result)
        
        # Normalizar espacios múltiples
        result = re.sub(r'\s+', ' ', result).strip()
        
        return result
    
    def _names_match(self, name1: str, name2: str) -> bool:
        """Verifica si dos nombres coinciden usando fuzzy matching."""
        from thefuzz import fuzz
        import unicodedata
        
        # Normalizar (uppercase, sin acentos)
        def normalize(s: str) -> str:
            s = s.upper().strip()
            s = unicodedata.normalize('NFKD', s)
            return ''.join(c for c in s if not unicodedata.combining(c))
        
        n1 = normalize(name1)
        n2 = normalize(name2)
        
        # Exacto después de normalización
        if n1 == n2:
            return True
        
        # Token set ratio es ideal para nombres:
        # "ROBERTO GARCIA MARTINEZ" vs "GARCIA MARTINEZ ROBERTO" → 100%
        # También maneja nombres con/sin segundo apellido
        token_set = fuzz.token_set_ratio(n1, n2)
        
        # Umbral de 80% para nombres (más estricto que direcciones)
        return token_set >= 80
    
    # =========================================================================
    # MÉTODOS PÚBLICOS PARA VALIDACIÓN DE DOCUMENTO INDIVIDUAL
    # =========================================================================
    
    def validate_single_document(
        self,
        doc_type: str,
        extracted_data: Dict[str, Any],
        fecha_referencia: Optional[date] = None
    ) -> "SingleDocumentValidation":
        """
        Valida un documento individual contra requisitos KYB (versión síncrona).
        
        Método público para uso en endpoints individuales (/docs/*).
        Aplica las mismas reglas que el flujo unificado del Orchestrator.
        
        Args:
            doc_type: Tipo de documento (ej: "constancia_situacion_fiscal")
            extracted_data: Datos extraídos por el agente de análisis
            fecha_referencia: Fecha para calcular vigencia (default: hoy)
        
        Returns:
            SingleDocumentValidation con status, errores y compliance score
        """
        import asyncio
        
        # Ejecutar la versión async sincrónicamente
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Si ya hay un loop corriendo, crear una tarea
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    self._validate_single_document_async(doc_type, extracted_data, fecha_referencia)
                )
            else:
                return loop.run_until_complete(
                    self._validate_single_document_async(doc_type, extracted_data, fecha_referencia)
                )
        except RuntimeError:
            # No hay loop, crear uno nuevo
            return asyncio.run(
                self._validate_single_document_async(doc_type, extracted_data, fecha_referencia)
            )
    
    async def _validate_single_document_async(
        self,
        doc_type: str,
        extracted_data: Dict[str, Any],
        fecha_referencia: Optional[date] = None
    ) -> "SingleDocumentValidation":
        """Versión async interna de validate_single_document."""
        from api.model.validator import SingleDocumentValidation, RequirementStatus
        
        if fecha_referencia is None:
            fecha_referencia = date.today()
        
        # Mapear doc_type a clave de DOCUMENT_REQUIREMENTS
        doc_key = self._normalize_doc_type_key(doc_type)
        
        # Obtener requisitos del documento
        if doc_key not in self.DOCUMENT_REQUIREMENTS:
            return SingleDocumentValidation(
                documento_tipo=doc_type,
                es_requerido=False,
                status=RequirementStatus.NOT_APPLICABLE,
                errores=[f"Tipo de documento '{doc_type}' no tiene requisitos KYB definidos"],
                compliance_score=0.0
            )
        
        requirement = self.DOCUMENT_REQUIREMENTS[doc_key].model_copy(deep=True)
        
        # Obtener datos extraídos
        datos = extracted_data
        
        # Determinar si es requerido
        es_requerido = requirement.requerimiento == "Requerido"
        
        # Estructuras de resultado
        errores = []
        warnings = []
        campos_validados = {}  # Nuevo formato: {"campo": "compliant"|"non_compliant"}
        recomendaciones = []
        fecha_emision = None
        fecha_vencimiento = None
        vigente = False
        status = RequirementStatus.NON_COMPLIANT
        
        # Validar tipo de documento
        # Usar document_identification del DocumentIdentifierAgent si está disponible
        doc_identification = datos.get("document_identification", {})
        if doc_identification:
            # Usar resultado del DocumentIdentifierAgent (más preciso)
            documento_tipo_correcto = doc_identification.get("is_correct", True)
            confianza_tipo = 1.0 if documento_tipo_correcto else 0.0
            should_reject = doc_identification.get("should_reject", False)
        else:
            # Fallback al método interno
            doc_type_validation = self._validate_document_type_match(doc_key, datos)
            documento_tipo_correcto = doc_type_validation["is_correct"]
            confianza_tipo = doc_type_validation["confidence"]
            should_reject = not documento_tipo_correcto

        if should_reject:
            errores.append(
                f"El documento subido no corresponde al tipo esperado '{doc_key}'. "
                f"Por favor suba el documento correcto."
            )
            # Retorno temprano: no validar campos con datos de tipo de documento incorrecto
            return SingleDocumentValidation(
                documento_tipo=doc_type,
                es_requerido=es_requerido,
                status=RequirementStatus.NON_COMPLIANT,
                vigente=False,
                fecha_emision=None,
                fecha_vencimiento=None,
                documento_tipo_correcto=False,
                confianza_tipo=0.0,
                errores=errores,
                warnings=[],
                compliance_score=0.0,
                campos_validados={},
                recomendaciones=["Suba el documento correcto para este endpoint."]
            )

        # 1. Validar vigencia
        vigencia_result = await self._validate_vigencia(
            doc_type=doc_key,
            vigencia_type=requirement.vigencia_maxima,
            datos=datos
        )
        
        vigente = vigencia_result.get("valid", True)
        fecha_emision = vigencia_result.get("fecha_emision")
        fecha_vencimiento = vigencia_result.get("fecha_vencimiento")
        
        # Agregar vigencia al diccionario de campos validados
        campos_validados["vigencia"] = "compliant" if vigente else "non_compliant"
        
        if not vigente:
            if vigencia_result.get("error"):
                errores.append(vigencia_result.get("error"))
                warnings.append("El documento no está vigente o no se pudo determinar vigencia")
        
        # 2. Validar requisitos específicos (ahora retorna validaciones detalladas)
        specific_errors, specific_validations = await self._validate_specific_requirements(
            doc_type=doc_key,
            requisitos=requirement.requisitos_especificos,
            datos=datos
        )
        
        # Incorporar validaciones específicas al diccionario
        for validation in specific_validations:
            campos_validados[validation.tipo] = "compliant" if validation.passed else "non_compliant"
        
        errores.extend(specific_errors)
        
        # Determinar status basado en campos no compliant
        campos_no_compliant = [k for k, v in campos_validados.items() if v == "non_compliant"]
        if campos_no_compliant:
            status = RequirementStatus.NON_COMPLIANT
        elif warnings:
            status = RequirementStatus.COMPLIANT_WITH_OBSERVATIONS
        else:
            status = RequirementStatus.COMPLIANT
        
        # Calcular compliance score
        total_campos = len(campos_validados)
        campos_compliant = sum(1 for v in campos_validados.values() if v == "compliant")
        if total_campos > 0:
            compliance_score = campos_compliant / total_campos
        else:
            compliance_score = 1.0 if status == RequirementStatus.COMPLIANT else 0.0
        
        # Generar recomendaciones
        if campos_no_compliant:
            recomendaciones.append(f"Completar los siguientes campos: {', '.join(campos_no_compliant)}")
        if not vigente:
            recomendaciones.append("Obtener documento con fecha de emisión reciente")
        
        return SingleDocumentValidation(
            documento_tipo=doc_type,
            es_requerido=es_requerido,
            status=status,
            vigente=vigente,
            fecha_emision=fecha_emision,
            fecha_vencimiento=fecha_vencimiento,
            documento_tipo_correcto=documento_tipo_correcto,
            confianza_tipo=confianza_tipo,
            errores=errores,
            warnings=warnings,
            compliance_score=round(compliance_score, 2),
            campos_validados=campos_validados,
            recomendaciones=recomendaciones
        )
    
    def _normalize_doc_type_key(self, doc_type: str) -> str:
        """Normaliza el tipo de documento a la clave usada en DOCUMENT_REQUIREMENTS."""
        # Las claves en DOCUMENT_REQUIREMENTS son:
        # acta_constitutiva, comprobante_domicilio, csf, estado_cuenta, fiel, ine, ine_reverso, poder, reforma
        mapping = {
            "csf": "csf",
            "constancia_situacion_fiscal": "csf",
            "constancia": "csf",
            "fiel": "fiel",
            "efirma": "fiel",
            "estado_cuenta": "estado_cuenta",
            "estadocuenta": "estado_cuenta",
            "domicilio": "comprobante_domicilio",
            "comprobante_domicilio": "comprobante_domicilio",
            "acta_constitutiva": "acta_constitutiva",
            "acta": "acta_constitutiva",
            "poder_notarial": "poder",
            "poder": "poder",
            "reforma_estatutos": "reforma",
            "reforma": "reforma",
            "ine": "ine",
            "identificacion": "ine",
            "ine_back": "ine",
            "ine_reverso": "ine_reverso",
        }
        return mapping.get(doc_type.lower().strip(), doc_type.lower().strip())
    
    def _get_required_fields_for_doc(self, doc_key: str) -> List[str]:
        """Retorna los campos obligatorios según el tipo de documento.
        
        IMPORTANTE: Estos campos deben coincidir con los nombres que retornan
        los extractores en api/service/openai.py
        """
        required_fields = {
            # CSF extrae: rfc, razon_social, giro_mercantil, fecha_emision
            "csf": ["rfc", "razon_social"],
            
            # FIEL extrae: rfc, vigencia_desde, vigencia_hasta
            "fiel": ["rfc", "vigencia_hasta"],
            
            # Estado cuenta extrae: titular/banco, numero_cuenta, periodo
            "estado_cuenta": ["numero_cuenta"],
            
            # Comprobante domicilio: calle, colonia, codigo_postal, fecha_emision
            "comprobante_domicilio": ["calle"],
            
            # Acta constitutiva extrae: numero_escritura_poliza, nombre_notario, folio_mercantil
            "acta_constitutiva": ["numero_escritura_poliza", "nombre_notario"],
            
            # Poder notarial
            "poder": ["numero_escritura", "nombre_notario"],
            
            # Reforma estatutos
            "reforma": ["numero_escritura"],
            
            # INE - El extractor devuelve DocumentNumber para clave de elector
            "ine": ["nombre_completo", "DocumentNumber"],
            
            # INE Reverso - El extractor devuelve IdMex (código MRZ) y datos personales
            "ine_reverso": ["IdMex"],
        }
        return required_fields.get(doc_key, [])
    
    def _extract_field_value(self, valor_raw: Any) -> Any:
        """Extrae el valor real de un campo que puede venir anidado.
        
        Los campos pueden venir en formato:
        - String directo: "2028-09-23"
        - Dict con valor: {"valor": "2028-09-23", "confiabilidad": 70, ...}
        
        Retorna el valor real en ambos casos.
        """
        if valor_raw is None:
            return None
        
        # Si es un dict con clave "valor", extraer el valor real
        if isinstance(valor_raw, dict):
            return valor_raw.get("valor", valor_raw)
        
        return valor_raw


# Instancia global del agente
validator_agent = ValidatorAgent()
