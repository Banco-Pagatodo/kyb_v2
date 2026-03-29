# Colorado — Agente de Validación Cruzada KYB

> **Versión**: 1.2.1  
> **Última actualización**: 27 de marzo de 2026  
> **Puerto**: 8011 | **API Prefix**: `/api/v1/validacion`

Colorado es un agente que **valida automáticamente los documentos corporativos de empresas mexicanas** (proceso KYB — _Know Your Business_). Recibe un expediente digital ya extraído por **Dakota** (el agente de extracción) y cruza la información entre documentos para detectar inconsistencias, documentos faltantes o vencidos, y validar datos contra portales gubernamentales en tiempo real.

Colorado forma parte de un **sistema de 5 agentes independientes**:

| Agente | Puerto | Función |
|--------|--------|--------|
| **Dakota** | 8010 | Extracción de datos de documentos (OCR + LLM) |
| **Colorado** | 8011 | Validación cruzada + portales gubernamentales |
| **Arizona** | 8012 | PLD/AML: completitud, screening, MER, dictamen PLD/FT |
| **Nevada** | 8013 | Dictamen Jurídico DJ-1 (reglas + LLM narrativo) |
| **Orquestrador** | 8002 | Coordinación automática del flujo completo |

> **Nota**: En uso normal, no necesitas llamar a Colorado directamente. El **Orquestrator** se encarga de coordinar Dakota → Colorado automáticamente. Los endpoints de Colorado están disponibles para uso directo cuando se requiera validar sin pasar por el pipeline completo.

## ¿Qué hace exactamente?

Imagina que una empresa quiere abrir una cuenta bancaria. Tiene que entregar: acta constitutiva, constancia de situación fiscal (CSF), comprobante de domicilio, estado de cuenta, FIEL, INE del apoderado legal, poder notarial y reforma de estatutos.

Colorado toma **todos esos documentos** (que Dakota ya extrajo a JSON) y los cruza entre sí para responder preguntas como:

- ¿El RFC coincide en todos los documentos?
- ¿El domicilio de la CSF coincide con el comprobante?
- ¿La FIEL está vigente?
- ¿La INE del apoderado corresponde al poder notarial?
- ¿El titular del estado de cuenta es la misma empresa?
- ¿El RFC es válido en el portal del SAT?
- ¿La INE aparece en la Lista Nominal del INE?

Al final genera un **reporte de texto** con dictamen (APROBADO / RECHAZADO), hallazgos clasificados por severidad, y recomendaciones concretas.

---

## Estructura del proyecto

```
Colorado/
├── README.md                          ← Este archivo
├── cross_validation/                  ← Paquete principal de Python
│   ├── __init__.py                    ← Metadatos del paquete (versión)
│   ├── __main__.py                    ← Permite ejecutar con: python -m cross_validation
│   ├── main.py                        ← ★ Punto de entrada: CLI + servidor FastAPI
│   ├── pyproject.toml                 ← Configuración del proyecto (dependencias, scripts)
│   │
│   ├── core/                          ← Configuración y conexión a BD
│   │   ├── config.py                  ← Variables de entorno, umbrales, docs mínimos
│   │   └── database.py                ← Pool de conexiones asyncpg a PostgreSQL
│   │
│   ├── models/                        ← Modelos de datos (Pydantic)
│   │   └── schemas.py                 ← Hallazgo, ExpedienteEmpresa, ReporteValidacion, etc.
│   │
│   ├── api/                           ← API REST (FastAPI)
│   │   └── router.py                  ← Endpoints: /empresas, /validar, /reporte
│   │
│   └── services/                      ← ★ Toda la lógica de negocio
│       ├── data_loader.py             ← Carga expedientes de la BD (PostgreSQL)
│       ├── engine.py                  ← ★ Motor principal: ejecuta validaciones y genera dictamen
│       ├── persistence.py             ← Guarda resultados en tabla validaciones_cruzadas
│       ├── text_utils.py              ← Utilidades: normalización, fuzzy matching, parsing fechas
│       ├── report_generator.py        ← Genera el reporte de texto formateado
│       │
│       ├── validators/                ← Bloques de validación (1 archivo = 1 bloque)
│       │   ├── base.py                ← Funciones compartidas entre validadores
│       │   ├── bloque1_identidad.py   ← RFC, razón social, estatus fiscal
│       │   ├── bloque2_domicilio.py   ← CP, domicilio fiscal vs comprobante
│       │   ├── bloque3_vigencia.py    ← Vigencia de FIEL, INE, CSF, estados de cuenta
│       │   ├── bloque4_apoderado.py   ← INE vs Poder, apoderado en estructura
│       │   ├── bloque5_estructura.py  ← Estructura accionaria, capital social
│       │   ├── bloque6_bancarios.py   ← Titular = empresa, CLABE válida
│       │   ├── bloque7_notarial.py    ← Datos notariales, folio mercantil
│       │   ├── bloque8_calidad.py     ← Confiabilidad de extracción
│       │   ├── bloque9_completitud.py ← Documentos mínimos requeridos
│       │   └── bloque10_portales.py   ← Integración con portal_validator
│       │
│       └── portal_validator/          ← Automatización de portales web (Playwright)
│           ├── __init__.py            ← Lazy import del orquestador
│           ├── base.py                ← Clase base: retry, delays, screenshots, stealth
│           ├── captcha.py             ← Resolución de CAPTCHAs (Azure CV, GPT-4o, Tesseract)
│           ├── engine.py              ← Orquestador: ejecuta los 3 módulos en secuencia
│           ├── report.py              ← Genera reportes Excel/CSV de portales
│           ├── fiel_validator.py      ← Portal SAT: vigencia de e.firma (FIEL)
│           ├── rfc_validator.py       ← Portal SAT: validación de RFC
│           └── ine_validator.py       ← Lista Nominal del INE (con reCAPTCHA v2)
│
├── logs/                              ← Logs generados en runtime (gitignore)
├── screenshots/                       ← Screenshots de evidencia de portales (gitignore)
├── reports/                           ← Reportes Excel/CSV de portales (gitignore)
└── scripts/                           ← Scripts auxiliares (vacío por ahora)
```

---

## Flujo de ejecución

Cuando ejecutas `python -m cross_validation validar-rfc SCX190531824 --portales`, pasa esto:

```
1.  main.py (CLI)
    └── Parsea argumentos → llama a _cli_validar_rfc()

2.  data_loader.py
    └── Conecta a PostgreSQL → carga todos los documentos de la empresa
    └── Devuelve un ExpedienteEmpresa (con todos los JSONs extraídos por Dakota)

3.  engine.py → validar_empresa()
    ├── Ejecuta bloques 1-9 en secuencia:
    │   ├── bloque1 → ¿RFC coincide? ¿Razón social coincide?
    │   ├── bloque2 → ¿Domicilio coincide?
    │   ├── bloque3 → ¿Documentos vigentes?
    │   ├── bloque4 → ¿Apoderado correcto?
    │   ├── bloque5 → ¿Estructura accionaria completa?
    │   ├── bloque6 → ¿Datos bancarios correctos?
    │   ├── bloque7 → ¿Datos notariales consistentes?
    │   ├── bloque8 → ¿Extracción confiable?
    │   └── bloque9 → ¿Expediente completo?
    │
    ├── Si --portales: ejecuta bloque 10
    │   └── bloque10_portales.py
    │       ├── FIELValidator → abre navegador → portal SAT → CAPTCHA → resultado
    │       ├── RFCValidator  → abre navegador → portal SAT → CAPTCHA → resultado
    │       └── INEValidator  → abre navegador → lista nominal INE → reCAPTCHA → resultado
    │
    ├── Calcula dictamen (APROBADO / RECHAZADO)
    ├── Genera recomendaciones
    └── Persiste resultado en tabla validaciones_cruzadas (auto-save)

4.  report_generator.py
    └── Convierte ReporteValidacion → texto con emojis, tablas, secciones

5.  main.py
    └── Imprime o guarda en archivo
```

---

## Los 10 bloques de validación

| Bloque | Nombre | Qué valida |
|--------|--------|------------|
| 1 | Identidad Corporativa | RFC, razón social y estatus fiscal consistentes entre todos los docs |
| 2 | Domicilio | CP y dirección: CSF vs comprobante vs acta constitutiva |
| 3 | Vigencia | FIEL no vencida, INE vigente, CSF/domicilio/edo. cuenta < 3 meses |
| 4 | Apoderado Legal | INE = poder notarial, apoderado aparece en estructura, facultades |
| 5 | Estructura Societaria | Accionistas suman 100%, evolución accionaria, capital social |
| 6 | Datos Bancarios | Titular del estado de cuenta = empresa, CLABE válida (18 dígitos) |
| 7 | Consistencia Notarial | Notaría, folio mercantil, inscripción en Registro Público |
| 8 | Calidad de Extracción | Confiabilidad de campos > 70%, campos faltantes, parsing nombres |
| 9 | Completitud | ¿Están los 7 docs mínimos? ¿Reforma, INE reverso, docs PagaTodo? |
| 10 | Portales Gubernamentales | FIEL vigente (SAT), RFC válido (SAT), INE en Lista Nominal |

---

## Modelos de datos clave

### `Hallazgo` (schemas.py)
Un resultado individual de una validación. Campos importantes:
- `codigo`: Identificador como `V1.1`, `V4.3`, `V10.2`
- `pasa`: `True` (✅), `False` (❌), `None` (⚪ no aplica)
- `severidad`: `CRITICA`, `MEDIA`, `INFORMATIVA`
- `mensaje`: Texto descriptivo del resultado

### `ExpedienteEmpresa` (schemas.py)
Los datos de una empresa cargados de PostgreSQL:
- `rfc`, `razon_social`
- `documentos`: diccionario donde la llave es el tipo (ej. `"csf"`, `"fiel"`) y el valor es el JSON con los datos extraídos

### `ReporteValidacion` (schemas.py)
El resultado final: lista de hallazgos, dictamen, conteos, recomendaciones.

### `ValidacionCruzadaDB` (schemas.py)
Modelo Pydantic que mapea una fila de la tabla `validaciones_cruzadas`:
- `id`: UUID del registro
- `empresa_id`, `rfc`, `razon_social`: identificación de la empresa
- `dictamen`: resultado (`APROBADO`, `APROBADO_CON_OBSERVACIONES`, `RECHAZADO`)
- `total_pasan`, `total_criticos`, `total_medios`, `total_informativos`: conteos
- `hallazgos`, `recomendaciones`, `documentos_presentes`: datos JSONB
- `portales_ejecutados`: si se consultaron portales gubernamentales
- `modulos_portales`: detalle de módulos ejecutados (JSONB, nullable)
- `created_at`: timestamp de creación

---

## Portales gubernamentales (Bloque 10)

El bloque 10 es especial porque **abre un navegador real** (Playwright) para consultar portales del gobierno mexicano:

| Módulo | Portal | Qué consulta | Desafío |
|--------|--------|-------------|---------|
| FIEL | SAT Certificados | Vigencia de e.firma por RFC + serie | CAPTCHA de imagen |
| RFC | SAT Validación RFC | ¿RFC existe y está activo? | CAPTCHA de imagen |
| INE | Lista Nominal INE | ¿La INE está en el padrón electoral? | reCAPTCHA v2 + Cloudflare |

### Estrategia de CAPTCHAs
Configurado vía `PORTAL_CAPTCHA_STRATEGY` en `.env`:

- **`cascada`** (recomendada): Azure Computer Vision → GPT-4o → Tesseract (para CAPTCHA de imagen del SAT)
- **`manual`**: Pausa y espera input del usuario

El validador de INE usa `playwright-stealth` para evadir Cloudflare Turnstile automáticamente.

---

## Configuración

El archivo `.env` se busca automáticamente en varias rutas (ver `core/config.py`). Variables importantes:

```env
# Base de datos PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=tu_password

# Portales (opcionales, solo si usas --portales)
PORTAL_CAPTCHA_STRATEGY=cascada

# Azure Computer Vision (para CAPTCHAs de imagen)
AZURE_CV_ENDPOINT=https://tu-recurso.cognitiveservices.azure.com
AZURE_CV_KEY=tu_clave

# Azure OpenAI GPT-4o (fallback para CAPTCHAs)
AZURE_OPENAI_ENDPOINT=https://tu-recurso.openai.azure.com/
AZURE_OPENAI_KEY=tu_clave
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

---

## Cómo ejecutarlo

### Requisitos previos
- **Python 3.12+**
- **PostgreSQL** con la base de datos KYB (creada por Dakota)
- **Playwright** instalado (solo si usas `--portales`)

### Instalación

```bash
# Desde la carpeta Colorado/
pip install -e cross_validation/

# Si vas a usar portales, instala también:
pip install -e "cross_validation/[portales]"
playwright install chromium
```

> **Nota**: En el entorno actual, todos los agentes comparten el venv de Dakota (`Dakota/kyb_review/.venv`).

### Comandos CLI

```bash
# Listar empresas en la BD
python -m cross_validation listar

# Validar una empresa por RFC (sin portales)
python -m cross_validation validar-rfc ASO110413438

# Validar con portales gubernamentales
python -m cross_validation validar-rfc ASO110413438 --portales

# Validar con portales y navegador visible (para debug)
python -m cross_validation validar-rfc ASO110413438 --portales --visible

# Guardar reporte en archivo
python -m cross_validation validar-rfc ASO110413438 --portales -o reporte.txt

# Validar TODAS las empresas
python -m cross_validation validar-todas --portales -o resumen.txt

# Solo portales específicos (ine, fiel, rfc)
python -m cross_validation validar-rfc SCX190531824 --portales --modulos ine,rfc
```

### Servidor API

```bash
python -m cross_validation server
# → http://localhost:8011/docs (Swagger UI)
```

Endpoints disponibles:
- `GET /api/v1/validacion/empresas` — Lista empresas
- `POST /api/v1/validacion/empresa/{id}` — Validar empresa (JSON)
- `POST /api/v1/validacion/empresa/{id}/reporte` — Validar empresa (texto)
- `POST /api/v1/validacion/todas` — Validar todas (JSON)
- `GET /api/v1/validacion/historial` — Historial de validaciones (filtros: `empresa_id`, `rfc`, `dictamen`, `limit`, `offset`)
- `GET /api/v1/validacion/historial/{id}` — Detalle de una validación por UUID
- `GET /api/v1/validacion/empresa/{id}/ultima` — Última validación de una empresa

---

## Relación con Dakota y el Orquestrator

```
Orquestrador (Coordinador)             Dakota (Extracción)              Colorado (Validación Cruzada)
┌──────────────────────────┐           ┌──────────────────────┐          ┌──────────────────────────────┐
│ Recibe archivos del      │   HTTP    │ Recibe PDF/imagen    │          │ Lee los JSONs de la BD       │
│ usuario                  │──────────▶│ Extrae datos GPT-4o  │          │ Cruza información            │
│ Coordina flujo completo  │           │ Guarda en PostgreSQL │   HTTP   │ Valida en portales (web)     │
│                          │──────────────────────────────────────────▶│ Persiste en validaciones_    │
│ Puerto 8002              │           │  Puerto 8010         │          │   cruzadas (auto-save)       │
│                          │◀──────────│   tabla: documentos  │          │ Puerto 8011                  │
│                          │◀──────────────────────────────────────────│ Genera reporte + dictamen    │
└──────────────────────────┘           └──────────┬───────────┘          └──────────────┬───────────────┘
                                                  │                                     │
                                                  ▼                                     ▼
                                       ┌──────────────────────────────────────────────────┐
                                       │               PostgreSQL (kyb)                   │
                                       │  empresas · documentos · validaciones_cruzadas   │
                                       │  analisis_pld · dictamenes_pld ·                 │
                                       │  dictamenes_legales · pipeline_resultados        │
                                       └──────────────────────────────────────────────────┘
```

Los cinco agentes comparten la **misma base de datos PostgreSQL** (`kyb`):
- **Dakota** escribe en las tablas `empresas` y `documentos` (datos extraídos de PDFs)
- **Colorado** lee de `documentos`, valida y escribe en `validaciones_cruzadas`
- **Arizona** lee de `documentos` + `validaciones_cruzadas`, escribe en `analisis_pld` y `dictamenes_pld`
- **Nevada** lee de todas las tablas anteriores, escribe en `dictamenes_legales`
- **Orquestrador** registra progreso en `pipeline_resultados` y coordina vía HTTP

### Flujo automático (recomendado)

El **Orquestrator** (puerto 8002) coordina todo automáticamente:
1. Recibe el archivo del usuario
2. Lo envía a Dakota para extracción + persistencia
3. Llama a Colorado para validación cruzada
4. Retorna respuesta unificada

```powershell
# Solo necesitas subir el archivo al Orquestrador
curl.exe -X POST http://localhost:8002/api/v1/pipeline/process `
  -F "file=@acta_constitutiva.pdf" -F "rfc=ACA230223IA7" -F "doc_type=acta_constitutiva"
```

### Flujo manual (uso directo)

También puedes usar Colorado directamente si los documentos ya están en la BD:

```powershell
# Validar empresa por ID
curl.exe -X POST http://localhost:8011/api/v1/validacion/empresa/{empresa_id}
```

Colorado **no procesa documentos originales** (PDFs/imágenes). Solo lee los datos que Dakota ya extrajo y guardó en la tabla `documentos` de PostgreSQL.

---

## Dictamen

El motor (`engine.py`) calcula el dictamen así:

| Resultado | Condición |
|-----------|-----------|
| ✅ **APROBADO** | 0 hallazgos críticos y 0 medios |
| ⚠️ **APROBADO CON OBSERVACIONES** | 0 críticos pero hay medios |
| ❌ **RECHAZADO** | 1 o más hallazgos críticos |

---

## Persistencia en PostgreSQL

Cada validación se **guarda automáticamente** en la tabla `validaciones_cruzadas`. Esto permite:

- Consultar historiales de validación por empresa o RFC
- Comparar dictámenes entre ejecuciones (auditoría)
- Que otros agentes (ej. Accionaria) lean los resultados sin re-ejecutar
- Exponer resultados vía API REST

### Tabla `validaciones_cruzadas`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | UUID | Clave primaria (generada automáticamente) |
| `empresa_id` | UUID | FK → tabla `empresas` |
| `rfc` | VARCHAR(13) | RFC de la empresa |
| `razon_social` | VARCHAR(200) | Razón social |
| `dictamen` | VARCHAR(30) | APROBADO / APROBADO_CON_OBSERVACIONES / RECHAZADO |
| `total_pasan` | INT | Hallazgos que pasan |
| `total_criticos` | INT | Hallazgos críticos |
| `total_medios` | INT | Hallazgos medios |
| `total_informativos` | INT | Hallazgos informativos |
| `hallazgos` | JSONB | Lista completa de hallazgos (serializada) |
| `recomendaciones` | JSONB | Lista de recomendaciones |
| `documentos_presentes` | JSONB | Tipos de documento en el expediente |
| `portales_ejecutados` | BOOLEAN | Si se corrieron portales gubernamentales |
| `modulos_portales` | JSONB | Detalle de módulos (ine, fiel, rfc) — nullable |
| `created_at` | TIMESTAMPTZ | Fecha/hora de la validación |

**Índices:** empresa_id, rfc, dictamen, created_at, hallazgos (GIN para consultas JSONB).

### Migración Alembic

La tabla se crea con la migración `0004_crear_tabla_validaciones_cruzadas` ubicada en `Dakota/kyb_review/alembic/versions/`. Después de las migraciones existentes de Dakota:

```
0001 → 0002 → 0003 → 0004 (validaciones_cruzadas)
```

### Servicio de persistencia

En `services/persistence.py`:

| Función | Descripción |
|---------|-------------|
| `guardar_validacion(reporte, ...)` | Inserta un registro después de cada validación |
| `obtener_validacion(uuid)` | Busca por ID |
| `obtener_ultima_validacion(empresa_id)` | La más reciente de una empresa |
| `listar_validaciones(filtros)` | Lista con filtros opcionales |
| `contar_validaciones(filtros)` | Conteo para paginación |

La persistencia es **no bloqueante**: si falla (ej. BD desconectada), el motor registra un warning y continúa normalmente.

---

## Carpetas de runtime

Estas carpetas se crean automáticamente y **no deben subirse a git**:

| Carpeta | Contenido |
|---------|-----------|
| `cross_validation/logs/` | Logs del portal_validator (un archivo por ejecución) |
| `cross_validation/screenshots/` | Capturas PNG de evidencia: CAPTCHAs, resultados, errores |
| `cross_validation/reports/` | Reportes Excel/CSV generados por el comando legacy `validar-portales` |
