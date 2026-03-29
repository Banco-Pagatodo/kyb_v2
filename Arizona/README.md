# Arizona — Agente PLD/AML

**Puerto:** 8012  
**Versión:** 2.3.0

Servicio de análisis PLD/AML para Personas Morales.

| Módulo | Prefijo API | Responsabilidad |
|--------|-------------|------------------|
| `pld_agent` | `/api/v1/pld` | Completitud documental (Etapa 1) + Screening listas negras (Etapa 2) + Estructura accionaria (Etapa 4) + MER PLD/FT v7.0 (Etapa 5) + Dictamen PLD/FT + Reporte PLD unificado |

---

## ⚠️ Requisito: VPN

> **Es necesario conectarse a la VPN antes de ejecutar este agente.**
>
> Arizona consulta bases de datos de listas negras (SQL Server) que solo son
> accesibles a través de la red interna. Sin la VPN activa, el screening
> de la Etapa 2 fallará al intentar conectarse a las tablas
> `CatPLD69BPerson`, `CatPLDLockedPerson` y `TraPLDBlackListEntry`.

---

## Ejecución

```bash
cd Arizona
python -m uvicorn main:app --host 127.0.0.1 --port 8012
```

## Arquitectura

```
┌────────────────┐   ┌────────────────┐   ┌──────────────────────────────┐
│   Dakota       │──▶│  Colorado      │──▶│         Arizona (:8012)      │
│  (Port 8010)   │   │  (Port 8011)   │   │                              │
│  Extracción    │   │  Validación    │   │  ┌─────────────────────────┐  │
│  documental    │   │  cruzada       │   │  │ pld_agent               │  │
│                │   │                │   │  │  /api/v1/pld            │  │
└────────────────┘   └────────────────┘   │  │  Completitud + screening│  │
                                          │  │  + MER + reporte PLD    │  │
                                          │  └─────────────────────────┘  │
                                          └──────────────┬───────────────┘
                                                         │
                                                ┌────────▼────────┐
                                                │   PostgreSQL    │
                                                │   (kyb - 5432)  │
                                                └─────────────────┘
```

## Endpoints principales

### PLD Agent
- `GET  /api/v1/pld/empresas` — Lista empresas con estatus
- `POST /api/v1/pld/etapa1/{empresa_id}` — Completitud documental (JSON)
- `POST /api/v1/pld/etapa1/{empresa_id}/reporte` — Reporte texto Etapa 1
- `POST /api/v1/pld/etapa2/{empresa_id}` — Screening listas negras (JSON)
- `POST /api/v1/pld/etapa2/{empresa_id}/reporte` — Reporte texto Etapa 2
- `POST /api/v1/pld/reporte/{empresa_id}` — Reporte consolidado (Etapa 1+2+Colorado)
- `POST /api/v1/pld/completo/{empresa_id}` — Pipeline completo: Etapas 1–5 + Dictamen PLD/FT (genera `reporte.txt` + `dictamen_pld.txt`)
- `GET  /api/v1/pld/dictamen/{empresa_id}` — Obtiene dictamen PLD/FT (JSON)
- `GET  /api/v1/pld/dictamen/{empresa_id}/txt` — Obtiene dictamen PLD/FT (texto plano)
- `GET  /api/v1/pld/analisis/{empresa_id}` — Obtiene análisis PLD guardado

### MER (Etapa 5 — standalone)
- `POST /api/v1/mer/evaluar` — Evaluar MER desde JSON (SolicitudMER)
- `POST /api/v1/mer/evaluar/{empresa_id}` — Evaluar MER desde expediente BD
