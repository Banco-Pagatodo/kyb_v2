# api/client.py
# Test clients for the FastMCP server.
from ..model.PersonaFisica import PersonaFisica
from ..model.TipoPersonaFisica import TipoPersonaFisica

def get_apoderado_legal() -> PersonaFisica:
    """Get a sample legal representative (apoderado legal)."""
    return PersonaFisica(
        rfc = "XAXX010101000",
        name="John",
        last_name_1="Doe",
        last_name_2=None,
        gender="X",
        national=True,
        birth_date="2000-01-01",
        tipo_persona=TipoPersonaFisica.legal
    )

def get_ubo() -> PersonaFisica:
    """Get a sample ultimate beneficial owner (ubo)."""
    return PersonaFisica(
        rfc = "PAAL031119AZA",
        name="Daelyn",
        last_name_1="Doe",
        last_name_2=None,
        gender="M",
        national=True,
        birth_date="2000-01-01",
        tipo_persona=TipoPersonaFisica.ubo,
    )