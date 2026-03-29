# Guía de la Base de Datos KYB — Para Principiantes

> Esta guía explica la base de datos del sistema KYB como si nunca hubieras
> trabajado con SQL. Al terminar, sabrás qué se guarda, dónde se guarda y
> cómo consultarlo.

---

## Índice

1. [¿Qué es una base de datos?](#1-qué-es-una-base-de-datos)
2. [Conceptos clave de SQL](#2-conceptos-clave-de-sql)
3. [Nuestras tablas](#3-nuestras-tablas)
4. [Tabla `empresas`](#4-tabla-empresas)
5. [Tabla `documentos`](#5-tabla-documentos)
6. [Tabla `validaciones_cruzadas`](#6-tabla-validaciones_cruzadas)
7. [¿Cómo se relacionan?](#7-cómo-se-relacionan)
8. [Consultas útiles (copiar y pegar)](#8-consultas-útiles-copiar-y-pegar)
9. [El campo mágico: `datos_extraidos`](#9-el-campo-mágico-datos_extraidos)
10. [Glosario rápido](#10-glosario-rápido)
11. [¿Cómo se conecta la API a la base de datos?](#11-cómo-se-conecta-la-api-a-la-base-de-datos)

---

## 1. ¿Qué es una base de datos?

Piensa en una **hoja de Excel** con varias pestañas. Cada pestaña es una
**tabla** y cada tabla tiene columnas (los encabezados) y filas (los datos).

| Término SQL | Equivalente en Excel |
|-------------|----------------------|
| Base de datos | El archivo `.xlsx` completo |
| Tabla | Una pestaña / hoja |
| Columna (campo) | Un encabezado (A, B, C…) |
| Fila (registro) | Una línea de datos |

Nuestra base de datos se llama **`kyb`** y usa **PostgreSQL**, un motor de
bases de datos gratuito y muy popular.

---

## 2. Conceptos clave de SQL

### Primary Key (PK) — Llave Primaria 🔑

Un valor que **identifica de forma única** cada fila. Nunca se repite.
Es como el número de folio en un recibo: no puede haber dos iguales.

En nuestras tablas usamos **UUID** (un texto largo aleatorio) como PK:
```
dadd384a-a420-40c3-af71-0884b5e66e1f
```

### Foreign Key (FK) — Llave Foránea 🔗

Un campo en una tabla que **apunta a la PK de otra tabla**. Así se
conectan las tablas entre sí.  
Ejemplo: cada documento tiene `empresa_id` que apunta al `id` de la
tabla empresas → "este documento pertenece a esta empresa".

### Índice (Index) 🔍

Un "índice" es como el índice de un libro: permite encontrar datos
más rápido sin recorrer toda la tabla.

### JSONB 📦

Un tipo de dato especial de PostgreSQL que guarda **objetos JSON**
(como los que usas en JavaScript o Python). A diferencia de texto plano,
PostgreSQL puede **buscar dentro** de ese JSON de forma eficiente.

### NULL ❓

Significa "no tiene valor" / "vacío". No es lo mismo que cero o texto
vacío; es la ausencia de dato.

---

## 3. Nuestras tablas

El sistema KYB tiene **3 tablas**:

```
┌──────────────────┐         ┌──────────────────────┐         ┌───────────────────────────┐
│     empresas     │         │      documentos       │         │  validaciones_cruzadas   │
├──────────────────┤         ├──────────────────────┤         ├───────────────────────────┤
│ id          (PK) │◄────────│ empresa_id      (FK) │         │ id               (PK)   │
│ rfc              │         │ id              (PK) │         │ empresa_id       (FK)   │
│ razon_social     │    1  N │ doc_type             │         │ rfc                     │
│ fecha_registro   │ ─────►│ file_name            │         │ dictamen                │
│ metadata_extra   │         │ datos_extraidos      │         │ hallazgos        (JSON) │
└──────────────────┘    ◄───│ created_at           │         │ portales_ejecutados     │
                    │         └──────────────────────┘         │ created_at              │
                    │                                          └───────────────────────────┘
                    │                                                    ▲
                    └───────────────── 1  N ───────────────────────┘
```

**Relaciones:**
- Una empresa puede tener **muchos** documentos (1 → N)
- Una empresa puede tener **muchas** validaciones cruzadas (1 → N)
- Cada documento y cada validación pertenece a **una sola** empresa

**Quién escribe en cada tabla:**
- **Dakota** (agente de extracción) → escribe en `empresas` y `documentos`
- **Colorado** (agente de validación) → lee de `documentos`, escribe en `validaciones_cruzadas`
- **Orquestrator** → no accede a la BD — coordina todo vía HTTP

---

## 4. Tabla `empresas`

> Guarda la información de cada empresa que sube documentos al sistema.

| # | Columna | Tipo | ¿Obligatorio? | Descripción en español |
|---|---------|------|----------------|------------------------|
| 1 | **`id`** | UUID | Sí (auto) | **Identificador interno único.** Se genera solo. Es la "llave primaria". Ejemplo: `dadd384a-a420-40c3-af71-0884b5e66e1f` |
| 2 | **`rfc`** | Texto (máx 13 car.) | Sí | **RFC de la empresa.** El Registro Federal de Contribuyentes, como `ACA230223IA7`. No puede haber dos empresas con el mismo RFC (es único). Tiene un **índice** para buscar rápido. |
| 3 | **`razon_social`** | Texto (sin límite) | Sí | **Nombre legal de la empresa.** Ejemplo: `Constructora Almirante SA de CV`. |
| 4 | **`fecha_registro`** | Fecha y hora (UTC) | Sí (auto) | **Cuándo se registró la empresa en el sistema.** Se llena automáticamente con la fecha y hora actual en UTC. Ejemplo: `2026-02-20 16:43:12+00`. |
| 5 | **`metadata_extra`** | JSONB | No | **Datos adicionales opcionales.** Un objeto JSON libre para guardar lo que haga falta en el futuro. Por defecto es `{}` (objeto vacío). |

### Reglas importantes de `empresas`

- El `rfc` es **UNIQUE** (único): si intentas crear dos empresas con el mismo RFC,
  PostgreSQL lo rechaza.
- Si borras una empresa, **todos sus documentos se borran automáticamente**
  (gracias a `ON DELETE CASCADE`).

### ¿Cómo se ve una fila real?

```
 id                                   | rfc           | razon_social                    | fecha_registro              | metadata_extra
--------------------------------------+---------------+---------------------------------+-----------------------------+----------------
 dadd384a-a420-40c3-af71-0884b5e66e1f | ABC123456789  | Constructora Almirante SA de CV | 2026-02-20 16:43:12.345+00  | {}
```

---

## 5. Tabla `documentos`

> Guarda cada documento procesado por la API (CSF, INE, Acta, etc.)
> junto con **todos los datos extraídos** del documento.

| # | Columna | Tipo | ¿Obligatorio? | Descripción en español |
|---|---------|------|----------------|------------------------|
| 1 | **`id`** | UUID | Sí (auto) | **Identificador interno único del documento.** Se genera solo. Ejemplo: `b12fa3e1-...` |
| 2 | **`empresa_id`** | UUID | Sí | **¿A qué empresa pertenece este documento?** Es una llave foránea (FK) que apunta al `id` de la tabla `empresas`. Si la empresa se borra, este documento también se borra. |
| 3 | **`doc_type`** | Texto (máx 30 car.) | Sí | **Tipo de documento.** Uno de los 9 valores posibles (ver tabla abajo). |
| 4 | **`file_name`** | Texto (sin límite) | Sí | **Nombre original del archivo** que subió el usuario. Ejemplo: `CSF_ACA230223IA7.pdf`. |
| 5 | **`datos_extraidos`** | JSONB | Sí | **Los datos que la IA extrajo del documento.** Este es el campo más importante — contiene toda la información extraída en formato JSON. Su estructura varía según el `doc_type`. [Ver sección 8](#8-el-campo-mágico-datos_extraidos). |
| 6 | **`created_at`** | Fecha y hora (UTC) | Sí (auto) | **Cuándo se procesó y guardó el documento.** Automático. |

### Valores posibles de `doc_type`

| Valor en la BD | Documento |
|-----------------|-----------|
| `csf` | Constancia de Situación Fiscal |
| `acta_constitutiva` | Acta Constitutiva |
| `poder` | Poder Notarial |
| `ine` | INE (anverso / frente) |
| `ine_reverso` | INE (reverso / atrás) |
| `fiel` | FIEL — Firma Electrónica Avanzada |
| `estado_cuenta` | Estado de Cuenta bancario |
| `domicilio` | Comprobante de Domicilio |
| `reforma_estatutos` | Reforma de Estatutos |

### Índices de `documentos`

La tabla tiene 3 índices para hacer búsquedas rápidas:

| Índice | ¿Qué optimiza? |
|--------|-----------------|
| `idx_doc_empresa` | Buscar todos los documentos de una empresa |
| `idx_doc_type` | Filtrar por tipo de documento |
| `idx_doc_datos` | Buscar **dentro** del JSON de `datos_extraidos` (índice GIN) |

### ¿Cómo se ve una fila real?

```
 id          | empresa_id       | doc_type | file_name          | datos_extraidos                          | created_at
-------------+------------------+----------+--------------------+------------------------------------------+---------------------------
 b12fa3e1-.. | dadd384a-a420-.. | csf      | CSF_ACA230223IA7.. | {"rfc":"ACA230223IA7","estatus":"ACTIVO"} | 2026-02-20 16:43:15+00
```

_(El JSON de `datos_extraidos` se muestra recortado. En la realidad contiene
muchos más campos.)_

---

## 6. Tabla `validaciones_cruzadas`

> Guarda el resultado de cada validación cruzada que **Colorado** ejecuta
> sobre el expediente de una empresa.

| # | Columna | Tipo | ¿Obligatorio? | Descripción en español |
|---|---------|------|----------------|-----------------------|
| 1 | **`id`** | UUID | Sí (auto) | **Identificador único de la validación.** |
| 2 | **`empresa_id`** | UUID | Sí | **¿A qué empresa pertenece?** FK → tabla `empresas`. |
| 3 | **`rfc`** | Texto (máx 13 car.) | Sí | **RFC de la empresa validada.** |
| 4 | **`razon_social`** | Texto | Sí | **Razón social de la empresa.** |
| 5 | **`dictamen`** | Texto (máx 30 car.) | Sí | **Resultado: `APROBADO`, `APROBADO_CON_OBSERVACIONES` o `RECHAZADO`.** |
| 6 | **`total_pasan`** | Entero | Sí | **Hallazgos que pasan.** |
| 7 | **`total_criticos`** | Entero | Sí | **Hallazgos críticos (los que rechazan).** |
| 8 | **`total_medios`** | Entero | Sí | **Hallazgos de severidad media.** |
| 9 | **`total_informativos`** | Entero | Sí | **Hallazgos informativos (no afectan dictamen).** |
| 10 | **`hallazgos`** | JSONB | Sí | **Lista completa de hallazgos serializada.** Cada hallazgo tiene: código, mensaje, severidad, pasa/no pasa. |
| 11 | **`recomendaciones`** | JSONB | Sí | **Lista de recomendaciones generadas.** |
| 12 | **`documentos_presentes`** | JSONB | Sí | **Tipos de documento encontrados en el expediente.** Ej: `["csf", "acta_constitutiva", "ine"]`. |
| 13 | **`portales_ejecutados`** | Boolean | Sí | **¿Se consultaron portales gubernamentales?** (SAT, INE). |
| 14 | **`modulos_portales`** | JSONB | No | **Detalle de módulos ejecutados.** Ej: `{"ine": "ok", "fiel": "error"}`. |
| 15 | **`resumen_bloques`** | JSONB | No | **Resumen por bloque de validación.** |
| 16 | **`created_at`** | Fecha/hora (UTC) | Sí (auto) | **Cuándo se ejecutó la validación.** |

### Índices de `validaciones_cruzadas`

| Índice | ¿Qué optimiza? |
|--------|-----------------|
| `idx_vc_empresa` | Buscar validaciones de una empresa |
| `idx_vc_rfc` | Filtrar por RFC |
| `idx_vc_dictamen` | Filtrar por dictamen (APROBADO, RECHAZADO, etc.) |
| `idx_vc_created` | Ordenar por fecha (más reciente primero) |
| `idx_vc_hallazgos` | Buscar dentro del JSON de hallazgos (GIN) |

### ¿Cómo se ve una fila real?

```
 id           | empresa_id       | rfc           | dictamen   | total_criticos | total_pasan | hallazgos       | portales_ejecutados | created_at
--------------+------------------+---------------+------------+----------------+-------------+-----------------+---------------------+---------------------------
 abc123-..    | dadd384a-a420-.. | ACA230223IA7  | RECHAZADO  | 5              | 20          | [{...}, ...]    | true                | 2026-02-27 09:44:42+00
```

### Consultas útiles para `validaciones_cruzadas`

```sql
-- Ver todas las validaciones de una empresa
SELECT dictamen, total_criticos, total_pasan, portales_ejecutados, created_at
FROM validaciones_cruzadas
WHERE rfc = 'ACA230223IA7'
ORDER BY created_at DESC;

-- Ver la última validación de cada empresa
SELECT DISTINCT ON (rfc) rfc, dictamen, total_criticos, created_at
FROM validaciones_cruzadas
ORDER BY rfc, created_at DESC;

-- Contar hallazgos críticos
SELECT rfc, dictamen, jsonb_array_length(hallazgos) AS total_hallazgos
FROM validaciones_cruzadas
ORDER BY created_at DESC;
```

---

## 7. ¿Cómo se relacionan?

```
   EMPRESA "Constructora Almirante"
   RFC: ACA230223IA7
   ┌─────────────────────────────────────┐
   │  id: dadd384a-...                   │
   │                                     │
   │  Tiene estos documentos:            │
   │                                     │
   │   📄 CSF         (empresa_id → dadd384a-...)
   │   📄 Acta        (empresa_id → dadd384a-...)
   │   📄 INE         (empresa_id → dadd384a-...)
   │   📄 INE Reverso (empresa_id → dadd384a-...)
   │   📄 FIEL        (empresa_id → dadd384a-...)
   │   📄 Poder       (empresa_id → dadd384a-...)
   │   📄 Domicilio   (empresa_id → dadd384a-...)
   │   📄 Estado Cta  (empresa_id → dadd384a-...)
   │   📄 Reforma     (empresa_id → dadd384a-...)
   └─────────────────────────────────────┘
```

El campo `empresa_id` en cada documento es lo que "amarra" el documento
a su empresa. Es como escribir el nombre de la empresa en cada folder de
un expediente físico.

---

## 8. Consultas útiles (copiar y pegar)

> Puedes ejecutar estas queries en **DBeaver**, **psql**, o cualquier
> cliente SQL conectado a la base `kyb`.

### 8.1 Ver todas las empresas

```sql
SELECT * FROM empresas;
```

### 8.2 Ver todos los documentos

```sql
SELECT id, empresa_id, doc_type, file_name, created_at
FROM documentos
ORDER BY created_at DESC;
```

### 8.3 Ver documentos de una empresa específica (por RFC)

```sql
SELECT d.doc_type, d.file_name, d.created_at
FROM documentos d
JOIN empresas e ON d.empresa_id = e.id
WHERE e.rfc = 'ACA230223IA7';
```

> **¿Qué significa `JOIN`?** Es como cruzar dos hojas de Excel por una
> columna en común. Aquí cruzamos `documentos.empresa_id` con `empresas.id`
> para poder filtrar por el RFC de la empresa.

### 8.4 Contar documentos por empresa

```sql
SELECT e.rfc, e.razon_social, COUNT(d.id) AS total_documentos
FROM empresas e
LEFT JOIN documentos d ON e.id = d.empresa_id
GROUP BY e.rfc, e.razon_social;
```

> **¿Qué significa `LEFT JOIN`?** Incluye empresas aunque no tengan
> documentos (aparecerían con `total_documentos = 0`).

### 8.5 Ver los datos extraídos de un documento específico

```sql
SELECT datos_extraidos
FROM documentos
WHERE doc_type = 'csf'
LIMIT 1;
```

> **Tip de DBeaver:** Si el JSON se ve en una sola línea, haz clic derecho
> en la celda → "View Value" para verlo formateado.

### 8.6 Buscar un valor dentro del JSON de datos_extraidos

```sql
-- Buscar todos los documentos cuyo RFC extraído sea 'ACA230223IA7'
SELECT doc_type, file_name
FROM documentos
WHERE datos_extraidos->>'rfc' = 'ACA230223IA7';
```

> **¿Qué significa `->>` ?** Es el operador de PostgreSQL para sacar un
> valor *como texto* de un campo JSON.
> - `->` devuelve JSON (objeto o array)
> - `->>` devuelve texto plano

### 8.7 Ver el progreso KYB de una empresa

```sql
-- Muestra qué tipos de documento ya subió cada empresa
SELECT
    e.rfc,
    e.razon_social,
    COUNT(DISTINCT d.doc_type) AS tipos_subidos,
    9 AS tipos_requeridos,
    ROUND(COUNT(DISTINCT d.doc_type) * 100.0 / 9, 1) AS progreso_pct
FROM empresas e
LEFT JOIN documentos d ON e.id = d.empresa_id
GROUP BY e.rfc, e.razon_social;
```

### 8.8 Borrar una empresa y todos sus documentos

```sql
-- ⚠️ CUIDADO: Esto borra la empresa Y todos sus documentos
DELETE FROM empresas WHERE rfc = 'ABC123456789';
```

> No necesitas borrar los documentos primero: el `ON DELETE CASCADE`
> los elimina automáticamente.

---

## 9. El campo mágico: `datos_extraidos`

Este es el campo más interesante de toda la base de datos. Es de tipo
**JSONB** y contiene **todo lo que la IA extrajo** del documento. Su
estructura cambia según el tipo de documento.

### Ejemplo: CSF (Constancia de Situación Fiscal)

```json
{
  "rfc": "ACA230223IA7",
  "estatus": "ACTIVO",
  "fecha_emision": "2026-01-15",
  "denominacion_razon_social": "ACABADOS Y CONSTRUCCIONES ALMIRANTE SA DE CV",
  "domicilio_fiscal": "AV INSURGENTES SUR 1234, COL TLACOQUEMECATL, BENITO JUAREZ, CDMX, 03200",
  "regimen_fiscal": "REGIMEN GENERAL DE LEY PERSONAS MORALES"
}
```

### Ejemplo: INE (anverso)

```json
{
  "nombre_completo": "JUAN CARLOS PÉREZ LÓPEZ",
  "curp": "PELJ850101HDFRPN09",
  "fecha_nacimiento": "1985-01-01",
  "clave_elector": "PRLJNC85010109H100",
  "vigencia": "2029",
  "seccion": "1234",
  "domicilio": "CALLE REFORMA 456, COL CENTRO, CDMX"
}
```

### Ejemplo: FIEL

```json
{
  "rfc": "SCX190531824",
  "razon_social": "SERVICIOS CONSTRUCTIVOS XYZ SA DE CV",
  "numero_serie_certificado": "00001000000504835167",
  "vigencia_desde": "2023-06-15",
  "vigencia_hasta": "2027-06-15"
}
```

### Ejemplo: Acta Constitutiva

```json
{
  "denominacion_social": "CONSTRUCTORA ALMIRANTE SA DE CV",
  "fecha_constitucion": "2018-03-15",
  "notario": "LIC. ROBERTO GARCÍA MENDOZA",
  "numero_notaria": "125",
  "folio_mercantil": "N-2018034567",
  "objeto_social": "CONSTRUCCIÓN, DISEÑO Y SUPERVISIÓN DE OBRAS...",
  "capital_social": "$500,000.00 MXN"
}
```

### ¿Cómo consultar campos dentro de `datos_extraidos`?

```sql
-- Sacar el RFC de todos los CSF
SELECT datos_extraidos->>'rfc' AS rfc_extraido
FROM documentos
WHERE doc_type = 'csf';

-- Sacar la razón social de las Actas
SELECT datos_extraidos->>'denominacion_social' AS empresa
FROM documentos
WHERE doc_type = 'acta_constitutiva';

-- Sacar vigencia de las FIEL
SELECT
    datos_extraidos->>'rfc' AS rfc,
    datos_extraidos->>'vigencia_desde' AS desde,
    datos_extraidos->>'vigencia_hasta' AS hasta
FROM documentos
WHERE doc_type = 'fiel';
```

---

## 10. Glosario rápido

| Término | Significado |
|---------|-------------|
| **PostgreSQL** | El motor de base de datos que usamos (como MySQL pero más potente) |
| **UUID** | Identificador único universal — un texto aleatorio de 36 caracteres que nunca se repite |
| **PK (Primary Key)** | La columna que identifica cada fila de forma única |
| **FK (Foreign Key)** | Una columna que apunta a la PK de otra tabla, creando una relación |
| **JSONB** | Tipo de dato de PostgreSQL para guardar JSON de forma eficiente y searchable |
| **CASCADE** | "En cascada" — si borras la empresa, sus documentos se borran automáticamente |
| **INDEX** | Un atajo que PostgreSQL construye para encontrar datos más rápido |
| **GIN** | Un tipo especial de índice optimizado para buscar dentro de JSON |
| **UTC** | Zona horaria universal (la misma en todo el mundo, sin horario de verano) |
| **SELECT** | Comando SQL para leer/consultar datos |
| **INSERT** | Comando SQL para agregar datos nuevos |
| **DELETE** | Comando SQL para borrar datos |
| **JOIN** | Cruzar dos tablas por una columna en común |
| **WHERE** | Filtrar filas que cumplan una condición |
| **GROUP BY** | Agrupar filas para hacer cálculos (como contar o sumar) |
| **`->>`** | Operador de PostgreSQL: saca un valor de un JSON como texto |
| **`->`** | Operador de PostgreSQL: saca un valor de un JSON como JSON |
| **NULL** | "Sin valor" — no es cero ni texto vacío, es la ausencia de dato |
| **ORM** | Object-Relational Mapping — traduce tablas SQL a clases de Python (usamos SQLAlchemy) |
| **Alembic** | Herramienta que maneja las "migraciones" (cambios al esquema de la BD de forma controlada) |

---

## Diagrama resumen

```
                          BASE DE DATOS: kyb
                    ┌─────────────────────────────┐
                    │                             │
     ┌──────────────┴──────────────┐   ┌──────────┴───────────────────┐
     │        EMPRESAS             │   │        DOCUMENTOS            │
     ├─────────────────────────────┤   ├──────────────────────────────┤
     │ 🔑 id           UUID (PK)  │   │ 🔑 id           UUID (PK)   │
     │    rfc          texto(13)   │◄──│ 🔗 empresa_id   UUID (FK)   │
     │    razon_social texto       │   │    doc_type     texto(30)   │
     │    fecha_registro   fecha   │   │    file_name    texto       │
     │    metadata_extra   JSON    │   │ 📦 datos_extraidos  JSON    │
     └──────────────┬──────────────┘   │    created_at   fecha       │
                    │                   └────────────────────────────┘
                    │
     ┌──────────────┴───────────────────┐
     │  VALIDACIONES_CRUZADAS            │
     ├──────────────────────────────────┤
     │ 🔑 id              UUID (PK)      │
     │ 🔗 empresa_id      UUID (FK)      │
     │    rfc             texto(13)      │
     │    dictamen        texto(30)      │
     │    total_criticos  entero         │
     │    total_pasan     entero         │
     │ 📦 hallazgos       JSON           │
     │    portales_ejecutados  boolean   │
     │    created_at      fecha          │
     └──────────────────────────────────┘

     1 empresa  ─────────────►  N documentos
     1 empresa  ─────────────►  N validaciones
```

---

## 11. ¿Cómo se conecta la API a la base de datos?

El flujo completo tiene **5 piezas** que trabajan en cadena:

```
.env → session.py → server.py (lifespan) → docs.py (endpoints) → repository.py
```

### 11.1 Las credenciales viven en el archivo `.env`

En `api/service/.env` están las variables de conexión:

```
DB_USER=kyb_app
DB_PASS=<TU_PASSWORD>
DB_HOST=localhost
DB_NAME=kyb
```

Estas le dicen a Python: "conéctate a PostgreSQL en localhost, base de datos
`kyb`, con el usuario `kyb_app`."

### 11.2 `session.py` — El archivo que maneja la conexión

`api/db/session.py` es el corazón de la conexión. Tiene 3 funciones clave:

**a) `_build_database_url()`** (línea 31)

Lee las variables del `.env` y construye la URL de conexión:

```
postgresql+asyncpg://kyb_app:<TU_PASSWORD>@localhost:5432/kyb
```

El `+asyncpg` indica que usa el driver **asíncrono** (no bloquea el servidor
mientras espera respuesta de la BD).

**b) `init_db()`** (línea 64)

Crea dos objetos globales:

- **`_engine`** — Es el "canal" de comunicación con PostgreSQL. Mantiene un
  **pool de conexiones** (5 conexiones listas + hasta 10 extras si hay mucha
  carga). Así no abre y cierra conexiones todo el tiempo.
- **`_session_factory`** — Es una "fábrica de sesiones". Cada vez que un
  endpoint necesita hablar con la BD, pide una sesión nueva a esta fábrica.

```python
_engine = create_async_engine(
    db_url,
    pool_size=5,           # 5 conexiones siempre listas
    max_overflow=10,       # hasta 10 extras si hay mucha carga
    pool_pre_ping=True,    # detecta conexiones rotas
    pool_recycle=300,      # recicla cada 5 minutos
)

_session_factory = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

**c) `get_db()`** (línea 105)

Esta es la función que los endpoints usan. Genera una sesión temporal:

```python
async with _session_factory() as session:
    yield session           # ← la entrega al endpoint
    await session.commit()  # ← si todo salió bien, guarda los cambios
# Si algo falla → session.rollback()  (deshace todo)
```

### 11.3 `server.py` — Cuándo se enciende y apaga la conexión

`api/server/server.py` tiene la función `lifespan` que funciona como el
"interruptor de luz" de la base de datos:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP — cuando el servidor arranca
    await init_db()           # ← enciende la conexión a PostgreSQL
    yield                     # ← la API corre normalmente aquí
    # SHUTDOWN — cuando el servidor se apaga
    await close_db()          # ← cierra la conexión limpiamente
```

**Detalle importante:** Si PostgreSQL no está disponible, la API **no se cae**.
Solo logea un warning y funciona sin persistencia:

```python
except Exception as e:
    logger.warning(f"No se pudo conectar a PostgreSQL: {e}. "
                   "La API funcionará sin persistencia.")
```

### 11.4 `docs.py` — Cómo los endpoints obtienen la sesión

Cada endpoint en `api/router/docs.py` recibe la BD como **dependency injection**
de FastAPI (un mecanismo automático para pasar dependencias).

La función `_get_db_or_none()` es una versión "tolerante" que no falla si
la BD no está conectada:

```python
async def _get_db_or_none():
    factory = db_session._session_factory  # ← lee la fábrica en runtime
    if factory is None:                    # ← si la BD no está conectada...
        yield None                         # ← devuelve None (no falla)
        return
    async with factory() as session:       # ← si sí está, entrega una sesión
        yield session
        await session.commit()
```

Los endpoints lo usan así:

```python
@router.post("/csf")
async def validate_csf(
    file: ...,
    rfc: str | None = None,
    db: AsyncSession | None = Depends(_get_db_or_none),  # ← se inyecta aquí
):
```

FastAPI automáticamente:
1. **Antes** de ejecutar el endpoint → llama a `_get_db_or_none()` y le da
   una sesión (o `None`)
2. **Ejecuta** el endpoint
3. **Después** → hace `commit` o `rollback` según si hubo error

### 11.5 `repository.py` — Quién realmente habla con las tablas

`api/db/repository.py` recibe la sesión y ejecuta las operaciones SQL. Por
ejemplo:

```python
async def get_or_create_empresa(db: AsyncSession, rfc: str):
    # SQL equivalente: SELECT * FROM empresas WHERE rfc = '...'
    stmt = select(Empresa).where(Empresa.rfc == rfc)
    result = await db.execute(stmt)
    empresa = result.scalar_one_or_none()
    # Si no existe, la crea
    if empresa is None:
        empresa = Empresa(rfc=rfc, razon_social=f"Empresa {rfc}")
        db.add(empresa)
        await db.flush()
    return empresa
```

No escribe SQL en texto — usa **SQLAlchemy ORM** que traduce clases Python
a operaciones SQL automáticamente.

### 11.6 Diagrama visual del flujo completo

```
  Usuario sube un documento
          │
          ▼
  ┌─────────────────────────────────────┐
  │  POST /docs/csf?rfc=ACA230223IA7   │
  │       (endpoint en docs.py)         │
  └──────────────┬──────────────────────┘
                 │
    FastAPI llama a _get_db_or_none()
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  session.py: _session_factory()  │ ← Crea una sesión del pool
  └──────────────┬───────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  repository.py:                  │
  │  get_or_create_empresa(rfc)      │ → SELECT * FROM empresas WHERE rfc=...
  │  save_documento(datos)           │ → INSERT INTO documentos VALUES(...)
  └──────────────┬───────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  PostgreSQL (puerto 5432)        │
  │  Base de datos: kyb              │
  │  Tablas: empresas, documentos    │
  └──────────────────────────────────┘
                 │
    Si todo OK → session.commit()   (guarda cambios)
    Si error   → session.rollback() (deshace todo)
```

### 11.7 Resumen en una frase

> El `.env` tiene las credenciales → `session.py` crea el pool de conexiones
> al arrancar el servidor → cada request obtiene una sesión temporal vía
> dependency injection → `repository.py` ejecuta las queries → al terminar
> el request se hace commit o rollback automáticamente.

---

> **¿Dudas?** Conecta a la BD con DBeaver y prueba las queries de la
> [sección 7](#7-consultas-útiles-copiar-y-pegar). La mejor forma de
> aprender SQL es experimentando.
