# Orquestrator Dakota â€” Agente Orquestador KYB (Flujo Dakota)

VersiÃ³n del orquestador que usa **Dakota** para OCR y persistencia de documentos,
en lugar de PagaTodo Hub.

## Flujo

```
Archivos (PDF/imagen) + RFC
        â”‚
        â–¼
  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
  â”‚ Orquestratorâ”‚  â† Este servicio (puerto 8002)
  â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”˜
         â”‚
    â”Œâ”€â”€â”€â”€â–¼â”€â”€â”€â”€â”
    â”‚ Dakota  â”‚  â† OCR + Persistencia (puerto 8010)
    â””â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”˜
         â”‚
    â”Œâ”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”
    â”‚ Colorado â”‚  â† ValidaciÃ³n cruzada (puerto 8011)
    â””â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”˜
         â”‚
    â”Œâ”€â”€â”€â”€â–¼â”€â”€â”€â”€â”
    â”‚ Arizona â”‚  â† PLD/AML + Compliance (puerto 8012)
    â””â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”˜
         â”‚
    â”Œâ”€â”€â”€â”€â–¼â”€â”€â”€â”€â”
    â”‚ Nevada  â”‚  â† Dictamen jurÃ­dico (puerto 8013)
    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

## Endpoints

| MÃ©todo | Ruta | DescripciÃ³n |
|--------|------|-------------|
| `POST` | `/api/v1/pipeline/process` | Procesa un documento (archivo + doc_type + rfc) |
| `POST` | `/api/v1/pipeline/expediente` | Procesa expediente completo (archivos + doc_types + rfc) |
| `GET`  | `/api/v1/pipeline/status/{rfc}` | Consulta estado del pipeline |
| `GET`  | `/api/v1/pipeline/health` | Health check de todos los servicios |

## Tipos de documento soportados

- `csf` â€” Constancia de SituaciÃ³n Fiscal
- `fiel` â€” Firma ElectrÃ³nica Avanzada
- `acta_constitutiva` â€” Acta Constitutiva
- `poder_notarial` â€” Poder Notarial
- `reforma_estatutos` â€” Reforma de Estatutos
- `estado_cuenta` â€” Estado de Cuenta Bancario
- `domicilio` â€” Comprobante de Domicilio (empresa)
- `ine` â€” INE del Representante Legal (frente)
- `ine_reverso` â€” INE del Representante Legal (reverso)
- `ine_propietario_real` â€” INE del Propietario Real
- `domicilio_rl` â€” Comprobante de Domicilio del RL
- `domicilio_propietario_real` â€” Comprobante de Domicilio del Propietario Real

## EjecuciÃ³n

```bash
# 1. Activar entorno virtual
# 2. Instalar dependencias
pip install -e .

# 3. Configurar .env (ver variables abajo)

# 4. Ejecutar
uvicorn app.main:app --port 8002 --reload
```

## Variables de entorno (.env)

```env
DAKOTA_BASE_URL=http://localhost:8010
COLORADO_BASE_URL=http://localhost:8011
ARIZONA_BASE_URL=http://localhost:8012
NEVADA_BASE_URL=http://localhost:8013

DB_HOST=localhost
DB_PORT=5432
DB_NAME=kyb
DB_USER=kyb_app
DB_PASS=<tu_password>
```

## Diferencia vs Orquestrator (PagaTodo)

| Aspecto | Orquestrator (PagaTodo) | Orquestrator (Dakota) |
|---------|------------------------|----------------------|
| **Entrada** | `prospect_id` + `DocumentType` | Archivo PDF/imagen + `doc_type` + `rfc` |
| **OCR** | PagaTodo Hub externo | Dakota local (Azure DI + OpenAI) |
| **Persistencia** | Directa via asyncpg | Dakota (ORM SQLAlchemy) |
| **Dependencia** | PagaTodo Hub (internet) | Dakota (localhost:8010) |
