# Instrucciones de Setup — KYB Agents (Flujo Dakota)

> **Fecha:** 29 de marzo de 2026
> **Autor:** Equipo KYB
> **Objetivo:** Guía paso a paso para levantar todo el stack de servicios KYB.

---

## 1. Arquitectura General

El sistema son **5 microservicios + 1 UI web** que se ejecutan localmente:

```
Archivos (PDF/imagen) + RFC
        ↓
  ┌─────────────────┐
  │  DemoUI (8501)  │  ← Interfaz web (Streamlit)
  └───────┬─────────┘
          ↓
  ┌──────────────────────┐
  │ Orquestrador (8002)  │  ← Coordina todo el pipeline
  └───────┬──────────────┘
          ↓
  ┌───────▼──────────┐
  │  Dakota (8010)   │  ← OCR + Persistencia de documentos
  └───────┬──────────┘
          ↓
  ┌───────▼──────────┐
  │ Colorado (8011)  │  ← Validación cruzada
  └───────┬──────────┘
          ↓
  ┌───────▼──────────┐
  │ Arizona (8012)   │  ← PLD/AML + Compliance (scoring + dictamen)
  └───────┬──────────┘
          ↓
  ┌───────▼──────────┐
  │  Nevada (8013)   │  ← Dictamen Jurídico DJ-1
  └──────────────────┘
```

| Servicio | Puerto | Prefijo API | Tecnología |
|----------|--------|-------------|------------|
| **Dakota** | 8010 | `/kyb/api/v1.0.0` | FastAPI (venv propio) |
| **Colorado** | 8011 | `/api/v1/validacion` | FastAPI |
| **Arizona** | 8012 | `/api/v1/pld` y `/api/v1/compliance` | FastAPI |
| **Nevada** | 8013 | `/api/v1/legal` | FastAPI |
| **Orquestrador** | 8002 | `/api/v1/pipeline` | FastAPI |
| **DemoUI** | 8501 | — | Streamlit |

---

## 2. Requisitos Previos

### Software necesario

| Software | Versión mínima | Notas |
|----------|---------------|-------|
| **Python** | 3.12+ | Verificar con `python --version` |
| **PostgreSQL** | 16 | BD `kyb`, usuario `kyb_app` |
| **Git** | cualquiera | Para clonar el repo |

### Base de datos

La BD de PostgreSQL debe estar corriendo con la siguiente configuración:

- **Host:** `localhost`
- **Puerto:** `5432`
- **Base de datos:** `kyb`
- **Usuario:** `kyb_app`
- **Contraseña:** `kyb_secure_2026!`

Para verificar la conexión:

```powershell
$env:PGPASSWORD='kyb_secure_2026!'
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -h localhost -p 5432 -U kyb_app -d kyb -c "SELECT version();"
```

---

## 3. Estructura de Carpetas

```
Agents/                           ← Raíz del workspace
├── .venv/                        ← Entorno virtual compartido (Colorado, Arizona, Nevada, Orquestrador, DemoUI)
├── Agents_Dakota/                ← Orquestrador (flujo Dakota)
│   ├── .env                      ← Variables de entorno del orquestrador
│   ├── app/                      ← Código del orquestrador
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── clients.py
│   │   ├── pipeline.py
│   │   ├── router.py
│   │   ├── persistence.py
│   │   └── database.py
│   └── pyproject.toml
├── Dakota/kyb_review/            ← Servicio Dakota (tiene su PROPIO .venv)
│   ├── .venv/                    ← ⚠️ Entorno virtual SEPARADO
│   └── api/service/.env          ← Variables de entorno de Dakota
├── Colorado/cross_validation/    ← Servicio Colorado
├── Arizona/pld_agent/            ← Servicio Arizona
├── Nevada/legal_agent/           ← Servicio Nevada
└── DemoUI/                       ← Interfaz web Streamlit
    └── app.py
```

> **IMPORTANTE:** Dakota usa su **propio entorno virtual** en `Dakota/kyb_review/.venv`.
> Todos los demás servicios usan el `.venv` de la raíz del workspace (`Agents/.venv`).

---

## 4. Instalación del Entorno Virtual

### 4.1 Entorno principal (para Colorado, Arizona, Nevada, Orquestrador, DemoUI)

```powershell
cd "C:\...\Agents"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e Agents_Dakota
pip install -e Colorado/cross_validation
pip install -e Arizona/pld_agent
pip install -e Nevada/legal_agent
pip install streamlit httpx
```

### 4.2 Entorno de Dakota (separado)

```powershell
cd "C:\...\Agents\Dakota\kyb_review"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

---

## 5. Archivos .env

### 5.1 Orquestrador Dakota — `Agents_Dakota/.env`

```env
# URLs de los agentes downstream
DAKOTA_BASE_URL=http://localhost:8010
DAKOTA_API_KEY=dakota-kyb-dev-2026
COLORADO_BASE_URL=http://localhost:8011
ARIZONA_BASE_URL=http://localhost:8012
NEVADA_BASE_URL=http://localhost:8013

# Puerto del Orquestrator
ORQUESTRATOR_PORT=8002

# Timeouts HTTP (segundos)
DAKOTA_TIMEOUT=300
COLORADO_TIMEOUT=300
ARIZONA_TIMEOUT=120
NEVADA_TIMEOUT=120

# Base de datos PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=kyb_secure_2026!
```

### 5.2 Dakota — `Dakota/kyb_review/api/service/.env`

Este archivo ya existe y contiene las credenciales de Azure (Document Intelligence, OpenAI, etc.). Solo asegúrate de que contenga al final:

```env
API_KEY=dakota-kyb-dev-2026
```

> Sin esta línea, Dakota rechaza todas las peticiones con HTTP 401.

---

## 6. Cómo Levantar los Servicios (Paso a Paso)

Abre **6 terminales de PowerShell** (una por servicio). El orden importa: levanta Dakota primero porque los demás dependen de él.

### Terminal 1 — Dakota (puerto 8010)

```powershell
cd "C:\...\Agents\Dakota\kyb_review"
& .\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8010
```

> Nota: usa el `.venv` **de Dakota**, no el de la raíz.

### Terminal 2 — Colorado (puerto 8011)

```powershell
cd "C:\...\Agents\Colorado"
& "C:\...\Agents\.venv\Scripts\python.exe" -m cross_validation.main server --port 8011
```

### Terminal 3 — Arizona (puerto 8012)

```powershell
cd "C:\...\Agents\Arizona"
& "C:\...\Agents\.venv\Scripts\python.exe" -m uvicorn pld_agent.main:app --host 0.0.0.0 --port 8012
```

> **⚠️ IMPORTANTE:** El directorio de trabajo debe ser `Arizona/`, NO `Arizona/pld_agent/`. Si entras al subdirectorio, Python no encuentra el módulo.

### Terminal 4 — Nevada (puerto 8013)

```powershell
cd "C:\...\Agents\Nevada"
& "C:\...\Agents\.venv\Scripts\python.exe" -m uvicorn legal_agent.main:app --host 0.0.0.0 --port 8013
```

### Terminal 5 — Orquestrador Dakota (puerto 8002)

```powershell
cd "C:\...\Agents\Agents_Dakota"
& "C:\...\Agents\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8002
```

### Terminal 6 — DemoUI (puerto 8501)

```powershell
cd "C:\...\Agents\DemoUI"
& "C:\...\Agents\.venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
```

> Reemplaza `C:\...\Agents` con la ruta real del workspace, por ejemplo:
> `C:\Users\aperez\OneDrive - IBERTEL\AI Engineering\BPT\Proyectos\1. KYB\Agents`

---

## 7. Verificar que Todo Funciona

### 7.1 Verificación rápida por terminal

Ejecuta esto desde cualquier terminal con el `.venv` activado:

```powershell
python -c "
import httpx
checks = [
    ('Dakota',       'http://localhost:8010/kyb/api/v1.0.0/health', {'X-API-Key': 'dakota-kyb-dev-2026'}),
    ('Colorado',     'http://localhost:8011/api/v1/validacion/health', {}),
    ('Arizona',      'http://localhost:8012/api/v1/pld/health', {}),
    ('Nevada',       'http://localhost:8013/api/v1/legal/health', {}),
    ('Orquestrator', 'http://localhost:8002/api/v1/pipeline/health', {}),
    ('DemoUI',       'http://localhost:8501', {}),
]
for name, url, headers in checks:
    try:
        r = httpx.get(url, headers=headers, timeout=5)
        status = 'OK' if r.status_code == 200 else str(r.status_code)
        print(f'{name:15s} | {status}')
    except Exception as e:
        print(f'{name:15s} | ERROR: {e}')
"
```

Resultado esperado:

```
Dakota          | OK
Colorado        | OK
Arizona         | OK
Nevada          | OK
Orquestrator    | OK
DemoUI          | OK
```

### 7.2 Verificación desde la UI

1. Abre http://localhost:8501 en el navegador
2. En la **barra lateral izquierda** haz clic en "Verificar servicios"
3. Todos deben aparecer en verde

---

## 8. Cómo Usar DemoUI

### Pestaña "Expediente Completo"
1. Ingresa el **RFC** de la empresa
2. Sube los documentos requeridos (mínimo 3: CSF, Acta Constitutiva, INE)
3. Haz clic en "Procesar Expediente"
4. El sistema ejecuta: Dakota → Colorado → Arizona → Nevada
5. Al terminar muestra dictámenes y permite descargar reportes

### Pestaña "Documento Individual"
1. Selecciona el tipo de documento
2. Sube el archivo PDF/imagen
3. Ingresa el RFC
4. Dakota extrae la información y la muestra en JSON
5. Puedes ejecutar pasos adicionales (validación, PLD, etc.) con los botones

### Pestaña "Consultar por RFC"
- Consulta empresas ya procesadas sin necesidad de re-subir archivos

---

## 9. Solución de Problemas Comunes

| Problema | Causa | Solución |
|----------|-------|----------|
| **HTTP 401 en Dakota** | Falta el `API_KEY` en el `.env` de Dakota | Agregar `API_KEY=dakota-kyb-dev-2026` a `Dakota/kyb_review/api/service/.env` |
| **ModuleNotFoundError: pld_agent** | Directorio de trabajo incorrecto al levantar Arizona | Ejecutar desde `Arizona/`, no desde `Arizona/pld_agent/` |
| **streamlit: command not found** | Streamlit no está en el PATH del sistema | Usar la ruta completa: `& .venv\Scripts\python.exe -m streamlit run app.py` |
| **Port already in use** | Un servicio anterior sigue corriendo | Matar el proceso: `Get-NetTCPConnection -LocalPort XXXX \| Select -First 1 \| % { Stop-Process -Id $_.OwningProcess -Force }` |
| **Dakota no extrae información** | DemoUI llama a Dakota sin header `X-API-Key` | Verificar que `DAKOTA_API_KEY` esté configurado en DemoUI (`app.py` línea 28) |
| **Orquestrador dice "Dakota no retornó resultado"** | El Orquestrador no envía `X-API-Key` | Verificar `DAKOTA_API_KEY` en `Agents_Dakota/.env` y reiniciar el servicio |
| **Error de conexión a BD** | PostgreSQL no está corriendo o credenciales incorrectas | Verificar con `psql` que la BD `kyb` existe y el usuario `kyb_app` tiene acceso |

### Cómo matar un proceso en un puerto específico

```powershell
# Ejemplo: liberar el puerto 8010
$proc = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proc) { Stop-Process -Id $proc.OwningProcess -Force; "Killed" } else { "Free" }
```

### Matar todos los servicios de golpe

```powershell
@(8010, 8011, 8012, 8013, 8002, 8501) | ForEach-Object {
    $port = $_
    $proc = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc) { Stop-Process -Id $proc.OwningProcess -Force; "Killed port $port" }
    else { "Port $port free" }
}
```

---

## 10. Documentación Swagger de cada servicio

Cada servicio expone su documentación interactiva en `/docs`:

| Servicio | URL Swagger |
|----------|-------------|
| Dakota | http://localhost:8010/docs |
| Colorado | http://localhost:8011/docs |
| Arizona | http://localhost:8012/docs |
| Nevada | http://localhost:8013/docs |
| Orquestrador | http://localhost:8002/docs |

---

## 11. Notas Técnicas

- **Python 3.12+** es requerido (el proyecto usa `type[str]` hints y otras features 3.12).
- **Timeout por defecto:** 600 segundos (10 min) en DemoUI para expedientes completos.
- **DemoUI no tiene base de datos propia** — toda la persistencia va a través de Dakota.
- **Circuit breaker:** El orquestrador tiene protección automática: si un servicio falla 5 veces consecutivas, deja de llamarlo por 60 segundos.
- **Retry:** Reintentos automáticos con exponential backoff (3 intentos, espera 1-10 segundos).
