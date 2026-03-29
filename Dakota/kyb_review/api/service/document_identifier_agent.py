"""
Agente de Identificación de Documentos con 4 Señales.

Este módulo implementa un clasificador robusto de documentos mexicanos
utilizando 4 señales independientes:
1. Keywords exclusivos (peso 35%)
2. Estructura de páginas (peso 20%)
3. Fingerprint de campos extraídos (peso 20%)
4. LLM semántico - GPT-4o (peso 25%)

El LLM solo se invoca si las señales 1+2+3 están en zona ambigua (0.40-0.75).
"""

import re
import logging
from typing import Optional, Any
from api.model.document_identity import (
    DocumentIdentityResult,
    WrongDocumentError
)

logger = logging.getLogger(__name__)


# =============================================================================
# SIGNAL 1: KEYWORDS EXCLUSIVOS
# =============================================================================

DOCUMENT_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "csf": {
        "exclusive_keywords": [
            "CONSTANCIA DE SITUACIÓN FISCAL",
            "CONSTANCIA DE SITUACION FISCAL",
            "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA",
            "SERVICIO DE ADMINISTRACION TRIBUTARIA",
            "RÉGIMEN FISCAL",
            "REGIMEN FISCAL",
            "ACTIVIDADES ECONÓMICAS",
            "ACTIVIDADES ECONOMICAS",
            "OBLIGACIONES FISCALES",
            "CIF",
            "CÉDULA DE IDENTIFICACIÓN FISCAL",
            "CEDULA DE IDENTIFICACION FISCAL",
            "ESTATUS EN EL PADRÓN",
            "ESTATUS EN EL PADRON",
            "ACTIVO",  # estatus típico
        ],
        "negative_keywords": [
            "PODER NOTARIAL",
            "INSTITUTO NACIONAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "ESCRITURA PÚBLICA",
            "ACTA CONSTITUTIVA",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
            "CFE370814QI0",
            "TELMEX",
            "TOTALPLAY",
            "AVISO RECIBO",
            "LECTURA ANTERIOR",
            "LECTURA ACTUAL",
            "KWH",
            "CONSUMO HISTÓRICO",
        ],
    },
    "ine": {
        "exclusive_keywords": [
            "INSTITUTO NACIONAL ELECTORAL",
            "INSTITUTO FEDERAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "CLAVE DE ELECTOR",
            "SECCIÓN ELECTORAL",
            "SECCION ELECTORAL",
            "VIGENCIA",
            "AÑO DE REGISTRO",
            "LOCALIDAD",
            "EMISIÓN",
            "EMISION",
            "INE",
            "IFE",
        ],
        "negative_keywords": [
            "SITUACIÓN FISCAL",
            "SITUACION FISCAL",
            "PODER NOTARIAL",
            "ESCRITURA PÚBLICA",
            "ACTA CONSTITUTIVA",
            "FOLIO MERCANTIL",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "AVISO RECIBO",
        ],
    },
    "ine_reverso": {
        "exclusive_keywords": [
            "INSTITUTO NACIONAL ELECTORAL",
            "INSTITUTO FEDERAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "CLAVE DE ELECTOR",
            "CÓDIGO DE BARRAS",
            "CODIGO DE BARRAS",
            "MRZ",
            "IDMEX",
            "SECCIÓN",
            "SECCION",
        ],
        "negative_keywords": [
            "SITUACIÓN FISCAL",
            "PODER NOTARIAL",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "AVISO RECIBO",
            "KWH",
        ],
    },
    "acta_constitutiva": {
        "exclusive_keywords": [
            # Frases únicas de constitución de sociedad
            "ACTA CONSTITUTIVA",
            "CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO",
            "CONSTITUYEN POR ESTE PÚBLICO INSTRUMENTO",
            "SOCIOS FUNDADORES",
            "SOCIOS CONSTITUYENTES",
            "CLAUSULAS DEL PACTO SOCIAL",
            "CLÁUSULAS DEL PACTO SOCIAL",
            "CLAUSULAS TRANSITORIAS",
            "CLÁUSULAS TRANSITORIAS",
            "DURACION DE LA SOCIEDAD",
            "DURACIÓN DE LA SOCIEDAD",
            "NOVENTA Y NUEVE AÑOS",
            "NOVENTA Y NUEVE ANOS",
            "99 NOVENTA Y NUEVE AÑOS",
            "CLAUSULA DE EXTRANJERIA",
            "CLÁUSULA DE EXTRANJERÍA",
            "PRIMERA ASAMBLEA",
            # Elementos estructurales de actas
            "FOLIO MERCANTIL ELECTRONICO",
            "FOLIO MERCANTIL ELECTRÓNICO",
            "SOCIEDAD ANÓNIMA",
            "SOCIEDAD ANONIMA",
            "S.A. DE C.V.",
            "S.A.P.I. DE C.V.",
            "CAPITAL SOCIAL MINIMO",
            "CAPITAL SOCIAL MÍNIMO",
            "CAPITAL SOCIAL FIJO",
            "OBJETO DE LA SOCIEDAD",
            "DENOMINACIÓN SOCIAL",
            "DENOMINACION SOCIAL",
            "REGISTRO PÚBLICO DE COMERCIO",
            "REGISTRO PUBLICO DE COMERCIO",
        ],
        "negative_keywords": [
            # Indicadores de Poder Notarial standalone (no aparecen en Actas de constitución)
            "OTORGAMIENTO DE PODER",
            "OTORGAMIENTO DE PODERES",
            "CONFIERE PODER A FAVOR DE",
            "OTORGA PODER A FAVOR DE",
            "MANDATARIO INSTITUIDO",
            "LA MANDANTE",
            "EL MANDANTE",
            "EN SU CARÁCTER DE MANDATARIO",
            "EN SU CARACTER DE MANDATARIO",
            "PODER GENERAL JUDICIAL Y PARA PLEITOS",
            "PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN",
            "PODER GENERAL PARA ACTOS DE ADMINISTRACION",
            "PODER CAMBIARIO",
            # Discriminantes directos de Poder Notarial (no aparecen en Actas constitutivas)
            "PODER NOTARIAL",
            "PODERDANTE",
            "APODERADO DESIGNADO",
            "EN SU CARÁCTER DE APODERADO",
            "EN SU CARACTER DE APODERADO",
            "FACULTADES QUE SE OTORGAN AL APODERADO",
            # NOTA: "PODER GENERAL" y "PODER ESPECIAL" se eliminaron porque las Actas
            # Constitutivas y de Asamblea otorgan poderes a administradores en sus estatutos.
            # Discriminantes de Reforma de Estatutos / Acta de Asamblea
            "PROTOCOLIZACION DE ACTA",
            "PROTOCOLIZACIÓN DE ACTA",
            "ASAMBLEA EXTRAORDINARIA",
            "ORDEN DEL DIA",
            "ORDEN DEL DÍA",
            "BAJAS VOLUNTARIAS",
            "AUMENTO DE CAPITAL",
            "RESTRUCTURACION DEL CONSEJO",
            "REESTRUCTURACION DEL CONSEJO",
            # Otros documentos
            "SITUACIÓN FISCAL",
            "SITUACION FISCAL",
            "CREDENCIAL PARA VOTAR",
            "INSTITUTO NACIONAL ELECTORAL",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
        ],
    },
    "poder_notarial": {
        "exclusive_keywords": [
            # SOLO frases que aparecen cuando el documento EN SÍ MISMO es un Poder Notarial,
            # nunca cuando se mencionan poderes incidentalmente en Actas o Reformas.
            "PODERDANTE",                          # Quien otorga el poder
            "APODERADO",                           # Quien recibe el poder
            "EN SU CALIDAD DE PODERDANTE",         # Rol explícito
            "APODERADO DESIGNADO",
            "EL MANDATARIO",                       # Cómo se llama al apoderado en el doc
            "OTORGA EL PRESENTE PODER",
            "CONFIERE PODER",
            "OTORGA PODER A FAVOR DE",
            "OTORGAMIENTO DE PODER",
            "OTORGAMIENTO DE PODERES",
            "OTORGAMIENTO DE PODERES Y FACULTADES",  # Notación del Registro Público
            "POR MEDIO DEL PRESENTE INSTRUMENTO OTORGA",
            "FACULTADES QUE SE OTORGAN AL APODERADO",
            "FACULTADES QUE SE CONFIEREN",
            "EN SU CARÁCTER DE APODERADO",
            "EN SU CARACTER DE APODERADO",
            "ACEPTA EL PODER",
            "REVOCACION DE PODERES ANTERIORES",
            "REVOCACIÓN DE PODERES ANTERIORES",
            # Tipos de poder standalone (cuando el doc es un poder, no cuando se menciona en acta)
            "PODER GENERAL JUDICIAL Y PARA PLEITOS",
            "PODER GENERAL PARA ACTOS DE ADMINISTRACIÓN",
            "PODER GENERAL PARA ACTOS DE ADMINISTRACION",
            "PODER CAMBIARIO",
            "PODER ESPECIAL PARA CONSTITUIR FIDEICOMISOS",
            "CONSTITUIR FIDEICOMISOS",
            "MANDATARIO INSTITUIDO",
            "LA MANDANTE",
            "EL MANDANTE",
            # Sección única del régimen legal en escrituras de poder
            "REGIMEN LEGAL DEL MANDATO",
            "RÉGIMEN LEGAL DEL MANDATO",
            # Inscripción del Registro Público de Comercio para poderes
            "M1 - ACTA DE SESION DE CONSEJO",
            "M1 - ACTA DE SESIÓN DE CONSEJO",
            # Referencias del Código Civil específicas de poderes
            "ARTÍCULO 2554",
            "ARTICULO 2554",
            "ARTÍCULO 2587",
            "ARTICULO 2587",
            "PARA DESISTIRSE",
            "PARA TRANSIGIR",
            "ABSOLVER Y ARTICULAR POSICIONES",
        ],
        "negative_keywords": [
            # Indicadores de Acta Constitutiva (no aparecen en Poderes standalone)
            "ACTA CONSTITUTIVA",
            "CONSTITUYEN POR ESTE",
            "SOCIOS FUNDADORES",
            "SOCIOS CONSTITUYENTES",
            "CLAUSULAS DEL PACTO SOCIAL",
            "CLÁUSULAS DEL PACTO SOCIAL",
            "CLAUSULAS TRANSITORIAS",
            "CLÁUSULAS TRANSITORIAS",
            "DURACION DE LA SOCIEDAD",
            "DURACIÓN DE LA SOCIEDAD",
            "OBJETO DE LA SOCIEDAD",
            "OBJETO SOCIAL",
            "CAPITAL SOCIAL FIJO",
            "PRIMERA ASAMBLEA",
            "CLAUSULA DE EXTRANJERIA",
            "CLÁUSULA DE EXTRANJERÍA",
            "FOLIO MERCANTIL ELECTRONICO",
            "FOLIO MERCANTIL ELECTRÓNICO",
            "S.A. DE C.V.",
            "S.A.P.I. DE C.V.",
            # Indicadores de Reforma / Acta de Asamblea de accionistas (NO aplican a Poderes)
            # NOTA: "PROTOCOLIZACION DE ACTA" se eliminó porque los Poderes protocolizados
            # desde sesiones de consejo también usan esa frase.
            "ASAMBLEA EXTRAORDINARIA",
            "ASAMBLEA GENERAL DE ACCIONISTAS",
            "ORDEN DEL DIA",
            "ORDEN DEL DÍA",
            "BAJAS VOLUNTARIAS",
            "AUMENTO DE CAPITAL",
            # Indicadores del SAT / CSF (NUNCA aparecen como contenido principal de un Poder)
            "SERVICIO DE ADMINISTRACION TRIBUTARIA",
            "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA",
            "REGIMEN FISCAL",
            "RÉGIMEN FISCAL",
            "ACTIVIDADES ECONOMICAS",
            "ACTIVIDADES ECONÓMICAS",
            "ESTATUS EN EL PADRON",
            "ESTATUS EN EL PADRÓN",
            # Otros documentos
            "CREDENCIAL PARA VOTAR",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
        ],
    },
    "comprobante_domicilio": {
        "exclusive_keywords": [
            # Recibos de luz - CFE
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
            "CFE370814QI0",
            "AVISO RECIBO",
            "LECTURA ANTERIOR",
            "LECTURA ACTUAL",
            "KWH",
            "CONSUMO HISTÓRICO",
            "CONSUMO HISTORICO",
            "PERIODO DE CONSUMO",
            "IMPORTE A PAGAR",
            "TARIFA DOMÉSTICA",
            "TARIFA DOMESTICA",
            "SUMINISTRO",
            "MEDIDOR",
            "SERVICIO DOMÉSTICO",
            "SERVICIO DOMESTICO",
            # Recibos de teléfono/internet - TELMEX
            "TELMEX",
            "TELEFONOS DE MEXICO",
            "TME840315-KT6",
            "MES DE FACTURACION",
            "MES DE FACTURACIÓN",
            "PAGAR ANTES DE",
            "ATENCION A CLIENTES: 800",
            "ATENCIÓN A CLIENTES: 800",
            # Otros proveedores de telecomunicaciones
            "TOTALPLAY",
            "IZZI",
            "MEGACABLE",
            "AXTEL",
            # Recibos de agua
            "SACMEX",
            "SISTEMA DE AGUAS",
            "ORGANISMO OPERADOR",
            # Recibos de gas
            "GAS NATURAL",
            "NATURGY",
            # Comprobantes genéricos
            "COMPROBANTE DE DOMICILIO",
        ],
        "negative_keywords": [
            "SITUACIÓN FISCAL",
            "SITUACION FISCAL",
            "CONSTANCIA DE SITUACIÓN FISCAL",
            "INSTITUTO NACIONAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "ACTA CONSTITUTIVA",
            "PODER NOTARIAL",
            "CLAVE DE ELECTOR",
            "RÉGIMEN FISCAL",
            "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA",
            # Bancos reales (estados de cuenta bancarios no son comprobantes)
            "SALDO INICIAL",
            "SALDO FINAL",
            "CLABE",
            "BBVA",
            "BANORTE",
            "SANTANDER",
            "CITIBANAMEX",
        ],
    },
    "fiel": {
        "exclusive_keywords": [
            "FIRMA ELECTRÓNICA AVANZADA",
            "FIRMA ELECTRONICA AVANZADA",
            "FIEL",
            "E.FIRMA",
            "EFIRMA",
            "CERTIFICADO DIGITAL",
            "NÚMERO DE SERIE DEL CERTIFICADO",
            "NUMERO DE SERIE DEL CERTIFICADO",
            "VIGENCIA DEL CERTIFICADO",
            "CER",
            "KEY",
            "SAT",
            "LLAVE PRIVADA",
        ],
        "negative_keywords": [
            "CREDENCIAL PARA VOTAR",
            "ACTA CONSTITUTIVA",
            "PODER NOTARIAL",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
        ],
    },
    "estado_cuenta": {
        "exclusive_keywords": [
            "ESTADO DE CUENTA",
            "SALDO INICIAL",
            "SALDO FINAL",
            "MOVIMIENTOS",
            "DEPÓSITOS",
            "DEPOSITOS",
            "RETIROS",
            "COMISIONES",
            "CLABE",
            "NÚMERO DE CUENTA",
            "NUMERO DE CUENTA",
            "RESUMEN DE MOVIMIENTOS",
            "PERIODO DEL ESTADO",
            "BBVA",
            "BANORTE",
            "SANTANDER",
            "CITIBANAMEX",
            "HSBC",
            "SCOTIABANK",
        ],
        "negative_keywords": [
            "SITUACIÓN FISCAL",
            "CREDENCIAL PARA VOTAR",
            "ACTA CONSTITUTIVA",
            "PODER NOTARIAL",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
            "KWH",
            "TELMEX",
            "TELEFONOS DE MEXICO",
            "MES DE FACTURACION",
            "PAGAR ANTES DE",
        ],
    },
    "reforma_estatutos": {
        "exclusive_keywords": [
            # Frases únicas de protocolización/modificación de estatutos por asamblea
            "PROTOCOLIZACION DE ACTA",
            "PROTOCOLIZACIÓN DE ACTA",
            "ASAMBLEA EXTRAORDINARIA",
            "ASAMBLEA GENERAL EXTRAORDINARIA DE ACCIONISTAS",
            "ASAMBLEA GENERAL DE ACCIONISTAS",
            "ORDEN DEL DIA",
            "ORDEN DEL DÍA",
            "ACUERDOS DE ASAMBLEA",
            "REFORMA DE ESTATUTOS",
            "REFORMA ESTATUTARIA",
            "REFORMA LA CLAUSULA",
            "REFORMA LA CLÁUSULA",
            "MODIFICACIÓN DE ESTATUTOS",
            "MODIFICACION DE ESTATUTOS",
            "SE MODIFICA",
            "EN MODIFICACION A LA ESCRITURA",
            "EN MODIFICACIÓN A LA ESCRITURA",
            "BAJAS VOLUNTARIAS DE SOCIOS",
            "ALTA DE NUEVOS SOCIOS",
            "AUMENTO DE CAPITAL",
            "RESTRUCTURACION DEL CONSEJO",
            "REESTRUCTURACION DEL CONSEJO",
            "ESTRUCTURA ACCIONARIA",
        ],
        "negative_keywords": [
            # Reforma modifica empresa existente — nunca crea una nueva
            "SE CONSTITUYE LA SOCIEDAD",
            "CONSTITUYEN POR ESTE PUBLICO INSTRUMENTO",
            "CONSTITUYEN POR ESTE PÚBLICO INSTRUMENTO",
            "SOCIOS FUNDADORES",
            # Nunca tiene la estructura de otorgamiento de poder
            "PODERDANTE",
            "OTORGA EL PRESENTE PODER",
            "ACEPTA EL PODER",
            # Nunca tiene contenido del SAT
            "SITUACIÓN FISCAL",
            "SITUACION FISCAL",
            "RÉGIMEN FISCAL",
            "REGIMEN FISCAL",
            "CREDENCIAL PARA VOTAR",
            "COMISIÓN FEDERAL DE ELECTRICIDAD",
            "COMISION FEDERAL DE ELECTRICIDAD",
        ],
    },
}


# =============================================================================
# SIGNAL 1.5: DECLARACIONES EN CABECERA DEL DOCUMENTO
# =============================================================================

# Los primeros 500 caracteres del OCR casi siempre contienen la declaración
# explícita del tipo de documento. Se usan para confirmar o contradecir el tipo esperado.
HEADER_DECLARATIONS: dict[str, list[str]] = {
    "reforma_estatutos": [
        "PROTOCOLIZACION DE ACTA",
        "PROTOCOLIZACIÓN DE ACTA",
        "ASAMBLEA EXTRAORDINARIA DE LA SOCIEDAD",
        "ACTA DE ASAMBLEA",
        "REFORMA DE ESTATUTOS",
        "ACTO: PROTOCOLIZACION",
    ],
    "acta_constitutiva": [
        "ACTA CONSTITUTIVA",
        "CONSTITUCION DE SOCIEDAD",
        "CONSTITUCIÓN DE SOCIEDAD",
        "ACTA CONSTITUTIVA DE",
    ],
    "poder_notarial": [
        "PODER NOTARIAL",
        "PODER GENERAL OTORGADO",
        "PODER ESPECIAL OTORGADO",
        "OTORGAMIENTO DE PODER",
        "OTORGAMIENTO DE PODERES",
        "A EFECTO DE SOLICITAR LA PROTOCOLIZACION",
        "A EFECTO DE SOLICITAR LA PROTOCOLIZACIÓN",
    ],
    "csf": [
        "CONSTANCIA DE SITUACION FISCAL",
        "CONSTANCIA DE SITUACIÓN FISCAL",
        "SERVICIO DE ADMINISTRACION TRIBUTARIA",
        "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA",
    ],
    "ine": [
        "INSTITUTO NACIONAL ELECTORAL",
        "CREDENCIAL PARA VOTAR",
    ],
    "comprobante_domicilio": [
        "AVISO RECIBO",
        "RECIBO DE",
        "TELMEX",
        "TELEFONOS DE MEXICO",
        "COMISION FEDERAL DE ELECTRICIDAD",
        "COMISIÓN FEDERAL DE ELECTRICIDAD",
        "SACMEX",
        "TOTALPLAY",
        "IZZI",
        "MEGACABLE",
    ],
}


# =============================================================================
# SIGNAL 1 GUARD: MENCIONES INCIDENTALES
# =============================================================================

# Frases que en los 150 caracteres ANTERIORES a un keyword indican que el
# keyword es una REFERENCIA al documento (el notario lo menciona como evidencia)
# y NO que el documento en cuestión SEA ese tipo.
# Ejemplo: "acreditandomelo con la Constancia de Situación Fiscal" → incidental.
REFERENCE_CONTEXT_PATTERNS: list[str] = [
    "ACREDITANDOMELO CON LA",
    "ACREDITANDOME CON LA",
    "CON LA CONSTANCIA DE",
    "ADJUNTO LA",
    "ADJUNTE LA",
    "ACOMPANO LA",
    "ACOMPAÑO LA",
    "A QUE SE REFIERE LA",
    "SEGUN CONSTA EN LA",
    "SEGÚN CONSTA EN LA",
    "COMO SE ACREDITA CON LA",
    "EN TERMINOS DE LA",
    "EN TÉRMINOS DE LA",
    "CONFORME A LA",
    "VERIFICADO MEDIANTE LA",
    "COPIA DE LA",
    "EXHIBE LA",
    "PRESENTA LA",
    "TUVE A LA VISTA LA",
    "TUVE A LA VISTA",
    "AGREGO COPIA",
    "SE AGREGA",
    "AGREGO AL APENDICE",
    "AGREGO AL APÉNDICE",
    "NUMERO DE RFC",
    "NÚMERO DE RFC",
    "COPIA CERTIFICADA DE LA",
]


# =============================================================================
# SIGNAL 2: ESTRUCTURA DE PÁGINAS
# =============================================================================

DOCUMENT_PAGE_PROFILE: dict[str, dict[str, int]] = {
    "csf": {"min": 1, "max": 3, "typical": 1},
    "ine": {"min": 1, "max": 2, "typical": 1},
    "ine_reverso": {"min": 1, "max": 2, "typical": 1},
    "acta_constitutiva": {"min": 5, "max": 200, "typical": 20},
    "poder_notarial": {"min": 3, "max": 50, "typical": 8},
    "comprobante_domicilio": {"min": 1, "max": 10, "typical": 2},
    "fiel": {"min": 1, "max": 2, "typical": 1},
    "estado_cuenta": {"min": 1, "max": 20, "typical": 3},
    "reforma_estatutos": {"min": 3, "max": 100, "typical": 10},
}


# =============================================================================
# SIGNAL 3: FINGERPRINT DE CAMPOS
# =============================================================================

DOCUMENT_FIELD_FINGERPRINT: dict[str, dict[str, list[str]]] = {
    "csf": {
        "discriminating_fields": [
            "regimen_fiscal",
            "actividad_economica",
            "estatus_padron",
            "fecha_emision",
            "obligaciones",
            "codigo_postal",
        ],
        "anti_fields": [
            "clave_elector",
            "numero_escritura",
            "folio_mercantil",
            "poderdante",
            "apoderado",
            "lectura_anterior",
            "lectura_actual",
        ],
    },
    "ine": {
        "discriminating_fields": [
            "clave_elector",
            "seccion",
            "vigencia",
            "curp",
            "fecha_nacimiento",
            "localidad",
        ],
        "anti_fields": [
            "regimen_fiscal",
            "numero_escritura",
            "folio_mercantil",
            "estatus_padron",
        ],
    },
    "ine_reverso": {
        "discriminating_fields": [
            "mrz",
            "codigo_barras",
            "cic",
            "ocr",
        ],
        "anti_fields": [
            "regimen_fiscal",
            "numero_escritura",
            "estatus_padron",
        ],
    },
    "acta_constitutiva": {
        "discriminating_fields": [
            "folio_mercantil",
            "numero_escritura",
            "notario",
            "capital_social",
            "objeto_social",
            "socios",
            "fecha_constitucion",
        ],
        "anti_fields": [
            "clave_elector",
            "regimen_fiscal",
            "estatus_padron",
            "lectura_anterior",
            # Campos específicos de Poder Notarial
            "poderdante",
            "apoderado",
            "mandatario",
            "mandante",
            "facultades_poder",
        ],
    },
    "poder_notarial": {
        "discriminating_fields": [
            "poderdante",
            "apoderado",
            "facultades",
            "numero_escritura",
            "notario",
            "fecha_otorgamiento",
            "mandatario",
            "mandante",
        ],
        "anti_fields": [
            "clave_elector",
            "regimen_fiscal",
            # Campos específicos de Acta Constitutiva
            "socios_fundadores",
            "objeto_social",
            "fecha_constitucion",
            "clausulas_transitorias",
        ],
    },
    "comprobante_domicilio": {
        "discriminating_fields": [
            "periodo_consumo",
            "lectura_anterior",
            "lectura_actual",
            "importe",
            "servicio",
            "medidor",
            "consumo",
        ],
        "anti_fields": [
            "clave_elector",
            "regimen_fiscal",
            "folio_mercantil",
            "numero_escritura",
            "estatus_padron",
        ],
    },
    "fiel": {
        "discriminating_fields": [
            "numero_serie_certificado",
            "vigencia_certificado",
            "vigencia_hasta",
            "llave_privada",
        ],
        "anti_fields": [
            "clave_elector",
            "folio_mercantil",
            "lectura_anterior",
        ],
    },
    "estado_cuenta": {
        "discriminating_fields": [
            "saldo_inicial",
            "saldo_final",
            "clabe",
            "numero_cuenta",
            "movimientos",
            "periodo",
        ],
        "anti_fields": [
            "clave_elector",
            "regimen_fiscal",
            "folio_mercantil",
            "lectura_anterior",
        ],
    },
    "reforma_estatutos": {
        "discriminating_fields": [
            "folio_mercantil",
            "numero_escritura",
            "notario",
            "estructura_accionaria",
            "capital",
        ],
        "anti_fields": [
            "clave_elector",
            "regimen_fiscal",
            "estatus_padron",
        ],
    },
}


class DocumentIdentifierAgent:
    """
    Agente de identificación de documentos con 4 señales.
    
    Combina keywords exclusivos, estructura de páginas, campos extraídos
    y opcionalmente LLM para clasificar documentos con alta precisión.
    """
    
    # Pesos de cada señal
    WEIGHT_KEYWORDS = 0.35
    WEIGHT_STRUCTURE = 0.20
    WEIGHT_FIELDS = 0.20
    WEIGHT_LLM = 0.25
    
    # Umbrales de decisión
    THRESHOLD_CONFIRMED = 0.75
    THRESHOLD_UNCERTAIN = 0.50
    
    # Zona ambigua para invocar LLM
    LLM_INVOKE_MIN = 0.40
    LLM_INVOKE_MAX = 0.75
    
    def __init__(self, openai_client: Optional[Any] = None):
        """
        Inicializa el agente de identificación.
        
        Args:
            openai_client: Cliente de OpenAI para invocar GPT-4o (opcional).
                          Si no se proporciona, no se usará el LLM.
        """
        self.openai_client = openai_client
    
    def _normalize_text(self, text: str) -> str:
        """
        Normaliza texto para búsqueda de keywords.
        
        Elimina acentos, convierte a mayúsculas y limpia caracteres especiales.
        """
        if not text:
            return ""
        
        # Convertir a mayúsculas
        text = text.upper()
        
        # Mapeo de caracteres acentuados
        accent_map = {
            'Á': 'A', 'À': 'A', 'Â': 'A', 'Ä': 'A', 'Ã': 'A',
            'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
            'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
            'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Ö': 'O', 'Õ': 'O',
            'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
            'Ñ': 'N',
            'Ç': 'C',
        }
        
        for accented, plain in accent_map.items():
            text = text.replace(accented, plain)
        
        return text
    
    def _calculate_keywords_score(
        self,
        ocr_text: str,
        doc_type: str
    ) -> tuple[float, list[str], list[str]]:
        """
        Calcula la puntuación de keywords exclusivos (Señal 1).
        
        Args:
            ocr_text: Texto OCR del documento
            doc_type: Tipo de documento esperado
            
        Returns:
            Tupla de (score, keywords_encontrados, negativos_encontrados)
        """
        if doc_type not in DOCUMENT_SIGNATURES:
            return 0.0, [], []
        
        signature = DOCUMENT_SIGNATURES[doc_type]
        normalized_text = self._normalize_text(ocr_text)
        
        # Buscar keywords exclusivos.
        # Si la keyword aparece SOLO como mención incidental (el notario cita el documento
        # como evidencia pero no lo está redactando), se descarta el match.
        keywords_found = []
        for keyword in signature["exclusive_keywords"]:
            normalized_keyword = self._normalize_text(keyword)
            if normalized_keyword in normalized_text:
                if not self._is_incidental_mention(ocr_text, keyword):
                    keywords_found.append(keyword)
                # else: mención incidental — no sumar puntos
        
        # Buscar keywords negativos (también filtramos menciones incidentales de negativos)
        negative_found = []
        for keyword in signature.get("negative_keywords", []):
            normalized_keyword = self._normalize_text(keyword)
            if normalized_keyword in normalized_text:
                if not self._is_incidental_mention(ocr_text, keyword):
                    negative_found.append(keyword)
        
        # Calcular score
        # Cada keyword exclusivo: +15 puntos (max 100)
        positive_score = min(len(keywords_found) * 15, 100)
        
        # Cada keyword negativo: -50 puntos
        negative_penalty = len(negative_found) * 50
        
        # Score final normalizado a 0.0-1.0
        raw_score = max(positive_score - negative_penalty, 0)
        score = raw_score / 100.0
        
        return score, keywords_found, negative_found
    
    def _calculate_structure_score(
        self,
        page_count: int,
        doc_type: str
    ) -> float:
        """
        Calcula la puntuación de estructura de páginas (Señal 2).
        
        Args:
            page_count: Número de páginas del documento
            doc_type: Tipo de documento esperado
            
        Returns:
            Score de 0.0 a 1.0
        """
        if doc_type not in DOCUMENT_PAGE_PROFILE:
            return 0.5  # Score neutral si no hay perfil
        
        profile = DOCUMENT_PAGE_PROFILE[doc_type]
        min_pages = profile["min"]
        max_pages = profile["max"]
        typical = profile["typical"]
        
        if page_count < min_pages:
            # Penalización por debajo del mínimo
            ratio = page_count / min_pages
            return max(ratio, 0.2)
        
        if page_count > max_pages:
            # Penalización por encima del máximo
            excess = page_count - max_pages
            penalty = excess / max_pages
            return max(1.0 - penalty, 0.2)
        
        # Dentro del rango: score base + bonus si es típico
        score = 1.0
        if page_count == typical:
            score = 1.0  # Bonus por valor típico
        elif abs(page_count - typical) <= 2:
            score = 0.95
        else:
            score = 0.85
        
        return score
    
    def _calculate_fields_score(
        self,
        extracted_fields: dict,
        doc_type: str
    ) -> float:
        """
        Calcula la puntuación de fingerprint de campos (Señal 3).
        
        Args:
            extracted_fields: Diccionario de campos extraídos
            doc_type: Tipo de documento esperado
            
        Returns:
            Score de 0.0 a 1.0
        """
        if doc_type not in DOCUMENT_FIELD_FINGERPRINT:
            return 0.5  # Score neutral si no hay fingerprint
        
        fingerprint = DOCUMENT_FIELD_FINGERPRINT[doc_type]
        discriminating = fingerprint["discriminating_fields"]
        anti_fields = fingerprint.get("anti_fields", [])
        
        # Normalizar nombres de campos a minúsculas
        field_names = set()
        for key, value in extracted_fields.items():
            key_lower = key.lower()
            # Solo contar campos con valor
            if value and value != "" and value != 0:
                field_names.add(key_lower)
                # También buscar en subcampos si es dict
                if isinstance(value, dict):
                    if value.get("valor"):
                        field_names.add(key_lower)
        
        # Contar campos discriminantes encontrados
        discriminating_found = 0
        for field in discriminating:
            field_lower = field.lower()
            # Buscar coincidencias parciales
            for name in field_names:
                if field_lower in name or name in field_lower:
                    discriminating_found += 1
                    break
        
        # Contar anti-campos encontrados
        anti_found = 0
        for field in anti_fields:
            field_lower = field.lower()
            for name in field_names:
                if field_lower in name or name in field_lower:
                    anti_found += 1
                    break
        
        # Calcular score
        if len(discriminating) == 0:
            positive_score = 0.5
        else:
            positive_score = discriminating_found / len(discriminating)
        
        # Penalizar por anti-campos
        anti_penalty = anti_found * 0.2
        
        score = max(positive_score - anti_penalty, 0.0)
        return min(score, 1.0)
    
    async def _calculate_llm_score(
        self,
        ocr_text: str,
        expected_type: str
    ) -> tuple[float, str, str]:
        """
        Calcula la puntuación del LLM semántico (Señal 4).
        
        Args:
            ocr_text: Texto OCR del documento
            expected_type: Tipo de documento esperado
            
        Returns:
            Tupla de (score, tipo_detectado, razonamiento)
        """
        if not self.openai_client:
            return 0.5, expected_type, "LLM no disponible"
        
        try:
            # Truncar texto a 1500 caracteres
            truncated_text = ocr_text[:1500] if len(ocr_text) > 1500 else ocr_text
            
            system_prompt = """Eres un clasificador de documentos para compliance bancario mexicano.
Recibirás texto OCR de un documento y un tipo de documento esperado.
Tu trabajo: determinar si el texto corresponde a ese tipo de documento.

Los tipos de documento posibles son:
- csf: Constancia de Situación Fiscal del SAT
- ine: Credencial del INE (anverso)
- ine_reverso: Credencial del INE (reverso)
- acta_constitutiva: Acta Constitutiva de empresa
- poder_notarial: Poder Notarial
- comprobante_domicilio: Recibos de servicios (luz, agua, teléfono, etc.)
- fiel: Firma Electrónica Avanzada
- estado_cuenta: Estado de cuenta bancario
- reforma_estatutos: Reforma de estatutos

Responde SOLO en JSON:
{
  "is_correct_document": true|false,
  "confidence": 0.0-1.0,
  "detected_document_type": "tipo_detectado",
  "reasoning": "una oración explicando"
}

No agregues texto fuera del JSON. No uses markdown."""

            user_prompt = f"""Tipo esperado: {expected_type}

Texto OCR del documento:
{truncated_text}"""

            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_tokens=200
            )
            
            # Parsear respuesta JSON
            content = response.choices[0].message.content.strip()
            
            # Limpiar posibles backticks de markdown
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            
            import json
            result = json.loads(content)
            
            confidence = float(result.get("confidence", 0.5))
            detected_type = result.get("detected_document_type", expected_type)
            reasoning = result.get("reasoning", "")
            is_correct = result.get("is_correct_document", False)
            
            # Si es correcto, score alto; si no, score bajo
            if is_correct:
                score = confidence
            else:
                score = 1.0 - confidence
            
            return score, detected_type, reasoning
            
        except Exception as e:
            logger.warning(f"Error al invocar LLM: {e}")
            return 0.5, expected_type, f"Error LLM: {str(e)}"
    
    def _is_incidental_mention(
        self,
        ocr_text: str,
        keyword: str,
        window: int = 150
    ) -> bool:
        """
        Verifica si una keyword aparece SOLO como referencia incidental
        (el notario menciona al documento como evidencia, no como contenido propio)
        en lugar de ser el encabezado o propósito del documento.

        Ejemplo incidental:
          "acreditandomelo con la Constancia de Situación Fiscal"
          → el notario citó la CSF como comprobante, el doc NO es una CSF.

        Retorna True únicamente si TODAS las ocurrencias de la keyword son
        incidentales.  Si al menos una aparición NO está precedida por un
        patrón de referencia, se considera match genuino (retorna False).
        """
        text_upper = self._normalize_text(ocr_text)
        keyword_upper = self._normalize_text(keyword)

        pos = 0
        incidental_count = 0
        total_count = 0

        while True:
            idx = text_upper.find(keyword_upper, pos)
            if idx == -1:
                break
            total_count += 1

            # Revisar los `window` caracteres anteriores al keyword
            context_before = text_upper[max(0, idx - window):idx]

            is_incidental = any(
                self._normalize_text(pattern) in context_before
                for pattern in REFERENCE_CONTEXT_PATTERNS
            )

            if is_incidental:
                incidental_count += 1

            pos = idx + 1

        # Solo se suprime si TODAS las ocurrencias son incidentales
        return total_count > 0 and incidental_count == total_count

    def _check_document_header(
        self,
        ocr_text: str
    ) -> tuple[str | None, float]:
        """
        Analiza los primeros 500 caracteres del OCR para detectar la
        declaración explícita del tipo de documento.

        Casi todos los documentos notariales mexicanos declaran su tipo
        en el encabezado (e.g., "ACTO: PROTOCOLIZACION DE ACTA DE ASAMBLEA...").
        Detectar esto antes de los demás signals evita clasificaciones erróneas.

        Incluye un chequeo compuesto para protocolización: si el header menciona
        PROTOCOLIZACIÓN, se determina el tipo según si es de poderes o de estatutos.

        Returns:
            Tupla (doc_type, multiplier):
            - Si hay match claro en header -> (tipo, 2.0)
            - Si no hay match -> (None, 1.0)
        """
        header = self._normalize_text(ocr_text[:500])

        # --- Chequeo compuesto para protocolización ---
        # "Protocolización" en el header puede ser de poderes o de estatutos;
        # discriminar por los indicadores que aparezcan en los primeros 500 chars.
        if "PROTOCOLIZACION" in header or "PROTOCOLIZACI" in header:
            poder_indicators = [
                "PODER GENERAL", "PODER ESPECIAL", "PODER CAMBIARIO",
                "OTORGAMIENTO DE PODER", "PODERES Y FACULTADES",
                "FACULTADES QUE SE", "PODERDANTE", "APODERADO",
                "SESION DEL CONSEJO", "SESIÓN DEL CONSEJO",
                "A EFECTO DE SOLICITAR LA PROTOCOLIZACION",
            ]
            reforma_indicators = [
                "ASAMBLEA EXTRAORDINARIA", "REFORMA DE ESTATUTOS",
                "BAJAS VOLUNTARIAS", "AUMENTO DE CAPITAL", "ORDEN DEL DIA",
                "ACTA DE ASAMBLEA",
            ]
            poder_matches = sum(1 for p in poder_indicators
                                if self._normalize_text(p) in header)
            reforma_matches = sum(1 for r in reforma_indicators
                                  if self._normalize_text(r) in header)

            if poder_matches > reforma_matches and poder_matches >= 1:
                return "poder_notarial", 2.0
            elif reforma_matches > poder_matches and reforma_matches >= 1:
                return "reforma_estatutos", 2.0
            # Si empatan, continuar con el análisis genérico

        # --- Búsqueda genérica en declaraciones de cabecera ---
        for doc_type, phrases in HEADER_DECLARATIONS.items():
            for phrase in phrases:
                normalized_phrase = self._normalize_text(phrase)
                if normalized_phrase in header:
                    return doc_type, 2.0
        return None, 1.0

    async def classify(
        self,
        ocr_text: str,
        ocr_fields: dict,
        page_count: int,
        expected_type: str,
        skip_llm: bool = False
    ) -> DocumentIdentityResult:
        """
        Clasifica el tipo de documento usando las 4 señales.
        
        Args:
            ocr_text: Texto OCR del documento
            ocr_fields: Campos extraídos por Azure DI
            page_count: Número de páginas
            expected_type: Tipo de documento esperado
            skip_llm: Si es True, no invoca el LLM
            
        Returns:
            Resultado de la clasificación con desglose de señales
        """
        # -----------------------------------------------------------------------
        # Señal 0 (prior): cabecera del documento
        # Los primeros 500 chars casi siempre declaran el tipo del documento.
        # Si la cabecera contradice el tipo esperado → penalizar score.
        # Si lo confirma → amplificar score.
        # -----------------------------------------------------------------------
        header_type, header_multiplier = self._check_document_header(ocr_text)

        # Señal 1: Keywords
        keywords_score, keywords_found, negative_found = self._calculate_keywords_score(
            ocr_text, expected_type
        )

        # Señal 2: Estructura
        structure_score = self._calculate_structure_score(page_count, expected_type)

        # Señal 3: Campos
        fields_score = self._calculate_fields_score(ocr_fields, expected_type)

        # Score combinado sin LLM
        combined_score_no_llm = (
            keywords_score * (self.WEIGHT_KEYWORDS / (1 - self.WEIGHT_LLM)) +
            structure_score * (self.WEIGHT_STRUCTURE / (1 - self.WEIGHT_LLM)) +
            fields_score * (self.WEIGHT_FIELDS / (1 - self.WEIGHT_LLM))
        )

        # -----------------------------------------------------------------------
        # Señal 4 (opcional): LLM — solo en zona ambigua
        # -----------------------------------------------------------------------
        llm_invoked = False
        llm_score = None
        llm_reasoning = None

        should_invoke_llm = (
            not skip_llm and
            self.openai_client is not None and
            self.LLM_INVOKE_MIN <= combined_score_no_llm <= self.LLM_INVOKE_MAX and
            len(negative_found) < 3  # No gastar en caso claramente incorrecto
        )

        if should_invoke_llm:
            llm_invoked = True
            llm_score_val, _, llm_reasoning = await self._calculate_llm_score(
                ocr_text, expected_type
            )
            llm_score = llm_score_val
            final_score = (
                keywords_score * self.WEIGHT_KEYWORDS +
                structure_score * self.WEIGHT_STRUCTURE +
                fields_score * self.WEIGHT_FIELDS +
                llm_score_val * self.WEIGHT_LLM
            )
        else:
            final_score = combined_score_no_llm
            if len(negative_found) >= 2:
                penalty = min(len(negative_found) * 0.15, 0.5)
                final_score = max(final_score - penalty, 0.0)

        # -----------------------------------------------------------------------
        # Aplicar prior de cabecera
        # -----------------------------------------------------------------------
        if header_type == expected_type:
            # La cabecera confirma el tipo esperado → reforzar confianza
            final_score = min(final_score * header_multiplier, 1.0)
        elif header_type is not None:
            # La cabecera declara un tipo DIFERENTE al esperado → limitar score
            final_score = min(final_score, 0.40)

        # -----------------------------------------------------------------------
        # Determinar veredicto: ¿eél documento correcto?
        # detected_type siempre es expected_type — solo evaluamos corrección.
        # -----------------------------------------------------------------------
        detected_type = expected_type

        if final_score >= self.THRESHOLD_CONFIRMED:
            status = "confirmed"
        elif final_score >= self.THRESHOLD_UNCERTAIN:
            status = "uncertain"
        else:
            status = "wrong_document"

        # Generar razonamiento
        reasoning = self._generate_reasoning(status, expected_type, final_score)

        return DocumentIdentityResult(
            is_correct=status in ("confirmed", "uncertain"),
            expected_type=expected_type,
            reasoning=reasoning,
            should_reject=status == "wrong_document"
        )

    def _generate_reasoning(
        self,
        status: str,
        expected_type: str,
        confidence: float
    ) -> str:
        """Genera una explicación legible del veredicto."""

        type_names = {
            "csf": "Constancia de Situación Fiscal",
            "ine": "INE (anverso)",
            "ine_reverso": "INE (reverso)",
            "acta_constitutiva": "Acta Constitutiva",
            "poder_notarial": "Poder Notarial",
            "comprobante_domicilio": "Comprobante de Domicilio",
            "fiel": "FIEL (Firma Electrónica)",
            "estado_cuenta": "Estado de Cuenta",
            "reforma_estatutos": "Reforma de Estatutos",
        }

        expected_name = type_names.get(expected_type, expected_type)

        if status == "confirmed":
            return f"Documento verificado como {expected_name}."

        if status == "uncertain":
            return (
                f"El documento podría ser {expected_name} pero presenta ambigüedad. "
                f"Se recomienda revisión manual."
            )

        return (
            f"El documento no parece corresponder a una {expected_name}. "
            f"Por favor suba el documento correcto."
        )


# =============================================================================
# FUNCIONES DE UTILIDAD
# =============================================================================

async def classify_document(
    ocr_text: str,
    ocr_fields: dict,
    page_count: int,
    expected_type: str,
    openai_client: Optional[Any] = None
) -> DocumentIdentityResult:
    """
    Función de conveniencia para clasificar un documento.
    
    Args:
        ocr_text: Texto OCR del documento
        ocr_fields: Campos extraídos
        page_count: Número de páginas
        expected_type: Tipo esperado
        openai_client: Cliente OpenAI opcional
        
    Returns:
        Resultado de la clasificación
    """
    agent = DocumentIdentifierAgent(openai_client=openai_client)
    return await agent.classify(
        ocr_text=ocr_text,
        ocr_fields=ocr_fields,
        page_count=page_count,
        expected_type=expected_type
    )
