from enum import Enum
class DocType(str, Enum):
    """Possible values for document formats"""
    ine                 = "INE"
    ine_reverso         = "INE Reverso"
    estado_cuenta       = "Estado de Cuenta"
    csf                 = "Constancia de Situación Fiscal"
    fiel                = "FIEL"
    domicilio           = "Comprobante de Domicilio"
    acta_constitutiva   = "Acta Constitutiva"
    poder_notarial      = "Poder Notarial"
    reforma_estatutos   = "Reforma de Estatutos"