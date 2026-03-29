# PLD Agent — Agente de Prevención de Lavado de Dinero

**Módulo de:** Arizona (servicio v2.4.0)  
**Prefijo API:** `/api/v1/pld`  
**Puerto:** 8012

Agente de análisis PLD/AML para Personas Morales en el proceso de onboarding bancario mexicano.  
Se integra con **Dakota** (extracción documental) y **Colorado** (validación cruzada) para ejecutar las 8 etapas del proceso de debida diligencia. Sus resultados alimentan a **Nevada** (dictamen jurídico DJ-1).

---

## Arquitectura del sistema (5 servicios)

```
┌────────────────┐   ┌────────────────┐   ┌──────────────────────────────┐   ┌────────────────┐
│   Dakota       │──▶│  Colorado      │──▶│         Arizona (:8012)      │──▶│   Nevada       │
│  (Port 8010)   │   │  (Port 8011)   │   │                              │   │  (Port 8013)   │
│                │   │                │   │  ┌─────────────────────────┐  │   │                │
│  Extracción    │   │  Validación    │   │  │ pld_agent               │  │   │  Dictamen      │
│  documental    │   │  cruzada       │   │  │  /api/v1/pld            │  │   │  Jurídico DJ-1 │
└────────────────┘   └────────────────┘   │  │  Completitud + screening│  │   └────────────────┘
                                          │  │  + MER + reporte PLD    │  │
                                          │  └─────────────────────────┘  │
                                          └──────────────┬───────────────┘
                                                         │
                                                ┌────────▼────────┐
                                                │   PostgreSQL    │
                                                │   (kyb - 5432)  │
                                                └─────────────────┘
```

El pipeline es coordinado por el **Orquestrador** (puerto 8002).

Arizona PLD **no reprocesa** documentos ni hallazgos de validación cruzada.  
Lee directamente de las tablas `empresas`, `documentos` y `validaciones_cruzadas` que Dakota y Colorado ya populan.

---

## Cómo funciona Arizona — Pipeline completo paso a paso

Cuando se invoca `POST /api/v1/pld/completo/{empresa_id}`, Arizona ejecuta el pipeline completo de análisis PLD.  
El resultado es un **reporte de texto plano** con dictamen (APROBADO / APROBADO CON OBSERVACIONES / RECHAZADO) y desglose de 5 etapas.

### Diagrama de flujo

```
                           POST /completo/{empresa_id}
                                     │
                    ┌────────────────▼────────────────┐
                    │  1. CARGA DE EXPEDIENTE          │
                    │     data_loader.py                │
                    │     PostgreSQL → ExpedientePLD    │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  2. ETAPA 1 — COMPLETITUD        │
                    │     etapa1_completitud.py         │
                    │     6 verificaciones → dictamen   │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  3. ETAPA 2 — SCREENING          │
                    │     blacklist_screening.py        │
                    │     SQL Server → scoring anti-    │
                    │     homónimos → ResumenScreening  │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  4. ETAPA 4 — ESTRUCTURA          │
                    │     ACCIONARIA + SCREENING BC     │
                    │     etapa4_propietarios_reales.py │
                    │     Look-through + cascada CNBV   │
                    │     + screening BCs (Etapa 2)     │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  5. ETAPA 5 — MER PLD/FT v7.0    │
                    │     mer_engine.py → calculator    │
                    │     CAPA 1 (determinista)         │
                    │     CAPA 2 (LLM solo pendientes)  │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  6. GENERACIÓN DE REPORTE         │
                    │     report_generator.py           │
                    │     Texto plano (reporte.txt)     │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  7. DICTAMEN PLD/FT               │
                    │     dictamen_generator.py          │
                    │     + dictamen_txt.py              │
                    │     JSON + texto (dictamen_pld.txt)│
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  8. PERSISTENCIA                  │
                    │     persistence.py → analisis_pld │
                    └────────────────┬────────────────┘
                                     │
                              PlainTextResponse
```

### Paso 1 — Carga de expediente (`data_loader.py`)

Arizona **no hace llamadas a Azure**. Todo lo lee de PostgreSQL (BD `kyb`):

| Query | Tabla | Datos obtenidos |
|-------|-------|-----------------|
| 1 | `empresas` | `id`, `rfc`, `razon_social` |
| 2 | `documentos` | Todos los `doc_type` con `datos_extraidos` (JSONs de Dakota), agrupados por tipo |
| 3 | `validaciones_cruzadas` | Dictamen, hallazgos, recomendaciones y `resumen_bloques` de Colorado |

El resultado es un `ExpedientePLD` con:
- Documentos indexados por tipo (`acta_constitutiva`, `csf`, `poder`, `ine`, `fiel`, `domicilio`, etc.)
- `datos_clave` extraídos del `resumen_bloques` de Colorado (datos ya validados cruzadamente)
- Resultado de validación cruzada de Colorado (dictamen + hallazgos)

### Paso 2 — Etapa 1: Completitud documental (`etapa1_completitud.py`)

Verifica que el expediente cumpla con la **Disposición 4ª de las DCG del art. 115 de la Ley de Instituciones de Crédito**.  
Ejecuta 6 verificaciones secuenciales:

| # | Verificación | Categoría | Qué revisa |
|---|-------------|-----------|------------|
| 1 | Documentos obligatorios | `DOCUMENTO` | Presencia de acta, CSF, domicilio, poder, INE, FIEL. Acepta alternativos: `domicilio_rl`/`domicilio_propietario_real`/`estado_cuenta` para domicilio, `ine_propietario_real` para INE |
| 2 | Datos obligatorios | `DATO_OBLIGATORIO` | Razón social, RFC, FIEL nº serie, giro, fecha constitución. **Prioriza `datos_clave` de Colorado** sobre documentos raw |
| 3 | Domicilio completo | `DOMICILIO` | Calle, número, colonia, CP, municipio, entidad, país |
| 4 | Personas identificadas | `PERSONAS` | Apoderados, representantes legales, accionistas, consejeros |
| 5 | Poder bancario | `PODER_BANCARIO` | Busca 32 keywords en las facultades del poder ("abrir cuentas", "operaciones bancarias", etc.) |
| 6 | Validación cruzada | `VALIDACION_CRUZADA` | Lee resultado de Colorado: 10 bloques de validación |

Cada item tiene severidad (`CRITICA`, `ALTA`, `MEDIA`, `INFORMATIVA`) y un código (`A1.x`, `A2.x`, etc.).

**Dictamen Etapa 1:**
- `COMPLETO` → 0 faltantes
- `PARCIAL` → 0 faltantes críticos pero hay faltantes menores
- `INCOMPLETO` → hay faltantes críticos

El sistema de **alias de campos** normaliza las diferencias entre los nombres que Dakota extrae y los que Arizona espera (ej. `numero_serie_certificado` → `no_serie`).

### Paso 3 — Etapa 2: Screening contra listas negras (`blacklist_screening.py`)

Para cada persona identificada en Etapa 1 (razón social, apoderados, representantes, accionistas), se cruza contra 3 tablas en **SQL Server** (`Siglonet_PagaTodo` vía pyodbc):

| Tabla | Lista | Consecuencia |
|-------|-------|-------------|
| `CatPLD69BPerson` | Lista 69-B SAT (EFOS/EDOS) | Alerta roja → posible rechazo |
| `CatPLDLockedPerson` | Personas Bloqueadas UIF | Suspensión inmediata + reporte 24h |
| `TraPLDBlackListEntry` | Consolidada (OFAC, PEP, ONU, etc.) | Bloqueo / EDD obligatoria |

**Sistema anti-homónimos con scoring:**

En México los nombres repetidos son muy comunes. Arizona implementa un sistema de puntuación para cada coincidencia:

| Criterio | Puntos |
|----------|--------|
| RFC exacto | +50 |
| CURP exacto | +50 |
| Nombre completo exacto | +30 |
| Similitud nombre ≥90% | +25 |
| Apellido coincide | +15 c/u |
| Apellido muy común (García, López, etc.) | −5 c/u |
| Solo primer nombre común | −10 |

**Clasificación por score:**

| Score | Nivel | Acción |
|-------|-------|--------|
| ≥90 | `CONFIRMADO` | Bloqueo / rechazo |
| ≥70 | `PROBABLE` | Revisión manual urgente |
| ≥50 | `POSIBLE` | Verificación adicional |
| ≥30 | `HOMONIMO` | Probablemente homónimo |
| <30 | Descartado | No se reporta |

### Paso 4 — Etapa 4: Estructura Accionaria, Beneficiario Controlador y Screening BC (`etapa4_propietarios_reales.py` + `blacklist_screening.py`)

Extrae la estructura accionaria de los documentos (prioridad: reforma de estatutos → acta constitutiva) e identifica:

- **Propietarios Reales** (DCG Art. 115): persona física con ≥25% del capital social
- **Beneficiarios Controladores** (CFF Art. 32-B Ter): persona física con >15%

**Look-through / perforación de cadena:** Si un accionista es persona moral, se multiplica `porcentaje_padre × porcentaje_hijo / 100` recursivamente hasta llegar a personas físicas (máximo 10 niveles, con detección de ciclos).

**Cascada CNBV** (cuando nadie alcanza ≥25%):
1. PF con ≥25% propiedad directa/indirecta
2. Control por otros medios (administrador con poder + acta)
3. Administrador Único o Consejo de Administración (fallback)
4. PF designada si administrador es PM

**Alerta EA004 — Accionista Persona Moral:**  
Si algún accionista es persona moral (detectado por sufijos: S.A., SA DE CV, SAPI, S. DE R.L., etc.), se genera una alerta **crítica** automática que lleva el dictamen a **RECHAZADO**. Fundamento: DCG Art. 115 / CFF Art. 32-B Ter — se requiere look-through hasta identificar a las personas físicas que controlan la PM accionista.

**Screening de Beneficiarios Controladores:**  
Cada BC identificado (≥25%) pasa por el mismo screening de la Etapa 2 (listas 69-B SAT, UIF, PEP) de forma independiente. El resultado se muestra en la sección Etapa 4 del reporte y alimenta el dictamen final. Una coincidencia en el screening BC genera un hallazgo crítico → RECHAZADO.

Se generan alertas automáticas cuando: la suma de porcentajes ≠ 100%, hay PMs sin perforar, la estructura tiene más de 3 niveles, o un accionista es persona moral.

### Paso 5 — Etapa 5: MER PLD/FT v7.0 (Matriz de Evaluación de Riesgos)

Primero, `construir_solicitud_mer()` extrae del expediente los datos necesarios:

| Campo | Fuentes (en orden de prioridad) |
|-------|-------------------------------|
| País constitución | Domicilio CSF → default "México" |
| Fecha constitución | `datos_clave` → acta constitutiva → CSF |
| Actividad económica | `datos_clave.giro_mercantil` → CSF → acta |
| Entidad federativa | Domicilio CSF |
| Alcaldía | Solo si es CDMX |
| Coincidencia LPB | Resultado del screening Etapa 2 |
| PEP | Detección en coincidencias tipo PEP |

Después, `calcular_riesgo_mer()` ejecuta la arquitectura de dos capas:

**CAPA 1 — Determinista** (`mer_calculator.py`):
- Calcula los 15 factores usando catálogos estáticos (`mer_catalogos.py`) + Excel CNBV
- Fórmula: `Puntaje_factor = Valor × Peso × 100`
- Puntaje total: `Σ puntajes de los 15 factores`
- Si algún factor no se resuelve en catálogo → `requiere_llm=True`
- Factores transaccionales (7–12) sin datos → se asumen valores prudenciales + `dato_asumido=True`

**CAPA 2 — Resolución LLM** (solo si hay factores pendientes):
- Factor 4 (actividad económica): `_resolver_actividad_por_rag()` busca keywords en el nombre de la actividad + resultados de Azure AI Search (índice `mer-pld-chunks`)
- Keywords de alto riesgo → Grupo 3 (FACTORING, SOFOM, INTERMEDIACIÓN CREDITICIA, CRIPTO, etc.)
- Keywords de bajo riesgo → Grupo 1 (AGRÍCOLA, EDUCACIÓN, SALUD, etc.)
- Sin match → Grupo 2 (default prudencial)
- `aplicar_resoluciones_llm()` inyecta los valores resueltos y recalcula el puntaje

**Clasificación final:**

| Rango | Grado | Símbolo |
|-------|-------|---------|
| 85–142 pts | BAJO | 🟢 |
| 143–199 pts | MEDIO | 🟡 |
| ≥200 pts | ALTO | 🔴 |

Coincidencia en LPB o listas negativas → **ALTO automático** independientemente del puntaje.

### Paso 6 — Generación de reporte (`report_generator.py`)

El reporte de texto plano (`reporte.txt`, ~18,000 caracteres) se estructura en las siguientes secciones:

| Sección | Contenido |
|---------|-----------|
| Encabezado | Empresa, RFC, fecha, documentos disponibles, base legal |
| Datos clave | Razón social, RFC, representante legal, poder bancario |
| Estructura accionaria | Tabla de accionistas con %, propietarios reales ≥25% |
| **Resumen ejecutivo** | **Dictamen Arizona** + cuadro visual de 5 etapas + conteo de hallazgos |
| Etapa 1 | 5 bloques con veredicto (✅ PASA / ❌ FALLA / ⚠️ CON OBS) |
| Etapa 2 | Detalle por persona: listas consultadas, coincidencias, scores |
| Etapa 3 | Resumen Colorado: dictamen, alertas, validación en portales gubernamentales |
| Etapa 4 | Beneficiarios controladores, look-through PM, cruce con screening |
| Etapa 5 | Tabla de 15 factores MER, puntaje, grado, datos asumidos, alertas |
| Alertas + Recomendaciones | Hallazgos por severidad, acciones requeridas, siguiente paso |

**Dictamen final de Arizona:**
- **RECHAZADO** → hallazgos críticos (screening confirmado, docs faltantes críticos, estructura inconsistente)
- **APROBADO CON OBSERVACIONES** → hallazgos altos/medios, Colorado con observaciones, coincidencias probables
- **APROBADO** → todo limpio

### Paso 7 — Dictamen PLD/FT (`dictamen_generator.py` + `dictamen_txt.py`)

Genera el **Dictamen PLD/FT** completo en dos formatos:

**`dictamen_generator.py`** — Construye el modelo `DictamenPLDFT` (JSON) con 22+ funciones helper:

| Función | Sección del dictamen |
|---------|----------------------|
| `_datos_clave()` | Datos de Colorado/expediente |
| `_construir_domicilio()` | Domicilio fiscal (prioriza `domicilio_fiscal` de CSF) |
| `_extraer_actividad()` | Actividad económica |
| `_extraer_perfil_transaccional()` | Datos de estado de cuenta (montos, frecuencias) |
| `_construir_vigencia_documentos()` | Verificación de vigencia de cada documento |
| `_extraer_detalle_poder()` | Datos notariales del poder (notario, número, estado) |
| `_extraer_folio_mercantil()` | Folio mercantil del acta constitutiva |
| `_extraer_clausula_extranjeros()` | Cláusula de exclusión de extranjeros |
| `_extraer_datos_notariales_acta()` | Número de escritura, notario, entidad del acta |
| `_screening_seccion_para_rol()` | Screening por rol (PM, accionistas, representantes) |

**`dictamen_txt.py`** — Renderiza el dictamen a texto plano (`dictamen_pld.txt`) con 13 secciones:

| # | Sección | Función |
|---|---------|--------|
| 1 | Datos generales PM | `_seccion_persona_moral()` |
| 2 | Screening PM | `_seccion_screening_pm()` |
| 3 | Actividad económica | `_seccion_actividad()` |
| 4 | Domicilio | `_seccion_domicilio()` |
| 5 | Estructura accionaria | `_seccion_estructura_accionaria()` |
| 6 | Propietarios reales / BC | `_seccion_propietarios()` |
| 7 | Representantes legales + poder | `_seccion_representantes()` |
| 8 | Administración / Consejo | `_seccion_administracion()` |
| 9 | Perfil transaccional | `_seccion_perfil_transaccional()` |
| 9-B | Vigencia de documentos | `_seccion_vigencia_documentos()` |
| 10 | Conclusiones PLD/FT | `_seccion_conclusiones()` |

**Campos nuevos en `DictamenPLDFT` (v2.3):**
- `perfil_transaccional` — montos recibidos/enviados, frecuencia, tipo de operaciones
- `vigencia_documentos` — lista de documentos con fechas de emisión/vencimiento
- `detalle_poder_notarial` — notario, número de escritura, estado, fecha
- `conclusiones` — dictamen final estructurado con justificación, EDD, CCC

### Paso 8 — Persistencia (`persistence.py`)

El resultado se guarda en la tabla `analisis_pld` de PostgreSQL (UPSERT para permitir re-ejecuciones sin duplicados):
- `empresa_id`, `etapa`, `dictamen`, `hallazgos`, `puntaje_mer`, `grado_riesgo`
- `resultado_completo` (JSON completo del análisis)
- `tiempo_pipeline_ms` (duración total del pipeline)
- Timestamp de creación/actualización

Finalmente, el endpoint retorna un `PlainTextResponse` con el reporte de texto completo.

### Diagrama de dependencias entre archivos

```
main.py
  ├── router.py ────────────── data_loader.py ──── [PostgreSQL: kyb]
  │     │                       │
  │     ├── etapa1_completitud.py ←── config.py (DOCS_OBLIGATORIOS, CAMPOS_ALIAS)
  │     │     └── schemas.py (ExpedientePLD, VerificacionCompletitud)
  │     │
  │     ├── blacklist_screening.py ── [SQL Server: Siglonet_PagaTodo]
  │     │     ↑ (reutilizado para screening BC en Etapa 4)
  │     │
  │     ├── etapa4_propietarios_reales.py ── (alertas EA004 PM)
  │     │     └── router.py: _construir_personas_bc() → screening BC
  │     │
  │     ├── mer_engine.py
  │     │     ├── mer_calculator.py ── mer_catalogos.py ── [Excel CNBV 2025]
  │     │     └── mer_search.py ────── [Azure AI Search: mer-pld-chunks]
  │     │
  │     ├── report_generator.py
  │     │
  │     └── persistence.py ─────────── [PostgreSQL: analisis_pld]
  │
  └── mer_router.py ──── mer_engine.py (reuso)
```

---

## Desarrollo Técnico — Paso a Paso

### 1. Sistema de Alias de Campos

Dakota extrae datos de documentos usando Azure Document Intelligence, pero los nombres de los campos pueden variar según el tipo de documento y la versión del modelo. Arizona implementa un **sistema de alias** para normalizar estos campos.

**Archivo:** `core/config.py`

```python
# Mapea nombre_arizona -> [alias_dakota1, alias_dakota2, ...]
CAMPOS_ALIAS: dict[str, list[str]] = {
    # CSF
    "denominacion_razon_social": ["razon_social", "nombre_razon_social", "denominacion_social"],
    "domicilio": ["domicilio_fiscal"],
    # FIEL
    "no_serie": ["numero_serie_certificado", "numero_serie", "serie_certificado"],
    # Acta constitutiva
    "objeto_social": ["giro_mercantil", "actividad_principal", "objeto"],
    "fecha_constitucion": ["fecha_creacion", "fecha_escritura"],
    # Domicilio
    "numero_exterior": ["num_exterior", "no_exterior", "numero_ext"],
    "municipio_delegacion": ["municipio", "delegacion", "alcaldia", "ciudad"],
    "entidad_federativa": ["estado", "entidad"],
    "codigo_postal": ["cp", "c_p"],
    # Actividad económica
    "actividad_economica": ["giro_mercantil", "actividades_economicas", "giro"],
}
```

**Función de extracción con alias:** `services/etapa1_completitud.py`

```python
def _get_valor(datos: dict[str, Any], campo: str) -> Any:
    """Extrae el valor de un campo de datos_extraidos.
    
    Dakota almacena campos con formato enriched:
      {"campo": {"valor": X, "confiabilidad": Y}}
    Esta función desenvuelve automáticamente ese formato.
    También busca alias de campos definidos en CAMPOS_ALIAS.
    """
    if not datos:
        return None
    
    # Buscar campo principal y sus alias
    campos_a_buscar = [campo] + CAMPOS_ALIAS.get(campo, [])
    
    for c in campos_a_buscar:
        field = datos.get(c)
        if field is not None:
            if isinstance(field, dict) and "valor" in field:
                v = field.get("valor")
                if v is not None and v != "" and v != "N/A":
                    return v
            elif field not in (None, "", "N/A"):
                return field
    return None
```

---

### 2. Integración con `datos_clave` de Colorado

Para evitar reprocesar documentos y optimizar el uso de recursos Azure, Arizona **prioriza** leer los `datos_clave` que Colorado ya validó durante la validación cruzada.

**Flujo de datos optimizado:**

```
Dakota (Azure DI)     Colorado (Validación)      Arizona (PLD)
      │                       │                       │
      │  datos_extraidos      │                       │
      ├──────────────────────▶│                       │
      │                       │  Extrae datos_clave   │
      │                       │  (ya validados)       │
      │                       │                       │
      │                       │  resumen_bloques      │
      │                       ├──────────────────────▶│
      │                       │  ↳ datos_clave        │
      │                       │                       │
      │                       │                       │  Lee datos_clave
      │                       │                       │  (0 llamadas Azure)
      │                       │                       │
      │    Fallback: lee datos_extraidos              │
      │◀──────────────────────────────────────────────│
      │    (solo si datos_clave no tiene el campo)    │
```

**Campos disponibles en `datos_clave`:**

| Campo | Descripción | Fuente original |
|-------|-------------|-----------------|
| `razon_social` | Razón social validada | CSF, Acta, FIEL |
| `rfc` | RFC con homoclave | CSF |
| `numero_serie_fiel` | Número de serie del certificado FIEL | FIEL |
| `giro_mercantil` | Actividad económica/objeto social | CSF, Acta |
| `fecha_constitucion` | Fecha de constitución | Acta constitutiva |
| `domicilio` | Domicilio estructurado | CSF, Comprobante |

**Implementación en Etapa 1:** `services/etapa1_completitud.py`

```python
def _verificar_datos_obligatorios(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    """Verifica los datos obligatorios de la Persona Moral.
    Prioriza datos_clave de Colorado (ya validados) sobre documentos raw.
    """
    dc = expediente.datos_clave
    
    # Mapa: (nombre_display, campo_datos_clave, doc_fallback, campo_fallback)
    campos_con_dc = [
        ("Denominación / razón social", "razon_social", "csf", "denominacion_razon_social"),
        ("RFC con homoclave", "rfc", "csf", "rfc"),
        ("e.firma (FIEL) — número de serie", "numero_serie_fiel", "fiel", "no_serie"),
        ("Objeto social / giro mercantil", "giro_mercantil", "csf", "actividad_economica"),
        ("Fecha de constitución", "fecha_constitucion", "acta_constitutiva", "fecha_constitucion"),
    ]
    
    for nombre, campo_dc, doc_fallback, campo_fallback in campos_con_dc:
        valor, fuente, presente = "", "", False
        
        # 1. Intentar datos_clave primero (ya validados por Colorado)
        if dc and isinstance(dc, dict):
            val_dc = dc.get(campo_dc)
            if val_dc and str(val_dc).strip() not in ("", "N/A", "None"):
                valor = str(val_dc).strip()
                fuente = "datos_clave"
                presente = True
        
        # 2. Fallback a documentos raw (solo si no encontró en datos_clave)
        if not presente:
            datos_doc = _obtener_datos(expediente, doc_fallback)
            valor = _get_valor_str(datos_doc, campo_fallback)
            # ...
```

---

### 3. Verificación de Completitud Documental

Implementación completa de la **Disposición 4ª de las DCG del artículo 115 de la Ley de Instituciones de Crédito**.

**Documentos obligatorios definidos en:** `core/config.py`

```python
DOCS_OBLIGATORIOS_PLD: list[str] = [
    "acta_constitutiva",
    "csf",
    "domicilio",
    "poder",
    "ine",
]

# Alternativas para comprobante de domicilio
DOCS_DOMICILIO_ALTERNATIVOS: list[str] = ["domicilio", "estado_cuenta"]
```

**Verificación con alternativas:**

```python
def _verificar_documentos(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    for doc_type in DOCS_OBLIGATORIOS_PLD:
        # Caso especial: domicilio acepta alternativas
        if doc_type == "domicilio":
            tiene_domicilio = any(
                alt in expediente.doc_types_presentes
                for alt in DOCS_DOMICILIO_ALTERNATIVOS
            )
            # estado_cuenta también vale como comprobante de domicilio
```

---

### 4. Detección de Poder Bancario

Verifica si el poder del representante legal incluye facultades para operar cuentas bancarias.

```python
_KEYWORDS_PODER_BANCARIO: list[str] = [
    "abrir cuentas", "apertura de cuentas", "cuentas bancarias",
    "contratos bancarios", "operaciones bancarias", "instituciones de crédito",
    "abrir, cerrar y manejar cuentas", "firmar contratos bancarios",
]

def _detectar_poder_bancario(expediente: ExpedientePLD) -> bool | None:
    # 1. Primero revisar si Colorado ya lo determinó
    if expediente.datos_clave:
        poder_bc = expediente.datos_clave.get("poder_cuenta_bancaria")
        if poder_bc is not None:
            return poder_bc

    # 2. Buscar en datos del poder directamente
    poder = _obtener_datos(expediente, "poder")
    campos_texto = ["facultades", "tipo_poder", "alcance_poder", "objeto_poder"]
    for campo in campos_texto:
        valor = _get_valor_str(poder, campo).lower()
        for kw in _KEYWORDS_PODER_BANCARIO:
            if kw in valor:
                return True
    return False
```

---

### 5. Identificación de Personas (Administradores/Apoderados)

Extrae y unifica información de administradores, consejo de administración y apoderados de múltiples fuentes.

```python
def _identificar_personas(expediente: ExpedientePLD) -> list[PersonaIdentificada]:
    personas: list[PersonaIdentificada] = []
    
    # 1. Administrador único (Acta)
    admin = _get_valor(acta, "administrador_unico")
    
    # 2. Consejo de administración (Acta + Reforma)
    consejo = _get_valor(acta, "consejo_administracion") or []
    
    # 3. Apoderados (Poder)
    apoderado = _get_valor_str(poder, "nombre_apoderado")
    
    # 4. Representante legal (CSF / datos_clave)
    rep = _get_valor_str(csf, "representante_legal")
    
    # Evitar duplicados por (nombre normalizado, rol)
    nombres_vistos: set[tuple[str, str]] = set()
```

---

### 6. Verificación de Domicilio Completo

Verifica que el domicilio tenga todos los componentes requeridos.

```python
CAMPOS_DOMICILIO: list[tuple[str, str]] = [
    ("calle", "calle"),
    ("numero_exterior", "numero_exterior"),
    ("colonia", "colonia"),
    ("codigo_postal", "codigo_postal"),
    ("municipio_delegacion", "municipio_delegacion"),
    ("entidad_federativa", "entidad_federativa"),
]

def _verificar_domicilio_completo(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    # 1. Intentar datos_clave.domicilio primero (ya validado)
    dc = expediente.datos_clave
    if dc and dc.get("domicilio"):
        dom_dc = dc["domicilio"]
        # Verificar campos del domicilio estructurado
    
    # 2. Fallback: buscar en CSF → comprobante de domicilio
    for doc_type in ["csf", "domicilio", "estado_cuenta"]:
        domicilio = _extraer_domicilio(expediente, doc_type)
```

---

### 7. Modelo de Datos (Pydantic)

**Archivo:** `models/schemas.py`

```python
class SeveridadPLD(str, Enum):
    CRITICA = "CRITICA"      # Bloquea aprobación
    ALTA = "ALTA"            # Requiere atención inmediata
    MEDIA = "MEDIA"          # Debe corregirse
    BAJA = "BAJA"            # Observación menor

class ItemCompletitud(BaseModel):
    codigo: str              # PLD1.01, PLD1.02, etc.
    categoria: str           # DOCUMENTO, DATO, DOMICILIO, PERSONA, PODER
    elemento: str            # Descripción del elemento verificado
    presente: bool           # ¿Está completo?
    fuente: str              # doc_type o "datos_clave"
    detalle: str             # Información adicional
    severidad: SeveridadPLD  # Nivel de criticidad

class ResultadoCompletitud(BaseModel):
    empresa_id: str
    razon_social: str
    etapa: str = "ETAPA_1"
    dictamen: Literal["COMPLETO", "INCOMPLETO", "REQUIERE_REVISION"]
    items: list[ItemCompletitud]
    total_items: int
    items_presentes: int
    items_faltantes: int
    porcentaje_completitud: float
    personas_identificadas: list[PersonaIdentificada]
    tiene_poder_bancario: bool | None
    timestamp: datetime
```

---

### 8. Carga de Expediente desde BD

**Archivo:** `services/data_loader.py`

```python
async def cargar_expediente(empresa_id: str) -> ExpedientePLD:
    """Carga el expediente completo de una empresa desde la BD.
    
    Lee de:
    - tabla `empresas` → información básica
    - tabla `documentos` → doc_types y datos_extraidos
    - tabla `validaciones_cruzadas` → resumen_bloques.datos_clave
    """
    async with pool.acquire() as conn:
        # 1. Cargar empresa
        empresa = await conn.fetchrow(
            "SELECT id, razon_social FROM empresas WHERE id = $1", empresa_id
        )
        
        # 2. Cargar documentos con datos extraídos
        docs = await conn.fetch(
            """SELECT doc_type, datos_extraidos 
               FROM documentos 
               WHERE empresa_id = $1""", empresa_id
        )
        
        # 3. Cargar datos_clave de la última validación cruzada
        validacion = await conn.fetchrow(
            """SELECT resumen_bloques 
               FROM validaciones_cruzadas 
               WHERE empresa_id = $1 
               ORDER BY created_at DESC LIMIT 1""", empresa_id
        )
        
        datos_clave = validacion["resumen_bloques"].get("datos_clave", {})
```

---

### 9. Suite de Tests (152 tests)

**Archivos:** `tests/test_etapa1.py`, `tests/test_etapa4.py`, `tests/test_mer_calculator.py`

Cobertura completa de:

| Categoría | Tests | Descripción |
|-----------|-------|-------------|
| Documentos | 15 | Presencia de docs obligatorios, alternativas de domicilio |
| Datos obligatorios | 20 | RFC, razón social, FIEL, fecha constitución |
| Sistema de alias | 12 | Mapeo de campos Dakota → Arizona |
| datos_clave | 10 | Priorización de datos validados por Colorado |
| Domicilio | 15 | Componentes completos, fuzzy matching |
| Personas | 8 | Extracción de admin/apoderados, deduplicación |
| Poder bancario | 6 | Detección de keywords en facultades |

**Tests Etapa 4:** `tests/test_etapa4.py` — 38 tests (propietarios reales, cascada CNBV, look-through, ciclos)

**Tests MER:** `tests/test_mer_calculator.py`

| Categoría | Tests | Descripción |
|-----------|-------|-------------|
| Valor tipo persona | 8 | PM, SAPI, SOFOM, PFAE, PF, defaults |
| Antigüedad | 3 | >3 años, 1–3 años, <1 año |
| Producto | 4 | Corporativa, Ya Ganaste, Fundadores, desconocido |
| Caso Capital X | 5 | Cálculo completo, puntaje 150.0, grado MEDIO, datos asumidos, alerta SAPI |
| Clasificación | 2 | Umbrales BAJO/MEDIO/ALTO, LPB → ALTO |
| Serialización | 2 | resultado_a_dict, opciones para factores pendientes |
| Resolución LLM | 2 | Aplicar valores, no alterar factores fijos |
| Pesos | 2 | Suma 1.10, siempre 15 factores |

**Ejecución:**
```bash
cd Arizona && python -m pytest pld_agent/tests/ -v
# 152 passed
```

---

### 10. Optimización de Recursos Azure

Arizona **no hace llamadas a Azure**. Toda la extracción la hace Dakota (con caché) y Colorado valida. Arizona solo lee de la BD:

| Agente | Llamadas Azure | Caché |
|--------|---------------|-------|
| Dakota | Azure DI + Azure OpenAI | ✅ Implementado (optimizer.py) |
| Colorado | Azure (portal SAT, captcha) | Solo runtime |
| Arizona | **0 llamadas** | Lee de BD |

**Beneficio:** Un expediente reprocesado **no genera llamadas Azure adicionales** si ya pasó por Dakota+Colorado.

---

## Proceso PLD — 8 Etapas

### Etapa 1 — Recepción y verificación de completitud documental
**Estado: ✅ Implementada**

El analista PLD confirma que el expediente contiene todos los elementos que exige la **Disposición 4ª de las DCG del artículo 115 de la Ley de Instituciones de Crédito**:

**Datos obligatorios de la Persona Moral:**
| # | Dato | Fuente en Dakota |
|---|---|---|
| 1 | Denominación o razón social | CSF → `denominacion_razon_social`, Acta → `denominacion_social` |
| 2 | RFC con homoclave | CSF → `rfc` |
| 3 | Número de serie de e.firma (FIEL) | FIEL → `no_serie`, `no_certificado` |
| 4 | País de constitución | Acta → `lugar_otorgamiento`, default "México" |
| 5 | Giro mercantil / objeto social | Acta → `objeto_social`, CSF → `actividad_economica` |
| 6 | Domicilio completo | CSF → domicilio, Comprobante de domicilio |
| 7 | Fecha de constitución | Acta → `fecha_constitucion` |
| 8 | Administradores / directores / apoderados legales | Acta → `administracion`, Poder → `nombre_apoderado`, Reforma → `consejo_administracion` |

**Documentos soporte obligatorios:**
| # | Documento | `doc_type` en Dakota |
|---|---|---|
| 1 | Testimonio de escritura constitutiva (inscrita en RPP) | `acta_constitutiva` |
| 2 | Cédula de Identificación Fiscal (CSF) | `csf` |
| 3 | Comprobante de domicilio | `domicilio` o `estado_cuenta` |
| 4 | Testimonio de instrumento con poderes del representante legal | `poder` |
| 5 | Identificación oficial vigente del representante legal | `ine` |

**Documentos adicionales para clientes de alto riesgo:**
| # | Documento | Notas |
|---|---|---|
| 1 | Estados financieros (2 últimos ejercicios) | Pendiente de integración |
| 2 | Declaraciones anuales al SAT (2 últimas) | Pendiente de integración |
| 3 | Detalle de accionistas principales | Ya se extrae de Acta/Reforma → `estructura_accionaria` |

**Fuentes de datos:**
- Tabla `documentos` → `datos_extraidos` (campos extraídos por Dakota)
- Tabla `validaciones_cruzadas` → `hallazgos`, `dictamen`, `resumen_bloques` (resultados de Colorado)
- Tabla `validaciones_cruzadas` → `resumen_bloques.datos_clave` (datos clave consolidados)

---

### Etapa 2 — Screening contra listas (barrera crítica)
**Estado: ✅ Implementada**

Cruce de nombres contra listas obligatorias PLD/AML:
| Lista | Consecuencia | Fuente |
|---|---|---|
| **LPB** (Lista de Personas Bloqueadas - UIF) | Suspensión inmediata + reporte 24h | `CatPLDLockedPerson` |
| **OFAC/ONU** (Sanciones internacionales) | Bloqueo | `TraPLDBlackListEntry` |
| **PEP** (Personas Expuestas Políticamente) | EDD obligatoria, no impide relación | `TraPLDBlackListEntry` |
| **Lista 69-B SAT** (EFOS/EDOS) | Alerta roja → posible rechazo | `CatPLD69BPerson` |

**Personas a verificar:** razón social (PM), apoderados, representantes legales, accionistas, beneficiarios controladores.

**Implementación:** `services/blacklist_screening.py` — Servicio completo con sistema de scoring para manejo de homónimos.

---

---

### Screening contra Listas Negras (Etapa 2)

**Archivo:** `services/blacklist_screening.py`

Servicio de screening contra las listas negras PLD/AML con **sistema de scoring para manejo de homónimos**.

#### Conexión a SQL Server

```python
# Variables de entorno (.env)
BLACKLIST_DB_HOST=172.26.3.5
BLACKLIST_DB_PORT=1433
BLACKLIST_DB_USER=usrSiglo
BLACKLIST_DB_PASS=****
BLACKLIST_DB_NAME=Siglonet_PagaTodo
BLACKLIST_DB_DRIVER=ODBC Driver 17 for SQL Server
```

#### Tablas consultadas

| Tabla | Contenido | Campos clave |
|-------|-----------|---------------|
| `CatPLD69BPerson` | Lista 69-B SAT (EFOS/EDOS) | `Name`, `RFC`, `SituacionId` |
| `CatPLDLockedPerson` | Personas Bloqueadas UIF | `Name`, `Type` (F/M) |
| `TraPLDBlackListEntry` | Lista Negra Consolidada (OFAC, PEP, etc.) | `Name`, `ListId` |

#### Sistema de Scoring para Homónimos

En México los nombres repetidos son muy comunes. El sistema implementa un scoring para diferenciar coincidencias verdaderas de homónimos:

```python
# Puntos por coincidencia
RFC_EXACTO = +50        # Confirma identidad
CURP_EXACTO = +50       # Confirma identidad
NOMBRE_EXACTO = +30     # Alta probabilidad
SIMILITUD_90 = +25      # Similitud >90%
APELLIDO_PATERNO = +15  # Coincide apellido paterno
APELLIDO_MATERNO = +15  # Coincide apellido materno

# Penalizaciones
APELLIDO_COMUN = -5     # García, López, Martínez, etc.

# Umbrales de decisión
CONFIRMADO = score >= 90   # Match confirmado → bloqueo
PROBABLE = score >= 70     # Requiere revisión manual urgente
POSIBLE = score >= 50      # Requiere verificación adicional
HOMONIMO = score >= 30     # Probablemente homónimo
DESCARTAR = score < 30     # Coincidencia descartada
```

**Apellidos comunes (penalizados):**
```python
APELLIDOS_COMUNES = {
    "garcia", "hernandez", "martinez", "lopez", "gonzalez",
    "rodriguez", "perez", "sanchez", "ramirez", "torres",
    "flores", "rivera", "gomez", "diaz", "cruz", "morales",
    "reyes", "ortiz", "gutierrez", "chavez"
}
```

#### Uso del servicio

```python
from services.blacklist_screening import (
    BlacklistScreeningService, PersonaBuscada
)

service = BlacklistScreeningService()  # Carga config desde .env
service.conectar()

# Persona a buscar
persona = PersonaBuscada(
    nombre="ARTURO PONS AGUIRRE",
    rfc="POAA790101XXX",
    curp=None,
    tipo_persona="fisica",
    rol="apoderado"
)

# Ejecutar screening
coincidencias = service.buscar_persona(persona)

for c in coincidencias:
    print(f"{c.nivel}: {c.score} pts - {c.lista}")
    print(f"  Explicación: {c.explicacion}")

service.cerrar()
```

#### Integración con reporte

La Etapa 2 se integra automáticamente al generar el reporte PLD:

```
ETAPA 2 — SCREENING CONTRA LISTAS NEGRAS (PLD/AML)
======================================================================
  Total personas verificadas:      7
  Personas con coincidencias:      0
  Coincidencias confirmadas:       0
  Coincidencias probables:         0

  📋 DETALLE POR PERSONA
  ✅ SOLUCIONES CAPITAL X (empresa, moral)
  ✅ Arturo Pons Aguirre (apoderado, fisica)
  ✅ ARTURO PONS AGUIRRE (accionista, fisica)
  ...
```

---

### Etapa 3 — Verificación de datos y existencia legal
**Estado: 🔲 Pendiente (parcialmente cubierta por Colorado)**

- RFC activo en SAT (no cancelado) → **Colorado V10.2 ya valida estatus**
- CURP de personas físicas contra RENAPO
- INE contra lista nominal del INE → **Colorado V10.3 ya valida (portal listanominal.ine.mx)**
- Existencia legal en Registro Público de Comercio
- Razón social RFC vs. Acta Constitutiva → **Colorado V1.1/V1.2 ya valida**

---

### Etapa 4 — Identificación del beneficiario controlador
**Estado: ✅ Implementada**

Identificación de beneficiarios controladores y screening independiente contra listas PLD:

- Persona física con ≥25% del capital social o derechos de voto (directo o indirecto)
- Look-through para personas morales accionistas (recursivo, máx. 10 niveles)
- Si nadie cumple ≥25%, el administrador/consejo es beneficiario controlador (cascada CNBV)
- Cada beneficiario controlador pasa por screening completo (Etapa 2 aplicada a BCs)
- **Alerta EA004** (crítica): cualquier accionista persona moral → RECHAZADO
- **Screening BC**: resultados se muestran en Etapa 4 del reporte y alimentan el dictamen final

**Implementación:**
- `services/etapa4_propietarios_reales.py` — Estructura accionaria, look-through, cascada CNBV, alertas EA004
- `api/router.py` — `_construir_personas_bc()` + screening independiente de BCs
- `services/report_generator.py` — Renderizado de screening BC en Etapa 4 + `_mostrar_screening_bc_persona()`

---

### Etapa 5 — Evaluación de riesgo MER PLD/FT v7.0
**Estado: ✅ Implementada**

Matriz de Evaluación de Riesgos (MER) con arquitectura de dos capas:

**CAPA 1 — Calculador determinista** (`services/mer_calculator.py`):
- 15 factores de riesgo evaluados con código Python puro
- Búsqueda en catálogos (`services/mer_catalogos.py`) + Excel CNBV
- Aritmética: `valor × peso × 100` por factor, suma total, clasificación
- Umbrales PM: BAJO (85–142), MEDIO (143–199), ALTO (200–255)
- LPB/listas negativas → ALTO automático
- Factores sin datos → `dato_asumido=True` con valor prudencial
- Factor no resuelto en catálogo → `requiere_llm=True`

**CAPA 2 — Resolución LLM** (`services/mer_engine.py`):
- Solo interviene en factores marcados `requiere_llm=True`
- `_resolver_actividad_por_rag()` busca actividad en índice RAG + keywords
- LLM elige un valor (1, 2 o 3); el código recalcula con `aplicar_resoluciones_llm()`
- El LLM **nunca** hace multiplicaciones, sumas ni clasificaciones

| Factor | Nombre | Peso |
|--------|--------|------|
| 1 | Tipo de persona | 0.10 |
| 2 | Nacionalidad | 0.05 |
| 3 | Antigüedad (fecha constitución) | 0.05 |
| 4 | Giro o actividad económica | 0.15 |
| 5 | Ubicación geográfica del domicilio | 0.10 |
| 6 | Productos y servicios | 0.05 |
| 7 | Volumen — monto recursos recibidos | 0.05 |
| 8 | Volumen — monto recursos enviados | 0.05 |
| 9 | Frecuencia — operaciones recibidas | 0.05 |
| 10 | Frecuencia — operaciones enviadas | 0.05 |
| 11 | Origen de los recursos | 0.05 |
| 12 | Destino de los recursos | 0.05 |
| 13 | Coincidencia LPB | 0.10 |
| 14 | Coincidencia listas/noticias negativas | 0.10 |
| 15 | PEP | 0.10 |

**Tests:** 28 tests en `tests/test_mer_calculator.py`

---

### Etapa 6 — Búsqueda de noticias adversas (adverse media)
**Estado: 🔲 Pendiente**

- Consulta de fuentes abiertas y bases comerciales
- Búsqueda de vínculos con: actividades criminales, corrupción, fraude, lavado de dinero, investigaciones judiciales, sanciones
- Recomendación de la Guía Anticorrupción CNBV (2020) y buena práctica GAFI
- Aplica a: razón social, representantes, apoderados, accionistas significativos

---

### Etapa 7 — Dictamen PLD/FT
**Estado: ✅ Implementada (v2.3)**

Generación del dictamen formal PLD/FT con análisis integral:

| Dictamen | Descripción |
|---|---|
| `APROBADO` | Sin hallazgos en listas, riesgo bajo/medio, expediente completo |
| `APROBADO CON OBSERVACIONES` | Hallazgos altos/medios, requiere Enhanced Due Diligence |
| `RECHAZADO` | Coincidencia confirmada en LPB/OFAC/ONU, estructura inconsistente, o riesgo inaceptable |

**Implementación:**
- `services/dictamen_generator.py` — Construcción del modelo `DictamenPLDFT` (22+ helpers)
- `services/dictamen_txt.py` — Renderizado a texto plano (13 secciones formales)
- `models/dictamen_schemas.py` — Modelos Pydantic del dictamen
- Endpoints: `GET /dictamen/{id}` (JSON), `GET /dictamen/{id}/txt` (texto)

**Contenido del dictamen:**
- Datos generales de persona moral (folio mercantil, datos notariales, cláusula extranjeros)
- Estructura accionaria vigente con screening por accionista
- Propietarios reales / beneficiarios controladores
- Representantes legales con detalle de poder notarial
- Perfil transaccional (estado de cuenta)
- Vigencia de documentos
- Conclusiones con justificación, indicadores EDD y CCC

---

### Etapa 8 — Documentación y conservación
**Estado: 🔲 Pendiente**

- Registro completo de análisis: consultas, evidencia, justificación, decisión
- Conservación: **5 años** (sector financiero CNBV) desde última operación
- **10 años** para actividades vulnerables (LFPIORPI reforma 2025)
- Tiempos estándar: 3-10 días hábiles (riesgo bajo/medio), 30-60 días (EDD)

---

## Estructura del proyecto

```
Arizona/
└── pld_agent/
    ├── __init__.py
    ├── main.py                 # FastAPI app + CLI (puerto 8012)
    ├── pyproject.toml
    ├── README.md
    ├── core/
    │   ├── __init__.py
    │   ├── config.py           # Variables de entorno y constantes
    │   └── database.py         # Pool asyncpg (misma BD que Colorado)
    ├── models/
    │   ├── __init__.py
    │   └── schemas.py          # Modelos Pydantic (Etapa1Result, etc.)
    ├── services/
    │   ├── __init__.py
    │   ├── data_loader.py         # Carga expediente + validación cruzada desde BD
    │   ├── etapa1_completitud.py  # Verificación de completitud documental
    │   ├── etapa4_propietarios_reales.py  # Cálculo de propietarios reales
    │   ├── blacklist_screening.py # Screening contra listas negras (SQL Server)
    │   ├── mer_calculator.py      # Calculador determinista MER (CAPA 1)
    │   ├── mer_catalogos.py       # Catálogos MER (pesos, países, entidades, actividades)
    │   ├── mer_engine.py          # Orquestador MER (CAPA 2 — resolución LLM)
    │   ├── mer_search.py          # Azure AI Search para RAG MER
    │   ├── report_generator.py    # Generador de reportes PLD (reporte.txt)
    │   ├── dictamen_generator.py  # Generador del dictamen PLD/FT (JSON)
    │   ├── dictamen_txt.py        # Renderizador del dictamen a texto plano
    │   └── persistence.py         # Persistencia de análisis PLD
    ├── api/
    │   ├── __init__.py
    │   ├── router.py           # Endpoints REST (pipeline completo)
    │   └── mer_router.py       # Endpoints REST (MER standalone)
    ├── models/
    │   ├── __init__.py
    │   ├── schemas.py          # Modelos Pydantic (ExpedientePLD, etc.)
    │   ├── mer_schemas.py      # Modelos MER (SolicitudMER, ResultadoMER, FactorRiesgo)
    │   └── dictamen_schemas.py # Modelos Dictamen PLD/FT (DictamenPLDFT, ScreeningSeccion, etc.)
    ├── docs/
    │   └── Modelo de riesgo de los clientes 2025.xlsx  # Catálogo CNBV actividades
    └── tests/
        ├── __init__.py
        ├── test_etapa1.py         # Tests unitarios Etapa 1
        ├── test_etapa4.py         # Tests unitarios Etapa 4
        └── test_mer_calculator.py # Tests unitarios MER (28 tests)
```

## Ejecución

```bash
# Servidor unificado Arizona (PLD + Compliance en puerto 8012)
cd Arizona && python -m uvicorn main:app --host 127.0.0.1 --port 8012 --reload

# Tests del módulo PLD
cd Arizona && python -m pytest pld_agent/tests/ -v
```

> **Nota:** Ya no se ejecuta `pld_agent.main:app` por separado. El entry point
> unificado es `Arizona/main.py` que monta ambos routers (PLD + Compliance).

## Base de datos

**PostgreSQL (`kyb`)** — Misma BD que Dakota y Colorado:
- Lee de: `empresas`, `documentos`, `validaciones_cruzadas`
- Escribirá en: `analisis_pld` (migración pendiente)

**SQL Server (`Siglonet_PagaTodo`)** — Listas negras PLD:
- Server: `172.26.3.5:1433`
- Tablas: `CatPLD69BPerson`, `CatPLDLockedPerson`, `TraPLDBlackListEntry`
- Driver: ODBC Driver 17 for SQL Server
- Dependencia: `pyodbc`

## Marco regulatorio

- **Ley de Instituciones de Crédito** — Art. 115, Disposición 4ª DCG
- **LFPIORPI** — Ley Federal para la Prevención e Identificación de Operaciones con Recursos de Procedencia Ilícita
- **CNBV** — Guía Anticorrupción (2020)
- **GAFI/FATF** — Recomendaciones 10, 24, 25
- **UIF** — Lineamientos de la Unidad de Inteligencia Financiera

---

## Historial de Desarrollo

### v1.0.0 — Etapa 1 Completa (Marzo 2026)

**Funcionalidades implementadas:**

| Componente | Descripción | Estado |
|------------|-------------|--------|
| Sistema de aliases | Mapeo de campos Dakota → Arizona normalizados | ✅ |
| Integración datos_clave | Prioriza datos validados por Colorado | ✅ |
| Verificación documentos | 5 docs obligatorios + alternativas domicilio | ✅ |
| Verificación datos | RFC, razón social, FIEL, fecha constitución, giro | ✅ |
| Domicilio completo | 6 componentes requeridos con fuzzy matching | ✅ |
| Identificación personas | Extracción admin/apoderados con deduplicación | ✅ |
| Detección poder bancario | Keywords en facultades del poder | ✅ |
| Modelo de dictamen | COMPLETO / INCOMPLETO / REQUIERE_REVISION | ✅ |
| Suite de tests | 86 tests unitarios | ✅ |

**Optimizaciones:**

1. **Zero Azure calls** — Arizona no hace llamadas a Azure; todo se lee de BD
2. **Priorización datos_clave** — Usa datos ya validados por Colorado antes de parsear documentos raw
3. **Sistema de aliases** — Tolera variaciones en nombres de campos de Dakota

**Archivos clave modificados:**

| Archivo | Cambios |
|---------|---------|
| `core/config.py` | Constantes PLD, aliases de campos, docs obligatorios |
| `services/etapa1_completitud.py` | Lógica completa de verificación (870 LOC) |
| `services/data_loader.py` | Carga expediente + datos_clave desde BD |
| `models/schemas.py` | Modelos Pydantic para resultados |
| `tests/test_etapa1.py` | 86 tests con cobertura completa |

**Dependencias de pipeline:**

```
Dakota (extracción)  →  Colorado (validación)  →  Arizona (PLD)
     │                        │                       │
     └── datos_extraidos ────▶│                       │
                              └── datos_clave ───────▶│
                                                      │
                              ◀── Solo lectura BD ────┘
```

### v1.1.0 — Etapa 2 Screening Listas Negras (Marzo 2026)

**Funcionalidades implementadas:**

| Componente | Descripción | Estado |
|------------|-------------|--------|
| Conexión SQL Server | pyodbc a BD Siglonet_PagaTodo (172.26.3.5) | ✅ |
| Lista 69-B SAT | Consulta CatPLD69BPerson (EFOS/EDOS) | ✅ |
| Bloqueados UIF | Consulta CatPLDLockedPerson | ✅ |
| Lista Negra Consolidada | Consulta TraPLDBlackListEntry (OFAC, PEP) | ✅ |
| Sistema de scoring | Manejo de homónimos (0-100 pts) | ✅ |
| Penalización apellidos comunes | -5 pts por García, López, etc. | ✅ |
| Integración al reporte | Sección Etapa 2 en reporte.txt | ✅ |

**Archivos clave:**

| Archivo | Cambios |
|---------|---------|
| `services/blacklist_screening.py` | Servicio completo de screening (350 LOC) |
| `.env` | Variables BLACKLIST_DB_* para SQL Server |
| `temp/gen_arizona_report.py` | Integración Etapa 2 en generación de reporte |

**Dependencias:**
```
pyodbc>=5.3.0
ODBC Driver 17 for SQL Server
```

---

### Próximos pasos

- [ ] Etapa 3: Verificación de existencia legal (RENAPO, INE, RPC)
- [ ] Etapa 6: Búsqueda de noticias adversas (adverse media)
- [ ] Etapa 8: Documentación y conservación (registros 5/10 años)

---

### v2.3.0 — Dictamen PLD/FT Completo (Junio 2026)

**Funcionalidades implementadas:**

| Componente | Descripción | Estado |
|------------|-------------|--------|
| Dictamen PLD/FT (JSON) | Modelo `DictamenPLDFT` con 22+ helpers | ✅ |
| Dictamen PLD/FT (texto) | Renderizado a `dictamen_pld.txt` (13 secciones) | ✅ |
| Deduplicación por (nombre, rol) | Permite misma persona con roles distintos | ✅ |
| Extracción apoderado de poder | `_extraer_apoderado_de_poder()` | ✅ |
| Perfil transaccional | Datos de estado de cuenta (montos, frecuencias) | ✅ |
| Vigencia de documentos | Verificación de fechas emissión/vencimiento | ✅ |
| Detalle poder notarial | Notario, número escritura, estado, fecha | ✅ |
| Folio mercantil | Extracción del acta constitutiva | ✅ |
| Cláusula extranjeros | Exclusión/admisión de extranjeros | ✅ |
| Datos notariales acta | Número escritura, notario, entidad del acta | ✅ |
| Domicilio mejorado | Prioriza `domicilio_fiscal` de CSF sobre componentes individuales | ✅ |
| Observaciones Colorado | Integración de hallazgos de Colorado en dictamen | ✅ |
| Tiempo pipeline | Medición de duración total (`tiempo_pipeline_ms`) | ✅ |
| Endpoints dictamen | `GET /dictamen/{id}` (JSON) + `GET /dictamen/{id}/txt` (texto) | ✅ |

**Archivos clave modificados/creados:**

| Archivo | Cambios |
|---------|---------|
| `services/dictamen_generator.py` | **Nuevo** — 22+ funciones para construir DictamenPLDFT |
| `services/dictamen_txt.py` | **Nuevo** — Renderizado a texto plano (13 secciones + tablas box-drawing) |
| `models/dictamen_schemas.py` | **Nuevo** — Modelos Pydantic: DictamenPLDFT, ScreeningSeccion, AccionistaDictamen, etc. |
| `services/etapa1_completitud.py` | Dedup por `(nombre, rol)`, `_extraer_apoderado_de_poder()`, enriquecimiento CURP INE |
| `api/router.py` | Endpoints `GET /dictamen/{id}`, `GET /dictamen/{id}/txt`, timer `tiempo_pipeline_ms` |

**Bugs corregidos (18):**

| Bug | Descripción |
|-----|-------------|
| BUG-02 | Domicilio: comparación campo-por-campo CSF vs comprobante |
| BUG-03/06 | Deduplicación por `(nombre, rol)` en vez de solo `nombre` |
| BUG-04 | Detección de Consejo de Administración desde poder |
| BUG-05 | Tabla propietarios: columna "Tipo control" expandida |
| BUG-07 | Enriquecimiento CURP desde INE por match de nombre |
| BUG-09 | Perfil transaccional: datos de estado de cuenta |
| BUG-10 | Observaciones desde hallazgos de Colorado |
| BUG-11 | Vigencia de documentos con fechas de emisión/vencimiento |
| BUG-12 | Razón social enriquecida con tipo societario |
| BUG-13 | Cláusula de exclusión de extranjeros |
| BUG-14 | Detalle del poder notarial (notario, escritura, estado) |
| BUG-15 | Actividad de mayor riesgo activa DDR |
| BUG-16 | Tiempo pipeline externo (`tiempo_pipeline_ms`) |
| BUG-17 | Folio mercantil desde acta constitutiva |
| BUG-18 | Datos notariales del acta (escritura, notario, entidad) |
