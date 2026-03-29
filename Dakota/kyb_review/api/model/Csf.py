from pydantic import BaseModel, Field
from typing import Optional

class Csf(BaseModel):
    """Data model for Constancia de Situación Fiscal (CSF)
    
    Campos requeridos por la plataforma Prospectos:
    - Razón Social: Nombre o denominación del contribuyente
    - RFC: Registro Federal de Contribuyentes
    - Extranjeras: Indica si la empresa tiene operaciones en el extranjero o es de origen extranjero
    """
    razon_social: str = Field(..., description="Denominación o razón social del contribuyente")
    rfc: str = Field(..., description="Registro Federal de Contribuyentes", min_length=12, max_length=13)
    extranjeras: bool = Field(default=False, description="Indica si la empresa es extranjera o tiene operaciones en el extranjero")
    
    # Campos adicionales opcionales para contexto
    regimen_capital: Optional[str] = Field(None, description="Régimen de capital de la empresa")
    estatus: Optional[str] = Field(None, description="Estatus en el padrón (ACTIVO, SUSPENDIDO, etc.)")
    fecha_inicio_operaciones: Optional[str] = Field(None, description="Fecha de inicio de operaciones")