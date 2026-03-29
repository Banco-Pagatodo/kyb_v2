from pydantic import BaseModel
from datetime import date

class ActaConstitutiva(BaseModel):
    """Data model for Acta Constitutiva"""
    writing_number:         int
    expedition_date:        date
    constitution_date:      date
    notary_number:          int
    notary_state:           str
    fme:                    int # Folio Mercantil Electrónico
    federatary_name:        str
    federatary_last_name_1: str
    federatary_last_name_2: str | None = None