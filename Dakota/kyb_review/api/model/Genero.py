from enum import Enum
class Genero(str, Enum):
    """Possible values for gender"""
    h = "H" # Hombre
    m = "M" # Mujer
    x = "X" # X for non-binary or unspecified