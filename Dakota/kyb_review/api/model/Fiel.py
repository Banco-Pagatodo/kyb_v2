from pydantic import BaseModel, Field
from typing import Optional

class Fiel(BaseModel):
    """Data model for FIEL (Firma Electrónica Avanzada)
    
    Campos requeridos por la plataforma Prospectos:
    - Razón Social: Nombre o denominación del contribuyente
    - RFC: Registro Federal de Contribuyentes
    - Extranjeras: Indica si la empresa tiene operaciones en el extranjero o es de origen extranjero
    """
    razon_social: str = Field(..., description="Denominación o razón social del contribuyente")
    rfc: str = Field(..., description="Registro Federal de Contribuyentes", min_length=12, max_length=13)
    extranjeras: bool = Field(default=False, description="Indica si la empresa es extranjera o tiene operaciones en el extranjero")
    
    # Campos adicionales opcionales para contexto
    numero_serie_certificado: Optional[str] = Field(None, description="Número de serie del certificado digital")
    fecha_solicitud: Optional[str] = Field(None, description="Fecha y hora de solicitud")
    vigencia_desde: Optional[str] = Field(None, description="Fecha de inicio de vigencia del certificado")
    vigencia_hasta: Optional[str] = Field(None, description="Fecha de fin de vigencia del certificado")
    numero_operacion: Optional[str] = Field(None, description="Número de operación del trámite")
