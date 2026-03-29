#!/bin/bash
# ============================================================================
# KYB API - Script de Despliegue
# ============================================================================
# Uso: ./scripts/deploy.sh [ambiente]
# Ambientes: staging | production
# ============================================================================

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuracion
REGISTRY="ghcr.io"
IMAGE_NAME="kyb-api"
DEFAULT_ENV="staging"

# Funciones
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Obtener ambiente
ENVIRONMENT=${1:-$DEFAULT_ENV}

log_info "Iniciando despliegue a: $ENVIRONMENT"

# Verificar que Docker este instalado
if ! command -v docker &> /dev/null; then
    log_error "Docker no esta instalado"
    exit 1
fi

# Verificar archivo .env
if [ ! -f "api/service/.env" ]; then
    log_error "Archivo api/service/.env no encontrado"
    log_info "Copia api/service/.env.example a api/service/.env y configura las credenciales"
    exit 1
fi

# Obtener version del proyecto
VERSION=$(grep 'version' pyproject.toml | head -1 | cut -d'"' -f2)
log_info "Version: $VERSION"

# Build de imagen
log_info "Construyendo imagen Docker..."
docker build -f Dockerfile.prod -t $IMAGE_NAME:$VERSION -t $IMAGE_NAME:latest .

if [ $? -ne 0 ]; then
    log_error "Error en build de Docker"
    exit 1
fi

log_info "Imagen construida: $IMAGE_NAME:$VERSION"

# Despliegue segun ambiente
case $ENVIRONMENT in
    staging)
        log_info "Desplegando a staging..."
        docker compose -f compose.prod.yml down || true
        docker compose -f compose.prod.yml up -d
        ;;
    production)
        log_warn "Desplegando a PRODUCCION..."
        read -p "Estas seguro? (y/N): " confirm
        if [ "$confirm" != "y" ]; then
            log_info "Despliegue cancelado"
            exit 0
        fi
        docker compose -f compose.prod.yml down || true
        docker compose -f compose.prod.yml up -d
        ;;
    *)
        log_error "Ambiente desconocido: $ENVIRONMENT"
        log_info "Ambientes validos: staging | production"
        exit 1
        ;;
esac

# Verificar que el servicio este corriendo
log_info "Esperando a que el servicio inicie..."
sleep 10

# Health check
HEALTH_URL="http://localhost:8000/kyb/api/v1.0.0/health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    log_info "Servicio saludable (HTTP $HTTP_CODE)"
    log_info "Despliegue completado exitosamente!"
else
    log_error "Health check fallido (HTTP $HTTP_CODE)"
    log_info "Revisa los logs: docker compose -f compose.prod.yml logs"
    exit 1
fi

# Mostrar info
log_info "============================================"
log_info "KYB API desplegada en: http://localhost:8000"
log_info "Swagger UI: http://localhost:8000/docs"
log_info "Health: http://localhost:8000/kyb/api/v1.0.0/health"
log_info "============================================"
