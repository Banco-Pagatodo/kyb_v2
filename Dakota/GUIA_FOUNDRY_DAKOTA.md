# Guía de Creación de Recursos en Azure AI Foundry para Dakota

> **Proyecto:** KYB (Know Your Business) — Servicio Dakota v1.3.1  
> **Fecha:** Marzo 2026  
> **Autor:** Equipo KYB

---

## Índice

1. [Visión General de Recursos](#1-visión-general-de-recursos)
2. [Prerequisitos](#2-prerequisitos)
3. [Recurso 1 — Azure AI Foundry Hub + Project](#3-recurso-1--azure-ai-foundry-hub--project)
4. [Recurso 2 — Azure Document Intelligence](#4-recurso-2--azure-document-intelligence)
5. [Recurso 3 — Azure OpenAI](#5-recurso-3--azure-openai)
6. [Recurso 4 — Azure Computer Vision](#6-recurso-4--azure-computer-vision)
7. [Recurso 5 — Azure Storage Account](#7-recurso-5--azure-storage-account)
8. [Recurso 6 — PostgreSQL](#8-recurso-6--postgresql)
9. [Entrenamiento de Modelos Custom (INE)](#9-entrenamiento-de-modelos-custom-ine)
10. [Configuración del `.env`](#10-configuración-del-env)
11. [Validación de Recursos](#11-validación-de-recursos)
12. [Estimación de Costos](#12-estimación-de-costos)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Visión General de Recursos

Dakota requiere **6 recursos de Azure** + **1 base de datos PostgreSQL** para operar:

```
┌─────────────────────────────────────────────────────────┐
│                   Azure AI Foundry Hub                  │
│                    (rg-kyb-foundry)                      │
│                                                         │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │  Document        │  │  Azure OpenAI                │  │
│  │  Intelligence    │  │  ┌────────────┐              │  │
│  │  ─────────────── │  │  │ gpt-4o     │ (chat/vision)│  │
│  │  • prebuilt-layout│  │  └────────────┘              │  │
│  │  • INE_Front *   │  │  ┌────────────┐              │  │
│  │  • INE_Back  *   │  │  │ text-      │ (embeddings) │  │
│  │    (* custom)    │  │  │ embedding- │              │  │
│  │                  │  │  │ ada-002    │              │  │
│  └─────────────────┘  │  └────────────┘              │  │
│                        └──────────────────────────────┘  │
│                                                         │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │ Computer Vision  │  │  Storage Account             │  │
│  │ (CAPTCHA OCR)   │  │  (Training Data)             │  │
│  └─────────────────┘  │  └── ine-training/           │  │
│                        └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

           ┌────────────────────┐
           │   PostgreSQL 16    │
           │   (localhost:5432) │
           │   db: kyb          │
           └────────────────────┘
```

### Tabla Resumen

| # | Recurso | SKU Recomendado | Región | Variable `.env` |
|---|---------|-----------------|--------|-----------------|
| 1 | AI Foundry Hub + Project | — | East US | — |
| 2 | Document Intelligence | S0 | East US | `DI_ENDPOINT`, `DI_KEY` |
| 3 | Azure OpenAI | S0 | East US | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` |
| 4 | Computer Vision | S1 | East US | `AZURE_CV_ENDPOINT`, `AZURE_CV_KEY` |
| 5 | Storage Account | Standard LRS | East US | `STORAGE_ACCOUNT`, `STORAGE_KEY` |
| 6 | PostgreSQL | Flexible Server B1ms | East US | `DB_HOST`, `DB_USER`, `DB_PASS` |

> **Región:** Todos los recursos deben estar en **East US** para minimizar latencia entre servicios.

---

## 2. Prerequisitos

### 2.1. Cuenta y suscripción Azure
- Suscripción Azure activa con permisos de **Contributor** o **Owner**
- Acceso aprobado a **Azure OpenAI Service** ([solicitar aquí](https://aka.ms/oai/access))
- Acceso a **Azure AI Foundry** ([portal](https://ai.azure.com))

### 2.2. Herramientas locales
```powershell
# Azure CLI
winget install Microsoft.AzureCLI

# Verificar
az --version
az login
```

### 2.3. Resource Group
```powershell
# Crear el grupo de recursos compartido
az group create --name rg-kyb-production --location eastus
```

---

## 3. Recurso 1 — Azure AI Foundry Hub + Project

El Hub es el contenedor central que agrupa todos los servicios de IA del proyecto.

### 3.1. Crear el Hub (Portal)

1. Ir a [ai.azure.com](https://ai.azure.com)
2. Click **Management** → **All hubs** → **+ New hub**
3. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Hub name | `hub-kyb-production` |
   | Subscription | *(tu suscripción)* |
   | Resource group | `rg-kyb-production` |
   | Location | `East US` |
   | Connect Azure AI Services | Crear nuevo o conectar existente |
   | Connect Azure OpenAI | Crear nuevo |

4. Click **Create**

### 3.2. Crear el Project dentro del Hub

1. Dentro del Hub → **+ New project**
2. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Project name | `proj-kyb-dakota` |
   | Hub | `hub-kyb-production` |
3. Click **Create**

### 3.3. Crear vía CLI (alternativa)

```powershell
# Instalar extensión ML
az extension add --name ml

# Crear Hub
az ml workspace create `
  --name hub-kyb-production `
  --resource-group rg-kyb-production `
  --kind hub `
  --location eastus

# Crear Project
az ml workspace create `
  --name proj-kyb-dakota `
  --resource-group rg-kyb-production `
  --kind project `
  --hub-id /subscriptions/<SUB_ID>/resourceGroups/rg-kyb-production/providers/Microsoft.MachineLearningServices/workspaces/hub-kyb-production
```

---

## 4. Recurso 2 — Azure Document Intelligence

Dakota usa Document Intelligence para OCR y extracción estructurada de **9 tipos de documentos**.

### 4.1. Modelos utilizados

| Modelo | Tipo | Documentos |
|--------|------|-----------|
| `prebuilt-layout` | Prebuilt (no requiere training) | Estado de cuenta, Acta constitutiva, Comprobante de domicilio, CSF, FIEL, Poder notarial, Reforma de estatutos |
| `INE_Front` | **Custom** (requiere training) | INE (frente) |
| `INE_Back` | **Custom** (requiere training) | INE (reverso) |

### 4.2. Crear el recurso (Portal)

1. Portal Azure → **Create a resource** → buscar **"Document Intelligence"**
2. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Name | `di-kyb-production` |
   | Subscription | *(tu suscripción)* |
   | Resource group | `rg-kyb-production` |
   | Region | **East US** |
   | Pricing tier | **S0** (Standard) |

3. Click **Review + Create** → **Create**

### 4.3. Crear vía CLI

```powershell
az cognitiveservices account create `
  --name di-kyb-production `
  --resource-group rg-kyb-production `
  --kind FormRecognizer `
  --sku S0 `
  --location eastus `
  --yes

# Obtener Endpoint y Key
az cognitiveservices account show `
  --name di-kyb-production `
  --resource-group rg-kyb-production `
  --query "properties.endpoint" -o tsv

az cognitiveservices account keys list `
  --name di-kyb-production `
  --resource-group rg-kyb-production `
  --query "key1" -o tsv
```

### 4.4. Configurar API Version

Dakota usa la API version **`2024-11-30`** (GA). El código en `di.py` construye las URL así:

```
POST {DI_ENDPOINT}/documentintelligence/documentModels/{model}:analyze?api-version=2024-11-30
```

### 4.5. Vincular a Foundry (opcional)

1. En [ai.azure.com](https://ai.azure.com) → Tu proyecto → **Management** → **Connected resources**
2. **+ New connection** → **Azure AI Document Intelligence**
3. Seleccionar `di-kyb-production`

---

## 5. Recurso 3 — Azure OpenAI

Dakota utiliza GPT-4o para extracción inteligente de datos y text-embedding-ada-002 para embeddings.

### 5.1. Deployments requeridos

| Deployment Name | Modelo Base | TPM Recomendado | Uso en Dakota |
|-----------------|-------------|-----------------|---------------|
| `gpt-4o` | GPT-4o (2024-08-06) | 80K–150K | Extracción de datos, clasificación de documentos, limpieza OCR, CAPTCHA vision |
| `text-embedding-ada-002` | text-embedding-ada-002 | 30K | Embeddings para búsqueda semántica |

### 5.2. Crear el recurso (Portal)

1. Portal Azure → **Create a resource** → buscar **"Azure OpenAI"**
2. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Name | `kyb-open-ai` |
   | Subscription | *(tu suscripción)* |
   | Resource group | `rg-kyb-production` |
   | Region | **East US** |
   | Pricing tier | **S0** |

3. Click **Review + Create** → **Create**

### 5.3. Crear Deployments

#### Opción A: Portal AI Foundry

1. [ai.azure.com](https://ai.azure.com) → Tu proyecto → **Deployments** → **+ Deploy model**
2. **Deploy base model** → Buscar **GPT-4o**
3. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Deployment name | `gpt-4o` |
   | Model version | `2024-08-06` (o más reciente) |
   | Deployment type | **Standard** |
   | Tokens per minute | `80000` (mínimo) |
   | Content filter | Default |

4. Repetir para **text-embedding-ada-002**:
   | Campo | Valor |
   |-------|-------|
   | Deployment name | `text-embedding-ada-002` |
   | Model version | `2` |
   | Deployment type | **Standard** |
   | Tokens per minute | `30000` |

#### Opción B: CLI

```powershell
# Deployment GPT-4o
az cognitiveservices account deployment create `
  --name kyb-open-ai `
  --resource-group rg-kyb-production `
  --deployment-name gpt-4o `
  --model-name gpt-4o `
  --model-version "2024-08-06" `
  --model-format OpenAI `
  --sku-capacity 80 `
  --sku-name Standard

# Deployment Embeddings
az cognitiveservices account deployment create `
  --name kyb-open-ai `
  --resource-group rg-kyb-production `
  --deployment-name text-embedding-ada-002 `
  --model-name text-embedding-ada-002 `
  --model-version "2" `
  --model-format OpenAI `
  --sku-capacity 30 `
  --sku-name Standard
```

### 5.4. Obtener credenciales

```powershell
# Endpoint
az cognitiveservices account show `
  --name kyb-open-ai `
  --resource-group rg-kyb-production `
  --query "properties.endpoint" -o tsv
# → https://kyb-open-ai.openai.azure.com/

# API Key
az cognitiveservices account keys list `
  --name kyb-open-ai `
  --resource-group rg-kyb-production `
  --query "key1" -o tsv
```

### 5.5. API Version utilizada

Dakota usa `api-version=2024-12-01-preview` configurada en:
```
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

El código inicializa el cliente así (LangChain):
```python
AzureChatOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_deployment=AZURE_DEPLOYMENT_NAME,   # "gpt-4o"
    api_version=AZURE_OPENAI_API_VERSION,
    api_key=AZURE_OPENAI_API_KEY,
    temperature=0
)
```

---

## 6. Recurso 4 — Azure Computer Vision

Usado por **Colorado** (no Dakota directamente) para OCR de CAPTCHAs del portal del SAT. Se configura en el `.env` de Dakota porque Colorado lo hereda.

### 6.1. Crear el recurso (Portal)

1. Portal Azure → **Create a resource** → buscar **"Computer Vision"**
2. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Name | `rg-kyb-comp-vision` |
   | Subscription | *(tu suscripción)* |
   | Resource group | `rg-kyb-production` |
   | Region | **East US** |
   | Pricing tier | **S1** (Standard) |

3. Click **Review + Create** → **Create**

### 6.2. Crear vía CLI

```powershell
az cognitiveservices account create `
  --name rg-kyb-comp-vision `
  --resource-group rg-kyb-production `
  --kind ComputerVision `
  --sku S1 `
  --location eastus `
  --yes

# Obtener credenciales
az cognitiveservices account show `
  --name rg-kyb-comp-vision `
  --resource-group rg-kyb-production `
  --query "properties.endpoint" -o tsv

az cognitiveservices account keys list `
  --name rg-kyb-comp-vision `
  --resource-group rg-kyb-production `
  --query "key1" -o tsv
```

### 6.3. Feature utilizada

Colorado invoca Image Analysis v4.0 con la feature **`read`**:
```
POST {AZURE_CV_ENDPOINT}/computervision/imageanalysis:analyze?features=read&api-version=2024-02-01
```

Estrategia cascada (`PORTAL_CAPTCHA_STRATEGY=cascada`):
1. **Azure CV Read** → OCR de la imagen CAPTCHA
2. **GPT-4o Vision** (fallback) → Enviar imagen base64 a gpt-4o
3. **Tesseract local** (último recurso) → OCR local

---

## 7. Recurso 5 — Azure Storage Account

Almacena los datos de entrenamiento para los modelos custom de Document Intelligence (INE).

### 7.1. Crear el recurso (Portal)

1. Portal Azure → **Create a resource** → buscar **"Storage account"**
2. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Name | `kybtrainingdata2849` |
   | Resource group | `rg-kyb-production` |
   | Region | **East US** |
   | Performance | **Standard** |
   | Redundancy | **LRS** (Locally redundant) |

3. Click **Review + Create** → **Create**

### 7.2. Crear contenedores

```powershell
# Crear contenedores para training data
az storage container create `
  --name ine-front-training `
  --account-name kybtrainingdata2849 `
  --auth-mode key

az storage container create `
  --name ine-back-training `
  --account-name kybtrainingdata2849 `
  --auth-mode key
```

### 7.3. Subir datos de entrenamiento

```powershell
# Subir imágenes de INE (frente) etiquetadas
az storage blob upload-batch `
  --destination ine-front-training `
  --source ./training-data/ine-front/ `
  --account-name kybtrainingdata2849

# Subir imágenes de INE (reverso) etiquetadas
az storage blob upload-batch `
  --destination ine-back-training `
  --source ./training-data/ine-back/ `
  --account-name kybtrainingdata2849
```

### 7.4. Obtener credenciales

```powershell
az storage account keys list `
  --account-name kybtrainingdata2849 `
  --resource-group rg-kyb-production `
  --query "[0].value" -o tsv
```

---

## 8. Recurso 6 — PostgreSQL

Dakota y Colorado comparten la misma base de datos para persistir datos extraídos y resultados de validación.

### 8.1. Opción A: Azure Database for PostgreSQL (Producción)

```powershell
az postgres flexible-server create `
  --name pg-kyb-production `
  --resource-group rg-kyb-production `
  --location eastus `
  --admin-user kyb_app `
  --admin-password "kyb_secure_2026!" `
  --sku-name Standard_B1ms `
  --tier Burstable `
  --version 16 `
  --storage-size 32 `
  --yes

# Crear base de datos
az postgres flexible-server db create `
  --server-name pg-kyb-production `
  --resource-group rg-kyb-production `
  --database-name kyb

# Permitir acceso desde tu IP
az postgres flexible-server firewall-rule create `
  --name allow-dev `
  --server-name pg-kyb-production `
  --resource-group rg-kyb-production `
  --start-ip-address <TU_IP> `
  --end-ip-address <TU_IP>
```

### 8.2. Opción B: PostgreSQL Local (Desarrollo)

Para desarrollo local (configuración actual):
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=kyb_secure_2026!
```

### 8.3. Tablas requeridas

Dakota usa Alembic para migraciones. Después de configurar la DB:
```powershell
cd Dakota/kyb_review
alembic upgrade head
```

---

## 9. Entrenamiento de Modelos Custom (INE)

Los modelos `INE_Front` e `INE_Back` son modelos custom de Document Intelligence entrenados con imágenes de INE mexicanas.

### 9.1. Preparar datos de entrenamiento

1. **Mínimo 5 imágenes** por modelo (recomendado: 15-50)
2. Formatos aceptados: PDF, JPEG, PNG, BMP, TIFF
3. Resolución mínima: 50x50 pixels

### 9.2. Etiquetar con Document Intelligence Studio

1. Ir a [documentintelligence.ai.azure.com](https://documentintelligence.ai.azure.com)
2. **Custom extraction model** → **+ Create a project**
3. Configurar:
   | Campo | Valor |
   |-------|-------|
   | Project name | `INE-Front-Training` |
   | DI resource | `di-kyb-production` |
   | Storage account | `kybtrainingdata2849` |
   | Container | `ine-front-training` |

4. Etiquetar campos de INE frente:
   - `nombre`, `apellido_paterno`, `apellido_materno`
   - `clave_elector`, `curp`, `seccion`
   - `fecha_nacimiento`, `sexo`, `domicilio`
   - `vigencia`, `numero_vertical`

5. Repetir para INE reverso (`INE-Back-Training`):
   - `codigo_barras`, `mrz`, `cic`
   - `numero_emision`, `ocr`

### 9.3. Entrenar modelos

#### Desde Document Intelligence Studio:
1. Click **Train** → Model ID: `INE_Front` → **Train**
2. Esperar ~10-30 minutos
3. Repetir para `INE_Back`

#### Desde código (ya implementado en Dakota):
```python
# ine.py usa DocumentIntelligenceAdministrationClient con AzureBlobContentSource
# para gestionar modelos custom programáticamente
```

### 9.4. Verificar modelos entrenados

```powershell
# Listar modelos custom
az rest --method get `
  --url "https://eastus.api.cognitive.microsoft.com/documentintelligence/documentModels?api-version=2024-11-30" `
  --headers "Ocp-Apim-Subscription-Key=<DI_KEY>"
```

---

## 10. Configuración del `.env`

Después de crear todos los recursos, configurar el archivo `.env` en `Dakota/kyb_review/api/service/.env`:

```dotenv
# ============================================================================
# Azure Document Intelligence
# ============================================================================
DI_ENDPOINT=https://<REGION>.api.cognitive.microsoft.com/
DI_KEY=<tu-document-intelligence-key>

# ============================================================================
# Azure OpenAI
# ============================================================================
AZURE_OPENAI_ENDPOINT=https://<tu-recurso>.openai.azure.com/
AZURE_DEPLOYMENT_NAME=gpt-4o
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_API_KEY=<tu-openai-key>

# ============================================================================
# Azure Storage (Training Data para modelos custom)
# ============================================================================
STORAGE_ACCOUNT=<tu-storage-account>
STORAGE_KEY=<tu-storage-key>

# ============================================================================
# PostgreSQL
# ============================================================================
DB_USER=kyb_app
DB_PASS=<tu-db-password>
DB_HOST=localhost          # o tu Azure PostgreSQL endpoint
DB_PORT=5432
DB_NAME=kyb
DB_SSL=disable             # usar "require" en producción Azure
DB_ECHO=false              # desactivar en producción

# ============================================================================
# Azure Computer Vision (CAPTCHA OCR — usado por Colorado)
# ============================================================================
AZURE_CV_ENDPOINT=https://<tu-recurso>.cognitiveservices.azure.com
AZURE_CV_KEY=<tu-computer-vision-key>

# Estrategia de resolución: "cascada" | "azure_ocr" | "gpt4_vision"
PORTAL_CAPTCHA_STRATEGY=cascada
```

### 10.1. Herencia de `.env`

Colorado busca el `.env` en cascada (prioridad descendente):
1. `Colorado/cross_validation/.env` (propio)
2. `Agents/.env` (raíz compartida)
3. `Dakota/kyb_review/.env`
4. `Dakota/kyb_review/api/service/.env` ← **ubicación actual**

> **Nota:** Solo es necesario mantener **un** archivo `.env`. La ubicación actual en `Dakota/kyb_review/api/service/.env` es compartida por ambos servicios.

---

## 11. Validación de Recursos

### 11.1. Script de verificación rápida

```powershell
# Verificar Document Intelligence
$headers = @{ "Ocp-Apim-Subscription-Key" = "<DI_KEY>" }
Invoke-RestMethod -Uri "https://eastus.api.cognitive.microsoft.com/documentintelligence/documentModels?api-version=2024-11-30" `
  -Headers $headers -Method GET | ConvertTo-Json -Depth 3

# Verificar Azure OpenAI
$body = @{
    messages = @(@{ role = "user"; content = "Responde OK" })
    max_tokens = 5
} | ConvertTo-Json
$oaiHeaders = @{
    "api-key" = "<OPENAI_KEY>"
    "Content-Type" = "application/json"
}
Invoke-RestMethod -Uri "https://kyb-open-ai.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-12-01-preview" `
  -Headers $oaiHeaders -Method POST -Body $body

# Verificar Computer Vision
$cvHeaders = @{ "Ocp-Apim-Subscription-Key" = "<CV_KEY>" }
Invoke-RestMethod -Uri "https://rg-kyb-comp-vision.cognitiveservices.azure.com/computervision/models?api-version=2024-02-01" `
  -Headers $cvHeaders -Method GET

# Verificar PostgreSQL
psql -h localhost -U kyb_app -d kyb -c "SELECT version();"
```

### 11.2. Verificar desde Python

```python
# Ejecutar desde Agents/
python -c "
from dotenv import load_dotenv
from pathlib import Path
import os, httpx

load_dotenv(Path('Dakota/kyb_review/api/service/.env'))

checks = {
    'Document Intelligence': f\"{os.getenv('DI_ENDPOINT')}documentintelligence/documentModels?api-version=2024-11-30\",
    'Computer Vision': f\"{os.getenv('AZURE_CV_ENDPOINT')}/computervision/models?api-version=2024-02-01\",
}

for name, url in checks.items():
    try:
        key = os.getenv('DI_KEY') if 'Document' in name else os.getenv('AZURE_CV_KEY')
        r = httpx.get(url, headers={'Ocp-Apim-Subscription-Key': key}, timeout=10)
        print(f'{name}: {\"OK\" if r.status_code == 200 else f\"FAIL ({r.status_code})\"}')
    except Exception as e:
        print(f'{name}: ERROR - {e}')
"
```

---

## 12. Estimación de Costos

### 12.1. Costos mensuales estimados (uso moderado)

| Recurso | SKU | Costo Estimado/Mes | Notas |
|---------|-----|---------------------|-------|
| Document Intelligence | S0 | ~$50–150 USD | ~500 páginas custom + 2,000 prebuilt-layout |
| Azure OpenAI (gpt-4o) | S0 | ~$100–300 USD | ~2M tokens input + 500K output |
| Azure OpenAI (embeddings) | S0 | ~$5–15 USD | ~1M tokens |
| Computer Vision | S1 | ~$5–20 USD | ~500 análisis CAPTCHA |
| Storage Account | Standard LRS | ~$1–5 USD | <1 GB training data |
| PostgreSQL (Flexible) | B1ms | ~$13–25 USD | Burstable, 1 vCPU, 2 GB RAM |
| **Total estimado** | | **~$175–515 USD** | |

### 12.2. Consejos de optimización

- **Document Intelligence:** `prebuilt-layout` es más barato que modelos custom. Solo usar custom para INE.
- **OpenAI:** Dakota usa `temperature=0` lo cual es óptimo para extracción determinística.
- **Caching:** Dakota implementa cache local (`optimizer.py`) para evitar llamadas repetidas a DI.
- **Circuit breaker:** `resilience.py` previene llamadas innecesarias cuando Azure falla.

---

## 13. Troubleshooting

### Error: `401 Unauthorized` en Document Intelligence
```
Causa: DI_KEY inválida o expirada
Fix:   Regenerar key en Azure Portal → Cognitive Services → Keys and Endpoint
```

### Error: `404 Model Not Found` para INE_Front/INE_Back
```
Causa: Modelos custom no entrenados en este recurso de Document Intelligence
Fix:   Entrenar los modelos (ver Sección 9) o verificar que el endpoint sea correcto
```

### Error: `429 Too Many Requests` en Azure OpenAI
```
Causa: Excediste los Tokens Per Minute (TPM)
Fix:   Aumentar TPM del deployment en Azure Portal → OpenAI → Deployments → Edit
```

### Error: `Connection refused` en PostgreSQL
```
Causa: PostgreSQL no está corriendo o firewall bloquea conexión
Fix:   Verificar que el servicio está activo: pg_isready -h localhost -p 5432
```

### Error: CAPTCHA no se resuelve
```
Causa: Estrategia cascada falla en los 3 niveles
Fix:   
  1. Verificar AZURE_CV_KEY
  2. Verificar que gpt-4o acepta imágenes (necesita modelo con vision)
  3. Verificar Tesseract instalado y accesible en PATH
```

---

## Checklist de Creación

- [ ] Resource Group creado (`rg-kyb-production`)
- [ ] AI Foundry Hub creado (`hub-kyb-production`)
- [ ] AI Foundry Project creado (`proj-kyb-dakota`)
- [ ] Document Intelligence creado (S0, East US)
- [ ] Azure OpenAI creado (S0, East US)
- [ ] Deployment `gpt-4o` creado (≥80K TPM)
- [ ] Deployment `text-embedding-ada-002` creado (≥30K TPM)
- [ ] Computer Vision creado (S1, East US)
- [ ] Storage Account creado (Standard LRS)
- [ ] Contenedores de training creados
- [ ] Modelos custom INE entrenados (`INE_Front`, `INE_Back`)
- [ ] PostgreSQL configurado (local o Azure Flexible)
- [ ] `.env` configurado con todas las credenciales
- [ ] Validación de conectividad exitosa
- [ ] Alembic migrations ejecutadas (`alembic upgrade head`)
