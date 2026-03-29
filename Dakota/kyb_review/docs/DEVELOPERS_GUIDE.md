# KYB API - Guía Técnica para Desarrolladores

> **Documentación exhaustiva del flujo completo del código, arquitectura interna y patrones de diseño**

**Versión**: 1.3.0  
**Última actualización**: 27 de febrero de 2026  
**Audiencia**: Desarrolladores, Arquitectos de Software, DevOps

> **Nota v1.3.0**: Dakota es uno de los **3 agentes** del sistema KYB. Esta guía documenta la
> arquitectura interna de Dakota (extracción y persistencia). Para la visión completa del sistema
> multi-agente, consulta [ARCHITECTURE.md](ARCHITECTURE.md).
>
> | Agente | Puerto | Responsabilidad | Documentación |
> |--------|--------|----------------|---------------|
> | **Dakota** | 8000 | Extracción + Persistencia | **Esta guía** |
> | **Colorado** | 8001 | Validación Cruzada + Portales | `Colorado/cross_validation/README.md` |
> | **Orquestrator** | 8002 | Coordinación del Pipeline | `Orquestrator/README.md` |

---

## Tabla de Contenidos

1. [Visión General](#1-visión-general)
2. [Arquitectura del Sistema](#2-arquitectura-del-sistema)
3. [Flujo Completo del Código](#3-flujo-completo-del-código)
4. [Componentes Principales](#4-componentes-principales)
5. [Modelos de Datos](#5-modelos-de-datos)
6. [Patrones de Diseño](#6-patrones-de-diseño)
7. [Manejo de Errores](#7-manejo-de-errores)
8. [Optimizaciones y Performance](#8-optimizaciones-y-performance)
9. [Seguridad](#9-seguridad)
10. [Guías de Desarrollo](#10-guías-de-desarrollo)

---

## 1. Visión General

### 1.1 Propósito del Sistema

El sistema KYB automatiza la verificación de documentos para apertura de cuentas bancarias de personas morales mediante:

- **Extracción automática** de datos usando OCR (Azure Document Intelligence)
- **Estructuración** de datos con LLMs (Azure OpenAI GPT-4o)
- **Validación individual** de cada documento según requisitos KYB
- **Veredicto final** basado en conteo de errores

### 1.2 Principios de Diseño

1. **Fail-Fast**: Validar temprano y fallar rápido (guardrails)
2. **Single Responsibility**: Cada componente tiene una responsabilidad única
3. **Composabilidad**: Servicios independientes que se pueden componer
4. **Type Safety**: Uso extensivo de Pydantic para validación de tipos
5. **Async First**: Operaciones async donde sea posible

### 1.3 Stack Tecnológico

```python
# Core Framework
FastAPI 0.116+         # Web framework con validación automática
Pydantic 2.11+         # Validación de datos y serialización
Python 3.12+           # Type hints, async/await, pattern matching

# Azure Services
azure-ai-documentintelligence  # OCR de documentos
azure-ai-textanalytics         # NLP (opcional)
openai (Azure)                 # GPT-4o para extracción estructurada

# Utilidades
python-magic           # Detección MIME type (magic bytes)
thefuzz                # Fuzzy string matching (normalización)
tenacity               # Reintentos con backoff exponencial
```

---

## 2. Arquitectura del Sistema

### 2.1 Arquitectura de Capas

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                       │
│  (FastAPI Routers + Swagger UI + Middleware)                │
│                                                             │
│  • onboarding.py  - Endpoint principal                      │
│  • docs.py        - Endpoints individuales                  │
│  • API Key Auth   - Autenticación                           │
│  • Rate Limiting  - Control de tráfico                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    BUSINESS LOGIC LAYER                     │
│  (Services - Orquestación y Validación)                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  OrchestratorService                                │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │  process_review(expediente_id, files)        │   │   │
│  │  │    │                                          │   │   │
│  │  │    ├─ FASE 1: Para cada documento            │   │   │
│  │  │    │    └─ _process_single_document()        │   │   │
│  │  │    │         ├─ Guardrails                   │   │   │
│  │  │    │         ├─ Extracción                   │   │   │
│  │  │    │         └─ Validación                   │   │   │
│  │  │    │                                          │   │   │
│  │  │    └─ FASE 2: Veredicto final                │   │   │
│  │  │         └─ _determine_verdict()               │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  GuardrailService                                   │   │
│  │  • validate_file_format()                           │   │
│  │  • validate_file_size()                             │   │
│  │  • validate_security()                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ValidatorAgent                                     │   │
│  │  • _validate_vigencia()                             │   │
│  │  • _validate_specific_requirements()                │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  DATA ACCESS LAYER                          │
│  (Controllers - Interacción con APIs externas)              │
│                                                             │
│  • docs.py        - Azure DI + OpenAI orchestration         │
│  • openai.py      - Cliente OpenAI                          │
│  • di.py          - Cliente Azure DI                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  EXTERNAL SERVICES                          │
│                                                             │
│  • Azure Document Intelligence  (OCR)                       │
│  • Azure OpenAI                 (LLM)                       │
│  • Tesseract OCR               (Backup)                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Flujo de Datos

```
[Cliente HTTP Request]
        │
        ├─ Authorization: X-API-Key
        ├─ Content-Type: multipart/form-data
        └─ Body: {expediente_id, files}
        │
        ▼
[FastAPI Router: onboarding.py]
        │
        ├─ Validación Pydantic (OnboardingReviewRequest)
        ├─ API Key Verification (middleware)
        └─ Rate Limit Check (middleware)
        │
        ▼
[OrchestratorService.process_review()]
        │
        ├─ Para cada documento en files:
        │   │
        │   ├─ PASO 1: GUARDRAILS
        │   │   ├─ GuardrailService.validate_all()
        │   │   │   ├─ validate_file_format()  # MIME type
        │   │   │   └─ validate_security()     # Path traversal
        │   │   └─ Si falla → HTTPException 400
        │   │
        │   ├─ PASO 2: EXTRACCIÓN
        │   │   ├─ save_temp_file(upload_file)
        │   │   ├─ Controller: analyze_csf(temp_path)
        │   │   │   ├─ Azure DI: extract_document_text()
        │   │   │   │   └─ POST /documentModels/prebuilt-layout/analyze
        │   │   │   └─ OpenAI: structure_extracted_data()
        │   │   │       └─ POST /chat/completions
        │   │   │           {"model": "gpt-4o", "messages": [...]}
        │   │   └─ Resultado: {datos_extraidos: {...}}
        │   │
        │   └─ PASO 3: VALIDACIÓN
        │       ├─ ValidatorAgent._validate_single_document()
        │       │   ├─ _validate_vigencia()
        │       │   │   └─ Compara fecha_emision con now()
        │       │   └─ _validate_specific_requirements()
        │       │       └─ Verifica campos requeridos
        │       └─ Resultado: List[str] errores
        │
        ├─ FASE 2: VEREDICTO FINAL
        │   └─ _determine_verdict(document_results, all_errors)
        │       ├─ Contar errores_criticos
        │       ├─ Contar errores_altos
        │       └─ Retornar: APPROVED | REVIEW_REQUIRED | REJECTED
        │
        └─ Retornar: OnboardingReviewResponse
                     {verdict, documentos, errores, tiempo, ...}
        │
        ▼
[FastAPI Response]
        │
        ├─ Status: 200 OK
        ├─ Content-Type: application/json
        └─ Body: OnboardingReviewResponse serializado
```

---

## 3. Flujo Completo del Código

### 3.1 Entry Point: FastAPI Application

**Archivo**: `api/main.py`

```python
# api/main.py
from fastapi import FastAPI
from api.server.server import create_app

# Factory pattern para crear la app
app = create_app()

# El servidor se inicia con:
# python -m uvicorn api.main:app --reload --port 8000
```

**Archivo**: `api/server/server.py`

```python
# api/server/server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.router import onboarding, docs, people
from api.middleware.logging_middleware import logging_middleware
from api.middleware.rate_limit import rate_limit_middleware

def create_app() -> FastAPI:
    """Factory para crear la aplicación FastAPI."""
    
    app = FastAPI(
        title="KYB API",
        version="1.0.0",
        description="API de automatización KYB"
    )
    
    # Middleware (se ejecuta en orden inverso)
    app.middleware("http")(logging_middleware)  # Log de requests
    app.middleware("http")(rate_limit_middleware)  # Rate limiting
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # En prod: dominios específicos
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Routers
    app.include_router(onboarding.router)  # /onboarding/*
    app.include_router(docs.router)        # /docs/*
    app.include_router(people.router)      # /persona_fisica/*
    
    return app
```

### 3.2 Router: Endpoint Principal

**Archivo**: `api/router/onboarding.py`

```python
# api/router/onboarding.py
from fastapi import APIRouter, UploadFile, File, Form, Depends
from typing import Dict
from api.model.orchestrator import OnboardingReviewResponse
from api.service.orchestrator import orchestrator_service
from api.middleware.auth import require_api_key

router = APIRouter(
    prefix="/api/v1.0.0/onboarding",
    dependencies=[Depends(require_api_key)]
)

@router.post("/review", response_model=OnboardingReviewResponse)
async def process_onboarding_review(
    expediente_id: str = Form(...),
    fail_fast: bool = Form(True),
    # Archivos como dict: {doc_type: UploadFile}
    csf: UploadFile = File(None),
    acta_constitutiva: UploadFile = File(None),
    ine: UploadFile = File(None),
    ine_reverso: UploadFile = File(None),
    poder: UploadFile = File(None),
    comprobante_domicilio: UploadFile = File(None),
    fiel: UploadFile = File(None),
    estado_cuenta: UploadFile = File(None),
    reforma: UploadFile = File(None),
) -> OnboardingReviewResponse:
    """
    Endpoint principal para procesamiento de onboarding completo.
    
    Flujo:
    1. Para cada documento: Guardrails → Extracción → Validación
    2. Veredicto final basado en conteo de errores
    
    Args:
        expediente_id: ID único del expediente
        fail_fast: Detener al primer error crítico
        csf...reforma: Documentos opcionales
        
    Returns:
        OnboardingReviewResponse con veredicto y detalles
    """
    
    # Construir dict de files (solo los que se recibieron)
    files: Dict[str, UploadFile] = {}
    if csf:
        files["csf"] = csf
    if acta_constitutiva:
        files["acta_constitutiva"] = acta_constitutiva
    if ine:
        files["ine"] = ine
    if ine_reverso:
        files["ine_reverso"] = ine_reverso
    if poder:
        files["poder"] = poder
    if comprobante_domicilio:
        files["comprobante_domicilio"] = comprobante_domicilio
    if fiel:
        files["fiel"] = fiel
    if estado_cuenta:
        files["estado_cuenta"] = estado_cuenta
    if reforma:
        files["reforma"] = reforma
    
    # Delegar al Orchestrator Service
    return await orchestrator_service.process_review(
        expediente_id=expediente_id,
        files=files,
        fail_fast=fail_fast
    )
```

### 3.3 Service: Orchestrator (Componente Central)

**Archivo**: `api/service/orchestrator.py`

```python
# api/service/orchestrator.py (versión simplificada para claridad)
import asyncio
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from fastapi import UploadFile

from api.model.orchestrator import (
    OnboardingReviewResponse,
    DocumentResult,
    DocumentError,
    DocumentStage,
    ErrorSeverity,
    ReviewVerdict
)
from api.service.guardrails import guardrail_service
from api.service.validator import validator_agent
from api.controller.docs import analyze_csf, analyze_constitutiva, analyze_ine, ...

class OrchestratorService:
    """
    Coordinador central del flujo de onboarding.
    
    Responsabilidades:
    1. Procesar cada documento individualmente
    2. Coordinar Guardrails → Extracción → Validación
    3. Generar veredicto final
    """
    
    # Mapeo de tipos de documento a funciones de extracción
    EXTRACTORS = {
        "csf": analyze_csf,
        "acta_constitutiva": analyze_constitutiva,
        "ine": lambda path: analyze_ine(path, get_docformat(path)),
        "ine_reverso": analyze_ine_reverso,
        "poder": analyze_poder,
        "comprobante_domicilio": analyze_domicilio,
        "fiel": analyze_fiel,
        "estado_cuenta": analyze_estado_cuenta,
        "reforma": analyze_reforma
    }
    
    async def process_review(
        self,
        expediente_id: str,
        files: Dict[str, UploadFile],
        fail_fast: bool = True
    ) -> OnboardingReviewResponse:
        """
        Procesa una revisión completa de onboarding.
        
        Flujo detallado:
        
        FASE 1: Para cada documento
            ├─ Guardrails (formato, tamaño, seguridad)
            ├─ Extracción (Azure DI + OpenAI)
            └─ Validación individual (vigencia, campos, etc.)
        
        FASE 2: Veredicto final
            └─ Basado en conteo de errores críticos/altos
        
        Args:
            expediente_id: ID único del expediente
            files: Dict {"doc_type": UploadFile}
            fail_fast: Si True, detiene al primer error crítico
            
        Returns:
            OnboardingReviewResponse con todos los detalles
        """
        started_at = datetime.now()
        
        # Estructuras para resultados
        document_results: List[DocumentResult] = []
        all_errors: List[DocumentError] = []
        extracted_data: Dict[str, Any] = {}
        critical_error_encountered = False
        
        # ═══════════════════════════════════════════════════════
        # FASE 1: Procesamiento Individual de Documentos
        # ═══════════════════════════════════════════════════════
        
        for doc_type, upload_file in files.items():
            if critical_error_encountered and fail_fast:
                break
            
            # Procesar documento individual
            doc_result, doc_errors, doc_data = await self._process_single_document(
                doc_type=doc_type,
                upload_file=upload_file,
                fail_fast=fail_fast
            )
            
            # Acumular resultados
            document_results.append(doc_result)
            all_errors.extend(doc_errors)
            
            if doc_data:
                extracted_data[doc_type] = doc_data
            
            # Verificar errores críticos para fail-fast
            critical_errors = [e for e in doc_errors 
                             if e.severity == ErrorSeverity.CRITICAL]
            if critical_errors and fail_fast:
                critical_error_encountered = True
        
        # ═══════════════════════════════════════════════════════
        # FASE 2: Veredicto Final
        # ═══════════════════════════════════════════════════════
        
        completed_at = datetime.now()
        total_ms = int((completed_at - started_at).total_seconds() * 1000)
        
        # Calcular métricas
        docs_exitosos = sum(1 for d in document_results 
                           if d.validation_passed)
        docs_fallidos = sum(1 for d in document_results 
                           if d.stage == DocumentStage.FAILED)
        errores_criticos = sum(1 for e in all_errors 
                             if e.severity == ErrorSeverity.CRITICAL)
        
        # Determinar veredicto
        verdict, resumen, auto_aprobable = self._determine_verdict(
            document_results=document_results,
            all_errors=all_errors
        )
        
        # Generar recomendaciones
        recomendaciones = self._generate_recommendations(
            all_errors,
            document_results
        )
        
        return OnboardingReviewResponse(
            expediente_id=expediente_id,
            verdict=verdict,
            resumen=resumen,
            documentos_procesados=len(document_results),
            documentos_exitosos=docs_exitosos,
            documentos_fallidos=docs_fallidos,
            errores_criticos=errores_criticos,
            documentos=document_results,
            todos_errores=all_errors,
            recomendaciones=recomendaciones,
            auto_aprobable=auto_aprobable,
            started_at=started_at,
            completed_at=completed_at,
            total_processing_time_ms=total_ms
        )
    
    async def _process_single_document(
        self,
        doc_type: str,
        upload_file: UploadFile,
        fail_fast: bool
    ) -> Tuple[DocumentResult, List[DocumentError], Optional[Dict[str, Any]]]:
        """
        Procesa un documento individual siguiendo el pipeline:
        
        Guardrails → OCR/Extracción → Validación
        
        Returns:
            (DocumentResult, errores, datos_extraidos)
        """
        started_at = datetime.now()
        errors: List[DocumentError] = []
        extracted_data = None
        
        doc_result = DocumentResult(
            documento_tipo=doc_type,
            archivo=upload_file.filename or "unknown",
            started_at=started_at,
            stage=DocumentStage.GUARDRAILS
        )
        
        # ─────────────────────────────────────────────────────
        # PASO 1: GUARDRAILS (Fail-Fast)
        # ─────────────────────────────────────────────────────
        try:
            # Validación instantánea (<10ms)
            guardrail_service.validate_all(upload_file, doc_type)
        except HTTPException as e:
            # Guardrail rechazó el archivo
            doc_result.stage = DocumentStage.FAILED
            errors.append(DocumentError(
                documento=doc_type,
                stage=DocumentStage.GUARDRAILS,
                severity=ErrorSeverity.CRITICAL,
                mensaje=e.detail
            ))
            doc_result.errores = errors
            return doc_result, errors, None
        
        # ─────────────────────────────────────────────────────
        # PASO 2: EXTRACCIÓN (Azure DI + OpenAI)
        # ─────────────────────────────────────────────────────
        doc_result.stage = DocumentStage.EXTRACTING
        
        try:
            # Guardar archivo temporalmente
            temp_path = await self._save_temp_file(upload_file, doc_type)
            
            # Obtener función extractora para este tipo
            extractor_func = self.EXTRACTORS.get(doc_type)
            if not extractor_func:
                raise ValueError(f"No hay extractor para {doc_type}")
            
            # Ejecutar extracción (5-10 segundos)
            # Esta función llama a Azure DI y OpenAI internamente
            extraction_result = extractor_func(temp_path)
            extracted_data = extraction_result.get("datos_extraidos", {})
            
        except Exception as e:
            doc_result.stage = DocumentStage.FAILED
            errors.append(DocumentError(
                documento=doc_type,
                stage=DocumentStage.EXTRACTING,
                severity=ErrorSeverity.HIGH,
                mensaje=f"Error en extracción: {str(e)}"
            ))
            doc_result.errores = errors
            return doc_result, errors, None
        
        # ─────────────────────────────────────────────────────
        # PASO 3: VALIDACIÓN INDIVIDUAL
        # ─────────────────────────────────────────────────────
        doc_result.stage = DocumentStage.VALIDATING
        
        try:
            # Validar usando el Validator Agent
            validation_errors = await self._validate_single_document(
                doc_type=doc_type,
                doc_data=extracted_data
            )
            
            if validation_errors:
                # Hay errores de validación
                for error_msg in validation_errors:
                    severity = (ErrorSeverity.CRITICAL 
                              if self._is_critical_error(error_msg)
                              else ErrorSeverity.HIGH)
                    
                    errors.append(DocumentError(
                        documento=doc_type,
                        stage=DocumentStage.VALIDATING,
                        severity=severity,
                        mensaje=error_msg
                    ))
                
                doc_result.validation_passed = False
                doc_result.stage = DocumentStage.FAILED
            else:
                # Todo OK
                doc_result.validation_passed = True
                doc_result.stage = DocumentStage.COMPLETED
                
        except Exception as e:
            doc_result.stage = DocumentStage.FAILED
            errors.append(DocumentError(
                documento=doc_type,
                stage=DocumentStage.VALIDATING,
                severity=ErrorSeverity.HIGH,
                mensaje=f"Error en validación: {str(e)}"
            ))
        
        # Finalizar resultado
        completed_at = datetime.now()
        doc_result.completed_at = completed_at
        doc_result.processing_time_ms = int(
            (completed_at - started_at).total_seconds() * 1000
        )
        doc_result.errores = errors
        
        return doc_result, errors, extracted_data
    
    async def _validate_single_document(
        self,
        doc_type: str,
        doc_data: Dict[str, Any]
    ) -> List[str]:
        """
        Valida un documento usando el ValidatorAgent.
        
        Validaciones:
        1. Vigencia (para documentos con fecha de emisión/vencimiento)
        2. Requisitos específicos (campos obligatorios, formato RFC, etc.)
        
        Returns:
            Lista de mensajes de error (vacía si todo OK)
        """
        errors = []
        
        if doc_type not in validator_agent.DOCUMENT_REQUIREMENTS:
            return errors
        
        requirement = validator_agent.DOCUMENT_REQUIREMENTS[doc_type]
        datos = doc_data.get("datos_extraidos", {})
        
        # 1. Validar vigencia
        vigencia_result = await validator_agent._validate_vigencia(
            doc_type=doc_type,
            vigencia_type=requirement.vigencia_maxima,
            datos=datos
        )
        
        if not vigencia_result.get("valid", True):
            errors.append(vigencia_result.get("error", "Error de vigencia"))
        
        # 2. Validar requisitos específicos
        specific_errors = await validator_agent._validate_specific_requirements(
            doc_type=doc_type,
            requisitos=requirement.requisitos_especificos,
            datos=datos
        )
        
        errors.extend(specific_errors)
        
        return errors
    
    def _determine_verdict(
        self,
        document_results: List[DocumentResult],
        all_errors: List[DocumentError]
    ) -> Tuple[ReviewVerdict, str, bool]:
        """
        Determina el veredicto final basado en conteo de errores.
        
        Lógica:
        • APPROVED:         0 errores críticos + 0 errores altos
        • REVIEW_REQUIRED:  1-2 errores críticos/altos
        • REJECTED:         3+ errores críticos
        
        Returns:
            (verdict, resumen, auto_aprobable)
        """
        errores_criticos = [e for e in all_errors 
                           if e.severity == ErrorSeverity.CRITICAL]
        errores_altos = [e for e in all_errors 
                        if e.severity == ErrorSeverity.HIGH]
        
        docs_exitosos = sum(1 for d in document_results 
                           if d.validation_passed)
        docs_total = len(document_results)
        
        # REJECTED: Demasiados errores críticos
        if len(errores_criticos) >= 3:
            return (
                ReviewVerdict.REJECTED,
                f"Expediente rechazado: {len(errores_criticos)} errores críticos.",
                False
            )
        
        # APPROVED: Sin errores
        if len(errores_criticos) == 0 and len(errores_altos) == 0:
            if docs_exitosos == docs_total:
                return (
                    ReviewVerdict.APPROVED,
                    f"Expediente aprobado automáticamente. "
                    f"{docs_exitosos}/{docs_total} documentos validados.",
                    True
                )
        
        # REVIEW_REQUIRED: Hay algunos errores
        partes_resumen = []
        if errores_criticos:
            partes_resumen.append(f"{len(errores_criticos)} error(es) crítico(s)")
        if errores_altos:
            partes_resumen.append(f"{len(errores_altos)} advertencia(s)")
        
        return (
            ReviewVerdict.REVIEW_REQUIRED,
            f"Expediente requiere revisión manual: {', '.join(partes_resumen)}. "
            f"{docs_exitosos}/{docs_total} documentos validados.",
            False
        )


# Singleton
orchestrator_service = OrchestratorService()
```

---

## 4. Componentes Principales

### 4.1 GuardrailService

**Propósito**: Validación fail-fast para rechazar archivos inválidos antes de procesarlos.

**Archivo**: `api/service/guardrails.py`

```python
# api/service/guardrails.py
import magic
from fastapi import UploadFile, HTTPException, status
from pathlib import Path

class GuardrailService:
    """
    Servicio de validación temprana (fail-fast).
    
    Reduce costos al rechazar archivos inválidos ANTES de:
    - Llamadas a Azure DI (~$0.01-0.02 por página)
    - Llamadas a OpenAI (~$0.005 por documento)
    
    Tiempo de validación: <10ms
    """
    
    # NOTA: Validación de tamaño DESHABILITADA
    # Azure Document Intelligence soporta archivos de hasta 500MB
    # La validación de tamaño se removió para mayor flexibilidad
    
    # MIME types permitidos (validados con magic bytes)
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "application/zip"  # Para FIEL
    }
    
    # Extensiones permitidas
    ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".zip"}
    
    def validate_all(self, file: UploadFile, doc_type: str):
        """
        Ejecuta todas las validaciones. Lanza HTTPException si falla.
        
        Validaciones:
        1. Formato de archivo (MIME type + extensión)
        2. Seguridad (path traversal, extensiones peligrosas)
        
        NOTA: Validación de tamaño deshabilitada.
        """
        # 1. Validar formato
        format_result = self.validate_file_format(file)
        if not format_result.passed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=format_result.error_message
            )
        
        # 2. Validar seguridad
        security_result = self.validate_security(file)
        if not security_result.passed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=security_result.error_message
            )
    
    def validate_file_format(self, file: UploadFile):
        """
        Valida formato usando magic bytes (no confía en extensión).
        
        Detecta intentos de renombrar archivos:
        - archivo.txt → archivo.pdf (detectado como text/plain)
        - malware.exe → documento.pdf (detectado como application/x-executable)
        """
        file.file.seek(0)
        file_content = file.file.read(2048)  # Primeros 2KB
        file.file.seek(0)
        
        # Detectar MIME real con libmagic
        detected_mime = magic.from_buffer(file_content, mime=True)
        
        # Validar extensión
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in self.ALLOWED_EXTENSIONS:
            return GuardrailResult(
                passed=False,
                error_code="INVALID_EXTENSION",
                error_message=f"Extensión {file_ext} no permitida"
            )
        
        # Validar MIME type
        if detected_mime not in self.ALLOWED_MIME_TYPES:
            return GuardrailResult(
                passed=False,
                error_code="INVALID_MIME_TYPE",
                error_message=f"Tipo MIME {detected_mime} no permitido"
            )
        
        return GuardrailResult(passed=True)
    
    def validate_file_size(self, file: UploadFile, doc_type: str):
        """Valida tamaño del archivo según límites por tipo."""
        file.file.seek(0, 2)  # Ir al final
        file_size = file.file.tell()
        file.file.seek(0)  # Volver al inicio
        
        size_limit = self.FILE_SIZE_LIMITS.get(doc_type, 
                                               self.FILE_SIZE_LIMITS["default"])
        
        if file_size > size_limit:
            return GuardrailResult(
                passed=False,
                error_code="FILE_TOO_LARGE",
                error_message=f"Archivo de {file_size/1024/1024:.2f}MB "
                            f"excede {size_limit/1024/1024:.0f}MB"
            )
        
        if file_size == 0:
            return GuardrailResult(
                passed=False,
                error_code="EMPTY_FILE",
                error_message="El archivo está vacío"
            )
        
        return GuardrailResult(passed=True)
    
    def validate_security(self, file: UploadFile):
        """
        Valida que el archivo no tenga secuencias peligrosas.
        
        Bloquea:
        - Path traversal: ../../etc/passwd
        - Null bytes: archivo.pdf\x00.exe
        - Caracteres peligrosos en nombre de archivo
        """
        filename = file.filename or ""
        
        # Path traversal
        if ".." in filename:
            return GuardrailResult(
                passed=False,
                error_code="PATH_TRAVERSAL",
                error_message="Nombre de archivo con secuencias peligrosas (..)"
            )
        
        # Null bytes
        if "\x00" in filename:
            return GuardrailResult(
                passed=False,
                error_code="NULL_BYTE",
                error_message="Nombre de archivo con null bytes"
            )
        
        return GuardrailResult(passed=True)


# Singleton
guardrail_service = GuardrailService()
```

### 4.2 ValidatorAgent

**Propósito**: Validación de requisitos KYB para cada tipo de documento.

**Archivo**: `api/service/validator.py`

```python
# api/service/validator.py
from datetime import datetime, timedelta
from typing import Dict, List, Any
from enum import Enum

class VigenciaType(str, Enum):
    """Tipos de vigencia para documentos."""
    SIN_VENCIMIENTO = "sin_vencimiento"  # Acta Constitutiva
    TRES_MESES = "3_meses"               # CSF, Comprobante Domicilio
    VIGENTE = "vigente"                  # INE, Poder, FIEL (según fecha)
    VARIABLE = "variable"                # Poder (puede ser indefinido)


class DocumentRequirement:
    """Requisitos de validación para un tipo de documento."""
    def __init__(
        self,
        doc_type: str,
        vigencia_maxima: VigenciaType,
        requisitos_especificos: List[str]
    ):
        self.doc_type = doc_type
        self.vigencia_maxima = vigencia_maxima
        self.requisitos_especificos = requisitos_especificos


class ValidatorAgent:
    """
    Agente de validación de requisitos KYB.
    
    Para cada tipo de documento, valida:
    1. Vigencia (según tipo de documento)
    2. Requisitos específicos (campos obligatorios, formatos, etc.)
    """
    
    # Matriz de requisitos por tipo de documento
    DOCUMENT_REQUIREMENTS = {
        "csf": DocumentRequirement(
            doc_type="csf",
            vigencia_maxima=VigenciaType.TRES_MESES,
            requisitos_especificos=[
                "rfc_presente",
                "rfc_formato_valido",
                "estatus_activo",
                "denominacion_presente",
                "domicilio_fiscal_presente",
                "regimen_fiscal_presente"
            ]
        ),
        "ine": DocumentRequirement(
            doc_type="ine",
            vigencia_maxima=VigenciaType.VIGENTE,
            requisitos_especificos=[
                "curp_presente",
                "curp_formato_valido",
                "nombre_completo_presente",
                "fecha_nacimiento_presente"
            ]
        ),
        "acta_constitutiva": DocumentRequirement(
            doc_type="acta_constitutiva",
            vigencia_maxima=VigenciaType.SIN_VENCIMIENTO,
            requisitos_especificos=[
                "folio_mercantil_presente",
                "protocolizacion_evidencia",
                "fecha_constitucion_presente",
                "notario_presente",
                "rfc_presente",
                "denominacion_social_presente"
            ]
        ),
        "reforma": DocumentRequirement(
            doc_type="reforma",
            vigencia_maxima=VigenciaType.SIN_VENCIMIENTO,
            requisitos_especificos=[
                "numero_escritura_presente",
                "razon_social_presente",
                "fecha_otorgamiento_presente",
                "nombre_notario_presente",
                "numero_notaria_presente",
                "folio_mercantil_presente",
                "estructura_accionaria_presente"
            ]
        ),
        # ... otros documentos
    }
    
    async def _validate_vigencia(
        self,
        doc_type: str,
        vigencia_type: VigenciaType,
        datos: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Valida vigencia según tipo de documento.
        
        Lógica por tipo:
        • TRES_MESES:       fecha_emision debe ser ≤ 90 días
        • VIGENTE:          fecha_vencimiento debe ser > hoy
        • SIN_VENCIMIENTO:  Siempre válido
        • VARIABLE:         Verificar si tiene fecha_vencimiento
        
        Returns:
            {"valid": bool, "error": str | None}
        """
        now = datetime.now()
        
        if vigencia_type == VigenciaType.SIN_VENCIMIENTO:
            return {"valid": True}
        
        if vigencia_type == VigenciaType.TRES_MESES:
            fecha_emision = datos.get("fecha_emision")
            if not fecha_emision:
                return {
                    "valid": False,
                    "error": f"{doc_type}: fecha_emision no proporcionada"
                }
            
            # Convertir a datetime si es string
            if isinstance(fecha_emision, str):
                try:
                    fecha_emision = datetime.fromisoformat(
                        fecha_emision.replace('Z', '+00:00')
                    )
                except:
                    return {
                        "valid": False,
                        "error": f"{doc_type}: fecha_emision formato inválido"
                    }
            
            # Verificar antigüedad
            dias_antiguedad = (now - fecha_emision).days
            if dias_antiguedad > 90:
                return {
                    "valid": False,
                    "error": f"{doc_type}: documento con {dias_antiguedad} "
                           f"días de antigüedad (máximo 90)"
                }
            
            return {"valid": True}
        
        if vigencia_type == VigenciaType.VIGENTE:
            fecha_vencimiento = datos.get("fecha_vencimiento")
            if not fecha_vencimiento:
                # Algunos documentos usan vigencia_años
                vigencia_años = datos.get("vigencia_años", 10)
                fecha_emision = datos.get("fecha_emision")
                
                if fecha_emision:
                    if isinstance(fecha_emision, str):
                        fecha_emision = datetime.fromisoformat(
                            fecha_emision.replace('Z', '+00:00')
                        )
                    fecha_vencimiento = fecha_emision + timedelta(
                        days=vigencia_años * 365
                    )
            
            if isinstance(fecha_vencimiento, str):
                fecha_vencimiento = datetime.fromisoformat(
                    fecha_vencimiento.replace('Z', '+00:00')
                )
            
            if fecha_vencimiento and fecha_vencimiento < now:
                return {
                    "valid": False,
                    "error": f"{doc_type}: documento vencido "
                           f"(vencimiento: {fecha_vencimiento.date()})"
                }
            
            return {"valid": True}
        
        return {"valid": True}
    
    async def _validate_specific_requirements(
        self,
        doc_type: str,
        requisitos: List[str],
        datos: Dict[str, Any]
    ) -> List[str]:
        """
        Valida requisitos específicos del documento.
        
        Cada requisito es un string descriptivo que se mapea a una función de validación.
        
        Ejemplo para CSF:
        • "rfc_presente"             → Verificar que datos.rfc existe
        • "rfc_formato_valido"       → Verificar regex [A-Z]{3,4}\d{6}[A-Z0-9]{3}
        • "estatus_activo"           → Verificar que datos.estatus == "ACTIVO"
        • "denominacion_presente"    → Verificar que datos.denominacion_razon_social existe
        
        Returns:
            Lista de mensajes de error (vacía si todo OK)
        """
        errors = []
        
        for requisito in requisitos:
            # Determinar qué validar según el requisito
            if requisito == "rfc_presente":
                if not datos.get("rfc"):
                    errors.append(f"{doc_type}: RFC no proporcionado")
            
            elif requisito == "rfc_formato_valido":
                rfc = datos.get("rfc", "")
                # RFC moral: 3 letras + 6 dígitos + 3 alfanuméricos
                # RFC físico: 4 letras + 6 dígitos + 3 alfanuméricos
                import re
                if not re.match(r'^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$', rfc):
                    errors.append(f"{doc_type}: RFC con formato inválido ({rfc})")
            
            elif requisito == "estatus_activo":
                estatus = datos.get("estatus_padron", "").upper()
                if estatus != "ACTIVO":
                    errors.append(
                        f"{doc_type}: RFC no está en estatus ACTIVO (estatus: {estatus})"
                    )
            
            elif requisito == "denominacion_presente":
                if not datos.get("denominacion_razon_social") and \
                   not datos.get("nombre_razon_social"):
                    errors.append(
                        f"{doc_type}: denominación/razón social no proporcionada"
                    )
            
            elif requisito == "domicilio_fiscal_presente":
                domicilio = datos.get("domicilio_fiscal") or datos.get("domicilio")
                if not domicilio:
                    errors.append(f"{doc_type}: domicilio fiscal no proporcionado")
            
            elif requisito == "regimen_fiscal_presente":
                if not datos.get("regimen_fiscal") and \
                   not datos.get("regimenes_fiscales"):
                    errors.append(f"{doc_type}: régimen fiscal no proporcionado")
            
            elif requisito == "curp_presente":
                if not datos.get("curp"):
                    errors.append(f"{doc_type}: CURP no proporcionada")
            
            elif requisito == "curp_formato_valido":
                curp = datos.get("curp", "")
                # CURP: 18 caracteres alfanuméricos
                if not re.match(r'^[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$', curp):
                    errors.append(f"{doc_type}: CURP con formato inválido ({curp})")
            
            elif requisito == "nombre_completo_presente":
                if not (datos.get("nombre") and 
                       (datos.get("apellido_paterno") or datos.get("apellidos"))):
                    errors.append(f"{doc_type}: nombre completo incompleto")
            
            elif requisito == "fecha_nacimiento_presente":
                if not datos.get("fecha_nacimiento"):
                    errors.append(f"{doc_type}: fecha de nacimiento no proporcionada")
            
            elif requisito == "folio_mercantil_presente":
                if not datos.get("folio_mercantil") and \
                   not datos.get("folio"):
                    errors.append(f"{doc_type}: folio mercantil no proporcionado")
            
            elif requisito == "protocolizacion_evidencia":
                # Verificar que haya evidencia de protocolización
                if not (datos.get("numero_notaria") or 
                       datos.get("notario") or 
                       datos.get("escritura")):
                    errors.append(
                        f"{doc_type}: no muestra evidencia de protocolización notarial"
                    )
            
            elif requisito == "fecha_constitucion_presente":
                if not datos.get("fecha_constitucion"):
                    errors.append(
                        f"{doc_type}: fecha de constitución no proporcionada"
                    )
            
            elif requisito == "notario_presente":
                if not datos.get("notario") and \
                   not datos.get("numero_notaria"):
                    errors.append(f"{doc_type}: información de notario no proporcionada")
            
            elif requisito == "denominacion_social_presente":
                if not datos.get("denominacion_social") and \
                   not datos.get("razon_social"):
                    errors.append(
                        f"{doc_type}: denominación social no proporcionada"
                    )
            
            # ... otros requisitos
        
        return errors


# Singleton
validator_agent = ValidatorAgent()
```

---

## 5. Modelos de Datos

### 5.1 Modelos del Orchestrator

**Archivo**: `api/model/orchestrator.py`

```python
# api/model/orchestrator.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from enum import Enum

class ReviewVerdict(str, Enum):
    """Veredicto final del proceso de onboarding."""
    APPROVED = "APPROVED"                # Auto-aprobable
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # Requiere revisión manual
    REJECTED = "REJECTED"                # Rechazado

class DocumentStage(str, Enum):
    """Etapa del procesamiento de un documento."""
    PENDING = "PENDING"          # Sin procesar
    GUARDRAILS = "GUARDRAILS"    # Validando guardrails
    EXTRACTING = "EXTRACTING"    # Extrayendo datos
    VALIDATING = "VALIDATING"    # Validando requisitos
    COMPLETED = "COMPLETED"      # Completado exitosamente
    FAILED = "FAILED"            # Falló en alguna etapa

class ErrorSeverity(str, Enum):
    """Severidad de un error."""
    CRITICAL = "CRITICAL"  # Bloquea aprobación automática
    HIGH = "HIGH"          # Advertencia importante
    MEDIUM = "MEDIUM"      # Advertencia menor
    LOW = "LOW"            # Informativo

class DocumentError(BaseModel):
    """Error encontrado en un documento."""
    documento: str
    stage: DocumentStage
    severity: ErrorSeverity
    mensaje: str

class DocumentResult(BaseModel):
    """Resultado del procesamiento de un documento individual."""
    documento_tipo: str
    archivo: str
    stage: DocumentStage
    validation_passed: bool = False
    processing_time_ms: int = 0
    errores: List[DocumentError] = []
    started_at: datetime
    completed_at: Optional[datetime] = None

class OnboardingReviewRequest(BaseModel):
    """Request para el endpoint de onboarding."""
    expediente_id: str = Field(..., description="ID único del expediente")
    fail_fast: bool = Field(True, description="Detener al primer error crítico")

class OnboardingReviewResponse(BaseModel):
    """Response del proceso de onboarding completo."""
    expediente_id: str
    verdict: ReviewVerdict
    resumen: str
    documentos_procesados: int
    documentos_exitosos: int
    documentos_fallidos: int
    errores_criticos: int
    documentos: List[DocumentResult]
    todos_errores: List[DocumentError]
    recomendaciones: List[str]
    auto_aprobable: bool
    started_at: datetime
    completed_at: datetime
    total_processing_time_ms: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "expediente_id": "EXP-2026-001",
                "verdict": "APPROVED",
                "resumen": "Expediente aprobado automáticamente. 5/5 documentos validados.",
                "documentos_procesados": 5,
                "documentos_exitosos": 5,
                "documentos_fallidos": 0,
                "errores_criticos": 0,
                "auto_aprobable": True,
                "documentos": [...],
                "todos_errores": [],
                "recomendaciones": [],
                "started_at": "2026-02-17T10:00:00",
                "completed_at": "2026-02-17T10:00:25",
                "total_processing_time_ms": 25340
            }
        }
```

---

## 6. Patrones de Diseño

### 6.1 Factory Pattern

**Uso**: Crear la aplicación FastAPI.

```python
# api/server/server.py
def create_app() -> FastAPI:
    """Factory para crear y configurar la app."""
    app = FastAPI(...)
    # Configurar middleware, routers, etc.
    return app
```

### 6.2 Singleton Pattern

**Uso**: Servicios globales compartidos.

```python
# api/service/orchestrator.py
class OrchestratorService:
    # ...clase...

# Singleton global
orchestrator_service = OrchestratorService()

# Uso en routers
from api.service.orchestrator import orchestrator_service
await orchestrator_service.process_review(...)
```

### 6.3 Strategy Pattern

**Uso**: Diferentes estrategias de extracción por tipo de documento.

```python
# api/service/orchestrator.py
class OrchestratorService:
    EXTRACTORS = {
        "csf": analyze_csf,
        "acta_constitutiva": analyze_constitutiva,
        "ine": analyze_ine,
        # ... etc
    }
    
    async def _extract_document(self, doc_type: str, path: str):
        extractor = self.EXTRACTORS[doc_type]
        return extractor(path)
```

### 6.4 Pipeline Pattern

**Uso**: Procesamiento secuencial de documentos.

```python
async def _process_single_document(...):
    # Stage 1: Guardrails
    guardrail_service.validate_all(file, doc_type)
    
    # Stage 2: Extraction
    extracted_data = await self._extract_document(...)
    
    # Stage 3: Validation
    errors = await self._validate_document(...)
    
    return result
```

---

## 7. Manejo de Errores

### 7.1 Jerarquía de Excepciones

```
HTTPException (FastAPI)
├─ 400 Bad Request
│  ├─ Guardrails: formato/tamaño inválido
│  └─ Validación: datos faltantes
├─ 401 Unauthorized
│  └─ API Key inválida o ausente
├─ 413 Payload Too Large
│  └─ Archivo excede límite
├─ 429 Too Many Requests
│  └─ Rate limit excedido
└─ 500 Internal Server Error
   └─ Errores no manejados
```

### 7.2 Manejo de Errores en Orchestrator

```python
try:
    # Procesamiento de documento
    result = await process_document(...)
except HTTPException:
    # Guardrails rechazó el archivo
    # Propagar excepción (se convierte en respuesta HTTP)
    raise
except Exception as e:
    # Error inesperado
    # Crear DocumentError y continuar (no propagar)
    errors.append(DocumentError(
        documento=doc_type,
        stage=current_stage,
        severity=ErrorSeverity.HIGH,
        mensaje=f"Error: {str(e)}"
    ))
```

---

## 8. Optimizaciones y Performance

### 8.1 Guardrails Fail-Fast

- **Tiempo**: <10ms
- **Costo evitado**: ~$0.02 por archivo inválido
- **ROI**: 99.9% del tiempo de respuesta ahorrado

### 8.2 Async/Await

Todas las operaciones I/O son async para no bloquear el loop:

```python
# Correcto
async def process_review(...):
    result = await azure_di_client.analyze(...)
    
# Incorrecto (bloquea el event loop)
def process_review(...):
    result = azure_di_client.analyze_sync(...)
```

### 8.3 Connection Pooling

Azure clients reutilizan conexiones HTTP:

```python
# api/service/di.py
client = DocumentIntelligenceClient(
    endpoint=AZURE_DI_ENDPOINT,
    credential=AzureKeyCredential(AZURE_DI_KEY)
)
# Cliente se reutiliza en todas las llamadas
```

---

## 9. Seguridad

### 9.1 API Key Authentication

```python
# api/middleware/auth.py
async def require_api_key(api_key: str = Header(..., alias="X-API-Key")):
    if api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

### 9.2 Rate Limiting

```python
# api/middleware/rate_limit.py
# Límite: 100 requests por minuto por IP
```

### 9.3 Input Validation

- **Pydantic**: Validación automática de tipos
- **Guardrails**: Validación de archivos (MIME, tamaño, path traversal)
- **Sanitización**: Nombres de archivo limpiados antes de guardar

---

## 10. Guías de Desarrollo

### 10.0 Validaciones Específicas por Tipo de Documento

Esta sección documenta las validaciones implementadas para cada tipo de documento.

#### 10.0.1 Acta Constitutiva

**Método**: `_validate_acta_constitutiva()`  
**Requisitos validados**:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `acta_protocolizacion` | ValidationDetail | Evidencia de protocolización ante notario |
| `acta_folio_mercantil` | ValidationDetail | Folio mercantil del RPP |
| `acta_fecha_constitucion` | ValidationDetail | Fecha de constitución de la empresa |
| `acta_notario` | ValidationDetail | Nombre y número del notario |
| `acta_denominacion_social` | ValidationDetail | Denominación o razón social |

#### 10.0.2 Reforma de Estatutos (Actualización v1.0.1)

**Método**: `_validate_reforma()`  
**Requisitos validados**:

| Campo | Tipo | Descripción | Validación |
|-------|------|-------------|------------|
| `reforma_numero_escritura` | ValidationDetail | Número de escritura notarial | Presente y no vacío |
| `reforma_razon_social` | ValidationDetail | Razón social | Longitud > 3 caracteres |
| `reforma_fecha_otorgamiento` | ValidationDetail | Fecha de otorgamiento | Fecha válida presente |
| `reforma_nombre_notario` | ValidationDetail | Nombre completo del notario | Al menos 2 palabras (nombre + apellido) |
| `reforma_numero_notaria` | ValidationDetail | Número de notaría | Presente y no vacío |
| `reforma_folio_mercantil` | ValidationDetail | Folio mercantil del RPP | Longitud ≥ 4 caracteres |
| `reforma_estructura_accionaria` | ValidationDetail | Composición accionaria | Lista con elementos o texto > 10 caracteres |

**Ejemplo de respuesta**:
```json
{
  "kyb_compliance": {
    "requisitos_cumplidos": [
      "vigencia",
      "reforma_numero_escritura",
      "reforma_razon_social",
      "reforma_fecha_otorgamiento",
      "reforma_nombre_notario",
      "reforma_numero_notaria",
      "reforma_folio_mercantil",
      "reforma_estructura_accionaria"
    ]
  }
}
```

#### 10.0.2.1 BACKUP ROBUSTO - Extracción de Estructura Accionaria (v1.2.1)

**Aplica a**: Acta Constitutiva y Reforma de Estatutos

El mecanismo BACKUP ROBUSTO garantiza la extracción completa de la estructura accionaria cuando la extracción inicial del LLM es incompleta (suma de porcentajes < 98%).

**Pipeline de Extracción**:

```
┌─────────────────────────────────────────────────────────────┐
│  1. Extracción inicial por LLM (GPT-4o)                     │
│     └─ Analiza texto OCR y extrae estructura_accionaria    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Validación: ¿suma_porcentajes >= 98%?                   │
│     ├─ SÍ  → Continuar al paso 7                           │
│     └─ NO  → Activar BACKUP ROBUSTO (paso 3)               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Backup Regex: _extract_accionistas_regex_backup()       │
│     └─ 12+ patrones regex para diferentes formatos:        │
│        • Tablas: NOMBRE | ACCIONES | %                     │
│        • Narrativo: "El señor X aporta Y acciones"         │
│        • OCR linearizado con multi-línea (v1.2.1)          │
│        • Empresas: S.A.P.I., S.A. de C.V., LLC            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Si aún < 98%: Re-extracción LLM                         │
│     └─ _reextract_estructura_accionaria(text_ocr, llm)     │
│        Prompt especializado enfocado solo en accionistas   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  5. Merge inteligente con normalización de acentos (v1.2.1) │
│     ├─ LLM merge: _strip_accents() para comparación        │
│     ├─ Multi-sección merge: accent-insensitive             │
│     └─ Enrichment: transferir datos numéricos al duplicado │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  6. Deduplicación con accionistas_validators (v1.2.1)       │
│     ├─ Filtrar entradas basura (headers, labels OCR)       │
│     ├─ Fuzzy matching (SequenceMatcher + word overlap)     │
│     ├─ Normalización accent-insensitive (_strip_accents)   │
│     └─ Enrichment: datos numéricos migran al sobreviviente │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  7. Recálculo de confiabilidad                              │
│     ├─ suma >= 100% (±2%): confiabilidad=1.0, "Verificada" │
│     ├─ suma >= 95%: confiabilidad=0.9, "Verificada"        │
│     ├─ suma >= 80%: confiabilidad=0.7, "Parcial"           │
│     └─ suma < 80%: confiabilidad=0.5, "Requiere_Verif"     │
└─────────────────────────────────────────────────────────────┘
```

**Normalización de Acentos (v1.2.1)**:

La función global `_strip_accents()` usa `unicodedata.normalize('NFKD')` para eliminar
marcas diacríticas antes de comparar nombres. Se aplica en 5 puntos del pipeline:

```python
import unicodedata as _unicodedata

def _strip_accents(text: str) -> str:
    """Elimina acentos/diacríticos para comparación insensible."""
    nfkd = _unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not _unicodedata.combining(c))

# Uso: _strip_accents("ELÍAS") == _strip_accents("ELIAS")  → True
```

**Regex Multi-línea OCR (v1.2.1)**:

El patrón `patron_tabla_ocr` soporta nombres divididos en dos líneas OCR:

```python
# Antes (v1.2.0): solo captura nombres en una línea
patron_tabla_ocr = r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,50})\n(\d{1,6})\n'

# Después (v1.2.1): acepta línea de continuación opcional
patron_tabla_ocr = r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,50})\n(?:([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{2,50})\n)?(\d{1,6})\n'
#                    ↑ grupo 1: nombre base        ↑ grupo 2: continuación opcional  ↑ grupo 3: acciones
```

Ejemplo real (Capital X): `"ESTEBAN SANTIAGO\nVARELA VEGA\n35\n"` → captura completa.

**Funciones Involucradas**:

| Función | Ubicación | Propósito |
|---------|-----------|-----------|
| `_strip_accents()` | openai.py:32-39 | Normalización accent-insensitive (global) |
| `_validate_and_correct_acta_fields()` | openai.py:1237 | Validación post-extracción para Acta |
| `_validate_and_correct_reforma_fields()` | openai.py:3210 | Validación post-extracción para Reforma |
| `_extract_accionistas_regex_backup()` | openai.py:2848 | Backup con 12+ patrones regex |
| `_reextract_estructura_accionaria()` | openai.py:2965 | Re-extracción LLM con prompt enfocado |

**Módulo accionistas_validators (v1.2.1)**:

Nuevo módulo `api/service/accionistas_validators/` (~400 líneas) con utilidades de
validación y deduplicación de accionistas:

| Función | Propósito |
|---------|-----------|
| `es_nombre_persona_valido()` | Validación de 8 reglas para nombres de personas/entidades |
| `es_nombre_similar()` | Fuzzy matching con SequenceMatcher (ratio ≥ 0.85) + word overlap |
| `filtrar_entradas_basura()` | Elimina headers OCR, labels, frases prohibidas |
| `deduplicar_accionistas()` | Deduplicación con fuzzy matching y enriquecimiento |
| `limpiar_y_deduplicar()` | Pipeline combinado: limpiar + deduplicar |
| `calcular_confiabilidad_estructura()` | Scoring de confiabilidad para estructura accionaria |

**Patrones Regex Soportados**:

```python
# 1. Tabla con % explícito
patron_tabla = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{10,50})\s+(\d{1,6})\s+(\d{1,3}[.,]\d{1,2})\s*%'

# 2. Narrativo con acciones numéricas
patron_narrativo = r'(?:EL\s+)?(?:SEÑOR|C\.)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,50}?)\s+APORTA[^\d]{0,100}?(\d{1,6})\s*ACCIONES?'

# 3. Empresas (personas morales)
patron_empresa = r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,60})\s+(?:S\.?A\.?P\.?I\.?|S\.?A\.?\s*(?:DE\s+)?C\.?V\.?|LLC)'
```

**Métricas de Resultado**:

La respuesta incluye campos de diagnóstico para monitorear la efectividad del backup:

```json
{
  "_suma_porcentajes": 100.02,
  "_estructura_accionaria_status": "Verificada",
  "_estructura_confiabilidad": 1.0,
  "_backup_regex_aplicado": true,
  "_accionistas_backup": 2,
  "_reextraccion_llm_aplicada": false
}
```

#### 10.0.3 INE Frente (Actualización v1.0.1)

**Método**: `_validate_ine()`  
**Requisitos validados**:

| Campo | Tipo | Descripción | Mejora v1.0.1 |
|-------|------|-------------|---------------|
| `ine_nombre` | ValidationDetail | Nombre completo | - |
| `ine_curp` | ValidationDetail | CURP presente | **✨ Extracción automática desde OCR con regex** |
| `ine_curp_formato` | ValidationDetail | CURP formato válido (18 chars) | **✨ Validación con patrón regex** |
| `ine_fecha_nacimiento` | ValidationDetail | Fecha de nacimiento | - |
| `ine_clave_elector` | ValidationDetail | Clave de elector (18 chars) | - |

**Mejora en extracción de CURP**:
```python
# Patrón regex para CURP (18 caracteres)
# Formato: 4 letras + 6 dígitos + 1 letra (H/M) + 5 letras + 1 alfanumérico + 1 dígito
curp_pattern = r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b'

# Fallback: Si Azure DI no extrae el CURP, buscar en texto OCR
if "curp" not in filtered_results:
    curp_match = re.search(curp_pattern, raw_txt.upper())
    if curp_match:
        filtered_results["curp"] = {
            "content": curp_match.group(0),
            "confidence": 0.9
        }
```

**Impacto**: Reduce falsos negativos de 33% (compliance_score: 0.67) a 0% (compliance_score: 1.0)

#### 10.0.4 INE Reverso (Corrección v1.0.1)

**Método**: `_validate_ine_reverso()`  
**Requisitos validados**:

| Campo | Tipo | Descripción | Cambio v1.0.1 |
|-------|------|-------------|---------------|
| `ine_reverso_mrz` | ValidationDetail | MRZ (Machine Readable Zone) legible | - |
| `ine_reverso_fecha_nacimiento` | ValidationDetail | Fecha de nacimiento del MRZ | **✨ Nuevo** |
| `ine_reverso_vigencia` | ValidationDetail | Vigencia del MRZ | **✨ Nuevo** |
| ~~`ine_reverso_domicilio`~~ | ❌ **Eliminado** | ~~Domicilio~~ | **🔧 Corrección: El domicilio está en el frente, no en el reverso** |

**Nota importante**: El reverso del INE contiene:
- **MRZ**: 3 líneas con formato `IDMEX...`
- **Información electoral**: Fechas de elecciones, firma del secretario ejecutivo
- **Código QR**: Para verificación electrónica
- **NO contiene domicilio** (está en el frente)

#### 10.0.5 CSF (Constancia de Situación Fiscal)

**Método**: `_validate_csf()`  
**Requisitos validados**:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `campo_rfc` | ValidationDetail | RFC presente |
| `campo_rfc_formato` | ValidationDetail | RFC formato válido (12-13 chars) |
| `campo_estatus` | ValidationDetail | Estatus "ACTIVO" |
| `campo_denominacion_razon_social` | ValidationDetail | Razón social presente |
| `campo_domicilio_fiscal` | ValidationDetail | Domicilio fiscal presente |
| `campo_regimen_fiscal` | ValidationDetail | Régimen fiscal presente |

**Vigencia**: 3 meses desde fecha de emisión

#### 10.0.6 Documentos Adicionales

| Documento | Método | Requisitos Principales |
|-----------|--------|------------------------|
| **Poder Notarial** | `_validate_poder_notarial()` | Número de escritura, notario, poderdante, apoderado, facultades |
| **FIEL** | `_validate_fiel()` | Certificado válido, no revocado, vigencia |
| **Comprobante Domicilio** | `_validate_comprobante_domicilio()` | Calle, colonia, código postal |
| **Estado de Cuenta** | `_validate_estado_cuenta()` | Número de cuenta/CLABE, titular, período |

---

## 10.1 Guías de Desarrollo

### 10.1.1 Agregar un Nuevo Tipo de Documento

1. **Crear modelo Pydantic** en `api/model/`:

```python
# api/model/NuevoDocumento.py
from pydantic import BaseModel

class NuevoDocumento(BaseModel):
    campo1: str
    campo2: int
```

2. **Agregar función de extracción** en `api/controller/docs.py`:

```python
def analyze_nuevo_documento(file_path: str) -> Dict:
    # Azure DI + OpenAI
    return {...}
```

3. **Agregar requisitos de validación** en `api/service/validator.py`:

```python
DOCUMENT_REQUIREMENTS["nuevo_documento"] = DocumentRequirement(
    doc_type="nuevo_documento",
    vigencia_maxima=VigenciaType.TRES_MESES,
    requisitos_especificos=["campo1_presente", "campo2_valido"]
)
```

4. **Agregar al EXTRACTORS** en `api/service/orchestrator.py`:

```python
EXTRACTORS = {
    ...
    "nuevo_documento": analyze_nuevo_documento
}
```

5. **Agregar endpoint** en `api/router/docs.py`:

```python
@router.post("/nuevo_documento")
async def validate_nuevo_documento(file: UploadFile = File(...)):
    guardrail_service.validate_all(file, "nuevo_documento")
    path = await save_file(file)
    return analyze_nuevo_documento(path)
```

---

## 10.2 Características Avanzadas (v1.0.2)

### 10.2.1 Validación de Tipo de Documento

El sistema detecta automáticamente si el documento subido no corresponde al tipo esperado.

#### Algoritmo de Detección

Ubicación: `api/service/validator.py` - Método `_validate_document_type_match()`

**Paso 1: Definición de Campos Clave**

```python
KEY_FIELDS = {
    "csf": {
        "required": ["rfc", "regimen_fiscal"],
        "optional": ["denominacion_razon_social", "domicilio_fiscal"],
        "keywords": ["CONSTANCIA", "SITUACIÓN FISCAL", "SAT"]
    },
    "poder": {
        "required": ["poderdante", "apoderado"],
        "optional": ["facultades", "nombre_notario"],
        "keywords": ["PODER", "OTORGA", "FACULTADES"]
    },
    # ... otros tipos
}
```

**Paso 2: Búsqueda Inteligente en Texto OCR**

```python
# Priorizar texto_ocr (poblado por Azure DI) sobre texto_completo
texto_busqueda = datos.get("texto_ocr", "") if datos.get("texto_ocr") else datos.get("texto_completo", "")
texto_busqueda = texto_busqueda.upper()

# Buscar keywords en el texto
for keyword in key_fields["keywords"]:
    if keyword.upper() in texto_busqueda:
        keyword_score += 1

keyword_score = keyword_score / len(key_fields["keywords"]) if key_fields["keywords"] else 0
```

**Paso 3: Cálculo de Score con Ponderación Adaptativa**

```python
# Score base = (requeridos * 50%) + (opcionales * 30%) + (keywords * 20%)
required_score = campos_requeridos_encontrados / total_requeridos
optional_score = campos_opcionales_encontrados / total_opcionales

# ALGORITMO ADAPTATIVO: Si no hay campos extraídos, keywords = 100%
if required_score == 0 and optional_score == 0:
    # Cuando el extractor no encuentra campos, confiar 100% en keywords
    final_score = keyword_score
else:
    # Ponderación normal cuando hay campos
    final_score = (required_score * 0.5) + (optional_score * 0.3) + (keyword_score * 0.2)
```

**¿Por qué scoring adaptativo?**

Cuando un documento del tipo incorrecto es procesado (ej: INE subido al endpoint CSF), el extractor de CSF retorna 0 campos encontrados. Con ponderación fija 20% para keywords, el score sería muy bajo incluso con todas las keywords presentes. El algoritmo adaptativo detecta esta situación y da peso 100% a keywords cuando no hay información estructurada, permitiendo detección precisa en casos edge.

**Paso 4: Decisión y Comparación con Otros Tipos**

```python
if expected_score < 0.3:
    # Score muy bajo - comparar con otros tipos
    for otro_tipo in KEY_FIELDS:
        # Calcular score con MISMO algoritmo adaptativo
        otro_required = calcular_campos_requeridos(otro_tipo, datos)
        otro_optional = calcular_campos_opcionales(otro_tipo, datos)
        otro_keyword = calcular_keywords(otro_tipo, datos, texto_ocr_prioritario=True)
        
        # Aplicar scoring adaptativo también aquí
        if otro_required == 0 and otro_optional == 0:
            otro_score = otro_keyword
        else:
            otro_score = (otro_required * 0.5) + (otro_optional * 0.3) + (otro_keyword * 0.2)
        
        if otro_score > expected_score and otro_score > 0.4:
            return {
                "is_correct": False,
                "detected_type": otro_tipo,
                "confidence": otro_score
            }

return {"is_correct": True, "detected_type": tipo_esperado, "confidence": expected_score}
```

#### Integración en el Flujo

```python
# api/service/validator.py - validate_single_document()

# Validar tipo de documento
doc_type_validation = self._validate_document_type_match(doc_key, datos)
documento_tipo_correcto = doc_type_validation["is_correct"]
tipo_detectado = doc_type_validation["detected_type"]
confianza_tipo = doc_type_validation["confidence"]

if not documento_tipo_correcto:
    errores.append(
        f"El documento subido no corresponde al tipo esperado. "
        f"Se esperaba '{doc_key}' pero parece ser '{tipo_detectado}'"
    )
    status = RequirementStatus.NON_COMPLIANT
```

#### Respuesta API

```json
{
  "kyb_compliance": {
    "status": "non_compliant",
    "documento_tipo_correcto": false,
    "tipo_detectado": "poder",
    "confianza_tipo": 0.67,
    "errores": [
      "El documento subido no corresponde al tipo esperado. Se esperaba 'csf' pero parece ser 'poder'"
    ]
  }
}
```

#### Casos de Uso

**Caso 1: Usuario sube Poder Notarial al endpoint CSF**
- Sistema detecta campos: `poderdante`, `apoderado`, keywords: "FACULTADES"
- Score CSF: 0.15 (muy bajo)
- Score Poder: 0.72 (alto)
- Resultado: `documento_tipo_correcto: false`, `tipo_detectado: "poder"`

**Caso 2: Usuario sube CSF al endpoint CSF**
- Sistema detecta campos: `rfc`, `regimen_fiscal`, keywords: "SAT"
- Score CSF: 0.85
- Resultado: `documento_tipo_correcto: true`, `tipo_detectado: "csf"`

**Caso 3: Documento dañado o ilegible**
- Sistema no detecta campos suficientes de ningún tipo
- Score máximo: 0.20
- Resultado: `documento_tipo_correcto: false`, `tipo_detectado: "desconocido"`

**Caso 4: INE subido al endpoint CSF (Caso Edge - Scoring Adaptativo)**
- Extractor CSF encuentra: 0/9 campos CSF
- Keywords en texto_ocr: "ELECTORAL", "CREDENCIAL", "VOTAR", "CURP", "ELECTOR" (5/5)
- **Score CSF**: 0 (sin campos) → Scoring adaptativo: keyword_score = 1.0 pero es INE
- **Score INE**: required=0, optional=0, keywords=5/5 → **Adaptativo: 1.0**
- Comparación: INE (1.0) > CSF (0.05) → `tipo_detectado: "ine"`, `confianza_tipo: 1.0`
- **Clave del fix**: texto_ocr contiene "INSTITUTO NACIONAL ELECTORAL" → keyword "ELECTORAL" match
  - Keyword anterior "INE" no hacía match → detección fallaba
  - Nueva keyword "ELECTORAL" detecta correctamente

---

### 10.2.2 Formato de Validación Granular (campos_validados)

Cambio de formato de listas a diccionario para mayor claridad.

#### Formato Anterior (v1.0.1)

```json
{
  "kyb_compliance": {
    "requisitos_cumplidos": [
      "campo_rfc",
      "campo_rfc_formato",
      "campo_estatus"
    ],
    "requisitos_fallidos": [
      "vigencia",
      "campo_regimen_fiscal"
    ]
  }
}
```

**Problemas:**
- Requiere buscar en dos listas separadas
- No es inmediatamente claro el estado de cada campo
- Difícil de consultar programáticamente

#### Formato Nuevo (v1.0.2)

```json
{
  "kyb_compliance": {
    "campos_validados": {
      "vigencia": "non_compliant",
      "campo_rfc": "compliant",
      "campo_rfc_formato": "compliant",
      "campo_estatus": "compliant",
      "campo_denominacion_razon_social": "compliant",
      "campo_domicilio_fiscal": "compliant",
      "campo_regimen_fiscal": "non_compliant"
    }
  }
}
```

**Ventajas:**
- Estado visible por campo en un solo lugar
- Fácil de filtrar: `campos_validados.filter(v => v === 'non_compliant')`
- Estructura más clara para UI/dashboards
- Compatible con todos los 9 tipos de documentos

#### Implementación Técnica

**Modelo Pydantic:**

```python
# api/model/validator.py

class SingleDocumentValidation(BaseModel):
    campos_validados: Dict[str, str] = Field(
        default_factory=dict,
        description="Estado de cada campo validado: 'compliant' o 'non_compliant'"
    )
```

**Construcción del Diccionario:**

```python
# api/service/validator.py

campos_validados = {}

# Agregar vigencia
campos_validados["vigencia"] = "compliant" if vigente else "non_compliant"

# Agregar validaciones específicas
for validation in specific_validations:
    campos_validados[validation.tipo] = "compliant" if validation.passed else "non_compliant"

# Calcular compliance score
campos_compliant = sum(1 for v in campos_validados.values() if v == "compliant")
compliance_score = campos_compliant / len(campos_validados)
```

#### Uso desde Frontend

```javascript
// Obtener todos los campos no compliant
const errores = Object.entries(response.kyb_compliance.campos_validados)
  .filter(([campo, estado]) => estado === 'non_compliant')
  .map(([campo, _]) => campo);

console.log('Campos con error:', errores);
// ["vigencia", "campo_regimen_fiscal"]

// Renderizar badges por campo
Object.entries(campos_validados).map(([campo, estado]) => (
  <Badge color={estado === 'compliant' ? 'green' : 'red'}>
    {campo}: {estado}
  </Badge>
));
```

---

### 10.2.3 Logs sin Timestamps

Eliminación de timestamps para mejor legibilidad en desarrollo.

#### Configuración

Ubicación: `api/middleware/logging_middleware.py`

**JSONFormatter (antes):**

```python
def format(self, record: logging.LogRecord) -> str:
    log_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ Removido
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "environment": ENVIRONMENT,
    }
    return json.dumps(log_data)
```

**JSONFormatter (después):**

```python
def format(self, record: logging.LogRecord) -> str:
    log_data = {
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "environment": ENVIRONMENT,
    }
    # Agregar campos extra si existen
    if hasattr(record, "request_id"):
        log_data["request_id"] = record.request_id
    if hasattr(record, "duration_ms"):
        log_data["duration_ms"] = record.duration_ms
    
    return json.dumps(log_data)
```

**TextFormatter (antes/después):**

```python
# Antes
base = f"[{timestamp}] {record.levelname:8} {record.name}: {record.getMessage()}"

# Después
base = f"{record.levelname:8} {record.name}: {record.getMessage()}"
```

#### Resultado

**Antes:**
```json
{"timestamp": "2026-02-17T22:58:20.280944Z", "level": "INFO", "logger": "api.service.di", "message": "Analysis succeeded", "environment": "development"}
```

**Después:**
```json
{"level": "INFO", "logger": "api.service.di", "message": "Analysis succeeded", "environment": "development"}
```

#### Ventajas

- ✅ Menos ruido visual durante debugging
- ✅ Logs más compactos (ahorro ~25% de espacio)
- ✅ Más fácil de leer en terminal
- ✅ Mantiene toda la información relevante

**Nota:** En producción, considera re-habilitar timestamps para auditoría.

---

**Fin de la Guía Técnica**

Para más información:
- [README.md](README.md) - Guía de usuario
- [TESTING_GUIDE.md](docs/TESTING_GUIDE.md) - Guía de testing
- [DEPLOYMENT_IT.md](docs/DEPLOYMENT_IT.md) - Guía de despliegue
