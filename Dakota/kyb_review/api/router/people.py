import time
from fastapi import (
    APIRouter, 
    Form,
    File,
    UploadFile,
    Query,
    Depends
)
from typing import Annotated
from datetime import date

from ..config import prefix

from ..model.Genero import Genero
from ..model.PersonaFisica import PersonaFisica
from ..model.AdditionalData import AdditionalData
from ..model.TipoPersonaFisica import TipoPersonaFisica
from ..model.DocFormat import DocFormat

from ..controller.files import save_file, delete_file
from ..controller.docs import analyze_ine, analyze_ine_reverso
from ..service.validation_wrapper import add_validation_to_response, normalize_dates_in_result
from ..middleware.auth import require_api_key

from ..client.client import *

router = APIRouter(
    prefix=prefix + "/persona_fisica",
    dependencies=[Depends(require_api_key)]  # Autenticacion requerida para todos los endpoints
)

@router.post("/ine")
async def validate_ine(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True
):
    """
    Endpoint to validate INE (frente).
    Returns structured extracted data with optional validation scores.
    """
    start_time = time.time()
    path = await save_file(file, prefix="ine_")
    from ..controller.docs import get_docformat
    format = get_docformat(path)
    result = analyze_ine(path, format)
    
    if include_validation:
        result = add_validation_to_response(
            result, "ine", file.filename or "unknown", time.time() - start_time
        )
    else:
        result = normalize_dates_in_result(result)
    
    return result

@router.post("/ine_reverso")
async def validate_ine_reverso(
    file: Annotated[UploadFile, File()],
    include_validation: Annotated[bool, Query(description="Include validation scores")] = True
):
    """
    Endpoint to validate INE back (reverso).
    Returns structured extracted data with optional validation scores.
    """
    start_time = time.time()
    path = await save_file(file, prefix="ine_reverso")
    from ..controller.docs import get_docformat
    format = get_docformat(path)
    result = analyze_ine_reverso(path, format)
    
    if include_validation:
        result = add_validation_to_response(
            result, "ine_reverso", file.filename or "unknown", time.time() - start_time
        )
    else:
        result = normalize_dates_in_result(result)
    
    return result

@router.post("/apoderado_legal")
async def validate_apoderado_legal(persona: Annotated[PersonaFisica, Form()]):
    """
    Endpoint to validate a legal representative (apoderado legal).
    """
    return persona

@router.post("/ubo")
async def validate_ubo(persona: Annotated[PersonaFisica, Form()]):
    """
    Endpoint to validate an ultimate beneficial owner (ubo).
    """
    return persona

@router.post("/update")
async def update_apoderado_legal(data: Annotated[AdditionalData, Form()]):
    """
    Endpoint to update a legal representative (apoderado legal).
    """
    if data.tipo_persona == TipoPersonaFisica.legal:
        persona = get_apoderado_legal()
    elif data.tipo_persona == TipoPersonaFisica.ubo:
        persona = get_ubo()
    else:
        return {"error": "Invalid tipo_persona"}
    persona.occupation       = data.ocupacion
    persona.birth_place      = data.pais_nacimiento
    persona.nationality      = data.nacionalidad
    persona.email            = data.email
    persona.phone            = data.telefono
    persona.street           = data.street
    persona.exterior         = data.exterior
    persona.interior         = data.interior
    persona.colony           = data.colony
    persona.postal_code      = data.postal_code
    persona.municipality     = data.municipality
    persona.state            = data.state
    return persona