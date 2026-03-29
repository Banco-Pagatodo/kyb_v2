# Changelog — Arizona PLD Agent

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.2.0] - 2026-03-27

### Added
- **`DOCS_INE_ALTERNATIVOS`** — Nueva constante en `core/config.py`: `["ine", "ine_propietario_real"]`. Permite que la Etapa 1 acepte `ine_propietario_real` como alternativa válida al documento INE del representante legal.
- **Soporte de domicilio alternativo ampliado** — `DOCS_DOMICILIO_ALTERNATIVOS` expandido a `["domicilio", "domicilio_rl", "domicilio_propietario_real", "estado_cuenta"]` para reconocer comprobantes de domicilio provenientes del flujo PagaTodo Hub.

### Changed
- **`_verificar_documentos()` en `etapa1_completitud.py`** — Nuevo branch `elif doc_type == "ine"` que verifica contra `DOCS_INE_ALTERNATIVOS`, análogo al branch existente de domicilio.
- **Cálculo `docs_presentes_pld`** — Ahora usa `DOCS_DOMICILIO_ALTERNATIVOS` (constante) en lugar de lista hardcoded, y añade lógica para `DOCS_INE_ALTERNATIVOS`.

---

## [2.1.0] - 2026-03-24

### Added
- **A4.4–A4.6: Validación de nombre completo** — Etapa 1 ahora verifica que apoderados, accionistas y administradores/consejeros tengan nombre completo (Nombre + Primer Apellido + Segundo Apellido). Si algún nombre está incompleto se marca como hallazgo y se genera recomendación.
- **Endpoint descargable `/etapa2/{empresa_id}/descargar`** — Nuevo endpoint que devuelve el reporte de screening contra listas negras como archivo `.txt` descargable con `Content-Disposition: attachment`.

---

## [2.0.1] - 2026-03-23

### Fixed
- **Dependencia `pyodbc` faltante** — Agregado `pyodbc>=5.1` a `pyproject.toml`. Un `pip install .` limpio ya no rompe el agente por módulo no encontrado.
- **Persistencia sin transacción** — `guardar_analisis_pld()` y `guardar_dictamen_pld()` ahora aceptan una conexión externa (`conn`) para participar en una transacción compartida.
- **Nueva función `guardar_resultado_completo()`** — Ejecuta ambos UPSERTs (`analisis_pld` + `dictamenes_pld`) dentro de `async with conn.transaction():`, garantizando atomicidad.
- **Router refactorizado** — El pipeline `/completo/{empresa_id}` usa `guardar_resultado_completo()` en lugar de dos llamadas independientes, eliminando el riesgo de estado inconsistente si falla el segundo INSERT.
- **Normalización de nombres centralizada** — Creado `core/normalize.py` con `normalizar_nombre`, `normalizar_rfc`, `normalizar_razon_social`. `blacklist_screening.py` y `etapa1_completitud.py` ahora importan de `core.normalize`.
- **Validación UUID en endpoints** — Todos los endpoints con `empresa_id` validan formato UUID; retornan HTTP 400 si es inválido.

---

## [1.5.0] - 2026-03-18

### Added
- **Dictamen PLD/FT — Banco PagaTodo** (6 páginas, formato bancario fijo)
  - `models/dictamen_schemas.py` — Modelos Pydantic: DictamenPLDFT, AccionistaDictamen, PropietarioRealDictamen, RepresentanteLegalDictamen, AdministradorDictamen, ScreeningSeccion
  - `services/dictamen_generator.py` — Motor de generación:
    - `generar_dictamen()` — Orquesta toda la información de Dakota/Colorado/Arizona
    - `determinar_grado_riesgo()` — Reglas de decisión: LPB/OFAC/ONU → alto, 69-B → alto, PEP → medio, actividad alto riesgo → medio, MER
    - `redactar_justificacion_descarte()` — Texto automático para homónimos descartados
    - `sanitizar_nombre_archivo()` — Genera nombre de archivo .txt seguro
  - `services/dictamen_txt.py` — Formateador a texto plano:
    - 11 secciones con tablas box-drawing: PM, screening, actividad, domicilio, accionistas, propietarios reales, representantes, administración, perfil transaccional, conclusiones, elaboró
  - Persistencia en `dictamenes_pld` tabla (migración 0010):
    - UPSERT por empresa_id con dictamen_json (JSONB) y dictamen_txt (TEXT)
    - `guardar_dictamen_pld()` / `obtener_dictamen_pld()` en persistence.py
  - Endpoints nuevos:
    - `GET /dictamen/{empresa_id}` — JSON completo del dictamen
    - `GET /dictamen/{empresa_id}/txt` — Dictamen en texto plano
  - Integración en pipeline `/completo/{empresa_id}` — genera y persiste dictamen tras reporte unificado

### Changed
- `api/router.py` — Importa dictamen_generator, dictamen_txt y nuevas funciones de persistencia

---

## [1.4.0] - 2026-03-18

### Added
- **Etapa 4 — Screening de Beneficiarios Controladores** (`api/router.py`)
  - `_construir_personas_bc()` convierte BCs identificados al formato de entrada de screening
  - Después de extraer estructura accionaria, ejecuta `ejecutar_screening_completo()` sobre cada BC
  - Resultado `screening_bc_resumen` se pasa a `generar_reporte_unificado()`

- **Alerta EA004 — Accionista Persona Moral** (`services/etapa4_propietarios_reales.py`)
  - Cualquier accionista persona moral genera alerta de severidad **crítica**
  - Detección por sufijos: S.A., SA DE CV, SAPI, S. DE R.L., SC, SAS, SOFOM, etc.
  - Incluye nombre de empresa, porcentaje y referencia regulatoria (DCG Art. 115 / CFF Art. 32-B Ter)
  - EA002 (alta) se anida dentro de EA004 para PM con ≥25%

- **Renderizado screening BC en reporte** (`services/report_generator.py`)
  - `_mostrar_screening_bc_persona()` — helper para mostrar resultado de screening por BC
  - Sección "SCREENING BC" debajo de cada beneficiario controlador en Etapa 4
  - `screening_bc_critico` alimenta `extra_criticos` → dictamen RECHAZADO si hay coincidencia
  - Parámetro `screening_bc_resumen` añadido a `generar_reporte_unificado()`

### Changed
- **`services/report_generator.py`** — Encabezado Etapa 3
  - "BLOQUE 10: VALIDACIÓN EN PORTALES GUBERNAMENTALES" → "VALIDACIÓN EN PORTALES GUBERNAMENTALES"
  - Se elimina prefijo redundante "BLOQUE 10:"

- **`services/report_generator.py`** — Dictamen final
  - Accionista PM en `extra_criticos` → dictamen pasa a RECHAZADO
  - Coincidencia screening BC en `extra_criticos` → dictamen pasa a RECHAZADO

---

## [1.3.0] - 2026-03-18

### Added
- **Calculador determinista MER** (`services/mer_calculator.py`)
  - Arquitectura de dos capas: CAPA 1 (Python determinista) + CAPA 2 (LLM solo para factores no resueltos)
  - El LLM **nunca** hace aritmética, multiplicaciones, sumas ni clasificaciones
  - Dataclasses `FactorCalc` y `ResultadoCalc` para resultados intermedios
  - Funciones:
    - `calcular_mer_pm()` — Cálculo completo de los 15 factores MER para Personas Morales
    - `aplicar_resoluciones_llm()` — Recibe valores del LLM y recalcula puntaje
    - `resultado_a_dict()` — Serialización con opciones válidas para factores pendientes
    - `_opciones_para_factor()` — Opciones válidas que el LLM puede elegir
  - Helpers deterministas: `_valor_tipo_persona()`, `_valor_antiguedad()`, `_valor_producto()`
  - Umbrales PM: BAJO (85–142), MEDIO (143–199), ALTO (200–255)
  - Coincidencia LPB → ALTO automático independientemente del puntaje
  - Factores 7–10 sin datos → asumido val=1 (dato_asumido=True)
  - Factores 11–12 sin datos → asumido val=2 (dato_asumido=True)
  - Factor 4 sin match en catálogo → `requiere_llm=True`
  - Alertas estructurales: SAPI, datos asumidos

- **Resolución de actividad por RAG** (`services/mer_engine.py`)
  - `_resolver_actividad_por_rag()` — Clasifica actividades económicas no encontradas en catálogo
  - Busca keywords de alto riesgo (FACTORING, SOFOM, INTERMEDIACIÓN CREDITICIA, etc.) → Grupo 3
  - Busca keywords de bajo riesgo (AGRÍCOLA, EDUCACIÓN, SALUD, etc.) → Grupo 1
  - Keywords evaluados tanto en nombre de actividad como en resultados RAG
  - Default prudencial: Grupo 2 si no hay match

- **Tests unitarios MER** (`tests/test_mer_calculator.py`)
  - 28 tests cubriendo:
    - Funciones de valor individual (tipo persona, antigüedad, producto)
    - Caso SOLUCIONES CAPITAL X completo (puntaje=150.0, grado=MEDIO)
    - Factores deterministas individuales con pytest.approx
    - Marcado de datos asumidos y alertas SAPI
    - Clasificación por umbrales y LPB → ALTO
    - Serialización y opciones para factores pendientes
    - Resolución LLM y recálculo sin alterar factores fijos
    - Pesos suman 1.10, siempre 15 factores

### Changed
- **`services/mer_engine.py`** — Refactorizado completamente
  - `calcular_riesgo_mer()` ahora delega a `calcular_mer_pm()` del calculador determinista
  - Eliminadas ~320 líneas de cálculo inline (aritmética en LLM)
  - Si hay factores pendientes, resuelve vía `_resolver_actividad_por_rag()` + `aplicar_resoluciones_llm()`
  - Mapeo `ResultadoCalc` → `ResultadoMER` (Pydantic) preservando interfaz pública
  - Import: `from .mer_calculator import calcular_mer_pm, aplicar_resoluciones_llm`

- **`models/mer_schemas.py`** — Campos extendidos
  - `FactorRiesgo`: añadidos `dato_asumido: bool` y `nota: str`
  - `ResultadoMER`: añadidos `alertas: list[str]` y `calculo_completo: bool`

- **`services/report_generator.py`** — Etapa 5 mejorada
  - Marcadores `⚠️ DATO ASUMIDO — {nota}` debajo de factores con datos asumidos
  - Marcadores `🤖 {nota}` para factores resueltos por LLM
  - Sección "⚠️ DATOS PENDIENTES DE CONFIRMACIÓN" con fecha límite de recalificación (90 días)
  - Sección "Alertas estructurales" con alertas SAPI y conteo de datos asumidos
  - Anchos de columna ajustados: # (4), Factor (44), Val (4), Peso (6), Pts (8)

### Fixed
- **Puntaje SOLUCIONES CAPITAL X**: 135 (BAJO) → 150 (MEDIO)
  - Factor 1 ahora siempre 3 para PM (antes el LLM lo cambiaba a 2)
  - Actividad "intermediación crediticia" ahora correctamente Grupo 3 (antes Grupo 2)
  - Keywords se evalúan en el nombre de la actividad + resultados RAG (antes solo RAG)

---

## [1.2.0] - 2026-03-11

### Added
- **Persistencia en PostgreSQL** (`services/persistence.py`)
  - Tabla `analisis_pld` para almacenar resultados de análisis PLD
  - Migración Alembic `0006_crear_tabla_analisis_pld`
  - UPSERT para permitir re-ejecuciones sin duplicados
  - Funciones:
    - `guardar_etapa1()` - Persiste resultados de Etapa 1 Completitud
    - `guardar_screening()` - Persiste resultados de Etapa 2 Screening
    - `obtener_analisis_pld()` - Consulta análisis por empresa
    - `obtener_ultimo_analisis()` - Último análisis por empresa/etapa

- **Endpoints Etapa 2** (`api/router.py`)
  - `POST /api/v1/pld/etapa2/{empresa_id}` - Ejecuta screening y persiste
  - `POST /api/v1/pld/etapa2/{empresa_id}/reporte` - Reporte texto screening

- **Endpoint consultas** (`api/router.py`)
  - `GET /api/v1/pld/analisis/{empresa_id}` - Consulta análisis guardados

- **Generador de reporte screening** (`services/blacklist_screening.py`)
  - `generar_reporte_screening()` - Reporte texto formateado

### Changed
- `api/router.py` - Ahora persiste automáticamente en BD al ejecutar etapas
- Versión API actualizada a `0.2.0`

---

## [1.1.0] - 2025-01-20

### Added
- **Etapa 4 — Propietarios Reales** (`services/etapa4_propietarios_reales.py`)
  - Cálculo de propiedad indirecta (look-through / perforación de cadena)
  - Cascada CNBV según lineamientos del 28-julio-2017
  - Consolidación de participaciones múltiples
  - Detección de ciclos en estructuras accionarias
  - Cadenas de titularidad para LFPIORPI

- **Funciones principales:**
  - `calcular_propiedad_indirecta()` - Look-through recursivo
  - `identificar_propietarios_reales_cnbv()` - Cascada de 4 pasos
  - `ejecutar_etapa4_propietarios_reales()` - Orquestador principal
  - `consolidar_propietarios()` - Agrupa participaciones múltiples
  - `generar_reporte_propietarios()` - Reporte DCG/CFF/LFPIORPI
  - `propietarios_a_personas_identificadas()` - Integración con Etapa 1

- **Constantes regulatorias:**
  - `UMBRAL_PROPIETARIO_REAL = 25.0` (DCG Art. 115)
  - `UMBRAL_BENEFICIARIO_CONTROLADOR = 15.0` (CFF Art. 32-B)
  - `UMBRAL_LFPIORPI = 25.0` (Reforma 2025)

- **Dataclasses:**
  - `PropietarioReal` - Persona identificada como propietario real
  - `ResultadoPropietariosReales` - Resultado del análisis completo
  - `CadenaTitularidad` - Cadena de titularidad LFPIORPI
  - `NodoEstructura` - Nodo en árbol de estructura accionaria

- **Enums:**
  - `CriterioIdentificacion` - Criterio usado para identificar propietario
  - `NivelRiesgo` - Nivel de riesgo PLD

- **Tests:** 38 tests para Etapa 4 (`tests/test_etapa4.py`)
  - Constantes y umbrales
  - Helpers (`_es_persona_moral`, `_normalizar_nombre`)
  - Perforación multinivel
  - Detección de ciclos
  - Consolidación de participaciones
  - Cascada CNBV completa
  - Integración con expediente
  - Generación de reportes

### Changed
- `services/__init__.py` - Exporta funciones de Etapa 1 y Etapa 4

---

## [1.0.0] - 2024-XX-XX

### Added
- **Etapa 1 — Completitud** (`services/etapa1_completitud.py`)
  - Verificación de documentos obligatorios
  - Identificación de personas
  - Validación de domicilio
  - Verificación de poder bancario
  - Sistema de alias de campos

- **Core:**
  - `core/config.py` - Configuración y alias
  - `core/database.py` - Conexión PostgreSQL

- **Models:**
  - `models/schemas.py` - Modelos Pydantic (ExpedientePLD, PersonaIdentificada, etc.)

- **API:**
  - `api/router.py` - Endpoints FastAPI

- **Services:**
  - `services/data_loader.py` - Carga de datos
  - `services/persistence.py` - Persistencia
  - `services/report_generator.py` - Generación de reportes
