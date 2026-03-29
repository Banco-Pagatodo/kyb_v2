from enum import Enum
class TipoPersonaFisica(str, Enum):
    """Valores posibles para tipo de persona física"""
    ubo         = "UBO"         # Ultimate Beneficial Owner
    legal       = "LEGAL"       # Legal Representative
    actionist   = "ACTIONIST"   # Actionist