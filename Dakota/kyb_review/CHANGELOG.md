# Changelog - KYB Document Validation System

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.5.0] - 2026-03-27

### Added
- **Endpoint `POST /docs/import/{doc_type}`** — Importa datos OCR pre-extraídos (JSON) sin ejecutar Azure DI ni OpenAI.
  Ejecuta validación de campos + persistencia sobre el JSON recibido. Pensado para el flujo **PagaTodo Hub → Dakota**.
- **3 nuevos doc_types en validators** — `ine_propietario_real`, `domicilio_rl`, `domicilio_propietario_real`.
  También aliases `reforma_estatutos` y `poder_notarial` agregados al mapa de validadores.
- **Pydantic model `ImportPayload`** — body: `datos_extraidos` (dict), `texto_ocr` (str), `archivo_procesado` (str).

### Changed
- **`REQUIRED_DOCS` ampliado** — `get_empresa_progress()` ahora incluye `ine_propietario_real`, `domicilio_rl` y `domicilio_propietario_real` en la lista de documentos requeridos (12 en total).

---

## [1.3.2] - 2026-03-23

### Security
- **Auth bypass eliminado** — `api/middleware/auth.py` ya no omite la validación de API key cuando `ENVIRONMENT != "production"`. La autenticación es obligatoria en todos los entornos. `API_KEY` debe estar configurada para que el servicio arranque.

---

## [1.4.0] - 2025-01-27

### Summary

**Major feature release**: Implementación completa de validación de estructura accionaria
conforme a PLD (DCG Art.115 Bis, CFF Art.32-B, LFPIORPI Art.18). Incluye validación RFC,
detección de alertas PLD/GAFI, y modelos Pydantic extendidos para accionistas.

### Added

#### Módulo `rfc_validator.py` — Validación RFC conforme SAT/CNBV

- **`validar_rfc()`** — Valida formato RFC 12/13 caracteres, fecha, homoclave
- **`normalizar_rfc()`** — Normaliza a mayúsculas, remueve espacios/guiones
- **`detectar_tipo_persona()`** — Inferencia PM/PF por RFC → nombre → sufijo → default
- **`validar_consistencia_rfc_tipo()`** — Verifica RFC vs tipo declarado
- **`validar_rfcs_estructura()`** — Validación batch de lista de accionistas
- **`generar_alertas_rfc()`** — Genera alertas por RFC inválido/inconsistente/genérico
- **`calcular_digito_verificador()`** — Algoritmo módulo 11 para dígito verificador
- Constantes: `RFC_PM_PATTERN`, `RFC_PF_PATTERN`, `RFCS_GENERICOS` (EXTF, XAXX, XEXX, etc.)
- Detección de sufijos corporativos: SA DE CV, SAPI, SC, FIDEICOMISO, etc.

#### Módulo `alertas_estructura.py` — Alertas PLD/GAFI

- **`detectar_estructura_multicapa()`** — PM con >25% requiere perforación
- **`detectar_shell_company()`** — PM constituida recientemente (<2 años)
- **`detectar_estructura_circular()`** — Cliente en estructura de sus propios accionistas
- **`detectar_jurisdiccion_alto_riesgo()`** — Accionistas de países lista GAFI
- **`detectar_requiere_perforacion()`** — PM >25% sin estructura de beneficiarios
- **`detectar_prestanombre_posible()`** — PF alta participación sin RFC
- **`detectar_capital_inconsistente()`** — Capital social vs actividad declarada
- **`detectar_cambios_frecuentes()`** — >3 reformas de capital en 12 meses
- **`detectar_documentacion_incompleta()`** — Accionistas >10% sin RFC
- **`generar_todas_alertas()`** — Agregador de todas las alertas por categoría
- Constantes: `UMBRAL_PROPIETARIO_REAL=25%`, `UMBRAL_BENEFICIARIO_CONTROLADOR=15%`
- Jurisdicciones alto riesgo: IRAN, COREA DEL NORTE, MYANMAR, SIRIA, etc.

#### Modelos Pydantic `estructura_accionaria.py`

- **`AccionistaCompleto`** — RFC, CURP, serie, clase, valor_nominal, porcentaje_directo/indirecto
- **`DomicilioCompleto`** — Domicilio conforme DCG Art.115 Bis
- **`EntidadCompleta`** — PM cliente con capital social y administración
- **`ReformaEstatutos`** — Tracking de reformas con tipo y notario
- **`PropietarioReal`** — Resultado de análisis look-through
- **`ResultadoEstructuraAccionaria`** — Resultado completo del análisis
- Enums: `TipoPersona`, `TipoAlerta`, `SeveridadAlerta`

### Changed

- **`openai.py`** — Integración de validación RFC en `_validate_estructura_accionaria()`:
  - Validación automática de RFCs al procesar estructura
  - Generación de alertas RFC y PLD en campos `_alertas_rfc` y `_alertas_pld`
  - Enriquecimiento de accionistas con campos `_validacion_rfc` y `_tipo_persona_inferido`

### Tests

- **`test_rfc_validator.py`** — 48 tests unitarios para validación RFC
- **`test_alertas_estructura.py`** — 35 tests unitarios para alertas PLD
- Cobertura: normalización, validación formato, detección tipo persona, consistencia, alertas

### Regulatory Compliance

- **DCG Art.115 Bis** — Propietario real >25% participación accionaria
- **CFF Art.32-B Ter** — Beneficiario controlador >15% participación
- **LFPIORPI Art.18** — Umbrales de identificación 25%
- **GAFI Rec.24** — Transparencia de personas jurídicas

---

## [1.3.1] - 2026-02-27

### Summary

Patch release que corrige un **bug de producción** en la extracción de tablas de accionistas
vía OCR, estabiliza los tests unitarios y completa la configuración operacional del servicio.

### Bug Fixes

#### Extracción OCR de acciones cortas filtradas (P1)

```
Issue:    Números de acciones de 1-2 dígitos ("5", "45") eran descartados silenciosamente
          al procesar tablas OCR de estructura accionaria.
Root:     `es_linea_ignorable()` (que rechaza líneas con `len < 3`) se invocaba ANTES del
          regex de detección numérica `re.match(r'^\d{1,6}$', linea_sig)`.
Fix:      Se reordenó la lógica en `_extract_tabla_accionistas_estructurada()` para evaluar
          el patrón numérico primero. Se eliminó bloque muerto `if False:`.
File:     api/service/openai.py (línea ~1783)
Impact:   Los 4 accionistas de tablas OCR con acciones cortas ahora se extraen correctamente.
```

#### build-backend incorrecto en pyproject.toml

```
Issue:    `build-backend = "setuptools.backends._legacy:_Backend"` causaba warnings y era
          un path interno no documentado.
Fix:      Cambiado a `"setuptools.build_meta"` (estándar oficial).
```

### Fixed

- **8 tests fallidos** en `test_estructura_accionaria.py`:
  - Nombres genéricos cortos ("SOCIO A", 7 chars) filtrados por `es_nombre_persona_valido()` (mín. 8 chars) → reemplazados por nombres mexicanos realistas
  - Casing de status: tests esperaban "verificada" pero la función retorna "Verificada" (Title Case)
  - Assertions accedían a `_porcentajes_validos`, `_acciones_validas` a nivel de socio, pero solo existen a nivel del dict resultado
  - "FIDEICOMISO BANCOMEXT F/1234" contenía palabra prohibida → cambiado a "PROMOTORA BANCOMEXT S.C."
  - Test de tabla OCR capital × ahora valida correctamente 4 socios tras el bug fix

### Added

- **Azure DI connectivity check** en endpoint `/readiness` — verifica conectividad con Azure Document Intelligence (httpx, timeout 5s), reporta `ok` / `degraded` / `not_configured`
- **`alembic.ini`** — configuración de Alembic para migraciones; DB estampada a revisión `0005 (head)`
- **`.env.example`** — plantilla de variables de entorno para el servicio

### Technical Details

```
Tests:  18/18 passed (test_estructura_accionaria.py) — 4.53s
        85/85 passed (Colorado), 27/27 passed (Orquestrator)
Alembic: stamped 0005 (head)
Version: 1.3.0 → 1.3.1
```

---

## [1.3.0] - 2026-02-27

### Summary

Major release establishing the **arquitectura multi-agente de 3 servicios**: Dakota (extracción),
Colorado (validación cruzada) y un nuevo **Orquestrator** independiente que coordina el pipeline
completo. Se elimina la carpeta duplicada `document_extraction` y se actualiza toda la
documentación para reflejar el estado actual del sistema.

### Added

#### Orquestrator — Servicio Coordinador (Puerto 8002)
- Nuevo directorio independiente `Orquestrator/` fuera de Dakota y Colorado
- `POST /api/v1/pipeline/process` — pipeline completo: archivo → Dakota → Colorado
- `POST /api/v1/pipeline/expediente` — procesamiento multi-documento
- `GET /api/v1/pipeline/status/{rfc}` — consulta estado de empresa por RFC
- `GET /api/v1/pipeline/health` — health check unificado (reporta los 3 servicios)
- Sin acceso directo a base de datos (toda la persistencia vía HTTP a Dakota/Colorado)
- Cliente HTTP integrado para Dakota (`dakota_client.py`) y Colorado (`colorado_client.py`)
- Configuración centralizada en `config.py` con URLs de los servicios

#### Persistencia Automática en Pipeline
- Dakota persiste automáticamente empresa + documento cuando recibe parámetro `?rfc=`
- Colorado persiste validación cruzada con dictamen y hallazgos en `validaciones_cruzadas`
- El Orquestrator encadena ambas operaciones sin intervención manual

### Changed

#### Documentación Actualizada
- `Orquestrator/README.md` — documentación completa del nuevo servicio
- `Colorado/cross_validation/README.md` — añadida sección Orquestrator + tabla de 3 servicios
- `docs/ARCHITECTURE.md` — v1.3.0: tabla de agentes, §8.4 persistencia PostgreSQL, §9 progreso
- `docs/DATABASE_GUIDE.md` — nueva §6 tabla `validaciones_cruzadas`, diagramas actualizados a 3 tablas
- `docs/PRODUCTION_CHECKLIST.md` — checklist multi-servicio, orden de inicio, health checks
- `CHANGELOG.md` — esta entrada

### Removed

- **`Dakota/document_extraction/`** — carpeta duplicada eliminada (era un clon incompleto sin directorio `api/`). Solo persiste `Dakota/kyb_review/`.

### Technical Details

```
Arquitectura:
  Dakota      → :8000 → /kyb/api/v1.0.0/*     → Extracción + Persistencia
  Colorado    → :8001 → /api/v1/validacion/*   → Validación Cruzada + Portales
  Orquestrator→ :8002 → /api/v1/pipeline/*     → Coordinación del Pipeline

Base de datos: PostgreSQL 16 (kyb)
  empresas               ← Dakota escribe
  documentos             ← Dakota escribe
  validaciones_cruzadas  ← Colorado escribe

Entorno: Python 3.12 · venv compartido en Agents/.venv
```

### Files Created
```
Orquestrator/main.py
Orquestrator/config.py
Orquestrator/clients.py
Orquestrator/pipeline.py
Orquestrator/router.py
Orquestrator/.env
Orquestrator/pyproject.toml
Orquestrator/README.md
```

### Files Deleted
```
Dakota/document_extraction/   (directorio completo)
```

---

## [1.2.1] - 2026-02-24

### Summary

Patch release fixing **shareholder structure extraction** (`estructura_accionaria`) for acta
constitutiva documents with multi-line OCR names and accented characters. Introduces
accent-insensitive deduplication, multi-line regex support, and the new
`accionistas_validators` module.

### Bug Fixes

#### Multi-line OCR Name Extraction (P1)

```
Issue:    Shareholders with long names split across two OCR lines were not captured.
          Example: "ESTEBAN SANTIAGO\nVARELA VEGA" → missed entirely.
Root:     patron_tabla_ocr regex only matched single-line names.
Fix:      Modified regex to accept optional continuation line:
            NOMBRE\n(?:CONTINUATION\n)?NUMBER\n$VALUE
          Now captures 3 groups: base name + optional continuation + acciones.
File:     api/service/openai.py (~line 2507)
Impact:   Capital X: 3 socios → 4 socios (100% extraction)
```

#### Accent-Insensitive Deduplication (P1)

```
Issue:    "ELIAS" and "ELÍAS" treated as different shareholders, creating duplicates.
Root:     String comparison was byte-level, not accent-normalized.
Fix:      Created global _strip_accents() using unicodedata.normalize('NFKD').
          Applied in 5 deduplication/merge points:
            1. LLM merge (~line 1553)
            2. Multi-section merge (~line 1589)
            3. Main deduplication (~line 1627)
            4. normalizar_clave() (~line 2816)
            5. FALLBACK CASO 2 enrichment (~line 2993)
File:     api/service/openai.py (lines 32-39 + 5 merge points)
Impact:   Eliminated duplicate entries for accented vs non-accented names.
```

#### FALLBACK CASO 2 Trigger Condition (P2)

```
Issue:    FALLBACK CASO 2 only activated when socios_con_acciones == 0.
          Partially extracted data (1 of 4 socios) never triggered re-enrichment.
Fix:      Changed condition to socios_con_acciones < len(estructura).
File:     api/service/openai.py (~line 2988)
Impact:   Enrichment now activates for any incomplete extraction.
```

### New Features

#### accionistas_validators Module

New module `api/service/accionistas_validators/` providing shareholder validation utilities:

| Function | Purpose |
|----------|---------|
| `es_nombre_persona_valido()` | 8-rule validation for person/entity names |
| `es_nombre_similar()` | Fuzzy matching with SequenceMatcher + word overlap |
| `filtrar_entradas_basura()` | Remove garbage OCR entries (headers, labels) |
| `deduplicar_accionistas()` | Deduplicate with fuzzy matching and enrichment |
| `limpiar_y_deduplicar()` | Combined clean + dedup pipeline |
| `calcular_confiabilidad_estructura()` | Confidence scoring for shareholder structure |

#### Deduplication Enrichment

When a duplicate is detected during merge/dedup, numerical data (porcentaje, acciones)
is now transferred to the surviving entry if it was previously missing.

### Test Results

| Document | Socios | Suma % | Status | Confiabilidad | Verdict |
|----------|:------:|:------:|:------:|:-------------:|:-------:|
| Capital X | 4 | **100%** | Verificada | 1.0 | APROBADO |
| Arenosos | 2 | **100%** | Verificada | 1.0 | APROBADO |
| Avanza Sólido | 3 | **99.99%** | Verificada | 1.0 | APROBADO |
| Almirante Capital | 2 | N/A (implícita) | Estructura_Implicita | 0.25 | APROBADO |

### Files Modified

| File | Change |
|------|--------|
| `api/service/openai.py` | `_strip_accents()`, multi-line regex, accent-normalized merges, FALLBACK CASO 2 condition |
| `api/service/accionistas_validators/__init__.py` | New module exports |
| `api/service/accionistas_validators/accionistas_validator.py` | Validation, dedup, fuzzy matching (~400 lines) |
| `README.md` | Version bump, project structure, Acta validations |
| `CHANGELOG.md` | This entry |
| `docs/DEVELOPERS_GUIDE.md` | Updated BACKUP ROBUSTO documentation |

### Deployment Notes

- **Breaking Changes:** None
- **Database Migrations:** Not required
- **Environment Variables:** No changes
- **New Dependencies:** None (uses stdlib `unicodedata`)
- **Backward Compatible:** Yes

---

## [1.2.0] - 2026-02-23

### Summary

Enhancement release implementing **BACKUP ROBUSTO** mechanism for shareholder structure
extraction in Acta Constitutiva and Reforma de Estatutos documents. Both document types
now have identical robustness for extracting `estructura_accionaria`.

### New Features

#### Robust Shareholder Extraction (estructura_accionaria)

1. **BACKUP ROBUSTO Mechanism for Acta Constitutiva**

   ```
   Trigger:   When suma_porcentajes < 98%
   Action 1:  _extract_accionistas_regex_backup() - 12+ regex patterns
   Action 2:  _reextract_estructura_accionaria() - LLM re-extraction with focused prompt
   Action 3:  Intelligent deduplication (name length ordering, >= 12 chars)
   Action 4:  Recalculate _estructura_confiabilidad and status
   Impact:    100% extraction rate for documents with explicit shareholder data
   ```

2. **BACKUP ROBUSTO Mechanism for Reforma de Estatutos**

   ```
   Same mechanism as Acta Constitutiva (already implemented)
   Ensures parity between both document types
   ```

3. **New Helper Functions**

   | Function | Purpose |
   |----------|----------|
   | `_extract_accionistas_regex_backup()` | Backup regex extraction from OCR text |
   | `_reextract_estructura_accionaria()` | LLM re-extraction with specialized prompt |

### Technical Details

**Extraction Pipeline (when suma < 98%)**:

```
1. Initial LLM extraction
2. Validation: suma_porcentajes < 98%? → Activate BACKUP ROBUSTO
3. Regex backup: 12+ patterns for different table/narrative formats
4. If still < 98%: LLM re-extraction with focused prompt
5. Deduplication: order by name length (longest first), filter < 12 chars
6. Recalculate confiabilidad based on final suma:
   - >= 100% (within 2%): confiabilidad = 1.0, status = "Verificada"
   - >= 95%: confiabilidad = 0.9, status = "Verificada"
   - >= 80%: confiabilidad = 0.7, status = "Parcial"
```

**Regex Patterns Supported**:
- Table format: `NOMBRE | ACCIONES | PORCENTAJE`
- Narrative format: `El señor X aporta Y acciones`
- OCR linearized tables
- Enterprise detection: S.A.P.I., S.A. de C.V., LLC

### Test Results

| Document | Socios | Suma % | Status | Confiabilidad |
|----------|:------:|:------:|:------:|:-------------:|
| Acta - Capital X | 4 | **100%** | Verificada | 1.0 |
| Reforma - Ultima Reforma | 5 | **100%** | Verificada | 1.0 |

### Files Modified

| File | Change |
|------|--------|
| `api/service/openai.py` | Added `llm` param to `_validate_and_correct_acta_fields()`, added BACKUP ROBUSTO section |
| `docs/CHANGELOG.md` | This changelog entry |
| `docs/DEVELOPERS_GUIDE.md` | Documentation of BACKUP ROBUSTO mechanism |
| `README.md` | Version bump to 1.2.0 |

### Deployment Notes

- **Breaking Changes:** None
- **Database Migrations:** Not required
- **Environment Variables:** No changes
- **Backward Compatible:** Yes — existing clients unaffected

---

## [1.1.0] - 2026-02-19

### Summary

Major bug fix release resolving 5 critical issues discovered during comprehensive
integration testing. System achieves **100% test pass rate** (131/131 tests).

### Bug Fixes

#### Critical (P0) — Production Blockers

1. **TypeError in `validation_wrapper.py` (line 196)**

   ```
   Error:    TypeError: unsupported operand type(s) for +: 'float' and 'str'
   Cause:    LLM returns confiabilidad_promedio_openai as string instead of float
   Fix:      Added float() conversion with try/except fallback to 0.0
   Impact:   Eliminated 500 errors in all document validation endpoints
   ```

2. **TypeError in `metrics.py` (line 545)**

   ```
   Error:    TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'
   Cause:    scores list contained None values from incomplete field extractions
   Fix:      Filter None values before sum(); handle empty list edge case
   Impact:   Fixed /metrics endpoint returning 500 error
   ```

#### High Priority (P1) — Business Logic

3. **Comprobante de Domicilio — CSF Alternative Acceptance**

   ```
   Issue:    CSF rejected when uploaded to /domicilio endpoint
   Rule:     Mexican KYB practice accepts CSF as valid address proof
   Fix:      Added ACCEPTED_ALTERNATIVES dict in document_identifier.py
             CSF → comprobante_domicilio is now a valid mapping
   Files:    api/service/document_identifier.py
             tests/test_integration_endpoints.py
   Impact:   CSF now passes domicilio validation (aligns with CNBV standards)
   ```

4. **Reforma Estatutos Misclassification**

   ```
   Issue:    File 1 detected as "acta_constitutiva" (7 false negatives)
             File 2 detected as "poder" (3 false negatives)
   Fix:      Added 5 new discriminants:
               - ASAMBLEA GENERAL EXTRAORDINARIA
               - PARA QUEDAR COMO SIGUE
               - MODIFICACION A LOS ESTATUTOS
               - RATIFICACION DEL CONSEJO
               - PROTOCOLIZACION DEL ACTA DE ASAMBLEA
             Removed 8 false negative indicators that appear legitimately
             in Reforma docs (PODERDANTE, PRIMER EJERCICIO SOCIAL, etc.)
   Impact:   2/2 Reforma test files now pass classification
   ```

#### Medium Priority (P2) — Scoring

5. **Bonus Score Scale Adjustment**

   ```
   Previous: Flat bonus regardless of absolute discriminant count
   New:      Graduated scale:
               ≥7 discriminants → +0.40
               ≥5 discriminants → +0.30
               ≥3 discriminants → +0.20
               ≥2 discriminants → +0.10
   Rationale: Large keyword lists diluted the ratio; absolute count
              matters more than proportion for documents with 40+ keywords
   Impact:   More balanced confidence scoring across all document types
   ```

### Test Results

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Total Tests | 131 | 131 | — |
| Passing | 126 | 131 | **+5** |
| Failing | 5 | 0 | **−5** |
| Success Rate | 96.2% | 100% | **+3.8 pp** |

**Breakdown:**

- Unit Tests (document_identifier.py): 25/25
- Unit Tests (document_identifier_agent.py): 21/21
- Integration Tests (endpoints): 85/85

### Files Modified

| File | Change |
|------|--------|
| `api/service/validation_wrapper.py` | Type conversion for `confiabilidad_promedio_openai` |
| `api/service/metrics.py` | None-value filtering in `get_low_confidence_fields()` |
| `api/service/document_identifier.py` | `ACCEPTED_ALTERNATIVES` dict; Reforma discriminants (+5/−8); bonus scale |
| `tests/test_integration_endpoints.py` | Aligned CSF-as-domicilio tests with business rule |

### Known Issues (Non-Critical)

- `datetime.utcnow()` deprecation warnings (Python 3.12+). Cosmetic only.
  Plan: migrate to `datetime.now(datetime.UTC)` in v1.2.

### Deployment Notes

- **Breaking Changes:** None
- **Database Migrations:** Not required
- **Environment Variables:** No changes
- **Backward Compatible:** Yes — existing clients unaffected

---

## [1.0.3] - 2026-02-18

Maintenance release with documentation updates and minor improvements.

## [1.0.0] - 2026-01-XX

Initial release with support for 9 document types:

- Constancia de Situación Fiscal (CSF)
- Acta Constitutiva
- Poder Notarial
- Comprobante de Domicilio
- INE (Anverso)
- INE (Reverso)
- Estado de Cuenta
- FIEL
- Reforma de Estatutos
