# KYB System - Checklist de Produccion

> **Versión**: 1.3.0  
> **Última actualización**: 27 de febrero de 2026

## Arquitectura Multi-Agente

El sistema se compone de **3 servicios independientes** que deben desplegarse por separado:

| Servicio | Puerto | Health Check |
|----------|--------|-------------|
| **Dakota** (extracción) | 8000 | `GET /kyb/api/v1.0.0/health` |
| **Colorado** (validación) | 8001 | `GET /api/v1/validacion/health` |
| **Orquestrator** (coordinador) | 8002 | `GET /api/v1/pipeline/health` |

## Novedades v1.3.0

### Características Nuevas a Validar
- [ ] **Orquestrator independiente**: Verificar flujo completo (subir archivo → extracción → validación cruzada)
- [ ] **Pipeline end-to-end**: Confirmar que `POST /api/v1/pipeline/process` ejecuta Dakota + Colorado automáticamente
- [ ] **Health check unificado**: Verificar que `/api/v1/pipeline/health` reporta estado de los 3 servicios
- [ ] **Persistencia automática**: Confirmar que Dakota guarda empresa + documento cuando recibe `?rfc=`
- [ ] **Validación cruzada**: Confirmar que Colorado genera dictamen y lo persiste en `validaciones_cruzadas`
- [ ] **Validación de tipo de documento**: Verificar detección de documentos incorrectos
- [ ] **Portales gubernamentales**: Verificar Bloque 10 (SAT + INE) con `--portales`

### Tests Multi-Servicio v1.3.0
```powershell
# Test 1: Health check completo (los 3 servicios corriendo)
Invoke-RestMethod http://localhost:8002/api/v1/pipeline/health
# Esperar: status=healthy, dakota.reachable=True, colorado.reachable=True

# Test 2: Pipeline end-to-end con Acta Constitutiva
curl.exe -X POST http://localhost:8002/api/v1/pipeline/process `
  -F "file=@Test_Files\Acta_Constitutiva\acta.pdf" `
  -F "rfc=ACA230223IA7" -F "doc_type=acta_constitutiva"
# Esperar: extraccion + persistencia + validacion_cruzada con dictamen

# Test 3: Documento tipo incorrecto
curl.exe -X POST http://localhost:8000/kyb/api/v1.0.0/docs/csf `
  -F "file=@poder_notarial.pdf"
# Esperar: documento_tipo_correcto=false, tipo_detectado="poder"
```

---

## Pre-Despliegue

### 1. Configuracion de Credenciales
- [ ] Generar API Key segura:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- [ ] Copiar `.env.example` a `.env` y configurar todas las variables
- [ ] Verificar credenciales de Azure Document Intelligence
- [ ] Verificar credenciales de Azure OpenAI
- [ ] Configurar Azure Key Vault (opcional pero recomendado)

### 2. Configuracion de Ambiente
- [ ] Establecer `ENVIRONMENT=production` en `.env`
- [ ] Configurar `API_KEY` con la key generada
- [ ] Ajustar `RATE_LIMIT_REQUESTS` segun necesidades
- [ ] Establecer `LOG_FORMAT=json` para logging estructurado
- [ ] Configurar `ALLOWED_ORIGINS` para CORS

### 3. Infraestructura
- [ ] Provisionar recursos de computo (minimo 4 CPU, 8 GB RAM por servicio)
- [ ] **PostgreSQL 16** operativo (localhost:5432 o servidor dedicado)
  - Base de datos `kyb` creada
  - Usuario `kyb_app` con permisos en las 3 tablas (`empresas`, `documentos`, `validaciones_cruzadas`)
  - Extensión `uuid-ossp` habilitada
- [ ] Configurar volumenes persistentes para `/app/temp`
- [ ] Configurar red (VNet, NSG, etc.)
- [ ] Habilitar acceso HTTPS saliente a:
  - `*.api.cognitive.microsoft.com`
  - `*.openai.azure.com`
  - `portalsat.plataforma.sat.gob.mx` (validación RFC — Colorado)
  - `listanominal.ine.mx` (validación INE — Colorado)

### 4. SSL/TLS
- [ ] Obtener certificados SSL
- [ ] Configurar API Gateway o Load Balancer con terminacion SSL
- [ ] Verificar que HTTPS funcione correctamente

### 5. Monitoreo
- [ ] Configurar Azure Monitor / Log Analytics
- [ ] Crear alertas para:
  - Error rate > 5%
  - Latencia P95 > 30s
  - Disponibilidad < 99%
- [ ] Configurar dashboard de metricas

## Despliegue

### Orden de Inicio (importante)

Los servicios deben iniciarse en este orden:

1. **PostgreSQL** — base de datos disponible primero
2. **Dakota** (puerto 8000) — depende de PostgreSQL + Azure
3. **Colorado** (puerto 8001) — depende de PostgreSQL + Playwright
4. **Orquestrator** (puerto 8002) — depende de Dakota + Colorado

### Opcion A: Docker Compose (simple)
```bash
# Build de cada servicio
docker build -f Dakota/kyb_review/Dockerfile.prod -t kyb-dakota:v1.3.0 .
docker build -f Colorado/cross_validation/Dockerfile -t kyb-colorado:v1.0.0 .
docker build -f Orquestrator/Dockerfile -t kyb-orquestrator:v1.0.0 .

# Deploy (asumiendo compose.prod.yml actualizado con los 3 servicios)
docker compose -f compose.prod.yml up -d

# Verificar los 3 servicios
curl http://localhost:8000/kyb/api/v1.0.0/health
curl http://localhost:8001/api/v1/validacion/health
curl http://localhost:8002/api/v1/pipeline/health
```

### Opcion B: Ejecución directa (desarrollo)
```powershell
# Desde la raíz del workspace (Agents/)
# Terminal 1 — Dakota
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --app-dir Dakota\kyb_review

# Terminal 2 — Colorado
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8001 --app-dir Colorado\cross_validation

# Terminal 3 — Orquestrator
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --app-dir Orquestrator
```

### Opcion C: Script de despliegue
```bash
# Linux/Mac
./scripts/deploy.sh production

# Windows
.\scripts\deploy.ps1 -Environment production
```

## Post-Despliegue

### 1. Verificacion de Salud (los 3 servicios)
- [ ] **Dakota** responde 200:
  ```bash
  curl http://<host>:8000/kyb/api/v1.0.0/health
  ```
- [ ] **Colorado** responde 200:
  ```bash
  curl http://<host>:8001/api/v1/validacion/health
  ```
- [ ] **Orquestrator** responde 200 y reporta los 3 servicios healthy:
  ```bash
  curl http://<host>:8002/api/v1/pipeline/health
  ```
- [ ] Swagger UI accesible en cada servicio (`/docs`)
- [ ] Autenticacion funciona (probar con API Key)
- [ ] Rate limiting funciona

### 2. Test de Integracion
- [ ] Probar endpoint de CSF con documento real (Dakota directo)
- [ ] Probar endpoint de INE con documento real (Dakota directo)
- [ ] Probar pipeline completo con Acta Constitutiva (vía Orquestrator)
- [ ] Probar validación cruzada manual (Colorado con empresa_id existente)
- [ ] Verificar que los 3 registros se crean en PostgreSQL (`empresas`, `documentos`, `validaciones_cruzadas`)
- [ ] Verificar tiempos de respuesta: pipeline < 60s, extracción individual < 30s

### 3. Documentacion
- [ ] Actualizar URLs en documentacion
- [ ] Distribuir API Keys a clientes autorizados
- [ ] Actualizar runbook de operaciones

## Comandos Utiles

```bash
# Ver logs de todos los servicios
docker compose -f compose.prod.yml logs -f

# Ver logs de un servicio específico
docker compose -f compose.prod.yml logs -f dakota
docker compose -f compose.prod.yml logs -f colorado
docker compose -f compose.prod.yml logs -f orquestrator

# Reiniciar un servicio
docker compose -f compose.prod.yml restart dakota

# Ver metricas de contenedores
docker stats

# Entrar al contenedor de Dakota
docker exec -it kyb-dakota-prod /bin/bash

# Rollback a version anterior
docker compose -f compose.prod.yml down
docker tag kyb-dakota:v1.2.1 kyb-dakota:latest
docker compose -f compose.prod.yml up -d

# Verificar tablas en PostgreSQL
psql -U kyb_app -d kyb -c "SELECT relname, n_live_tup FROM pg_stat_user_tables;"
```
docker compose -f compose.prod.yml up -d
```

## Contactos

| Rol | Nombre | Email |
|-----|--------|-------|
| Desarrollo | | |
| IT/Infraestructura | | |
| Seguridad | | |

---
Fecha de creacion: Enero 2026
Version: 1.0.0
