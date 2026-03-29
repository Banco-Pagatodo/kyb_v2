"""
Router de endpoints para el Agente de Validación.

Proporciona endpoints para consultar reglas de compliance KYB.
"""

from fastapi import APIRouter, Depends
from api.service.validator import validator_agent
from api.middleware.auth import require_api_key
import logging

router = APIRouter(
    prefix="/validator",
    tags=["Validator"],
    dependencies=[Depends(require_api_key)]
)

logger = logging.getLogger(__name__)


@router.get("/rules")
async def get_compliance_rules():
    """
    Obtiene la matriz de requisitos documentales y reglas de validación.
    
    Retorna:
    - document_requirements: Matriz completa de requisitos por documento
    - validation_rules: Reglas de validación con severidad y lógica
    
    Útil para:
    - Consultar qué documentos son requeridos vs condicionales
    - Ver vigencias máximas por tipo de documento
    - Entender requisitos específicos de cada documento
    - Revisar lógica de validación implementada
    """
    return {
        "document_requirements": {
            doc_type: req.dict()
            for doc_type, req in validator_agent.DOCUMENT_REQUIREMENTS.items()
        },
        "validation_rules": [rule.dict() for rule in validator_agent.validation_rules],
        "total_documents": len(validator_agent.DOCUMENT_REQUIREMENTS),
        "required_documents": sum(
            1 for req in validator_agent.DOCUMENT_REQUIREMENTS.values()
            if req.requerimiento == "Requerido"
        ),
        "conditional_documents": sum(
            1 for req in validator_agent.DOCUMENT_REQUIREMENTS.values()
            if req.requerimiento == "Condicional"
        )
    }
