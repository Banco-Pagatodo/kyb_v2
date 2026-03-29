from pydantic import BaseModel, EmailStr
from datetime import date

from api.model.Genero import Genero
from api.model.TipoPersonaFisica import TipoPersonaFisica

class PersonaFisica(BaseModel):
    """Data model for Persona Física"""
    rfc:                str
    name:               str
    last_name_1:        str
    last_name_2:        str | None = None
    gender:             Genero
    national:           bool
    birth_date:         date
    birth_place:        str | None = None
    tipo_persona:       TipoPersonaFisica
    occupation:         str | None = None
    nationality:        str | None = None
    email:              EmailStr | None = None
    phone:              int | None = None
    street:             str | None = None
    exterior:           str | None = None
    interior:           str | None = None
    colony:             str | None = None
    postal_code:        int | None = None
    municipality:       str | None = None
    state:              str | None = None