# Changelog — Colorado (Validación Cruzada)

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.3.0] - 2026-04-06

### Changed — Optimización de rendimiento en portales (Bloque 10)
- **Browser compartido** — Los 3 validadores de portales (FIEL, RFC, INE) ahora comparten **una sola instancia de Chromium** en lugar de lanzar 3 navegadores independientes. Nuevo método `usar_navegador_compartido(browser)` en `ValidadorPortalBase`. Ahorra ~12-16s de overhead por empresa.
- **Carga de variables de entorno** — `core/config.py` ahora carga **todos** los archivos `.env` encontrados (con `override=False`) en lugar de detenerse en el primero. Esto asegura que las claves de Azure CV y OpenAI (necesarias para resolver CAPTCHAs) se carguen correctamente desde el `.env` de Dakota.
- **Delays y reintentos reducidos** — `MAX_REINTENTOS` 3→2, `DELAY_MIN` 1→0.5s, `DELAY_MAX` 3→1.5s, `NAVEGACION_TIMEOUT` 20→15s. Reduce tiempos muertos ~50%.
- **`validar_todas()` paralelo** — El motor (`engine.py`) ahora procesa empresas en paralelo con `asyncio.gather` + `Semaphore(3)`, en lugar de un bucle secuencial. Un lote de 10 empresas pasa de ~250s a ~30-40s.

### Fixed
- **Resolución de CAPTCHAs** — La cascada Azure CV → GPT-4o → Tesseract ahora funciona correctamente porque las variables `AZURE_CV_ENDPOINT`, `AZURE_CV_KEY`, `AZURE_OPENAI_ENDPOINT` y `AZURE_OPENAI_API_KEY` se cargan desde el `.env` de Dakota.

---

## [1.1.0] - 2026-03-28

### Added
- **Bloque 11 — Comparación Manual vs OCR** — Nuevo bloque condicional que compara datos del formulario manual de PagaTodo (`formulario_manual`) contra datos extraídos por OCR. Se ejecuta automáticamente si el expediente incluye un `formulario_manual`.
  - 10 validaciones (V11.1–V11.10): RFC PM (CRÍTICA), Razón Social (CRÍTICA), Nombre R.L. (CRÍTICA), RFC R.L. (MEDIA), Domicilio calle (MEDIA), CP (MEDIA), Serie FIEL (MEDIA), Instrumento público (INFORMATIVA), Fecha constitución (INFORMATIVA), Giro mercantil (INFORMATIVA).
  - Nuevo modelo `ComparacionCampo` en schemas.py para resultados campo a campo.
  - Campo `comparacion_fuentes` añadido a `ReporteValidacion`.
  - Tabla comparativa en el reporte texto (sección Bloque 11).
  - Umbrales configurables: `UMBRAL_SIMILITUD_MANUAL_OCR=0.80`, `UMBRAL_SIMILITUD_DIRECCION_MANUAL_OCR=0.70`.
- **Archivo**: `services/validators/bloque11_comparacion_fuentes.py`.

---

## [1.2.1] - 2026-03-27

### Added
- **Bloque 9 — 3 nuevos doc_types complementarios** — `ine_propietario_real`, `domicilio_rl` y `domicilio_propietario_real` añadidos a `DOCS_COMPLEMENTARIOS` y al mapa de nombres legibles `_NOMBRES_DOC` en `bloque9_completitud.py`. Permiten que el Bloque 9 reconozca y contabilice documentos provenientes del flujo PagaTodo Hub.

### Changed
- **`_NOMBRES_DOC`** — Renombrado `"domicilio"` a `"Comprobante de domicilio (empresa)"` para diferenciar del `domicilio_rl` (representante legal) y `domicilio_propietario_real`.

---

## [1.2.0] - 2026-03-25

### Changed
- **V4.2 — Apoderado en estructura** — Reducido de `Severidad.MEDIA` (fallo) a `Severidad.INFORMATIVA` (N/A) cuando el apoderado no aparece como accionista o consejero. El apoderado/RL no está obligado a ser socio de la empresa.

### Fixed
- **V4.5 — INE anverso vs reverso** — Cuando falta alguna cara de la INE, ahora se marca como `pasa=False` (fallo crítico). Antes era `pasa=None` (N/A), que no reflejaba la gravedad de una identificación incompleta.
- **V4.5 — Detección INE doble cara** — Si el documento INE (anverso) contiene ambas caras en un solo archivo, se reconoce automáticamente como identificación completa. Detecta dos escenarios: (1) multi-página con campos en `pagina >= 2`, y (2) ambas caras en la misma página, detectado por presencia de campos exclusivos del reverso (MachineReadableZone, CIC, código de barras, etc.).

---

## [1.1.1] - 2026-03-23

### Fixed
- **Screenshots y logs sin protección** — Agregados `.gitignore` en `screenshots/` y `logs/` para excluir datos sensibles del repositorio.
- **Sanitización de logs** — Nuevo filtro `_SanitizeFilter` que enmascara RFC y CURP automáticamente en los registros de log.
- **Permisos de directorio** — `LOG_DIR` y `SCREENSHOT_DIR` restringidos a `0o700` (owner-only) al iniciar.

---

## [1.1.0] - 2026-03-11

### Summary

**Major feature release**: Implementación de **Bloque 5B — Validación de Reformas y Estructura Accionaria PLD**.
Cumple con DCG Art.115-bis (25%), CFF Art.32-B Ter (15%) y LFPIORPI Art.18.

### Added

#### Bloque 5B — Validación de Reformas y Estructura Accionaria
- **V5.5 — Cruce cronológico:** Determina estructura vigente aplicando reformas en orden de inscripción RPC
- **V5.6 — Consistencia RFC:** Valida formato RFC (12/13 chars) vs tipo persona declarado
- **V5.7 — Cross-reference:** Compara accionistas entre Acta Constitutiva y Reforma
- **V5.8 — Inscripción RPC:** Verifica folio mercantil y fecha de inscripción
- **V5.9 — Alertas PLD:** Detecta estructuras de riesgo:
  - `EST001` — Estructura multicapa (2+ PM con >25%)
  - `EST002` — PM requiere perforación
  - `EST003` — Shell company (PM <2 años antigüedad)
  - `EST004` — Jurisdicción de alto riesgo (GAFI)
  - `EST005` — Accionista >10% sin RFC
  - `RFC001` — RFC formato inválido
  - `RFC002` — RFC inconsistente con tipo persona
- **V5.10 — Estructura vigente:** Resumen consolidado de accionistas (PF/PM, >25%)

#### Funciones exportadas para Arizona
- `determinar_estructura_vigente()` — Aplica reformas cronológicamente
- `EstructuraVigente` — Dataclass con resultado de cruce
- `AlertaEstructura` — Dataclass para alertas PLD
- `UMBRAL_PROPIETARIO_REAL` — 25% (DCG)
- `UMBRAL_BENEFICIARIO_CONTROLADOR` — 15% (CFF)

#### Tests (37 tests adicionales)
- `test_bloque5b_reformas.py` — Cobertura completa del nuevo bloque

### Changed

- `validators/__init__.py` — Incluye `validar_reformas` en `TODOS_LOS_BLOQUES`
- Bloques ejecutados: 1-5, 5B, 6-10 (ahora 11 bloques totales)

### Regulatory Compliance

- **DCG Art.115-bis:** Propietario real >25% participación
- **CFF Art.32-B Ter:** Beneficiario controlador >15%
- **LFPIORPI Art.18:** Umbrales de identificación
- **GAFI Rec.24:** Jurisdicciones de alto riesgo

---

## [1.0.0] - 2026-02-27

### Summary

Release inicial del agente **Colorado** — servicio de validación cruzada KYB para empresas
mexicanas. Compara datos extraídos por Dakota entre documentos, detecta inconsistencias y
genera un dictamen automático con puntuación de confiabilidad.

### Added

#### Motor de Validación Cruzada (10 bloques)
- **Bloque 1 — Identidad:** Razón social, RFC y representante legal entre CSF, acta y poder
- **Bloque 2 — Domicilio:** Dirección fiscal vs. comprobante de domicilio (similitud ≥ 0.75)
- **Bloque 3 — Vigencia:** Verificación de fechas de CSF, comprobante y estado de cuenta (≤ 3 meses)
- **Bloque 4 — Apoderado:** Consistencia de datos del apoderado legal entre INE, poder y acta
- **Bloque 5 — Estructura societaria:** Objeto social, capital social y duración de la sociedad
- **Bloque 6 — Bancarios:** Titular y RFC en estado de cuenta vs. CSF
- **Bloque 7 — Notarial:** Número de escritura, notario, fecha y protocolo del poder notarial
- **Bloque 8 — Calidad de datos:** Detección de campos vacíos, formatos inválidos y confianza baja
- **Bloque 9 — Completitud:** Verificación de documentos mínimos (7) y complementarios (3)
- **Bloque 10 — Portales:** Automatización con Playwright para consulta de RFC en portales SAT

#### API REST (Puerto 8001)
- `GET /empresas` — Listar empresas disponibles en BD
- `POST /empresa/{id}` — Ejecutar validación cruzada completa (JSON)
- `POST /empresa/{id}/reporte` — Generar reporte en texto plano
- `POST /todas` — Validar todas las empresas
- `POST /todas/reporte` — Reporte global en texto plano
- `GET /health` — Health check del servicio
- `GET /historial` — Historial de validaciones
- `GET /historial/{id}` — Detalle de validación por ID
- `GET /empresa/{id}/ultima` — Última validación de una empresa

#### Persistencia
- Upsert en tabla `validaciones_cruzadas` con dictamen, hallazgos y puntuación
- Conexión asíncrona a PostgreSQL vía `asyncpg`

#### Utilidades
- `text_utils.py` — Normalización Unicode, similitud Jaccard/SequenceMatcher, extracción de fechas
- `report_generator.py` — Generador de reportes estructurados por bloque
- `schemas.py` — Modelos Pydantic: `HallazgoValidacion`, `ResultadoBloque`, `ReporteValidacion`, `ResumenGlobal`

#### Configuración
- `config.py` — Variables de entorno con fallback, umbrales configurables, listas de documentos
- `.env.example` — Plantilla de configuración para desarrollo

#### Tests (85 tests)
- `test_text_utils.py` — Normalización, similitud, fechas
- `test_engine.py` — Motor de validación con casos edge
- `test_persistence.py` — Upsert y consulta a BD (mocked)
- `test_report_generator.py` — Formato de reportes
- `test_validators.py` — Bloques 1-9 con datos reales y ficticios

### Technical Details

```
Puerto:     8001
Prefijo:    /api/v1/validacion
Python:     ≥ 3.12
BD:         PostgreSQL 16 (asyncpg)
Tabla:      validaciones_cruzadas
```
