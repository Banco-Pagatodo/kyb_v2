# Changelog — Orquestrator (Pipeline KYB)

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.11.0] - 2026-03-28

### Changed
- **Eliminación de Dakota del pipeline** — El Orquestrador ya no depende de Dakota para la persistencia de documentos. Ahora persiste directamente en PostgreSQL usando `asyncpg` (`get_or_create_empresa()` y `persist_documento()` con UPSERT en `persistence.py`).
- **`pipeline.py`** — `procesar_documento()` y `procesar_expediente()` reescritos: PagaTodo OCR → persistencia directa en BD → Colorado → Arizona → Nevada.
- **`clients.py`** — Eliminadas funciones `dakota_import()`, `dakota_health()`, `dakota_empresa_progress()`, `SUPPORTED_IMPORT_DOC_TYPES` y circuit breaker de Dakota.
- **`router.py`** — Health check ya no consulta Dakota. Endpoint `/status/{rfc}` usa solo `pipeline_resultados`.

### Added
- **Persistencia de formulario manual** — Los datos crudos del prospecto (`/prospects/data/`) se persisten como `doc_type="formulario_manual"` para que Colorado pueda ejecutar el Bloque 11 (comparación Manual vs OCR).
- **`persistence.py`** — Nuevas funciones `get_or_create_empresa(rfc, razon_social)` y `persist_documento(empresa_id, doc_type, file_name, datos_extraidos)` con lógica UPSERT.

---

## [1.10.1] - 2026-03-27

### Fixed
- **`pagatodo_ocr_result()`** — Corregido endpoint OCR de PagaTodo Hub: ahora usa `POST /ocr` con body JSON `{"CustomerId", "DocumentType"}` en lugar del antiguo `GET /prospects/ocr/{id}?DocumentType=X`. Endpoint confirmado por el equipo de PagaTodo.

---

## [1.10.0] - 2026-03-26

### Added
- **Dos fuentes de datos complementarias** — El pipeline ahora obtiene datos de PagaTodo Hub desde dos endpoints independientes que se complementan para dar un veredicto final:
  - **`/prospects/data/{id}`** — Datos de registro manual del cliente (datos declarados en el formulario de alta).
  - **`/prospects/ocr/{id}?DocumentType=X`** — Extracción automática de documentos (OCR pre-extraído).
- **`transformar_datos_prospecto()`** en `clients.py` — Normaliza la respuesta de `/prospects/data/` (camelCase → snake_case) al formato interno: `persona_moral`, `domicilio_fiscal`, `acta_constitutiva`, `representante_legal`, `perfil_transaccional`, `usuario_banca`, `declaraciones_regulatorias`.
- **Campo `datos_prospecto`** en la respuesta de ambos endpoints (`/process` y `/expediente`) — Incluye los datos de registro manual del cliente junto con los resultados de los agentes.

### Changed
- **`procesar_documento()`** — Ahora ejecuta Paso 0 (`pagatodo_prospect_data`) antes del OCR. Los `datos_prospecto` se incluyen en la respuesta aunque el OCR falle.
- **`procesar_expediente()`** — Obtiene `prospect_data` una vez al inicio del flujo (ya no se importa a Dakota como documento). Los datos de registro manual y los de OCR son fuentes paralelas e independientes.
- **Tests actualizados** — `TestProcesarDocumento` ahora mockea `pagatodo_prospect_data`; se valida la presencia/ausencia de `datos_prospecto` en todos los escenarios.

---

## [1.9.0] - 2025-06-26

### Changed
- **Flujo único PagaTodo Hub** — El Orquestador ahora trabaja exclusivamente con PagaTodo Hub como fuente de OCR. Se eliminó el flujo antiguo de subida de archivos (file upload).
- **Endpoints renombrados:**
  - `POST /process/pagatodo` → `POST /process` (ahora es el único endpoint de procesamiento).
  - `POST /expediente/pagatodo` → `POST /expediente` (ahora es el único endpoint multi-documento).
- **`pipeline.py` simplificado** — Solo dos funciones: `procesar_documento()` y `procesar_expediente()`, ambas basadas en PagaTodo Hub.
- **`clients.py` simplificado** — Eliminado `dakota_extract()`, `_DAKOTA_ENDPOINTS` y `SUPPORTED_DOC_TYPES`.
- **`router.py` simplificado** — Eliminados endpoints de file-upload (`File`, `Form`, `UploadFile` ya no se usan).
- **Tests actualizados** — Todos los tests reescritos para el flujo PagaTodo-only.

### Removed
- `dakota_extract()` — Ya no se envían archivos directamente a Dakota para OCR.
- `SUPPORTED_DOC_TYPES` — Reemplazado por `SUPPORTED_IMPORT_DOC_TYPES` y `PAGATODO_DOCTYPE_MAP`.
- `procesar_documento_pagatodo()` / `procesar_expediente_pagatodo()` — Renombradas a `procesar_documento()` / `procesar_expediente()`.
- Endpoints `POST /process` (file upload) y `POST /expediente` (file upload) originales.

---

## [1.8.0] - 2026-03-27

### Added
- **Flujo PagaTodo Hub → Dakota import** — Nuevo pipeline que reemplaza el OCR propio de Dakota con OCR pre-extraído de PagaTodo Hub.
- **`dakota_import()`** — Nuevo cliente HTTP que envía JSON a Dakota `POST /docs/import/{doc_type}` (validación + persistencia, sin OCR).
- **`procesar_documento_pagatodo()`** — Pipeline para un documento: PagaTodo OCR → Dakota import → Colorado → Arizona → Compliance → Nevada.
- **`procesar_expediente_pagatodo()`** — Pipeline multi-documento: recorre lista de DocumentTypes, obtiene OCR de PagaTodo, importa en Dakota, luego Colorado/Arizona/Compliance/Nevada.
- **Endpoints del Orquestador:**
  - `POST /api/v1/pipeline/process/pagatodo` — Documento individual vía PagaTodo Hub.
  - `POST /api/v1/pipeline/expediente/pagatodo` — Expediente completo vía PagaTodo Hub.
- **`SUPPORTED_IMPORT_DOC_TYPES`** — Lista de doc_types soportados para import (incluye nuevos tipos PagaTodo).

---

## [1.7.0] - 2026-03-26

### Added
- **Integración PagaTodo Hub** — Nuevo cliente HTTP (`pagatodo_prospect_data`, `pagatodo_ocr_result`) para consumir la API externa de prospectos y resultados OCR de PagaTodo.
- **Mapeo `PAGATODO_DOCTYPE_MAP`** — Tabla de conversión de los 11 DocumentTypes externos (Csf, Fiel, ActaCons, PoderNotarial, ReformaEstatustos, EdoCuenta, RL_FrenteIne, PR_FrenteIne, EM_ComDomicilio, RL_ComDomicilio, PR_ComDomicilio) a doc_types internos KYB.
- **Nuevas variables de entorno** — `PAGATODO_HUB_BASE_URL`, `PAGATODO_HUB_API_KEY`, `PAGATODO_HUB_TIMEOUT`.
- **3 nuevos doc_types internos** — `ine_propietario_real`, `domicilio_rl`, `domicilio_propietario_real` para reflejar la separación por entidad (RL/PR/EM) del sistema externo.
- **Postman collection actualizada** — Endpoint `/prospects/ocr` con URL completa, query param `DocumentType` y lista de valores válidos.

---

## [1.6.0] - 2026-03-24

### Added
- **Pipeline detenido si Colorado RECHAZADO** — Tanto `procesar_documento()` como `procesar_expediente()` ahora verifican el dictamen de Colorado. Si es `RECHAZADO`, el pipeline se detiene inmediatamente sin ejecutar Arizona, Compliance ni Nevada. La respuesta incluye `pipeline_detenido: true` y `motivo_detencion`.

---

## [1.5.0] - 2026-03-23

### Fixed
- **CORS `allow_origins=["*"]`** — Reemplazado por whitelist configurable vía env `CORS_ORIGINS` (default: `http://localhost:8501,http://localhost:3000`). Métodos HTTP restringidos a GET/POST/PUT/DELETE.

### Added
- **Retry con exponential backoff** — `tenacity>=8.2.0` con 3 reintentos (1-10s) en las 6 funciones de `clients.py`.
- **Circuit breaker** — Clase `CircuitBreaker` con umbral de 5 fallos consecutivos y ventana de recuperación de 60s. Un CB por agente (Dakota, Colorado, Arizona, Nevada).
- **Config centralizada** — Nuevas variables: `RETRY_MAX_ATTEMPTS`, `RETRY_WAIT_MIN`, `RETRY_WAIT_MAX`, `CIRCUIT_BREAKER_THRESHOLD`, `CIRCUIT_BREAKER_RECOVERY`.

---

## [1.3.0] - 2026-03-12

### Summary

**Base de datos compartida** — El Orquestador ahora escribe el estado end-to-end del pipeline
en la tabla `pipeline_resultados` (PostgreSQL `kyb`). Integración completa con Alembic.

### Added

#### Base de datos (nuevo)
- `database.py` — Pool asyncpg para PostgreSQL (`kyb`), patrón lazy con lock
- `persistence.py` — 8 funciones CRUD sobre `pipeline_resultados`:
  - `iniciar_pipeline()` — UPSERT al iniciar procesamiento
  - `actualizar_dakota()` / `actualizar_colorado()` / `actualizar_arizona()` / `actualizar_nevada()` — Registro por agente
  - `finalizar_pipeline()` — Marca completado con tiempos
  - `obtener_estado_pipeline()` / `obtener_estado_por_rfc()` — Consultas

#### Migraciones Alembic (Dakota/kyb_review)
- **0007** — `dictamenes_pld`: tabla formalizada con UUID PK, FK a empresas, UNIQUE empresa_id, UPSERT-ready
- **0008** — `pipeline_resultados`: estado unificado por empresa con status/resultado por agente + tiempos

#### Configuración
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` — Variables para pool PostgreSQL

### Changed
- `pipeline.py` — Ambas funciones (`procesar_documento`, `procesar_expediente`) registran estado en BD tras cada agente
- `main.py` — Lifespan para cerrar pool asyncpg al apagar el servicio
- `router.py` — `/status/{rfc}` ahora consulta `pipeline_resultados` + Dakota combinados
- `pyproject.toml` — Dependencia `asyncpg>=0.30.0` añadida
- README actualizado con sección de BD, estructura de proyecto ampliada, diagrama corregido
- Tests actualizados: mock de `obtener_estado_por_rfc` en endpoint `/status/{rfc}`

### Technical Notes
- Todas las llamadas de persistencia envueltas en `try/except` — fallo de BD no interrumpe el pipeline
- Pool asyncpg se crea lazy (primera consulta) y se cierra con lifespan de FastAPI
- Nevada: `persistence.py` nuevo módulo, `router.py` refactorizado (eliminado SQL inline)

---

## [1.2.0] - 2026-03-12

### Summary

Integración de **Nevada** (agente de Dictamen PLD/FT) al pipeline del Orquestador.
Flujo completo: Dakota (extracción) → Colorado (validación) → Arizona (PLD/AML) → **Nevada** (dictamen PLD/FT con scoring + LLM + RAG sobre MER v7.0).

### Added

#### Nevada Client
- `nevada_dictamen()` — Genera dictamen PLD/FT completo para una empresa (score + LLM + RAG)
- `nevada_score()` — Obtiene solo el scoring determinista sin análisis LLM
- `nevada_health()` — Health check del servicio Nevada

#### Pipeline Updates
- Nuevo paso 5 en `procesar_documento()`: Nevada dictamen PLD/FT después de Arizona
- Nuevo paso en `procesar_expediente()`: Nevada dictamen PLD/FT del expediente
- Respuesta enriquecida con `dictamen_pld` incluyendo:
  - `dictamen` — APROBADO / APROBADO CON OBSERVACIONES / RECHAZADO
  - `score_total` — Puntuación determinista 0-100
  - `nivel_riesgo_score` — BAJO / MEDIO / ALTO / CRÍTICO
  - `nivel_riesgo_dictamen` — Nivel de riesgo del análisis LLM
  - `factores_riesgo` — Lista de factores detectados
  - `mitigantes` — Lista de factores mitigantes
  - `factor_mer` — Factor de riesgo MER
  - `mer_version` — Versión de la MER usada (7.0)

#### Health Check
- Ahora verifica 5 servicios: Orquestrator, Dakota, Colorado, Arizona, Nevada
- Estado `healthy` solo si todos responden

#### Configuración
- `NEVADA_BASE_URL` — URL del servicio Nevada (default: http://localhost:8013)
- `NEVADA_TIMEOUT` — Timeout para llamadas a Nevada (default: 120s)
- `NEVADA_API_PREFIX` — Prefijo de API: `/api/v1/compliance`

### Changed
- README actualizado con arquitectura de 5 servicios
- Diagrama de flujo extendido con paso 5 (dictamen PLD/FT) y paso 6 (respuesta)
- `.env.example` actualizado con variables Nevada + puertos corregidos
- `main.py` versión bumped a 1.2.0
- `clients.py` ahora importa configuración de los 4 agentes downstream

---

## [1.1.0] - 2026-03-11

### Summary

Integración de **Arizona** (agente PLD/AML) al pipeline del Orquestador.
Ahora el flujo completo incluye: Dakota (extracción) → Colorado (validación) → Arizona (análisis PLD).

### Added

#### Arizona Client
- `arizona_pld_analyze()` — Ejecuta análisis PLD Etapa 1 para una empresa
- `arizona_health()` — Health check del servicio Arizona

#### Pipeline Updates
- Nuevo paso 3 en `procesar_documento()`: Arizona análisis PLD después de Colorado
- Nuevo paso en `procesar_expediente()`: Arizona análisis PLD de todos los documentos
- Respuesta enriquecida con `analisis_pld` incluyendo:
  - `resultado` — COMPLETO / INCOMPLETO / REQUIERE_REVISION
  - `porcentaje_completitud` — 0-100%
  - `total_items`, `items_presentes`, `items_faltantes`
  - `tiene_poder_bancario` — boolean
  - `personas_identificadas` — número de personas detectadas

#### Health Check
- Ahora verifica 4 servicios: Orquestrator, Dakota, Colorado, Arizona
- Estado `healthy` solo si todos responden

#### Configuración
- `ARIZONA_BASE_URL` — URL del servicio Arizona (default: http://localhost:8012)
- `ARIZONA_TIMEOUT` — Timeout para llamadas a Arizona (default: 120s)
- `ARIZONA_API_PREFIX` — Prefijo de API: `/api/v1/pld`

### Changed
- README actualizado con arquitectura de 4 servicios
- Documentación del flujo extendido con paso PLD
- Puertos corregidos: Dakota=8010, Colorado=8011, Arizona=8012

---

## [1.0.0] - 2026-02-27

### Summary

Release inicial del **Orquestrator** — servicio coordinador que orquesta el pipeline completo
KYB: recibe documentos, los envía a Dakota (extracción) y a Colorado (validación cruzada),
devolviendo el resultado unificado. No accede directamente a base de datos; toda la
persistencia se delega a los servicios downstream.

### Added

#### Pipeline End-to-End
- Flujo automático: archivo → Dakota (extracción + BD) → Colorado (validación cruzada)
- Soporte para documento individual y expediente multi-documento
- Parámetro `skip_colorado` para omitir validación cruzada cuando no aplica
- Control de tipos de documento soportados con validación estricta

#### API REST (Puerto 8002)
- `POST /process` — Procesar un documento individual (archivo + RFC + tipo)
- `POST /expediente` — Procesar expediente completo (múltiples archivos)
- `GET /status/{rfc}` — Consultar estado/progreso de una empresa por RFC
- `GET /health` — Health check unificado (reporta estado de los 3 servicios)

#### Clientes HTTP
- `clients.py` — Clientes async (`httpx`) para Dakota y Colorado
  - `DakotaClient` — Envío de documentos, consulta de empresas y documentos
  - `ColoradoClient` — Disparo de validación cruzada, consulta de historial

#### Configuración
- `config.py` — URLs de Dakota/Colorado, timeouts, tipos de documento
- Variables de entorno: `DAKOTA_URL`, `COLORADO_URL`, `ORQUESTRATOR_HOST`, `ORQUESTRATOR_PORT`
- `pyproject.toml` — Dependencias: fastapi, httpx, uvicorn, python-dotenv, python-multipart

#### Tests (27 tests)
- `test_clients.py` — Clientes HTTP con respuestas mockeadas (happy path + errores)
- `test_pipeline.py` — Lógica de orquestación, skip_colorado, manejo de fallos
- `test_router.py` — Endpoints REST, validación de parámetros, respuestas HTTP

### Technical Details

```
Puerto:     8002
Prefijo:    /api/v1/pipeline
Python:     ≥ 3.12
BD:         Ninguna (sin acceso directo)
Upstream:   Dakota (:8000), Colorado (:8001)
```
