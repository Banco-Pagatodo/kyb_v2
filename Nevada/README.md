# Nevada — Agente de Dictamen Jurídico KYB

> **Versión**: 1.0.0  
> **Última actualización**: 19 de marzo de 2026  
> **Puerto**: 8013 | **API Prefix**: `/api/v1/legal`

Nevada es el agente de **dictamen jurídico** del sistema KYB. Consolida la información de los tres agentes anteriores (Dakota, Colorado y Arizona) para generar el **Dictamen Jurídico DJ-1** — la opinión legal sobre la viabilidad de apertura de cuenta bancaria de una persona moral.

---

## Arquitectura Multi-Agente (5 servicios)

| Agente | Puerto | Función |
|--------|--------|---------|
| **Dakota** | 8010 | Extracción documental (OCR + LLM) |
| **Colorado** | 8011 | Validación cruzada + portales gubernamentales |
| **Arizona** | 8012 | PLD/AML: completitud, screening, MER, dictamen PLD/FT |
| **Nevada** | 8013 | Dictamen Jurídico DJ-1 (reglas + LLM narrativo) |
| **Orquestrador** | 8002 | Coordinación del pipeline completo |

```
Dakota (:8010)  →  Colorado (:8011)  →  Arizona (:8012)  →  Nevada (:8013)
     │                    │                    │                    │
     │  OCR + persistencia│  Validación cruzada│  PLD/AML + MER     │  Dictamen DJ-1
     │                    │                    │                    │
     └────────────────────┴────────────────────┴────────────────────┘
                              PostgreSQL (kyb:5432)
```

Nevada **no recibe documentos** ni realiza extracción. Lee directamente de PostgreSQL toda la información que Dakota, Colorado y Arizona ya persistieron.

---

## Flujo de generación del DJ-1

```
       POST /api/v1/legal/dictamen/{empresa_id}
                        │
       ┌────────────────▼────────────────┐
       │  1. CARGA DE EXPEDIENTE          │
       │     data_loader.py               │
       │     PostgreSQL → ExpedienteLegal │
       │     (empresas + documentos +     │
       │      validaciones_cruzadas +     │
       │      analisis_pld + dictamenes_  │
       │      pld)                        │
       └────────────────┬────────────────┘
                        │
       ┌────────────────▼────────────────┐
       │  2. EVALUACIÓN DE REGLAS         │
       │     rules_engine.py              │
       │     9 reglas deterministas       │
       │     → ResultadoReglas            │
       └────────────────┬────────────────┘
                        │
       ┌────────────────▼────────────────┐
       │  3. GENERACIÓN CON LLM           │
       │     dictamen_generator.py        │
       │     Azure OpenAI GPT-4o          │
       │     → observaciones, fundamento, │
       │       dictamen_resultado         │
       └────────────────┬────────────────┘
                        │
       ┌────────────────▼────────────────┐
       │  4. CÁLCULO DE CONFIABILIDAD     │
       │     score OCR (50%) +            │
       │     score reglas (40%) +         │
       │     bonus LLM (10%)              │
       │     → ConfiabilidadDictamen      │
       └────────────────┬────────────────┘
                        │
       ┌────────────────▼────────────────┐
       │  5. PERSISTENCIA                 │
       │     persistence.py               │
       │     → dictamenes_legales         │
       │     → texto plano DJ-1           │
       └────────────────┬────────────────┘
                        │
                  JSON Response
```

---

## API REST

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/legal/health` | Health check |
| `POST` | `/api/v1/legal/dictamen/{empresa_id}` | Generar dictamen DJ-1 |
| `GET` | `/api/v1/legal/dictamen/{empresa_id}` | Consultar último dictamen |
| `GET` | `/api/v1/legal/expediente/{empresa_id}` | Preview del expediente (sin generar) |

### POST /dictamen/{empresa_id}

Genera el dictamen jurídico completo. Respuesta:

```json
{
  "id": "UUID",
  "empresa_id": "UUID",
  "rfc": "SCX190531824",
  "razon_social": "SOLUCIONES CAPITAL X S.A. DE C.V.",
  "dictamen": "FAVORABLE | FAVORABLE_CON_CONDICIONES | NO_FAVORABLE",
  "fundamento_legal": "Texto jurídico...",
  "dictamen_json": { },
  "dictamen_texto": "Texto plano formateado del DJ-1",
  "reglas": { },
  "elapsed_ms": 3200
}
```

### GET /dictamen/{empresa_id}

Retorna el último dictamen generado (desde BD).

### GET /expediente/{empresa_id}

Preview del expediente consolidado sin generar dictamen:

```json
{
  "empresa_id": "UUID",
  "rfc": "SCX190531824",
  "razon_social": "...",
  "tipos_documento": ["acta_constitutiva", "poder", "ine", "csf"],
  "tiene_validacion_cruzada": true,
  "dictamen_colorado": "APROBADO_CON_OBSERVACIONES",
  "tiene_analisis_pld": true,
  "resultado_pld": "APROBADO CON OBSERVACIONES",
  "tiene_dictamen_pld": true
}
```

---

## Las 9 reglas del motor determinista

El `rules_engine.py` evalúa 9 reglas antes de invocar al LLM:

| # | Regla | Severidad si falla | Qué valida |
|---|-------|--------------------|------------|
| R1 | Denominación Social | CRITICA / MEDIA | Nombre de la empresa en acta/CSF, detecta cambios |
| R2 | Datos de Constitución | CRITICA / MEDIA | Escritura, fecha, notario, número de notaría |
| R3 | Folio Mercantil Electrónico | MEDIA | Existencia del FME / RPP |
| R4 | Actividad / Giro | MEDIA | Objeto social o actividad económica presente |
| R5 | Tenencia Accionaria | CRITICA / MEDIA | Accionistas existen, porcentajes suman ~100% |
| R6 | Régimen de Administración | MEDIA | Administrador único o consejo identificado |
| R7 | Representante Legal | CRITICA / MEDIA | Poder notarial e INE del apoderado |
| R8 | Facultades para Firma | MEDIA / INFORMATIVA | Keywords de facultades bancarias en el poder |
| R9 | Consistencia con PLD | CRITICA / MEDIA | Arizona sin coincidencias críticas |

**Lógica de dictamen sugerido:**

| Condición | Dictamen |
|-----------|----------|
| ≥1 regla crítica fallida | `NO_FAVORABLE` |
| >2 reglas medias fallidas | `FAVORABLE_CON_CONDICIONES` |
| Todo lo demás | `FAVORABLE` |

---

## Generación narrativa con LLM

El `dictamen_generator.py` combina datos deterministas + LLM para producir el DJ-1:

### Extracción determinista

| Función | Sección DJ-1 |
|---------|--------------|
| `extraer_datos_constitucion()` | Datos de escritura constitutiva |
| `extraer_datos_ultimos_estatutos()` | Última reforma de estatutos |
| `extraer_actividad()` | Actividad / giro mercantil |
| `extraer_tenencia()` | Tabla de accionistas + extranjeros |
| `extraer_administracion()` | Régimen de administración |
| `extraer_apoderados()` | Apoderados con facultades detalladas |

### Llamada Azure OpenAI

- **Modelo**: GPT-4o (`AZURE_DEPLOYMENT_NAME`)
- **Temperatura**: 0.2 (determinista)
- **Max tokens**: 2000
- **Formato**: JSON obligatorio

El LLM recibe:
- Datos de la empresa (RFC, razón social)
- Datos constitutivos extraídos (OCR)
- Resultado de las 9 reglas
- Validación cruzada de Colorado (hallazgos, dictamen)
- Análisis PLD de Arizona (screening, nivel de riesgo)
- Reglas de negocio (knowledge/reglas_dictamen.md)

El LLM responde con:
```json
{
  "observaciones": ["obs1", "obs2"],
  "dictamen_resultado": "FAVORABLE",
  "fundamento_legal": "Con base en...",
  "resumen_cambios_estatutos": "..."
}
```

**Fallback**: Si Azure OpenAI no está disponible, usa el dictamen sugerido por el motor de reglas. Se marca `usa_llm: false` en la confiabilidad.

---

## Modelo de datos DJ-1

El `DictamenJuridico` (schemas.py) mapea las 3 páginas del formato DJ-1:

### Secciones del dictamen

| # | Sección | Modelo |
|---|---------|--------|
| 1 | Datos de Constitución | `DatosEscritura` |
| 2 | Últimos Estatutos | `DatosEscritura` |
| 3 | Actividad / Giro | `ActividadGiro` |
| 4 | Tenencia Accionaria | `TenenciaAccionaria` → `AccionistaDJ[]` |
| 5 | Régimen de Administración | `RegimenAdministracion` → `MiembroAdministracion[]` |
| 6 | Apoderado(s) | `ApoderadoDJ[]` → `FacultadesApoderado` |
| 7 | Observaciones | `list[str]` |
| — | Confiabilidad | `ConfiabilidadDictamen` |
| — | Elaboración / Revisión | `ElaboracionRevision` |

### FacultadesApoderado

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `administracion` | bool | Actos de administración |
| `dominio` | bool | Actos de dominio |
| `titulos_credito` | bool | Títulos de crédito |
| `apertura_cuentas` | bool | Apertura de cuentas bancarias |
| `delegacion_sustitucion` | bool | Puede delegar / sustituir |
| `especiales` | str | Facultades especiales (fideicomiso, amparo, etc.) |

---

## Confiabilidad del dictamen

`ConfiabilidadDictamen` calcula un score compuesto:

| Componente | Peso | Fuente |
|------------|------|--------|
| Score OCR | 50% | Promedio de confiabilidad de campos extraídos (Dakota) |
| Score Reglas | 40% | % de reglas cumplidas (9 totales) |
| Bonus fuente | 10% | 100% si usó LLM, 60% si solo determinista |

**Niveles:**

| Score | Nivel |
|-------|-------|
| ≥80 | ALTA |
| 55–80 | MEDIA |
| <55 | BAJA |

---

## Persistencia en PostgreSQL

### Tabla `dictamenes_legales`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | UUID | PK (auto-generado) |
| `empresa_id` | UUID | FK → empresas (CASCADE) |
| `rfc` | VARCHAR(13) | RFC de la empresa |
| `razon_social` | TEXT | Razón social |
| `dictamen` | VARCHAR(40) | FAVORABLE / FAVORABLE_CON_CONDICIONES / NO_FAVORABLE |
| `fundamento_legal` | TEXT | Fundamento jurídico del dictamen |
| `dictamen_json` | JSONB | DictamenJuridico completo |
| `dictamen_texto` | TEXT | Texto plano formateado (DJ-1) |
| `datos_expediente` | JSONB | Expediente consolidado |
| `reglas_aplicadas` | JSONB | ResultadoReglas completo |
| `version` | VARCHAR(20) | `Nevada v1.0.0` |
| `generado_por` | VARCHAR(50) | `legal_agent` |
| `created_at` | TIMESTAMPTZ | Fecha de generación |
| `updated_at` | TIMESTAMPTZ | Última actualización |

**Índice:** `idx_dictamenes_legales_empresa` sobre `empresa_id`.

La tabla se crea automáticamente al iniciar el servicio (`crear_tabla_si_no_existe()`).

---

## Base de conocimiento

| Archivo | Propósito |
|---------|-----------|
| `knowledge/reglas_dictamen.md` | Reglas de negocio para DJ-1 (inyectado como contexto al LLM) |
| `knowledge/template_sections.json` | Estructura del template DJ-1 (3 páginas, 9 secciones) |

El `reglas_dictamen.md` define las reglas de extracción para cada sección: denominación social, constitución, estatutos, actividad, tenencia accionaria, régimen de administración, representantes, facultades y criterios de firma bancaria.

---

## Estructura del proyecto

```
Nevada/
├── README.md                           ← Este archivo
└── legal_agent/                        ← Paquete principal
    ├── __init__.py
    ├── main.py                         ← FastAPI app + lifespan (DB pool + tabla)
    ├── pyproject.toml                  ← Dependencias y metadata
    │
    ├── api/
    │   └── router.py                   ← 4 endpoints REST
    │
    ├── core/
    │   ├── config.py                   ← Variables de entorno, rutas .env
    │   └── database.py                 ← Pool asyncpg (lazy init)
    │
    ├── models/
    │   └── schemas.py                  ← Pydantic v2: DictamenJuridico, ExpedienteLegal,
    │                                      ReglaEvaluada, ResultadoReglas, etc.
    │
    ├── services/
    │   ├── data_loader.py              ← Carga expediente de PostgreSQL (5 tablas)
    │   ├── rules_engine.py             ← Motor de 9 reglas + funciones de extracción
    │   ├── dictamen_generator.py       ← Generación DJ-1 (determinista + LLM)
    │   └── persistence.py              ← CRUD dictamenes_legales + texto plano
    │
    ├── knowledge/
    │   ├── reglas_dictamen.md           ← Reglas de negocio (contexto LLM)
    │   └── template_sections.json      ← Estructura template DJ-1
    │
    └── tests/                          ← Tests unitarios
```

---

## Dependencias

```toml
[project]
requires-python = ">=3.11"

[project.dependencies]
asyncpg = ">=0.29"
fastapi = ">=0.115"
uvicorn = ">=0.34"
pydantic = ">=2.0"
python-dotenv = ">=1.0"
openai = ">=1.12"
httpx = ">=0.27"
```

---

## Configuración

### Variables de entorno

```env
# Base de datos
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=<requerida>

# API
LEGAL_HOST=0.0.0.0
LEGAL_PORT=8013

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<recurso>.openai.azure.com/
AZURE_OPENAI_API_KEY=<clave>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_DEPLOYMENT_NAME=gpt-4o
```

El `.env` se busca automáticamente en:
1. `Nevada/legal_agent/.env`
2. `Agents/.env` (raíz)
3. `Dakota/kyb_review/.env`
4. `Dakota/kyb_review/api/service/.env`

---

## Ejecución

```bash
# Desde la raíz del workspace (Agents/)
Dakota\kyb_review\.venv\Scripts\python.exe -m uvicorn Nevada.legal_agent.main:app --host 0.0.0.0 --port 8013

# O dentro del directorio Nevada:
cd Nevada
python -m legal_agent.main
```

**Swagger UI:** http://localhost:8013/docs

### Health check

```bash
curl http://localhost:8013/api/v1/legal/health
# → {"status": "ok", "service": "nevada", "version": "1.0.0"}
```

### Generar dictamen

```bash
curl -X POST http://localhost:8013/api/v1/legal/dictamen/{empresa_uuid}
```

### Consultar dictamen

```bash
curl http://localhost:8013/api/v1/legal/dictamen/{empresa_uuid}
```

---

## Integración con otros agentes

### Datos que consume de cada agente

| Agente | Tabla PostgreSQL | Datos que lee Nevada |
|--------|-----------------|----------------------|
| **Dakota** | `empresas` | id, rfc, razon_social |
| **Dakota** | `documentos` | OCR JSON por tipo de documento |
| **Colorado** | `validaciones_cruzadas` | dictamen, hallazgos, recomendaciones, datos_clave |
| **Arizona** | `analisis_pld` | dictamen PLD, screening, nivel de riesgo |
| **Arizona** | `dictamenes_pld` | dictamen PLD/FT completo, JSON |

### Prerequisitos para generar un dictamen

1. La empresa debe existir en la tabla `empresas` (creada por Dakota)
2. Debe haber al menos documentos OCR en la tabla `documentos` (procesados por Dakota)
3. Idealmente: validación cruzada de Colorado y análisis PLD de Arizona ya ejecutados

Si Colorado o Arizona no han corrido, Nevada genera el dictamen con los datos disponibles pero las reglas R9 (consistencia PLD) fallarán y la confiabilidad será menor.

---

## Texto plano DJ-1

La función `_generar_texto_plano()` formatea el dictamen como texto con ancho de 70 caracteres:

```
══════════════════════════════════════════════════════════════════════
                        DICTAMEN JURÍDICO DJ-1
══════════════════════════════════════════════════════════════════════
Empresa:  SOLUCIONES CAPITAL X S.A. DE C.V.
RFC:      SCX190531824
Fecha:    2026-03-19

1. DATOS DE CONSTITUCIÓN
──────────────────────────────────────────────────────────────────────
   Escritura:       12345
   Fecha:           2019-05-31
   Notario:         Lic. Juan Pérez
   Nº Notaría:      42
   Residencia:      Ciudad de México
   Folio Mercantil: N-2019-123456

2. ÚLTIMOS ESTATUTOS SOCIALES
   ...

3. ACTIVIDAD / GIRO
   ...

4. TENENCIA ACCIONARIA
   Accionista                         %        Tipo    Extr.
   ─────────────────────────────────────────────────────────
   Persona Uno                       60.00%    física   No
   Persona Dos                       40.00%    física   No

5. RÉGIMEN DE ADMINISTRACIÓN
   ...

6. APODERADO(S)
   ...

7. OBSERVACIONES
   ...

══════════════════════════════════════════════════════════════════════
DICTAMEN:    FAVORABLE
FUNDAMENTO:  Con base en la revisión documental...
══════════════════════════════════════════════════════════════════════

CONFIABILIDAD: 89.8% — ALTA
  OCR: 92.0%  |  Reglas: 88.9%  |  Fuente: LLM

Elaboró:  Nevada v1.0.0 — Agente IA Legal  (2026-03-19)
```

Este texto se devuelve en el campo `dictamen_texto` de la API y se persiste en la columna `dictamen_texto` de la BD.
