from pydantic import BaseModel
class Domicilio(BaseModel):
    """Data model for Domicilio"""
    street:         str
    exterior:       str
    interior:       str | None = None
    colony:         str
    postal_code:    int
    municipality:   str
    state:          str