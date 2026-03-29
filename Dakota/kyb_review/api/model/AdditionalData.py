from pydantic import BaseModel, EmailStr

from api.model.TipoPersonaFisica import TipoPersonaFisica


class AdditionalData(BaseModel):
    """Data model for additional information"""
    ocupacion:          str
    pais_nacimiento:    str
    nacionalidad:       str
    email:              EmailStr
    telefono:           int
    street:             str
    exterior:           str
    interior:           str | None = None
    colony:             str
    postal_code:        int
    municipality:       str
    state:              str
    tipo_persona:       TipoPersonaFisica