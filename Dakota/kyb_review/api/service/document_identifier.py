"""
DocumentIdentifierAgent - Agente de Identificación de Tipo de Documento KYB.

Este agente se ejecuta DESPUÉS de la extracción OCR de Azure Document Intelligence
y ANTES del procesamiento LLM. Su propósito es clasificar si el documento subido
corresponde al tipo esperado por el endpoint.

Sistema de 4 Señales (v2.0):
1. Keywords exclusivos (peso 35%)
2. Estructura de páginas (peso 20%)  
3. Fingerprint de campos extraídos (peso 20%)
4. LLM semántico - GPT-4o (peso 25%) - solo si es ambiguo

El LLM solo se invoca si las señales 1+2+3 están en zona ambigua (0.40-0.75).
"""

import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Tipos de documento soportados."""
    CSF = "csf"
    ACTA_CONSTITUTIVA = "acta_constitutiva"
    PODER = "poder"
    INE = "ine"
    INE_REVERSO = "ine_reverso"
    FIEL = "fiel"
    COMPROBANTE_DOMICILIO = "comprobante_domicilio"
    ESTADO_CUENTA = "estado_cuenta"
    REFORMA = "reforma"


@dataclass
class IdentificationResult:
    """Resultado de la identificación de documento."""
    is_correct: bool
    expected_type: str
    detected_type: str
    confidence: float
    discriminants_found: List[str]
    negative_indicators: List[str]
    reasoning: str
    should_reject: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_correct": self.is_correct,
            "expected_type": self.expected_type,
            "reasoning": self.reasoning,
            "should_reject": self.should_reject
        }


class DocumentIdentifierAgent:
    """
    Agente que identifica el tipo de documento basándose en el texto OCR.
    
    Usa tres mecanismos:
    1. Keywords EXCLUSIVOS (discriminantes): Solo aparecen en UN tipo de documento
    2. Keywords NEGATIVOS: Indican que el documento NO es de cierto tipo
    3. LLM Fallback: Para casos ambiguos con confianza < 0.5
    
    Ventaja vs sistema anterior:
    - El scoring anterior usaba campos como RFC que aparecen en múltiples tipos
    - Este sistema usa palabras/frases que son ÚNICAS de cada tipo
    """
    
    # =========================================================================
    # KEYWORDS EXCLUSIVOS (DISCRIMINANTES)
    # Estas palabras/frases SOLO aparecen en documentos de ese tipo
    # =========================================================================
    DISCRIMINANT_KEYWORDS = {
        DocumentType.CSF: [
            "CONSTANCIA DE SITUACIÓN FISCAL",
            "CÉDULA DE IDENTIFICACIÓN FISCAL",
            "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA",
            "RÉGIMEN FISCAL",
            "ACTIVIDADES ECONÓMICAS",
            "OBLIGACIONES FISCALES",
            "FECHA DE INICIO DE OPERACIONES",
            "FECHA DE ÚLTIMO CAMBIO DE ESTADO",
            "SITUACIÓN DEL CONTRIBUYENTE",
            "PADRÓN DE CONTRIBUYENTES",
        ],
        DocumentType.ACTA_CONSTITUTIVA: [
            # =====================================================================
            # DISCRIMINANTES EXCLUSIVOS DE ACTA CONSTITUTIVA
            # SOLO frases que aparecen en el cuerpo principal de una Acta nueva,
            # NO en documentos que citan históricamente la creación de la empresa
            # (ej. un Poder Notarial puede citar la Acta, pero su ACTO es "otorgar poder")
            # =====================================================================

            # === CONSTITUCIÓN (la esencia del Acta) ===
            "ACTA CONSTITUTIVA",
            "CONSTITUCION DE SOCIEDAD",
            "CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO",  # Frase de constitución literal
            "LOS COMPARECIENTES CONSTITUYEN",
            "CONSTITUYENTES DECLARAN",

            # === TIPO DE SOCIEDAD (en el cuerpo constitutivo, no en nombre social) ===
            "SOCIEDAD ANONIMA DE CAPITAL VARIABLE",
            "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
            "SOCIEDAD POR ACCIONES SIMPLIFICADA",

            # === ESTRUCTURA CORPORATIVA INICIAL ===
            # Solo aparecen cuando se DEFINEN POR PRIMERA VEZ en el acta
            "CAPITAL SOCIAL MINIMO",      # "el Capital Social Mínimo Fijo es de..."
            "ACCIONES EN QUE SE DIVIDE",  # "las acciones en que se divide el capital"
            "PRIMER EJERCICIO SOCIAL",    # Exclusivo del primer ejercicio — solo en Acta

            # === CLAUSULADO INICIAL EXCLUSIVO ===
            "DENOMINACION DE LA SOCIEDAD",   # Cláusula que nombra la empresa
            "DURACION DE LA SOCIEDAD",       # Cláusula exclusiva del Acta original
            "NOVENTA Y NUEVE ANOS",          # Duración típica — solo en el Acta
            "CLAUSULAS TRANSITORIAS",        # Sección final del Acta constitutiva

            # === ADMINISTRACIÓN INICIAL ===
            "ADMINISTRADOR UNICO",   # Cargo que solo se designa en el Acta
            "COMISARIO",             # Figura del Acta Constitutiva
        ],
        DocumentType.PODER: [
            # =====================================================================
            # DISCRIMINANTES DE PODER NOTARIAL
            # Frases que aparecen en documentos que otorgan poderes:
            # - Poderes Notariales standalone
            # - Protocolizaciones de Actas de Asamblea que otorgan poderes
            # - Sesiones de Consejo de Administración para otorgar poderes
            #
            # En KYB, cualquiera de estos documentos se acepta como "Poder".
            # =====================================================================
            
            # === PODERDANTE Y APODERADO (sujetos del Poder) ===
            "PODERDANTE",
            "EN SU CALIDAD DE PODERDANTE",
            "EL PODERDANTE DECLARA",
            "COMPARECE COMO PODERDANTE",
            "APODERADO DESIGNADO",
            "EN CALIDAD DE APODERADO",
            "EL APODERADO QUEDA FACULTADO",
            "AL APODERADO SE LE CONFIERE",
            "REPRESENTANTE LEGAL",
            
            # === OTORGAMIENTO DE PODER (acción principal) ===
            "OTORGA PODER A FAVOR DE",
            "CONFIERE PODER A FAVOR DE",
            "SE OTORGA PODER",
            "PODER QUE SE OTORGA",
            "PODER QUE SE CONFIERE",
            "EL PRESENTE PODER",
            "INSTRUMENTO DE PODER",
            "POR MEDIO DEL PRESENTE SE OTORGA",
            
            # === TIPOS DE PODER (aparecen al otorgar facultades) ===
            "PODER GENERAL",
            "PODER ESPECIAL",
            "PODER CAMBIARIO",
            "PODER GENERAL PARA",
            "PODER AMPLIO",
            "PLEITOS Y COBRANZAS",
            "ACTOS DE ADMINISTRACION",
            "ACTOS DE DOMINIO",
            "SUSCRIBIR TITULOS DE CREDITO",
            "PODERES Y FACULTADES",
            "FACULTADES GENERALES",
            "CLAUSULA ESPECIAL",
            "CUMPLIDO Y BASTANTE",
            
            # === BOLETA DE INSCRIPCIÓN - TIPO DE ACTO ===
            "OTORGAMIENTO DE PODERES Y FACULTADES",
            "OTORGAMIENTO DE PODERES",
            "M1-ACTA DE SESION DE CONSEJO DE ADMINISTRACION",
            
            # === PROTOCOLIZACIÓN (forma común de Poderes en KYB) ===
            "PROTOCOLIZACION DE ACTA",
            "COMPARECE A PROTOCOLIZAR",
            "ANTE MI COMPARECE",
            "DOY FE",
            
            # === SESIÓN DEL CONSEJO PARA OTORGAR PODERES ===
            "SE LE OTORGARA",
            "SE LE OTORGARAN LAS FACULTADES",
            "APROBACION DEL OTORGAMIENTO DE",
            "EN SU CASO, APROBACION DEL OTORGAMIENTO",
            "EN MATERIA LABORAL",
            
            # === MANDATO (sinónimo legal de poder) ===
            "MANDATARIO",
            "MANDANTE",
            
            # === REVOCACIÓN (solo en Poderes) ===
            "REVOCACION DE PODER",
            "REVOCA EL PODER",
            "QUEDA REVOCADO",
            "SUSTITUCION DE PODER",
            
            # === TIPOS DE PODER COMO DOCUMENTO ===
            "CARTA PODER",
            "PODER NOTARIAL",
            "PODER IRREVOCABLE",
            "PODER ANTE NOTARIO",
        ],
        DocumentType.INE: [
            "INSTITUTO NACIONAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "CLAVE DE ELECTOR",
            "SECCIÓN ELECTORAL",
            "AÑO DE REGISTRO",
            "ESTADO DONDE VOTA",
            "MUNICIPIO DONDE VOTA",
            "LOCALIDAD DONDE VOTA",
        ],
        DocumentType.INE_REVERSO: [
            "IDMEX",  # Código en reverso INE (específico)
            "<<",  # MRZ siempre tiene estos caracteres
            "INEMEX",  # Código MRZ específico de INE
            "M<<",  # Patrón MRZ mexicano
        ],
        DocumentType.FIEL: [
            "CERTIFICADO DE SELLO DIGITAL",
            "FIRMA ELECTRÓNICA AVANZADA",
            "CERTIFICADO DIGITAL",
            "NÚMERO DE SERIE DEL CERTIFICADO",
            "FECHA DE INICIO DE VIGENCIA DEL CERTIFICADO",
            "FECHA DE FIN DE VIGENCIA DEL CERTIFICADO",
            "CLAVE PÚBLICA",
            "ALGORITMO DE FIRMA",
        ],
        DocumentType.COMPROBANTE_DOMICILIO: [
            # CFE - Comisión Federal de Electricidad
            "COMISION FEDERAL DE ELECTRICIDAD",
            "CFE SUMINISTRADOR",
            "CFE DISTRIBUCION",
            "CFE370814QI0",  # RFC de CFE
            "CONSUMO DEL PERIODO",
            "PERIODO DE CONSUMO",
            "TARIFA DOMESTICA",
            "NUMERO DE SERVICIO",
            "DATOS DEL SERVICIO",
            "MEDIDOR",
            "KWH",
            "LECTURA ANTERIOR",
            "LECTURA ACTUAL",
            "AVISO RECIBO",
            # Servicios de agua
            "SISTEMA DE AGUAS",
            "SACMEX",
            "AGUA POTABLE",
            "CONSUMO FACTURADO",
            # Telecomunicaciones - TELMEX
            "TELMEX",
            "TELEFONOS DE MEXICO",
            "TME840315-KT6",  # RFC de TELMEX (con guiones, formato oficial)
            "TME840315KT6",   # RFC de TELMEX (sin guiones, variante OCR)
            "SERVICIOS DE TELECOMUNICACIONES",
            "MES DE FACTURACION",
            "FACTURA NO",
            "PAGAR ANTES DE",
            # Otras empresas de telecomunicaciones
            "TOTALPLAY",
            "IZZI",
            "MEGACABLE",
            "AXTEL",
            # Gas
            "GAS NATURAL",
            "NATURGY",
            # Genéricos de recibos
            "IMPORTE A PAGAR",
            "TOTAL A PAGAR",
            "FECHA DE VENCIMIENTO",
            "NO PAGAR DESPUES",
            "SERVICIO DOMESTICO",
            "CARGOS DEL MES",
        ],
        DocumentType.ESTADO_CUENTA: [
            "ESTADO DE CUENTA",
            "RESUMEN DE MOVIMIENTOS",
            "SALDO ANTERIOR",
            "SALDO ACTUAL",
            "SALDO PROMEDIO",
            "CUENTA CLABE",
            "CUENTA DE CHEQUES",
            "DEPÓSITOS",
            "RETIROS",
            "COMISIONES COBRADAS",
            "FECHA DE CORTE",
            "MOVIMIENTOS DEL PERIODO",
        ],
        DocumentType.REFORMA: [
            # =====================================================================
            # DISCRIMINANTES EXCLUSIVOS DE REFORMA DE ESTATUTOS
            # La diferencia clave: SIEMPRE referencia una escritura anterior
            # (el Acta Constitutiva original que modifica)
            # =====================================================================
            
            # === MODIFICACIÓN (la esencia de la Reforma) ===
            "REFORMA DE ESTATUTOS",
            "REFORMAR LOS ESTATUTOS",
            "REFORMA AL ACTA CONSTITUTIVA",
            "MODIFICACION DE ESTATUTOS",
            "MODIFICACION AL ACTA",
            "REFORMA TOTAL DE ESTATUTOS",
            "REFORMA PARCIAL DE ESTATUTOS",
            
            # === REFERENCIA A ESCRITURA ANTERIOR (CLAVE!) ===
            "EN RELACION CON LA ESCRITURA",
            "EN MODIFICACION A LA ESCRITURA",
            "MODIFICA LA CLAUSULA",
            "SE MODIFICA LA CLAUSULA",
            "REFORMAR LA CLAUSULA",
            "SE REFORMA LA CLAUSULA",
            "EN EJERCICIO DE LAS FACULTADES QUE LE CONFIERE",
            
            # === ASAMBLEA QUE APRUEBA REFORMA ===
            "ASAMBLEA EXTRAORDINARIA DE ACCIONISTAS",
            "ASAMBLEA GENERAL EXTRAORDINARIA",
            "ACUERDOS DE LA ASAMBLEA EXTRAORDINARIA",
            
            # === INDICADORES DE MODIFICACIÓN TEXTUAL ===
            "PARA QUEDAR COMO SIGUE",
            "MODIFICACION A LOS ESTATUTOS",
            "MODIFICACION DE LOS ESTATUTOS",
            "RATIFICACION DEL CONSEJO",
            "PROTOCOLIZACION DEL ACTA DE ASAMBLEA",
            
            # === TIPOS DE MODIFICACIONES ===
            "AUMENTO DE CAPITAL",
            "AUMENTO DEL CAPITAL SOCIAL",
            "REDUCCION DE CAPITAL",
            "REDUCCION DEL CAPITAL SOCIAL",
            "CAMBIO DE DENOMINACION",
            "CAMBIO DE RAZON SOCIAL",
            "CAMBIO DE OBJETO SOCIAL",
            "MODIFICACION DEL OBJETO SOCIAL",
            "FUSION",
            "ESCISION",
            "TRANSFORMACION DE SOCIEDAD",
            
            # === INSCRIPCIÓN DE LA REFORMA ===
            "INSCRIPCION DE LA REFORMA",
            "SE INSCRIBIO LA REFORMA",
        ],
    }
    
    # =========================================================================
    # KEYWORDS NEGATIVOS
    # Si aparecen, el documento NO es de ese tipo
    # =========================================================================
    NEGATIVE_KEYWORDS = {
        DocumentType.CSF: [
            # Si tiene estos, NO es CSF
            "ESCRITURA PUBLICA",
            "PROTOCOLIZACION",
            "ANTE LA FE",
            "ACTA CONSTITUTIVA",
            "PODER GENERAL",
            "PODER ESPECIAL",
            "CREDENCIAL PARA VOTAR",
            "ESTADO DE CUENTA",
            "CERTIFICADO DE SELLO DIGITAL",
            # Indicadores de comprobante de domicilio (CFE)
            "COMISION FEDERAL DE ELECTRICIDAD",
            "CFE370814QI0",
            "PERIODO DE CONSUMO",
            "CONSUMO DEL PERIODO",
            "LECTURA ANTERIOR",
            "LECTURA ACTUAL",
            "KWH",
            "MEDIDOR",
            "TARIFA DOMESTICA",
            "AVISO RECIBO",
            "IMPORTE A PAGAR",
            "SACMEX",
            # Indicadores de comprobante de domicilio (TELMEX)
            "TELMEX",
            "TELEFONOS DE MEXICO",
            "TME840315KT6",
            "MES DE FACTURACION",
            "SERVICIOS DE TELECOMUNICACIONES",
            "TOTAL A PAGAR",
            "PAGAR ANTES DE",
            "CARGOS DEL MES",
            # Otras telecom
            "TOTALPLAY",
            "IZZI",
            "MEGACABLE",
        ],
        DocumentType.ACTA_CONSTITUTIVA: [
            # Si tiene estos, NO es Acta Constitutiva (es otro tipo)
            # NOTA: NO incluir "PODER GENERAL" ni "PODER ESPECIAL" porque
            # las Actas SÍ otorgan estas facultades a los administradores
            "REFORMA DE ESTATUTOS",
            "MODIFICACION DE ESTATUTOS",
            "EN MODIFICACION A LA ESCRITURA",  # Indica Reforma, no Acta original
            "CONSTANCIA DE SITUACION FISCAL",
            "SERVICIO DE ADMINISTRACION TRIBUTARIA",
            "CREDENCIAL PARA VOTAR",
            "ESTADO DE CUENTA",
            "CERTIFICADO DE SELLO DIGITAL",
            # Indicadores de Poder como documento (no como facultad)
            "PODERDANTE",  # Esto indica un Poder, no un Acta
            "EN SU CALIDAD DE PODERDANTE",
            # El acto inscrito en el RPP revela el propósito real del documento:
            # si es "Otorgamiento de poderes", NO es Acta Constitutiva
            "OTORGAMIENTO DE PODERES Y FACULTADES",  # Boleta RPP de un Poder
            "ACTA DE SESION DEL CONSEJO DE ADMINISTRACION",  # Protocolización de sesión → Poder
            "OTORGA PODER A FAVOR DE",
            "CONFIERE PODER A FAVOR DE",
        ],
        DocumentType.PODER: [
            # =====================================================================
            # NEGATIVOS DE PODER: Si aparecen, NO es un Poder Notarial
            #
            # IMPORTANTE: Los Poderes Notariales SIEMPRE citan la empresa que
            # otorga el poder (acta constitutiva, folio mercantil, S.A. DE C.V.,
            # duración de la sociedad, etc.) como ANTECEDENTES.
            # Esos términos NO son negativos.
            #
            # Solo incluir frases que indican que el ACTO PRINCIPAL del documento
            # es CONSTITUIR una sociedad nueva, NO otorgar poder.
            # =====================================================================
            
            # === Indicadores de ACTA CONSTITUTIVA (el ACTO es constituir) ===
            # Solo frases que indican el ACTO de constitución, no meras referencias
            "CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO",
            "LOS COMPARECIENTES CONSTITUYEN",
            "PRIMER EJERCICIO SOCIAL",
            
            # === Indicadores de otros documentos ===
            "ESTADO DE CUENTA",
        ],
        DocumentType.INE: [
            # Si tiene estos, NO es INE anverso
            "IDMEX",  # Solo está en reverso
            "<<",  # MRZ solo en reverso
            "PROTOCOLIZACIÓN",
            "ESCRITURA",
        ],
        DocumentType.INE_REVERSO: [
            # Si tiene estos, NO es INE reverso (es otra cosa)
            "DOMICILIO",  # Domicilio solo en anverso
            "SECCIÓN ELECTORAL",  # Solo en anverso
            # Comprobantes de domicilio (NO son INE reverso)
            "TELMEX",
            "TELEFONOS DE MEXICO",
            "COMISION FEDERAL DE ELECTRICIDAD",
            "CFE SUMINISTRADOR",
            "CFE DISTRIBUCION",
            "TOTALPLAY",
            "IZZI",
            "MEGACABLE",
            "NATURGY",
            "GAS NATURAL",
            "SACMEX",
            "SISTEMA DE AGUAS",
            "IMPORTE A PAGAR",
            "TOTAL A PAGAR",
            "PAGAR ANTES DE",
            "MES DE FACTURACION",
            "ESTADO DE CUENTA",
        ],
        DocumentType.FIEL: [
            # Si tiene estos, NO es FIEL
            "ACTA CONSTITUTIVA",
            "PODER NOTARIAL",
            "CREDENCIAL PARA VOTAR",
            "ESTADO DE CUENTA",
        ],
        DocumentType.COMPROBANTE_DOMICILIO: [
            # Si tiene estos, NO es comprobante domicilio
            "ESCRITURA PÚBLICA",
            "PROTOCOLIZACIÓN",
            # RFC: eliminado — los recibos de servicio (TELMEX, CFE) incluyen su propio RFC
            "RÉGIMEN FISCAL",  # Exclusivo de CSF
            # Bancarios: si aparecen, es estado de cuenta, no recibo de servicio
            "SALDO ANTERIOR",
            "FECHA DE CORTE",
            "CUENTA CLABE",
        ],
        DocumentType.ESTADO_CUENTA: [
            # Si tiene estos, NO es estado de cuenta
            "ESCRITURA PÚBLICA",
            "PROTOCOLIZACIÓN",
            "CONSTANCIA DE SITUACIÓN",
            "CREDENCIAL PARA VOTAR",
        ],
        DocumentType.REFORMA: [
            # =====================================================================
            # NEGATIVOS DE REFORMA: Si aparecen, NO es Reforma
            # NOTA: Las Reformas CITAN la constitución original en sus
            # "resultandos" y pueden incluir otorgamiento de poderes.
            # Solo incluir frases que indican el ACTO PRINCIPAL es otro.
            # =====================================================================
            
            # === Indicadores de ACTA CONSTITUTIVA ORIGINAL (acto de constituir) ===
            "CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO",
            "CONSTITUCION DE SOCIEDAD",
            "CONSTITUCION DE LA SOCIEDAD",
            
            # === Indicadores de otros documentos ===
            "CONSTANCIA DE SITUACION FISCAL",
            "ESTADO DE CUENTA",
        ],
    }
    
    # Umbral mínimo de confianza para aceptar el documento
    CONFIDENCE_THRESHOLD = 0.4
    
    # Umbral para rechazar categóricamente
    REJECTION_THRESHOLD = 0.2
    
    # Tipos de documento alternativos aceptables por endpoint.
    # En KYB mexicano, una CSF se acepta como comprobante de domicilio
    # porque contiene la dirección fiscal registrada.
    ACCEPTED_ALTERNATIVES = {
        DocumentType.COMPROBANTE_DOMICILIO: {DocumentType.CSF},
    }
    
    def __init__(self, openai_client: Any = None):
        """
        Inicializa el DocumentIdentifierAgent.
        
        Args:
            openai_client: Cliente de Azure OpenAI para fallback LLM (opcional)
        """
        self.openai_client = openai_client
    
    def identify(
        self,
        ocr_text: str,
        expected_type: str,
        extracted_fields: Optional[Dict[str, Any]] = None
    ) -> IdentificationResult:
        """
        Identifica si el documento corresponde al tipo esperado.
        
        Este método debe llamarse DESPUÉS de Azure DI OCR y ANTES del LLM.
        
        Args:
            ocr_text: Texto extraído por Azure DI
            expected_type: Tipo esperado por el endpoint (csf, ine, acta, etc.)
            extracted_fields: Campos ya extraídos (opcional, para análisis adicional)
            
        Returns:
            IdentificationResult con el resultado de la identificación
        """
        # Normalizar tipo esperado
        try:
            expected = DocumentType(expected_type.lower())
        except ValueError:
            # Tipo no reconocido, asumir correcto
            return IdentificationResult(
                is_correct=True,
                expected_type=expected_type,
                detected_type=expected_type,
                confidence=1.0,
                discriminants_found=[],
                negative_indicators=[],
                reasoning="Tipo de documento no reconocido, asumiendo correcto",
                should_reject=False
            )
        
        # Normalizar texto para búsqueda
        texto_normalizado = self._normalize_text(ocr_text)
        
        # Fase 1: Buscar discriminantes del tipo esperado
        discriminants_found = self._find_discriminants(texto_normalizado, expected)
        
        # Fase 2: Buscar indicadores negativos
        negative_indicators = self._find_negative_indicators(texto_normalizado, expected)
        
        # Fase 3: Calcular confianza
        confidence, reasoning = self._calculate_confidence(
            discriminants_found, 
            negative_indicators,
            expected
        )
        
        # Fase 4: Si confianza baja, detectar tipo más probable
        detected_type = expected.value
        accepted_as_alternative = False
        if confidence < self.CONFIDENCE_THRESHOLD:
            detected_type, alt_confidence = self._detect_most_probable_type(texto_normalizado)
            
            # Si encontramos otro tipo con mayor confianza
            if alt_confidence > confidence * 1.5:  # Al menos 50% más confianza
                if detected_type == expected.value:
                    # El mismo tipo fue identificado como el más probable
                    # (la confianza es baja pero no hay tipo alternativo mejor)
                    is_correct = True
                    reasoning = f"Se encontraron {len(discriminants_found)} indicadores del tipo esperado"
                else:
                    # Verificar si el tipo detectado es una alternativa aceptable
                    accepted = self.ACCEPTED_ALTERNATIVES.get(expected, set())
                    if any(detected_type == alt.value for alt in accepted):
                        is_correct = True
                        accepted_as_alternative = True
                        reasoning = (
                            f"Documento identificado como {detected_type}, "
                            f"aceptado como alternativa válida para {expected.value}"
                        )
                    else:
                        is_correct = False
                        type_names = {
                            "csf": "Constancia de Situación Fiscal",
                            "ine": "INE (anverso)",
                            "ine_reverso": "INE (reverso)",
                            "acta_constitutiva": "Acta Constitutiva",
                            "poder_notarial": "Poder Notarial",
                            "poder": "Poder Notarial",
                            "comprobante_domicilio": "Comprobante de Domicilio",
                            "fiel": "FIEL (Firma Electrónica)",
                            "estado_cuenta": "Estado de Cuenta",
                            "reforma_estatutos": "Reforma de Estatutos",
                            "reforma": "Reforma de Estatutos",
                        }
                        expected_name = type_names.get(expected.value, expected.value)
                        reasoning = (
                            f"El documento no parece corresponder a una {expected_name}. "
                            f"Por favor suba el documento correcto."
                        )
            else:
                is_correct = confidence >= self.REJECTION_THRESHOLD
                detected_type = expected.value
        else:
            is_correct = True
        
        # Determinar si debe rechazarse
        # should_reject = True si:
        # 1. No es correcto Y no hay suficientes discriminantes del tipo esperado
        # 2. Se detectó otro tipo con mayor confianza (excepto alternativas aceptadas)
        should_reject = (
            not is_correct or
            (not accepted_as_alternative and confidence < self.REJECTION_THRESHOLD and len(discriminants_found) < 2)
        )
        
        result = IdentificationResult(
            is_correct=is_correct,
            expected_type=expected.value,
            detected_type=detected_type,
            confidence=confidence,
            discriminants_found=discriminants_found,
            negative_indicators=negative_indicators,
            reasoning=reasoning,
            should_reject=should_reject
        )
        
        # Log del resultado
        logger.info(json.dumps({
            "event": "document_identification",
            "expected_type": expected.value,
            "detected_type": detected_type,
            "is_correct": is_correct,
            "confidence": round(confidence, 3),
            "should_reject": should_reject,
            "discriminants_count": len(discriminants_found),
            "negatives_count": len(negative_indicators)
        }))
        
        return result
    
    def _normalize_text(self, text: str) -> str:
        """Normaliza texto para búsqueda de keywords."""
        if not text:
            return ""
        
        # Convertir a mayúsculas
        text = text.upper()
        
        # Normalizar caracteres especiales (acentos, ñ, etc.)
        replacements = {
            "Á": "A", "À": "A", "Â": "A", "Ä": "A", "Ã": "A",
            "É": "E", "È": "E", "Ê": "E", "Ë": "E",
            "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
            "Ó": "O", "Ò": "O", "Ô": "O", "Ö": "O", "Õ": "O",
            "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
            "Ñ": "N",
            # Caracteres que pueden aparecer corruptos en OCR
            "Ë": "E", "Ï": "I", "Ö": "O", "Ü": "U",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Normalizar espacios múltiples
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    def _find_discriminants(
        self, 
        texto: str, 
        doc_type: DocumentType
    ) -> List[str]:
        """Encuentra keywords exclusivos del tipo de documento."""
        found = []
        keywords = self.DISCRIMINANT_KEYWORDS.get(doc_type, [])
        
        for keyword in keywords:
            keyword_normalized = self._normalize_text(keyword)
            if keyword_normalized in texto:
                found.append(keyword)
        
        return found
    
    def _find_negative_indicators(
        self, 
        texto: str, 
        doc_type: DocumentType
    ) -> List[str]:
        """Encuentra keywords que indican que NO es este tipo de documento."""
        found = []
        keywords = self.NEGATIVE_KEYWORDS.get(doc_type, [])
        
        for keyword in keywords:
            keyword_normalized = self._normalize_text(keyword)
            if keyword_normalized in texto:
                found.append(keyword)
        
        return found
    
    def _calculate_confidence(
        self,
        discriminants_found: List[str],
        negative_indicators: List[str],
        doc_type: DocumentType
    ) -> Tuple[float, str]:
        """
        Calcula la confianza de que el documento sea del tipo esperado.
        
        Returns:
            Tuple (confianza, razonamiento)
        """
        total_discriminants = len(self.DISCRIMINANT_KEYWORDS.get(doc_type, []))
        found_count = len(discriminants_found)
        negative_count = len(negative_indicators)
        
        if total_discriminants == 0:
            return 0.5, "No hay discriminantes definidos para este tipo"
        
        # Score positivo: proporción de discriminantes encontrados
        positive_score = found_count / total_discriminants
        
        # Penalización por indicadores negativos (cada uno resta 15%)
        penalty = min(negative_count * 0.15, 0.6)  # Máximo 60% de penalización
        
        # Bonus por cantidad absoluta de discriminantes encontrados
        # Escala mejor con listas grandes de discriminantes donde la proporción
        # es baja pero la cantidad absoluta es significativa
        if found_count >= 7:
            bonus = 0.40
        elif found_count >= 5:
            bonus = 0.30
        elif found_count >= 3:
            bonus = 0.20
        elif found_count >= 2:
            bonus = 0.10
        else:
            bonus = 0.0
        
        confidence = max(0.0, min(1.0, positive_score - penalty + bonus))
        
        # Generar razonamiento
        if found_count == 0 and negative_count == 0:
            reasoning = "No se encontraron indicadores claros"
        elif found_count > 0 and negative_count == 0:
            reasoning = f"Se encontraron {found_count} indicadores positivos del tipo esperado"
        elif found_count == 0 and negative_count > 0:
            reasoning = f"Se encontraron {negative_count} indicadores de que NO es este tipo de documento"
        else:
            reasoning = f"Indicadores mixtos: {found_count} positivos, {negative_count} negativos"
        
        return confidence, reasoning
    
    def _detect_most_probable_type(self, texto: str) -> Tuple[str, float]:
        """
        Detecta el tipo de documento más probable basándose en discriminantes.
        
        Usa un algoritmo de scoring mejorado que:
        1. Cuenta keywords exclusivos encontrados
        2. Aplica bonus por múltiples keywords del mismo tipo
        3. Penaliza por keywords negativos
        4. Prioriza matches con más keywords absolutos (no solo proporción)
        
        Returns:
            Tuple (tipo_detectado, confianza)
        """
        best_type = DocumentType.CSF.value
        best_score = 0.0
        best_keyword_count = 0
        
        scores_by_type = {}
        
        for doc_type in DocumentType:
            discriminants = self._find_discriminants(texto, doc_type)
            negatives = self._find_negative_indicators(texto, doc_type)
            
            total = len(self.DISCRIMINANT_KEYWORDS.get(doc_type, []))
            found_count = len(discriminants)
            negative_count = len(negatives)
            
            if total == 0:
                continue
            
            # Score base: proporción de discriminantes encontrados
            base_score = found_count / total
            
            # Bonus por cantidad absoluta de keywords (más keywords = más confianza)
            if found_count >= 5:
                quantity_bonus = 0.30
            elif found_count >= 3:
                quantity_bonus = 0.20
            elif found_count >= 2:
                quantity_bonus = 0.10
            else:
                quantity_bonus = 0.0
            
            # Penalización por negativos (más suave para no eliminar candidatos)
            penalty = min(negative_count * 0.08, 0.40)
            
            # Score final
            score = base_score + quantity_bonus - penalty
            
            scores_by_type[doc_type.value] = {
                "score": score,
                "found_count": found_count,
                "discriminants": discriminants[:5],  # Solo primeros 5 para log
            }
            
            # Criterio de selección: priorizar por score, pero desempatar por cantidad
            if score > best_score or (score == best_score and found_count > best_keyword_count):
                best_score = score
                best_type = doc_type.value
                best_keyword_count = found_count
        
        # Log para debugging
        logger.debug(json.dumps({
            "event": "detect_most_probable_type",
            "best_type": best_type,
            "best_score": round(best_score, 3),
            "all_scores": {k: v["score"] for k, v in scores_by_type.items() if v["score"] > 0}
        }))
        
        return best_type, max(0.0, min(1.0, best_score))
    
    async def identify_with_llm_fallback(
        self,
        ocr_text: str,
        expected_type: str,
        extracted_fields: Optional[Dict[str, Any]] = None
    ) -> IdentificationResult:
        """
        Identifica con fallback a LLM para casos ambiguos.
        
        Usa LLM solo si:
        1. La confianza del análisis de keywords es < 0.5
        2. Hay conflicto entre indicadores positivos y negativos
        
        Args:
            ocr_text: Texto extraído por OCR
            expected_type: Tipo esperado
            extracted_fields: Campos extraídos (opcional)
            
        Returns:
            IdentificationResult
        """
        # Primero intentar con keywords
        result = self.identify(ocr_text, expected_type, extracted_fields)
        
        # Si confianza es suficiente o no tenemos LLM, retornar
        if result.confidence >= 0.5 or self.openai_client is None:
            return result
        
        # Casos ambiguos: usar LLM
        if len(result.discriminants_found) > 0 and len(result.negative_indicators) > 0:
            try:
                llm_result = await self._classify_with_llm(ocr_text, expected_type)
                if llm_result:
                    logger.info(json.dumps({
                        "event": "document_identification_llm",
                        "expected_type": expected_type,
                        "llm_decision": llm_result
                    }))
                    
                    return IdentificationResult(
                        is_correct=llm_result["is_correct"],
                        expected_type=expected_type,
                        detected_type=llm_result.get("detected_type", expected_type),
                        confidence=llm_result.get("confidence", 0.8),
                        discriminants_found=result.discriminants_found,
                        negative_indicators=result.negative_indicators,
                        reasoning=f"LLM: {llm_result.get('reasoning', 'Clasificado por LLM')}",
                        should_reject=not llm_result["is_correct"]
                    )
            except Exception as e:
                logger.warning(f"LLM fallback failed: {e}")
        
        return result
    
    async def _classify_with_llm(
        self, 
        ocr_text: str, 
        expected_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Usa LLM para clasificar el tipo de documento.
        
        Solo se llama cuando hay ambigüedad en el análisis de keywords.
        """
        if not self.openai_client:
            return None
        
        # Tomar solo los primeros 2000 caracteres para eficiencia
        text_sample = ocr_text[:2000] if len(ocr_text) > 2000 else ocr_text
        
        system_prompt = """Eres un experto en documentos legales y fiscales mexicanos.
Tu tarea es clasificar si un documento corresponde al tipo esperado.

Tipos de documentos posibles:
- csf: Constancia de Situación Fiscal (SAT)
- acta_constitutiva: Acta Constitutiva de sociedad
- poder: Poder Notarial
- ine: Credencial INE (anverso)
- ine_reverso: Credencial INE (reverso con MRZ)
- fiel: Certificado de FIEL/e.firma
- comprobante_domicilio: Recibo de luz/agua/teléfono
- estado_cuenta: Estado de cuenta bancario
- reforma: Reforma de estatutos sociales

Responde SOLO en JSON:
{
    "is_correct": true/false,
    "detected_type": "tipo_detectado",
    "confidence": 0.0-1.0,
    "reasoning": "explicación breve"
}"""

        user_prompt = f"""Tipo esperado: {expected_type}

Texto del documento (muestra):
{text_sample}

¿El documento corresponde al tipo esperado?"""

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return None


# Singleton global para uso en controllers
_identifier_agent: Optional[DocumentIdentifierAgent] = None


def get_identifier_agent(openai_client: Any = None) -> DocumentIdentifierAgent:
    """
    Obtiene o crea el DocumentIdentifierAgent singleton.
    
    Args:
        openai_client: Cliente OpenAI opcional para fallback
        
    Returns:
        DocumentIdentifierAgent instance
    """
    global _identifier_agent
    
    if _identifier_agent is None:
        _identifier_agent = DocumentIdentifierAgent(openai_client)
    
    return _identifier_agent


def identify_document_type(
    ocr_text: str,
    expected_type: str,
    extracted_fields: Optional[Dict[str, Any]] = None
) -> IdentificationResult:
    """
    Función helper para identificar tipo de documento.
    
    Uso típico en controllers:
    
    ```python
    # Después de Azure DI OCR
    raw_txt = extract_text_from_document(file_path, DocType.csf)
    
    # NUEVO: Verificar tipo de documento
    from api.service.document_identifier import identify_document_type
    identification = identify_document_type(raw_txt, "csf")
    
    if identification.should_reject:
        return {
            "error": "WRONG_DOCUMENT_TYPE",
            "message": f"El documento parece ser '{identification.detected_type}' en lugar de 'csf'",
            "confidence": identification.confidence
        }
    
    # Continuar con OpenAI structuring si pasó la verificación
    extracted_data = extract_csf_fields(raw_txt, llm)
    ```
    
    Args:
        ocr_text: Texto extraído por Azure DI
        expected_type: Tipo esperado por el endpoint
        extracted_fields: Campos ya extraídos (opcional)
        
    Returns:
        IdentificationResult
    """
    agent = get_identifier_agent()
    return agent.identify(ocr_text, expected_type, extracted_fields)
