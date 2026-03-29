# ============================================================================
# KYB API - Script de Despliegue para Windows
# ============================================================================
# Uso: .\scripts\deploy.ps1 [-Environment staging|production]
# ============================================================================

param(
    [ValidateSet("staging", "production")]
    [string]$Environment = "staging"
)

$ErrorActionPreference = "Stop"

# Configuracion
$ImageName = "kyb-api"

function Write-Info($message) {
    Write-Host "[INFO] $message" -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host "[WARN] $message" -ForegroundColor Yellow
}

function Write-Err($message) {
    Write-Host "[ERROR] $message" -ForegroundColor Red
}

Write-Info "Iniciando despliegue a: $Environment"

# Verificar Docker
try {
    docker --version | Out-Null
} catch {
    Write-Err "Docker no esta instalado o no esta corriendo"
    exit 1
}

# Verificar archivo .env
if (-not (Test-Path "api/service/.env")) {
    Write-Err "Archivo api/service/.env no encontrado"
    Write-Info "Copia api/service/.env.example a api/service/.env y configura las credenciales"
    exit 1
}

# Obtener version
$version = (Select-String -Path "pyproject.toml" -Pattern 'version = "(.+)"' | ForEach-Object { $_.Matches.Groups[1].Value }) | Select-Object -First 1
Write-Info "Version: $version"

# Build de imagen
Write-Info "Construyendo imagen Docker..."
docker build -f Dockerfile.prod -t "${ImageName}:${version}" -t "${ImageName}:latest" .

if ($LASTEXITCODE -ne 0) {
    Write-Err "Error en build de Docker"
    exit 1
}

Write-Info "Imagen construida: ${ImageName}:${version}"

# Despliegue
switch ($Environment) {
    "staging" {
        Write-Info "Desplegando a staging..."
        docker compose -f compose.prod.yml down 2>$null
        docker compose -f compose.prod.yml up -d
    }
    "production" {
        Write-Warn "Desplegando a PRODUCCION..."
        $confirm = Read-Host "Estas seguro? (y/N)"
        if ($confirm -ne "y") {
            Write-Info "Despliegue cancelado"
            exit 0
        }
        docker compose -f compose.prod.yml down 2>$null
        docker compose -f compose.prod.yml up -d
    }
}

# Esperar inicio
Write-Info "Esperando a que el servicio inicie..."
Start-Sleep -Seconds 10

# Health check
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/kyb/api/v1.0.0/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Info "Servicio saludable (HTTP $($response.StatusCode))"
        Write-Info "Despliegue completado exitosamente!"
    }
} catch {
    Write-Err "Health check fallido"
    Write-Info "Revisa los logs: docker compose -f compose.prod.yml logs"
    exit 1
}

# Info final
Write-Info "============================================"
Write-Info "KYB API desplegada en: http://localhost:8000"
Write-Info "Swagger UI: http://localhost:8000/docs"
Write-Info "Health: http://localhost:8000/kyb/api/v1.0.0/health"
Write-Info "============================================"
