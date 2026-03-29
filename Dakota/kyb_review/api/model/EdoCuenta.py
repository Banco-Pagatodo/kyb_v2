from pydantic import BaseModel
class EdoCuenta(BaseModel):
    """Data model for Estado de Cuenta"""
    bank:        str
    clabe:       str