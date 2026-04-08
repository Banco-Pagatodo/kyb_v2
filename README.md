# KYB Document Review — Plataforma Multi-Agente

> Python 3.12+ · FastAPI · PostgreSQL · Azure AI

Plataforma de **Know Your Business** para automatización del proceso de revisión documental de personas morales en el sector bancario mexicano. Compuesta por 5 microservicios especializados que ejecutan extracción OCR, validación cruzada, análisis PLD/AML y dictamen jurídico.

**Marco regulatorio:** DCG Art.115, CFF Art.32-B Ter, LFPIORPI 2025.

---

## Arquitectura

```
                     ┌─────────────────┐
                     │   DemoUI (8501) │  Streamlit
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │ Orquestador     │  Pipeline coordinator (8002)
                     │ retry + circuit │
                     │ breaker         │
                     └──┬──┬──┬──┬────┘
                        │  │  │  │
          ┌─────────────┘  │  │  └─────────────┐
          ▼                ▼  ▼                 ▼
   ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
   │  Dakota    │  │ Colorado │  │ Arizona  │  │ Nevada   │
   │  (8010)    │  │  (8011)  │  │  (8012)  │  │  (8013)  │
   │ OCR + LLM  │  │ 11 bloq. │  │ 5 etapas │  │ 9 reglas │
   └─────┬──────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │              │              │              │
         │         SAT/INE        SQL Server          │
         │         Playwright     (listas negras)     │
         │              │              │              │
         └──────────────┴──────┬───────┴──────────────┘
                               │
                        PostgreSQL (kyb)
                          9 tablas
```

**Flujo del pipeline:**

```
PDF/imagen + RFC
      │
      ▼
1. DAKOTA ──────► OCR (Azure DI) + extracción (GPT-4o) + persistencia
      │
      ▼
2. COLORADO ───► 11 bloques de validación cruzada + portales gubernamentales
      │            Si RECHAZADO → pipeline se detiene
      ▼
3. ARIZONA ────► Completitud → Screening → Estructura accionaria → MER → Dictamen PLD
      │
      ▼
4. NEVADA ─────► 9 reglas deterministas + LLM → Dictamen Jurídico DJ-1
      │
      ▼
   Resultado agregado (4 agentes)
```

---

## Agentes

| Agente | Puerto | Versión | Paquete | Responsabilidad |
|--------|--------|---------|---------|-----------------|
| **Dakota** | 8010 | 1.5.0 | `kyb` | Extracción OCR con Azure Document Intelligence + GPT-4o. Persistencia de documentos |
| **Colorado** | 8011 | 1.3.0 | `cross-validation` | Validación cruzada (11 bloques) + scraping de portales SAT/INE |
| **Arizona** | 8012 | 2.4.0 | `arizona` | Análisis PLD/AML: completitud, screening, estructura accionaria, MER PLD/FT, dictamen |
| **Nevada** | 8013 | 1.0.0 | `nevada` | Dictamen Jurídico DJ-1 con motor de 9 reglas deterministas + LLM |
| **Orquestador** | 8002 | 2.0.0 | `orquestrator` | Coordinación secuencial del pipeline con retry y circuit breaker |
| **DemoUI** | 8501 | 2.4.0 | — | Panel Streamlit para demostración interactiva |

---

## Dakota — Extracción OCR + Persistencia

**API Prefix:** `/kyb/api/v1.0.0`

Recibe documentos PDF/imagen, extrae datos vía OCR (Azure Document Intelligence) + LLM (GPT-4o), valida individualmente y persiste en PostgreSQL.

### Pipeline de extracción

```
PDF/imagen → Guardrails (MIME, tamaño) → Azure DI (texto + tablas)
→ Document Identifier (4 señales) → GPT-4o (extracción por tipo)
→ Validador individual (vigencia, campos requeridos) → PostgreSQL
```

**Document Identifier** clasifica el tipo de documento con 4 señales: keywords, estructura, fingerprint, semántica LLM. Cada campo extraído incluye un score de `confiabilidad: 0.0–1.0`.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/docs/{tipo}` | Extrae documento (multipart). `?rfc=` activa auto-persistencia |
| `POST` | `/docs/import/{doc_type}` | Importa JSON pre-extraído |
| `POST` | `/onboarding/review` | Revisión unificada → APPROVED / REVIEW_REQUIRED / REJECTED |
| `POST` | `/empresas` | Crear empresa |
| `GET` | `/empresas/{rfc}` | Consultar empresa + documentos |
| `GET` | `/empresas` | Listar empresas |
| `GET` | `/docs/metrics` | Métricas de uso y costos |
| `GET` | `/health` | Health check |
| `GET` | `/health/ready` | Readiness check |

### Tipos de documento soportados (12)

| Clave | Documento |
|-------|-----------|
| `csf` | Constancia de Situación Fiscal |
| `fiel` | Firma Electrónica Avanzada (FIEL) |
| `acta_constitutiva` | Acta Constitutiva |
| `poder_notarial` | Poder Notarial |
| `reforma_estatutos` | Reforma de Estatutos |
| `estado_cuenta` | Estado de Cuenta Bancario |
| `domicilio` | Comprobante de Domicilio (empresa) |
| `ine` | INE del Representante Legal (frente) |
| `ine_reverso` | INE del Representante Legal (reverso) |
| `ine_propietario_real` | INE del Propietario Real |
| `domicilio_rl` | Comprobante de Domicilio del RL |
| `domicilio_propietario_real` | Comprobante de Domicilio del Propietario Real |

### Tablas

| Tabla | Columnas clave | Propósito |
|-------|----------------|-----------|
| `empresas` | id (UUID), rfc, razon_social, fecha_registro | Registro de empresas |
| `documentos` | id, empresa_id (FK), doc_type, datos_extraidos (JSONB), confiabilidad | Datos OCR extraídos |

### Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `DI_ENDPOINT` | Azure Document Intelligence endpoint |
| `DI_KEY` | Azure DI API key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_DEPLOYMENT_NAME` | Deployment GPT-4o (default: `gpt-4o`) |
| `DATABASE_URL` | PostgreSQL connection string |
| `API_KEY` | API key de autenticación (obligatoria) |
| `ENVIRONMENT` | `development` / `production` |
| `RATE_LIMIT_REQUESTS` | Máx. requests/minuto en producción (default: 60) |

---

## Colorado — Validación Cruzada

**API Prefix:** `/api/v1/validacion`

Valida consistencia entre documentos corporativos usando 11 bloques de validación + automatización de portales gubernamentales (SAT, INE) con Playwright.

### 11 Bloques de validación

| Bloque | Nombre | Qué valida | Severidad |
|--------|--------|------------|-----------|
| 1 | Identidad Corporativa | RFC, razón social, estatus fiscal entre documentos | CRÍTICA |
| 2 | Domicilio | CP + dirección: CSF vs comprobante vs acta | CRÍTICA/MEDIA |
| 3 | Vigencia | FIEL no expirada, INE vigente, CSF/domicilio/estado de cuenta < 3 meses | CRÍTICA/MEDIA |
| 4 | Apoderado Legal | INE = poder, representante en estructura, facultades | CRÍTICA |
| 5 | Estructura Societaria | Accionistas suman 100%, capital social, evolución | CRÍTICA/MEDIA |
| 5B | Reformas Estatutarias | Cronología de reformas, evolución de estructura | MEDIA |
| 6 | Datos Bancarios | Titular = empresa, CLABE válida (18 dígitos) | MEDIA |
| 7 | Consistencia Notarial | Notario, folio, inscripción en RPP | MEDIA |
| 8 | Calidad de Extracción | Confianza de campos > 70%, campos faltantes | INFORMATIVA |
| 9 | Completitud | 7 documentos mínimos presentes | CRÍTICA |
| 10 | Portales Gubernamentales | Vigencia FIEL (SAT), validación RFC (SAT), Lista Nominal INE | CRÍTICA |
| 11 | Comparación Manual vs OCR | Desviaciones entre formulario del usuario y extracción OCR | INFORMATIVA |

### Lógica de dictamen

| Dictamen | Condición |
|----------|-----------|
| **APROBADO** | 0 hallazgos críticos Y ≤2 medios |
| **APROBADO CON OBSERVACIONES** | 0 críticos Y >2 medios |
| **RECHAZADO** | ≥1 hallazgo crítico |

### Portales gubernamentales (Bloque 10)

| Módulo | Portal | Consulta | Reto |
|--------|--------|----------|------|
| FIEL | SAT Certificados | Vigencia e.firma por RFC + serie | CAPTCHA imagen |
| RFC | SAT Validación RF | RFC activo / no cancelado | CAPTCHA imagen |
| INE | Lista Nominal INE | INE en padrón electoral | reCAPTCHA v2 + Cloudflare |

**Estrategia CAPTCHA** (`PORTAL_CAPTCHA_STRATEGY`): `cascada` (Azure CV → GPT-4o → Tesseract) o `manual`.

Browser Chromium compartido entre los 3 validadores. Batch de 10 empresas ~30-40s.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/empresas` | Listar empresas |
| `POST` | `/empresa/{id}` | Validar empresa (JSON) |
| `POST` | `/empresa/{id}/reporte` | Validar + reporte texto |
| `POST` | `/todas` | Validar todas las empresas |
| `GET` | `/historial` | Historial de validaciones |
| `GET` | `/historial/{id}` | Detalle por UUID |
| `GET` | `/empresa/{id}/ultima` | Última validación |

### Tabla

| Tabla | Columnas clave | Propósito |
|-------|----------------|-----------|
| `validaciones_cruzadas` | id, empresa_id, dictamen, hallazgos (JSONB), portales_ejecutados, modulos_portales (JSONB) | Resultados de validación |

### Variables de entorno adicionales

| Variable | Descripción |
|----------|-------------|
| `PORTAL_CAPTCHA_STRATEGY` | `cascada` (recomendado) o `manual` |
| `AZURE_CV_ENDPOINT` | Azure Computer Vision (resolución CAPTCHA) |
| `AZURE_CV_KEY` | API key Computer Vision |

---

## Arizona — Análisis PLD/AML

**API Prefix:** `/api/v1/pld`

Análisis de Prevención de Lavado de Dinero en 5 etapas conforme a regulación bancaria mexicana. Incluye screening contra listas negras (UIF, OFAC, SAT 69-B), identificación de propietarios reales y cálculo de Matriz de Evaluación de Riesgos (MER) PLD/FT v7.0.

**Requiere VPN** para acceso a SQL Server (listas negras).

### 5 Etapas

#### Etapa 1 — Completitud documental

6 verificaciones secuenciales per Disposición 4ª, DCG Art.115:

| # | Verificación | Qué revisa |
|---|-------------|------------|
| 1 | Documentos requeridos | Presencia de acta, CSF, domicilio, poder, INE, FIEL |
| 2 | Datos obligatorios | Razón social, RFC, serie FIEL, giro, fecha constitución |
| 3 | Domicilio completo | Calle, número, colonia, CP, municipio, estado, país |
| 4 | Personas identificadas | Apoderados, representantes, accionistas, consejeros |
| 5 | Poder bancario | 32 keywords en facultades del poder ("abrir cuentas", "operaciones bancarias"...) |
| 6 | Validación cruzada | Resultado de los 10 bloques de Colorado |

**Veredicto:** COMPLETO (0 críticos) / PARCIAL (0 críticos, algunos menores) / INCOMPLETO (críticos presentes).

#### Etapa 2 — Screening contra listas negras

Para cada persona (razón social, apoderados, representantes, accionistas):

| Fuente | Tabla SQL Server | Impacto |
|--------|-----------------|---------|
| LPB (UIF) | CatPLD69BPerson | Suspensión inmediata + reporte 24h |
| Bloqueados (UIF) | CatPLDLockedPerson | Suspensión |
| Consolidada | TraPLDBlackListEntry | Bloqueo OFAC/ONU/GAFI |
| SAT 69-B EFOS | — | Alerta RED / posible rechazo |

**Sistema anti-homónimos** (puntaje 0–100):

| Puntaje | Nivel | Acción |
|---------|-------|--------|
| ≥90 | CONFIRMADO | Bloquear / rechazar |
| ≥70 | PROBABLE | Revisión manual urgente |
| ≥50 | POSIBLE | Verificación adicional |
| ≥30 | HOMÓNIMO | Posible falso positivo |
| <30 | Descartado | No se reporta |

#### Etapa 3 — Validación de datos cruzados

Lee resultados de Colorado: consistencia RF, domicilio, vigencia, poder, estructura, notarial, calidad y completitud.

#### Etapa 4 — Estructura accionaria + propietarios reales

- **Look-through / perforación de cadena**: si un accionista es PM, se perfora recursivamente hasta encontrar personas físicas (máx. 10 niveles, detección de ciclos)
- **Umbrales**: ≥25% (DCG) y ≥15% (CFF)
- **Cascada CNBV**: PF ≥25% → control efectivo → administrador único → consejo → persona designada
- **Alerta EA004**: accionista PM → alerta crítica → RECHAZADO. Requiere documentación look-through
- **Screening BC**: cada beneficiario controlador (≥25%) pasa screening completo de Etapa 2

#### Etapa 5 — MER PLD/FT v7.0

Matriz de Evaluación de Riesgos con arquitectura de 2 capas:

**Capa 1 — Determinista** (Python, reproducible):
- 15 factores calculados con catálogos estáticos + Excel CNBV
- `Puntaje_factor = Valor × Peso × 100`
- Factores transaccionales (7–12) sin datos → valores prudenciales + `dato_asumido=True`

**Capa 2 — LLM** (solo factores pendientes):
- Factor 4 (Actividad): RAG sobre Azure AI Search (`mer-pld-chunks`)
- Keywords alto riesgo → Grupo 3 (FACTORING, SOFOM, CRIPTO...)
- Keywords bajo riesgo → Grupo 1 (AGRÍCOLA, EDUCACIÓN, SALUD...)

**Clasificación final:**

| Rango | Grado | |
|-------|-------|-|
| 85–142 pts | BAJO | Verde |
| 143–199 pts | MEDIO | Amarillo |
| ≥200 pts | ALTO | Rojo |

Match en LPB/listas negras → fuerza ALTO automáticamente.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/empresas` | Lista empresas con estatus |
| `POST` | `/etapa1/{empresa_id}` | Completitud documental |
| `POST` | `/etapa1/{empresa_id}/reporte` | Reporte texto Etapa 1 |
| `POST` | `/etapa2/{empresa_id}` | Screening listas negras |
| `POST` | `/etapa2/{empresa_id}/reporte` | Reporte texto Etapa 2 |
| `GET` | `/etapa2/{empresa_id}/descargar` | Descargar reporte screening |
| `POST` | `/completo/{empresa_id}` | Pipeline PLD completo (Etapas 1–5 + Dictamen) |
| `POST` | `/reporte/{empresa_id}` | Reporte consolidado |
| `GET` | `/analisis/{empresa_id}` | Obtiene análisis PLD guardado |
| `GET` | `/dictamen/{empresa_id}` | Dictamen PLD/FT (JSON) |
| `GET` | `/dictamen/{empresa_id}/txt` | Dictamen PLD/FT (texto) |
| `GET` | `/health` | Health check |

### Dictamen PLD/FT (6 secciones)

Generado en dos formatos (JSON + texto plano):

1. Datos generales de la PM
2. Screening por rol (PM, accionistas, representantes)
3. Actividad, domicilio, estructura
4. Propietarios reales / beneficiarios controladores
5. Representantes + facultades del poder
6. Datos notariales, perfil transaccional, vigencia documental, conclusiones

### Tablas

| Tabla | Columnas clave | Propósito |
|-------|----------------|-----------|
| `analisis_pld` | id, empresa_id, etapa, dictamen, puntaje_mer, grado_riesgo, resultado_completo (JSONB) | Análisis completo |
| `dictamenes_pld` | id, empresa_id, dictamen_json (JSONB), dictamen_txt (TEXT), created_at | Reporte PLD/FT de 6 secciones |

---

## Nevada — Dictamen Jurídico DJ-1

**API Prefix:** `/api/v1/legal`

Genera el **Dictamen Jurídico DJ-1** (3 páginas) consolidando resultados de Dakota (extracción), Colorado (validación) y Arizona (PLD/AML) mediante 9 reglas deterministas + narrativa LLM.

### 9 Reglas deterministas

| # | Regla | Qué valida | Severidad si falla |
|---|-------|------------|-------------------|
| R1 | Denominación Social | Nombre de la empresa en acta y CSF | CRÍTICA / MEDIA |
| R2 | Datos de Constitución | Escritura, fecha, notario, número | CRÍTICA / MEDIA |
| R3 | Folio Mercantil Electrónico | Existencia de FME / RPP | MEDIA |
| R4 | Actividad / Giro | Objeto social o actividad económica | MEDIA |
| R5 | Tenencia Accionaria | Accionistas existen, porcentajes suman ~100% | CRÍTICA / MEDIA |
| R6 | Régimen de Administración | Administrador único o consejo identificado | MEDIA |
| R7 | Representante Legal | Poder notarial + INE del representante | CRÍTICA / MEDIA |
| R8 | Facultades para Firma | Keywords bancarios en facultades del poder | MEDIA / INFORMATIVA |
| R9 | Consistencia con PLD | Arizona sin hallazgos críticos | CRÍTICA / MEDIA |

### Lógica de dictamen

| Dictamen | Condición |
|----------|-----------|
| **FAVORABLE** | 0 reglas críticas fallidas Y ≤2 medias |
| **FAVORABLE CON CONDICIONES** | 0 críticas Y >2 medias |
| **NO FAVORABLE** | ≥1 regla crítica fallida |

### Score de confianza

| Componente | Peso | Fuente |
|-----------|------|--------|
| OCR Score | 50% | Promedio de `confiabilidad` de campos (Dakota) |
| Rules Score | 40% | % de 9 reglas aprobadas |
| LLM Bonus | 10% | 100% si LLM usado, 60% si solo determinista |

Niveles: ≥80 **ALTA** · 55–80 **MEDIA** · <55 **BAJA**

### Estructura del DJ-1

| Sección | Contenido |
|---------|-----------|
| 1 | Datos de escritura constitutiva (escritura, fecha, notario) |
| 2 | Última reforma de estatutos |
| 3 | Actividad / giro |
| 4 | Tenencia accionaria (tabla con %, tipo, bandera extranjero) |
| 5 | Régimen de administración |
| 6 | Representante(s) con facultades |
| 7 | Observaciones |
| — | Score de confianza + metadata de elaboración |

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/dictamen/{empresa_id}` | Generar dictamen DJ-1 |
| `GET` | `/dictamen/{empresa_id}` | Consultar último dictamen |
| `GET` | `/expediente/{empresa_id}` | Preview del expediente (sin generar) |
| `GET` | `/health` | Health check |

### Tabla

| Tabla | Columnas clave | Propósito |
|-------|----------------|-----------|
| `dictamenes_legales` | id, empresa_id, dictamen, dictamen_json (JSONB), dictamen_texto (TEXT), reglas_aplicadas (JSONB) | Dictamen Jurídico DJ-1 |

---

## Orquestador — Coordinador del Pipeline

**API Prefix:** `/api/v1/pipeline`

Coordina la ejecución secuencial Dakota → Colorado → Arizona → Nevada vía HTTP. Incluye retry con backoff exponencial (tenacity) y circuit breaker por agente.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/process` | Procesa documento individual (file + doc_type + rfc) |
| `POST` | `/expediente` | Procesa expediente completo (files + doc_types + rfc) |
| `GET` | `/status/{rfc}` | Estado del pipeline por RFC |
| `GET` | `/health` | Health check de todos los servicios |

### Resiliencia

| Mecanismo | Configuración |
|-----------|---------------|
| **Retry** | 3 intentos, backoff exponencial 1–10s (tenacity) |
| **Circuit Breaker** | 5 fallos consecutivos → circuito abierto 60s |
| **Timeouts** | 300s por agente (configurable) |
| **Fallback** | Si un agente falla, retorna resultado parcial |
| **Stop condition** | Colorado RECHAZADO → no ejecuta Arizona ni Nevada |

### Tabla

| Tabla | Columnas clave | Propósito |
|-------|----------------|-----------|
| `pipeline_resultados` | id, empresa_id, rfc, status_{dakota,colorado,arizona,nevada}, status_general, tiempo_total_ms | Tracking end-to-end |

---

## DemoUI — Panel Streamlit

**Puerto:** 8501

Dashboard interactivo para demostrar el pipeline completo. Funcionalidades:

- **Health check** en tiempo real de los 5 servicios
- **Carga de documentos** con selector de tipo y RFC
- **Progreso en vivo** paso a paso (Dakota → Colorado → Arizona → Nevada)
- **Resultados por agente**: JSON extraído, hallazgos, puntaje MER, DJ-1
- **Indicadores visuales** de dictamen y nivel de riesgo
- **Descarga** de reportes en `.txt` y `.json`

---

## Base de datos

PostgreSQL compartida (`kyb`) con 7 tablas principales:

| Tabla | Agente | Propósito |
|-------|--------|-----------|
| `empresas` | Dakota | Registro de empresas (RFC, razón social) |
| `documentos` | Dakota | Datos OCR extraídos (JSONB) |
| `validaciones_cruzadas` | Colorado | Resultados de validación (11 bloques) |
| `analisis_pld` | Arizona | Análisis PLD de 5 etapas |
| `dictamenes_pld` | Arizona | Dictamen PLD/FT (6 secciones) |
| `dictamenes_legales` | Nevada | Dictamen Jurídico DJ-1 |
| `pipeline_resultados` | Orquestador | Tracking del pipeline end-to-end |

**Migraciones** con Alembic (`Dakota/kyb_review/alembic/`):

```bash
cd Dakota/kyb_review && alembic upgrade head
```

---

## Inicio rápido

### Requisitos previos

- Python 3.12+
- PostgreSQL 15+
- Acceso a Azure (Document Intelligence, OpenAI, Computer Vision)
- VPN para listas negras PLD (Arizona — SQL Server)

### 1. Base de datos

```bash
createdb kyb
cd Dakota/kyb_review && alembic upgrade head
```

### 2. Instalar cada agente

```bash
cd Dakota/kyb_review && pip install -e . && cd ../..
cd Colorado/cross_validation && pip install -e . && cd ../..
cd Arizona/pld_agent && pip install -e . && cd ../..
cd Nevada/legal_agent && pip install -e . && cd ../..
cd Orquestrator && pip install -e . && cd ..
```

Colorado con portales (opcional):

```bash
cd Colorado/cross_validation && pip install -e ".[portales]" && cd ../..
playwright install chromium
```

### 3. Configurar variables de entorno

Cada agente requiere un archivo `.env` en su directorio:

```env
# Base de datos compartida (todos los agentes)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=<tu_password>

# Azure OpenAI (Dakota, Arizona, Nevada, Colorado)
AZURE_OPENAI_ENDPOINT=https://<recurso>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_DEPLOYMENT_NAME=gpt-4o

# Azure Document Intelligence (Dakota)
DI_ENDPOINT=https://<recurso>.cognitiveservices.azure.com
DI_KEY=<key>
```

Orquestador — URLs de servicios:

```env
DAKOTA_BASE_URL=http://localhost:8010
COLORADO_BASE_URL=http://localhost:8011
ARIZONA_BASE_URL=http://localhost:8012
NEVADA_BASE_URL=http://localhost:8013
```

### 4. Levantar los servicios

```bash
# Terminal 1 — Dakota
cd Dakota/kyb_review && uvicorn api.main:app --port 8010

# Terminal 2 — Colorado
cd Colorado/cross_validation && python -m cross_validation server

# Terminal 3 — Arizona
cd Arizona && uvicorn main:app --port 8012

# Terminal 4 — Nevada
cd Nevada/legal_agent && uvicorn main:app --port 8013

# Terminal 5 — Orquestador
cd Orquestrator && uvicorn app.main:app --port 8002

# Terminal 6 — DemoUI (opcional)
cd DemoUI && streamlit run app.py
```

---

## Estructura del repositorio

```
kyb_v2/
├── Dakota/kyb_review/         # Extracción OCR + persistencia
│   ├── api/                   #   FastAPI app, routers, controllers
│   │   ├── client/            #     Azure DI + Colorado client
│   │   ├── controller/        #     Lógica por tipo de documento
│   │   ├── db/                #     SQLAlchemy ORM + repositorio
│   │   ├── middleware/        #     Auth, guardrails, rate limit
│   │   ├── model/             #     Pydantic schemas por tipo
│   │   ├── router/            #     Endpoints REST
│   │   └── service/           #     OCR, GPT-4o, validación, métricas
│   ├── alembic/               #   Migraciones de BD
│   ├── docs/                  #   Arquitectura, guía dev, producción
│   └── tests/                 #   Tests unitarios + integración
│
├── Colorado/cross_validation/ # Validación cruzada
│   ├── api/                   #   Router REST
│   ├── core/                  #   Config + database
│   ├── models/                #   Pydantic schemas
│   └── services/              #   Motor de validación
│       ├── validators/        #     11 bloques (bloque1..bloque11)
│       └── portal_validator/  #     Playwright: SAT, INE, CAPTCHA
│
├── Arizona/pld_agent/         # PLD/AML + compliance
│   ├── api/                   #   Router PLD + MER
│   ├── core/                  #   Config, database, normalización
│   ├── models/                #   Schemas PLD, MER, dictamen
│   └── services/              #   5 etapas + MER + dictamen + persistencia
│
├── Nevada/legal_agent/        # Dictamen jurídico
│   ├── api/                   #   Router legal
│   ├── core/                  #   Config + database
│   ├── models/                #   Schemas DJ-1
│   ├── services/              #   9 reglas + generador + persistencia
│   └── knowledge/             #   Reglas de negocio + template DJ-1
│
├── Orquestrator/              # Coordinador del pipeline
│   ├── app/                   #   Pipeline, clients, resiliencia, router
│   └── tests/                 #   Tests unitarios
│
├── DemoUI/                    # Dashboard Streamlit
└── temp/                      # Scripts utilitarios y datos de prueba
```

## Stack tecnológico

| Capa | Tecnología |
|------|------------|
| Framework | FastAPI + Pydantic v2 |
| HTTP async | httpx + tenacity (retry) |
| Base de datos | PostgreSQL 16 + asyncpg + SQLAlchemy 2.0 |
| Migraciones | Alembic |
| OCR | Azure Document Intelligence |
| LLM | GPT-4o (Azure OpenAI) |
| RAG | Azure AI Search (índice `mer-pld-chunks`) |
| CAPTCHA | Azure Computer Vision + GPT-4o + Tesseract |
| Screening | SQL Server via pyodbc (listas negras UIF/OFAC/SAT) |
| Portales | Playwright + playwright-stealth (SAT, INE) |
| UI | Streamlit |