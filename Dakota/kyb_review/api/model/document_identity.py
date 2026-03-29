"""
Modelos Pydantic para identificación de tipo de documento.

Respuesta simplificada: solo indica si el documento es correcto o no.
"""

from typing import Optional
from pydantic import BaseModel, Field


class DocumentIdentityResult(BaseModel):
    """Resultado de la identificación de tipo de documento."""

    is_correct: bool = Field(
        description="True si el documento corresponde al tipo esperado en el endpoint"
    )
    expected_type: str = Field(
        description="Tipo de documento esperado según el endpoint"
    )
    reasoning: str = Field(
        description="Explicación del veredicto para el usuario"
    )
    should_reject: bool = Field(
        description="True si el documento debe rechazarse automáticamente"
    )


class WrongDocumentError(Exception):
    """
    Excepción lanzada cuando se detecta un documento del tipo incorrecto.
    """

    def __init__(
        self,
        expected: str,
        message: Optional[str] = None
    ):
        self.expected = expected
        self.message = message or (
            f"El documento no parece corresponder al tipo '{expected}'. "
            f"Por favor suba el documento correcto."
        )
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Convierte la excepción a un diccionario para respuesta JSON."""
        return {
            "error": "wrong_document_type",
            "expected": self.expected,
            "message": self.message
        }

