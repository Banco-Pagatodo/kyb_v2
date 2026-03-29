# Dakota — Agente de Extracción y Persistencia KYB

> **Versión**: 1.5.0  
> **Última actualización**: 27 de marzo de 2026

Dakota es el agente principal del sistema KYB. Recibe documentos en PDF/imagen, extrae sus datos mediante OCR (Azure Document Intelligence) + LLM (Azure OpenAI GPT-4o), los valida individualmente y los persiste en PostgreSQL.

## Arquitectura Multi-Agente

Dakota forma parte de un sistema de **5 servicios independientes**:

| Agente | Puerto | Responsabilidad | Directorio |
|--------|--------|----------------|------------|
| **Dakota** | 8010 | Extracción + Validación individual + Persistencia | `Dakota/kyb_review/` |
| **Colorado** | 8011 | Validación cruzada + Portales gubernamentales | `Colorado/cross_validation/` |
| **Arizona** | 8012 | PLD/AML: completitud, screening, MER, dictamen PLD/FT | `Arizona/pld_agent/` |
| **Nevada** | 8013 | Dictamen Jurídico DJ-1 (reglas + LLM narrativo) | `Nevada/legal_agent/` |
| **Orquestrador** | 8002 | Coordinación del pipeline completo | `Orquestrator/` |

```
                        ┌──────────────────┐
                        │   Orquestrador   │
                        │   Puerto 8002    │
                        └─────┬──────┬─────┘
                    archivo   │      │  empresa_id
                    + rfc     │      │
                  ┌───────────▼┐   ┌▼────────────┐
                  │   Dakota   │   │  Colorado    │
                  │   :8010    │   │  :8011       │
                  └──────┬─────┘   └──────┬───────┘
                         │ ┌──────────────┤
                    ┌────▼─▼──────────────▼────┐
                    │      PostgreSQL (kyb)     │
                    │  empresas · documentos ·  │
                    │  validaciones_cruzadas ·  │
                    │  analisis_pld ·            │
                    │  dictamenes_legales       │
                    └──────────────────────────┘
```

## Tipos de Documento Soportados

| Tipo | Endpoint | Descripción |
|------|----------|-------------|
| Constancia de Situación Fiscal | `POST /docs/csf` | RFC, régimen, domicilio fiscal |
| Acta Constitutiva | `POST /docs/acta_constitutiva` | Datos societarios, estructura accionaria |
| Poder Notarial | `POST /docs/poder_notarial` | Representante legal, facultades |
| Reforma de Estatutos | `POST /docs/reforma_estatutos` | Modificaciones estatutarias |
| INE (frente) | `POST /docs/ine` | Datos del representante legal |
| INE (reverso) | `POST /docs/ine_reverso` | Dirección del representante |
| FIEL | `POST /docs/fiel` | Firma electrónica avanzada |
| Estado de Cuenta | `POST /docs/estado_cuenta` | Datos bancarios, CLABE |
| Comprobante de Domicilio | `POST /docs/domicilio` | Dirección verificable |
| INE Propietario Real | `POST /docs/ine_propietario_real` | INE del propietario real (PagaTodo) |
| Domicilio Rep. Legal | `POST /docs/domicilio_rl` | Comprobante de domicilio del representante legal (PagaTodo) |
| Domicilio Prop. Real | `POST /docs/domicilio_propietario_real` | Comprobante de domicilio del propietario real (PagaTodo) |

> Los 3 últimos tipos provienen del flujo **PagaTodo Hub** y se importan como JSON pre-extraído vía `POST /docs/import/{doc_type}` (sin OCR).

## Endpoints

### Documentos individuales

Todos bajo el prefijo `/kyb/api/v1.0.0/docs`. Requieren API Key (`X-API-Key`).

```
POST /kyb/api/v1.0.0/docs/{tipo}
  Body: multipart/form-data
    - file: archivo PDF o imagen
  Query params (opcionales):
    - rfc: RFC de la empresa (activa persistencia automática)
    - validate: bool (activa validación individual)
```

Cuando se envía `?rfc=ABC123456XX0`, Dakota automáticamente:
1. Crea o recupera la empresa en tabla `empresas`
2. Guarda el documento extraído en tabla `documentos`
3. Dispara la validación cruzada vía Colorado (fire-and-forget)

### Importación de OCR pre-extraído (PagaTodo Hub)

```
POST /kyb/api/v1.0.0/docs/import/{doc_type}
  Body: application/json
    {
      "datos_extraidos": { ... },
      "texto_ocr": "texto completo del documento",
      "archivo_procesado": "nombre_archivo.pdf"
    }
  Query params (obligatorios):
    - rfc: RFC de la empresa
```

Recibe datos OCR ya extraídos por un sistema externo (PagaTodo Hub). Ejecuta validación de campos y persistencia **sin invocar Azure DI ni OpenAI**. Soporta los 12 doc_types listados arriba.

### Onboarding (expediente completo)

```
POST /onboarding/review
  Body: multipart/form-data con múltiples archivos
  Retorna: veredicto APPROVED | REVIEW_REQUIRED | REJECTED
```

### Empresas

```
POST /kyb/api/v1.0.0/empresas          → Crear empresa
GET  /kyb/api/v1.0.0/empresas/{rfc}    → Consultar empresa + documentos
GET  /kyb/api/v1.0.0/empresas          → Listar empresas
```

### Health & Métricas

```
GET /kyb/api/v1.0.0/health             → Estado del servicio
GET /kyb/api/v1.0.0/health/ready       → Readiness check
GET /kyb/api/v1.0.0/docs/metrics       → Métricas de uso
GET /kyb/api/v1.0.0/docs/health/services → Estado de servicios externos
```

## Estructura del Proyecto

```
kyb_review/
├── api/
│   ├── main.py                    # Entry point (crea servidor)
│   ├── config.py                  # Puerto, prefijo, rutas temporales
│   ├── client/
│   │   ├── client.py              # Cliente HTTP para Azure DI
│   │   └── colorado_client.py     # Cliente HTTP para Colorado (fire-and-forget)
│   ├── controller/                # Lógica de procesamiento por documento
│   ├── db/
│   │   ├── models.py              # ORM: Empresa, Documento (SQLAlchemy 2.0)
│   │   ├── repository.py          # CRUD (upsert empresa, guardar documento)
│   │   └── session.py             # Pool de conexiones asyncpg
│   ├── middleware/
│   │   ├── auth.py                # API Key authentication
│   │   ├── guardrails.py          # Validaciones tempranas (MIME, tamaño)
│   │   ├── logging_middleware.py  # Request/response logging
│   │   └── rate_limit.py          # Rate limiting (producción)
│   ├── model/                     # Pydantic schemas por tipo de documento
│   ├── prompts/                   # Historial de prompts LLM
│   ├── router/
│   │   ├── docs.py                # Endpoints de extracción por documento
│   │   ├── empresas.py            # CRUD de empresas
│   │   ├── onboarding.py          # Flujo unificado de revisión
│   │   ├── validator.py           # Endpoints de validación
│   │   └── router.py              # Health checks, root
│   ├── server/
│   │   └── server.py              # create_server() — FastAPI + middleware
│   └── service/
│       ├── openai.py              # Extracción LLM (GPT-4o) — ~3000 líneas
│       ├── di.py                  # Azure Document Intelligence wrapper
│       ├── document_identifier.py # Clasificación de tipo de documento (4 señales)
│       ├── guardrails.py          # Validaciones pre-extracción
│       ├── validator.py           # Validación individual post-extracción
│       ├── metrics.py             # Sistema de métricas y costos
│       ├── orchestrator.py        # Orquestación interna (onboarding)
│       └── .env / .env.example    # Credenciales Azure
├── alembic/                       # Migraciones de base de datos
├── docs/                          # Documentación detallada
│   ├── ARCHITECTURE.md            # Arquitectura técnica del sistema
│   ├── DATABASE_GUIDE.md          # Guía de base de datos (principiante)
│   ├── DEVELOPERS_GUIDE.md        # Guía exhaustiva para desarrolladores
│   ├── PRODUCTION_CHECKLIST.md    # Checklist de despliegue
│   └── MIGRATION_GUIDE_v1.1.md   # Guía de migración
├── scripts/                       # Utilidades (deploy, cleanup, encoding)
├── tests/                         # Tests unitarios e integración
├── Test_Files/                    # Archivos de prueba por tipo de documento
├── CHANGELOG.md                   # Historial de cambios
└── temp/                          # Archivos temporales (JSON, raw)
```

## Requisitos Previos

- **Python 3.12+**
- **PostgreSQL 16** corriendo en `localhost:5432` (db: `kyb`, user: `kyb_app`)
- **Azure Document Intelligence** — endpoint y API key
- **Azure OpenAI** — endpoint, deployment `gpt-4o`, API key

## Instalación y Ejecución

### 1. Configurar credenciales

```bash
cp api/service/.env.example api/service/.env
# Editar .env con las credenciales reales de Azure
```

### 2. Iniciar el servicio

Desde la raíz del workspace (`Agents/`), usando el venv compartido:

```powershell
# Activar entorno virtual
.\.venv\Scripts\Activate.ps1

# Iniciar Dakota en puerto 8010
cd Dakota\kyb_review
uvicorn api.main:app --reload --port 8010
```

### 3. Verificar

```powershell
# Health check
Invoke-RestMethod http://localhost:8010/kyb/api/v1.0.0/health

# Swagger UI
# Abrir en navegador: http://localhost:8010/docs
```

### 4. Extraer un documento

```powershell
# Extracción simple (sin persistencia)
curl.exe -X POST http://localhost:8010/kyb/api/v1.0.0/docs/csf `
  -H "X-API-Key: development" `
  -F "file=@Test_Files\Constancia_Situacion_Fiscal\csf.pdf"

# Extracción con persistencia automática
curl.exe -X POST "http://localhost:8010/kyb/api/v1.0.0/docs/acta_constitutiva?rfc=ABC230223IA7" `
  -H "X-API-Key: development" `
  -F "file=@Test_Files\Acta_Constitutiva\acta.pdf"
```

## Flujo de Procesamiento

```
Archivo PDF/imagen
       │
       ▼
┌──────────────┐
│  Guardrails  │  ← Valida MIME type, tamaño, formato
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Azure DI    │  ← OCR: extrae texto + tablas + layout
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Document    │  ← ¿El documento es del tipo esperado?
│  Identifier  │    Sistema de 4 señales (keywords, estructura,
└──────┬───────┘    fingerprint, LLM semántico)
       │
       ▼
┌──────────────┐
│  GPT-4o      │  ← Extracción estructurada con prompt específico
│  Extractor   │    por tipo de documento
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Validator   │  ← Validación individual (vigencia, campos req.)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  PostgreSQL  │  ← Persiste empresa + documento (si rfc presente)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Colorado    │  ← Fire-and-forget: validación cruzada
│  (async)     │    (solo si hay empresa_id)
└──────────────┘
```

## Base de Datos

Dakota escribe en 2 tablas de PostgreSQL:

| Tabla | Descripción | Campos clave |
|-------|-------------|-------------|
| `empresas` | Registro por RFC | `id` (UUID), `rfc`, `razon_social`, `fecha_registro` |
| `documentos` | Documento extraído | `id`, `empresa_id` (FK), `doc_type`, `datos_extraidos` (JSONB) |

La tercera tabla (`validaciones_cruzadas`) es escrita por Colorado.

Ver [docs/DATABASE_GUIDE.md](docs/DATABASE_GUIDE.md) para la guía completa.

## Variables de Entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `DI_ENDPOINT` | Endpoint de Azure Document Intelligence | — |
| `DI_KEY` | API key de Azure DI | — |
| `AZURE_OPENAI_ENDPOINT` | Endpoint de Azure OpenAI | — |
| `AZURE_OPENAI_API_KEY` | API key de Azure OpenAI | — |
| `AZURE_DEPLOYMENT_NAME` | Nombre del deployment GPT-4o | `gpt-4o` |
| `DATABASE_URL` | URL de conexión PostgreSQL | `postgresql+asyncpg://kyb_app:...@localhost:5432/kyb` |
| `ENVIRONMENT` | Modo de ejecución | `development` |
| `API_KEY` | API key para autenticación | `development` |
| `CLEANUP_ON_STARTUP` | Limpiar temporales al iniciar | `true` |
| `RATE_LIMIT_REQUESTS` | Máx. requests/minuto (producción) | `60` |

## Tests

```powershell
cd Dakota\kyb_review
python -m pytest tests/ -v
```

Archivos de prueba disponibles en `Test_Files/` organizados por tipo de documento.

## Documentación Adicional

| Documento | Descripción |
|-----------|-------------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arquitectura técnica completa del sistema |
| [DATABASE_GUIDE.md](docs/DATABASE_GUIDE.md) | Guía de base de datos para principiantes |
| [DEVELOPERS_GUIDE.md](docs/DEVELOPERS_GUIDE.md) | Guía exhaustiva de código y patrones |
| [PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) | Checklist de despliegue a producción |
| [CHANGELOG.md](CHANGELOG.md) | Historial de cambios por versión |
