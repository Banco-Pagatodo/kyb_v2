# api/model/__init__.py
"""
Modelos de datos para el sistema KYB.
"""

from .validator import (
    DocumentRequirement,
    ValidationResult,
    RequirementStatus,
    VigenciaType,
    ValidationRule,
    SingleDocumentValidation,
)

from .orchestrator import (
    ValidationDetail,
    DocumentError,
    DocumentResult,
    DocumentStage,
    ErrorSeverity,
    ReviewVerdict,
    OnboardingReviewRequest,
    OnboardingReviewResponse,
    REQUIRED_DOCUMENTS,
    CONDITIONAL_DOCUMENTS,
    DOCUMENT_NAMES,
)

__all__ = [
    # Validator models
    "DocumentRequirement",
    "ValidationResult",
    "RequirementStatus",
    "VigenciaType",
    "ValidationRule",
    "SingleDocumentValidation",
    # Orchestrator models
    "ValidationDetail",
    "DocumentError",
    "DocumentResult",
    "DocumentStage",
    "ErrorSeverity",
    "ReviewVerdict",
    "OnboardingReviewRequest",
    "OnboardingReviewResponse",
    "REQUIRED_DOCUMENTS",
    "CONDITIONAL_DOCUMENTS",
    "DOCUMENT_NAMES",
]