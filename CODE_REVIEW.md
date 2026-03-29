# Code Review — KYB Multi-Agent Platform

**Fecha:** 2026-03-23  
**Revisor:** Lead AI Engineer  
**Veredicto General:** **7.5/10** — Sólido para MVP, necesita hardening para producción

La arquitectura es limpia y bien pensada: 5 microservicios con responsabilidad única, async-first, Pydantic v2, PostgreSQL compartido. Para un equipo pequeño, el nivel de madurez es alto. Los problemas son los esperables en una transición MVP → producción.

---

## Arquitectura Revisada

| Agente | Puerto | Responsabilidad | LOC | Score |
|--------|--------|-----------------|-----|-------|
| Dakota | 8010 | Extracción OCR + LLM | ~8,000 | 7.8/10 |
| Colorado | 8011 | Validación cruzada + portales SAT/INE | ~8,000 | 7.5/10 |
| Arizona | 8012 | PLD/AML: completitud, screening, MER, dictamen | ~5,000 | 7.0/10 |
| Nevada | 8013 | Dictamen Jurídico DJ-1 | ~2,500 | 6.5/10 |
| Orquestador | 8002 | Pipeline coordinator | ~1,500 | 7.0/10 |
| DemoUI | 8501 | Streamlit dashboard | ~1,100 | N/A |

---

## CRÍTICOS (P0) — Bloquean producción

### 1. Zero autenticación en 4 de 5 agentes
- **Colorado, Arizona, Nevada, Orquestador**: Ningún endpoint requiere API key ni JWT.
- ~~**Dakota**: Tiene auth pero con bypass en modo dev (`ENVIRONMENT != "production"` → sin validación).~~
  - **RESUELTO (2026-03-23):** Auth obligatorio en todos los entornos. `API_KEY` requerida al arrancar.
- **Impacto**: Cualquiera con acceso a la red puede leer RFC, accionistas, dictámenes legales, screening PLD.
- **Fix**: Middleware compartido con API key mínimo. Un solo módulo `shared/auth.py` reutilizable.

### 2. ~~`pyodbc` falta en pyproject.toml de Arizona~~
- ~~El screening contra SQL Server importa `pyodbc` pero no está declarado como dependencia.~~
- ~~Un `pip install .` limpio rompe el agente.~~
- **RESUELTO (2026-03-23):** `pyodbc>=5.1` agregado a `Arizona/pld_agent/pyproject.toml`.

### 3. ~~Sin transacciones multi-tabla (Arizona + Nevada)~~
~~```python
await guardar_analisis_pld(resultado)       # Tabla 1
await guardar_dictamen_pld(empresa_id, ...) # Tabla 2
# Si falla tabla 2 → estado inconsistente
```~~
- ~~Mismo patrón en Nevada. Fix: usar `async with conn.transaction():`.~~
- **RESUELTO (2026-03-23):**
  - Arizona: nueva función `guardar_resultado_completo()` ejecuta ambos UPSERTs en `async with conn.transaction():`.
  - Nevada: `guardar_dictamen()` usa `async with conn.transaction():` explícito.

### 4. ~~CORS `allow_origins=["*"]` en Orquestador~~
- ~~Permite requests desde cualquier dominio. En producción debe ser whitelist.~~
- **RESUELTO (2026-03-23):** CORS cambiado a whitelist configurable vía env `CORS_ORIGINS` (default: `localhost:8501,localhost:3000`). Métodos restringidos a GET/POST/PUT/DELETE.

---

## ALTOS (P1) — Resolver antes de salir de piloto

### 5. ~~Sin retry/circuit breaker entre agentes~~
- ~~El Orquestador llama Dakota → Colorado → Arizona → Nevada secuencialmente.~~
- ~~Si uno falla, devuelve `None` y continúa — pero no reintenta.~~
- ~~Si un agente está caído, cada request espera el timeout completo (120-300s).~~
- **RESUELTO (2026-03-23):** Agregado `tenacity` con exponential backoff (3 reintentos, 1-10s). Circuit breaker propio (umbral 5 fallos, ventana 60s de recuperación) para las 6 funciones de `clients.py`.

### 6. ~~Normalización de nombres duplicada ×3 (Arizona)~~
- ~~`normalizar_nombre()` existe en `etapa1_completitud.py`, `blacklist_screening.py` y `mer_catalogos.py` con implementaciones diferentes.~~
- **RESUELTO (2026-03-23):** Creado `Arizona/pld_agent/core/normalize.py` con `normalizar_nombre`, `normalizar_rfc`, `normalizar_razon_social`. `blacklist_screening.py` y `etapa1_completitud.py` ahora importan de `core.normalize`. (`mer_catalogos._normalizar` no se tocó — es para catálogos, no nombres).

### 7. ~~Nevada: 0 tests unitarios~~
- ~~El directorio `tests/` está vacío. Es el agente con mayor riesgo legal (genera el Dictamen Jurídico DJ-1).~~
- ~~El rules engine (9 reglas), el confidence scoring y el generador LLM no tienen ningún test.~~
- **RESUELTO (2026-03-23):** Creado `test_rules_engine.py` con 54 tests: helpers, R1-R9 (pass/fail), lógica de dictamen (FAVORABLE/CON_CONDICIONES/NO_FAVORABLE), extractores de datos. 54/54 passing.

### 8. ~~Sin validación UUID en endpoints~~
- ~~Arizona y Nevada aceptan `empresa_id: str` sin validar formato UUID.~~
- ~~Un string arbitrario llega hasta las queries SQL.~~
- **RESUELTO (2026-03-23):** Agregado `_validar_uuid()` en ambos routers (Arizona 9 endpoints, Nevada 3 endpoints). UUID inválido retorna HTTP 400 en vez de propagarse a la BD.

### 9. ~~Screenshots y logs de portal almacenados sin protección (Colorado)~~
- ~~Los screenshots de portales SAT/INE contienen datos personales (RFC, CURP, nombres).~~
- ~~Se guardan en `screenshots/` sin cifrado ni control de acceso.~~
- ~~Los logs del portal registran datos de consulta en texto plano.~~
- **RESUELTO (2026-03-23):**
  - `.gitignore` en `screenshots/` y `logs/` para excluir del repositorio.
  - Filtro `_SanitizeFilter` en logger que enmascara RFC y CURP automáticamente.
  - Permisos de directorio restringidos a owner-only (`chmod 0o700`).

### 10. Confidence scoring arbitrario (Nevada)
- Pesos 50/40/10 (OCR/reglas/LLM) no tienen justificación documentada.
- `bonus_llm=100` vs `60` para determinista infla artificialmente el score cuando hay LLM.
- Riesgo regulatorio: si BPT audita, no pueden explicar por qué una confiabilidad es 89.8%.

---

## MEDIOS (P2) — Mejora continua

### 11. Configuración dispersa
- Dakota tiene config en 5 archivos diferentes (`auth.py`, `session.py`, `config.py`, etc.).
- **Fix**: Consolidar con `pydantic-settings` → un solo `Settings` class por agente.

### 12. Prompts LLM hardcodeados (Dakota ~1000 líneas)
- Los prompts de extracción están inline en el servicio OpenAI.
- Cambiar un prompt requiere editar código Python y redesplegar.
- **Fix**: Extraer a archivos YAML/Markdown en `prompts/`, cargados al inicio.

### 13. Sin deduplicación de personas (Arizona Etapa 4)
- "Arturo Pons Aguirre" aparece como apoderado Y accionista → se cuenta 2 veces en screening.
- Se ve en el reporte generado: persona [1] y [3] son la misma.

### 14. `except Exception` demasiado amplio
- Patrón repetido en los 5 agentes. Captura `KeyboardInterrupt`, `MemoryError`, `SystemExit`.
- **Fix**: Capturar excepciones específicas; o usar `except Exception` solo con `raise` después del logging.

### 15. Sin rate limiting
- Ningún agente limita requests por minuto.
- Colorado `/todas` puede lanzar validación de TODAS las empresas — potencial DoS.
- **Fix**: `slowapi` con `@limiter.limit("10/minute")` en endpoints costosos.

### 16. Selectores de portal SAT/INE hardcodeados (Colorado)
- `[id="formMain:captchaInput"]` cambia cuando SAT rediseña su sitio.
- **Fix**: Externalizar selectores a YAML con hash de versión del portal.

### 17. Sin soft-delete (compliance)
- Todas las tablas solo hacen INSERT o TRUNCATE. No hay `deleted_at` ni versionado.
- Para un sistema KYB/PLD bajo supervisión CNBV, necesitas audit trail completo.

### 18. Orquestador sin ejecución parcial/paralela
- Si Nevada falla, no se devuelven los resultados de Dakota+Colorado+Arizona que sí pasaron.
- Arizona PLD y Compliance podrían ejecutarse en paralelo (no dependen entre sí).

---

## Buenas Prácticas Detectadas ✅

| Aspecto | Implementación |
|---------|---------------|
| Async-first | Todos los agentes usan `asyncpg` + `httpx` + `async/await` |
| Type safety | Pydantic v2 con ~90-95% type hints |
| MER determinista | 15 factores sin LLM = reproducibilidad total |
| Circuit breaker (Dakota) | `resilience.py` con exponential backoff |
| Anti-homónimos (Arizona) | Scoring inteligente con penalización por nombres comunes mexicanos |
| File validation (Dakota) | Magic bytes + MIME type + filename sanitization |
| Waterfall .env | Busca en múltiples ubicaciones (robusto para dev local) |
| Portal automation | CAPTCHA cascade (Azure CV → GPT-4o → Tesseract) |
| Status tracking | `pipeline_resultados` con timestamps por agente |

---

## Plan de Acción Recomendado

| Prioridad | Acción | Esfuerzo | Impacto | Estado |
|-----------|--------|----------|---------|--------|
| P0 | Auth middleware compartido | 1 día | Seguridad | Dakota fix ✅ (bypass eliminado) |
| P0 | Agregar `pyodbc` a deps | 5 min | Deploy | ✅ Resuelto |
| P0 | Transacciones en persistencia | 2 hrs | Integridad | ✅ Resuelto |
| P0 | CORS whitelist | 15 min | Seguridad | Pendiente |
| P1 | Retry + circuit breaker en Orquestador | 1 día | Resiliencia |
| P1 | Tests Nevada (rules engine) | 1 día | Calidad |
| P1 | UUID validation en endpoints | 1 hr | Seguridad |
| P1 | Normalización centralizada | 2 hrs | Mantenibilidad |
| P2 | Pydantic Settings consolidado | 4 hrs | Mantenibilidad |
| P2 | Rate limiting | 2 hrs | Seguridad |
| P2 | Dedup personas screening | 2 hrs | Precisión |
| P2 | Prompts a YAML | 4 hrs | Mantenibilidad |
| P2 | Selectores portal a YAML | 2 hrs | Mantenibilidad |
| P2 | Soft-delete + audit trail | 1 día | Compliance |
