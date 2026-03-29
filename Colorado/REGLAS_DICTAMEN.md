# Reglas de Dictamen — Validación Cruzada KYB (Colorado)

> **Fecha:** 4 de marzo de 2026  
> **Propósito:** Documentar los criterios actuales que determinan si un expediente KYB es **APROBADO**, **APROBADO CON OBSERVACIONES** o **RECHAZADO**, para facilitar la revisión y modificación de reglas.

---

## 1. Regla de Dictamen Final

La función `_calcular_dictamen()` en `engine.py` evalúa **todos los hallazgos** y produce el dictamen según estas condiciones (evaluadas en orden):

| Dictamen | Condición |
|---|---|
| **RECHAZADO** | ≥1 hallazgo **CRÍTICO** con `pasa=False` |
| **APROBADO CON OBSERVACIONES** | 0 críticos fallidos **Y** >2 hallazgos **MEDIA** con `pasa=False` |
| **APROBADO** | 0 críticos fallidos **Y** ≤2 hallazgos MEDIA fallidos |

> **Nota:** Los hallazgos **INFORMATIVOS** **nunca** afectan el dictamen. Solo proporcionan contexto.

### Contadores utilizados

| Contador | Cómo se calcula |
|---|---|
| `criticos` | Hallazgos con `pasa=False` y `severidad=CRITICA` |
| `medios` | Hallazgos con `pasa=False` y `severidad=MEDIA` |
| `informativos` | Hallazgos con `severidad=INFORMATIVA` y `pasa != True` |
| `pasan` | Hallazgos con `pasa=True` (cualquier severidad) |

**Archivo fuente:** `Colorado/cross_validation/services/engine.py` → `_calcular_dictamen()` (líneas 28-56)

---

## 2. Niveles de Severidad

| Severidad | Impacto en Dictamen | Descripción |
|---|---|---|
| **CRITICA** | 1 sola falla → **RECHAZADO** | Inconsistencia grave que impide la aprobación del expediente |
| **MEDIA** | >2 fallas → **APROBADO CON OBSERVACIONES** | Discrepancia que requiere atención pero no es bloqueante por sí sola |
| **INFORMATIVA** | Sin impacto | Dato contextual o de calidad; nunca causa rechazo ni observaciones |

### Escalado dinámico de severidad

Algunas validaciones pueden **escalar** su severidad de MEDIA a CRITICA dependiendo del resultado:

| Código | Validación | Condición de escalado |
|---|---|---|
| V2.2 | Domicilio fiscal vs comprobante | MEDIA→**CRITICA** si similitud < 50% |
| V2.4 | Domicilio campo por campo | MEDIA→**CRITICA** si tasa de coincidencia < 60% |
| V5.1 | Estructura accionaria | MEDIA→**CRITICA** si suma de porcentajes ≠ ~100% |
| V10.x | Portales gubernamentales | INFORMATIVA(pasa) / **CRITICA**(falla) / MEDIA(error/captcha) |

---

## 3. Catálogo Completo de Validaciones por Bloque

### Bloque 1 — Identidad Corporativa

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V1.1** | RFC consistente | **CRITICA** | Compara RFC entre CSF, FIEL, Acta y BD | Todos los RFC normalizados idénticos | 2+ RFC distintos |
| **V1.2** | Razón social consistente | **CRITICA** | Compara razón social entre CSF, FIEL, Acta, Edo. Cta., Poder, Reforma y BD | Todas coinciden con la referencia (CSF) | Al menos una no coincide |
| **V1.3** | Estatus padrón fiscal | **CRITICA** | Verifica `estatus_padron` de la CSF | Estatus = "ACTIVO" | Cualquier otro estatus (suspendido, cancelado, etc.) |

### Bloque 2 — Domicilio

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V2.1** | CP consistente | MEDIA | Compara código postal entre CSF y comprobante | CP iguales | CP difieren |
| **V2.2** | Domicilio fiscal vs comprobante | MEDIA / **CRITICA** | Similitud de dirección completa CSF↔comprobante | Similitud ≥ 85% | < 85% (MEDIA si ≥ 50%, **CRITICA** si < 50%) |
| **V2.3** | Domicilio constitutivo vs actual | INFORMATIVA | Compara domicilio de acta/reforma vs CSF | Similitud ≥ 75% | Similitud < 75% (solo informativo) |
| **V2.4** | Domicilio campo por campo | MEDIA / **CRITICA** | Compara cada campo individual (calle, colonia, etc.) | Todos coinciden | Discrepancias: MEDIA si ≥ 60%, **CRITICA** si < 60% |

### Bloque 3 — Vigencia de Documentos

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V3.1** | FIEL vigente | **CRITICA** | Fecha de vencimiento de la FIEL | Fecha futura (vigente) | Fecha pasada (vencida) |
| **V3.2** | INE vigente | **CRITICA** | Año de vencimiento de la INE | Año ≥ año actual | Año < año actual |
| **V3.3** | Comprobante de domicilio reciente | MEDIA | Antigüedad del comprobante | ≤ 3 meses | > 3 meses |
| **V3.4** | CSF reciente | MEDIA | Antigüedad de la CSF | ≤ 3 meses | > 3 meses |
| **V3.5** | Estado de cuenta reciente | MEDIA | Antigüedad del estado de cuenta | ≤ 3 meses | > 3 meses |

> **Parámetros configurables** (en `core/config.py`):
> - `MESES_VIGENCIA_DOMICILIO = 3`
> - `MESES_VIGENCIA_CSF = 3`
> - `MESES_VIGENCIA_EDO_CTA = 3`

### Bloque 4 — Apoderado Legal

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V4.1** | Apoderado INE vs Poder | **CRITICA** | Nombre de INE vs `nombre_apoderado` del Poder | Nombres coinciden | Nombres no coinciden |
| **V4.2** | Apoderado en estructura | MEDIA | Busca al apoderado en estructura_accionaria y consejo_administracion | Encontrado (similitud ≥ 80%) | No aparece en acta ni reforma |
| **V4.3** | Poder otorgado por empresa | **CRITICA** | `nombre_poderdante` del Poder vs razón social | Coinciden | Poderdante no coincide con la empresa |
| **V4.4** | Facultades suficientes | MEDIA | Keywords de administración en tipo_poder/facultades | Keyword encontrada | Facultades posiblemente limitadas |
| **V4.5** | INE anverso vs reverso | **CRITICA** | Campos comunes entre INE frente y reverso | Todos los campos coinciden | Al menos un campo difiere |
| **V4.6** | Poderes del representante | MEDIA | Existencia de Poder Notarial o consejo en reforma | Poder presente, o reforma con consejo | Sin Poder ni consejo |

### Bloque 5 — Estructura Societaria

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V5.1** | Estructura accionaria completa | MEDIA / **CRITICA** | Status y suma de porcentajes de la estructura | "Verificada" y suma 99%-101% | Parcial/No_Confiable (**CRITICA** si suma ≠ ~100%) |
| **V5.2** | Evolución accionaria | INFORMATIVA | Cambios de accionistas entre acta y reforma | Siempre pasa (reporta diferencias) | N/A |
| **V5.3** | Capital social | MEDIA | Monto de capital social en reforma/acta | Capital > $0 | Capital = $0 con baja confiabilidad |
| **V5.4** | Cláusula extranjeros | INFORMATIVA | Presencia de `clausula_extranjeros` en acta | Cláusula encontrada | N/A (solo informativo) |

### Bloque 6 — Datos Bancarios

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V6.1** | Titular = empresa | MEDIA | `titular` del Edo. Cta. vs razón social | Coinciden | No coinciden o titular corrupto |
| **V6.2** | CLABE válida | MEDIA | Longitud de CLABE interbancaria | 18 dígitos exactos | Distinto de 18 dígitos |

### Bloque 7 — Consistencia Notarial

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V7.1** | Datos notariales | MEDIA | Presencia y confiabilidad (≥ 90%) de notario, notaría, estado, escritura | Todos presentes y confiables | Campos faltantes o baja confiabilidad |
| **V7.2** | Folio mercantil | MEDIA | Presencia de `folio_mercantil` en acta/reforma | Folio presente y no pendiente | Folio no encontrado o pendiente |
| **V7.3** | Consistencia folio | MEDIA | Folio mercantil de acta vs reforma | Folios normalizados iguales | Folios difieren |
| **V7.4** | Inscripción Registro Público | MEDIA | Inscripción en RPP/RPC vía folio mercantil electrónico | Folio presente y no pendiente | Sin folio o pendiente |

### Bloque 8 — Calidad de Extracción

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V8.1** | Confiabilidad de campos | INFORMATIVA | Campos con confiabilidad < 70% en todos los documentos | Todos ≥ 70% | Al menos un campo < 70% |
| **V8.2** | Campos faltantes | MEDIA / INFORMATIVA | `campos_no_encontrados` por documento | Sin campos críticos faltantes | Campos críticos (rfc, razon_social, etc.) no encontrados → MEDIA |
| **V8.3** | Parsing de nombres | INFORMATIVA | Confianza de `_nombres_parseados` | Todos ≥ 70% o persona moral | Persona física con confianza < 70% |
| **V8.4** | Titular estado de cuenta | MEDIA | Detección de titular corrupto en Edo. Cta. | Titular legible | Titular corrupto sin línea recuperable |

### Bloque 9 — Completitud del Expediente

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V9.1** | Documentos mínimos | **CRITICA** | Presencia de cada documento en `DOCS_MINIMOS` | Todos presentes | Un hallazgo **CRITICA** por cada doc faltante |
| **V9.2** | Documentos complementarios | MEDIA | Presencia de docs en `DOCS_COMPLEMENTARIOS` | Todos presentes | Complementarios faltantes listados |

> **Documentos mínimos** (`DOCS_MINIMOS` en `core/config.py`):
> `csf`, `fiel`, `ine`, `estado_cuenta`, `domicilio`, `acta_constitutiva`, `poder`
>
> **Documentos complementarios** (`DOCS_COMPLEMENTARIOS`):
> `reforma_estatutos`, `reforma`, `ine_reverso`

### Bloque 10 — Validación en Portales Gubernamentales (Async)

| Código | Nombre | Severidad | Qué valida | Pasa | Falla |
|---|---|---|---|---|---|
| **V10.1** | FIEL — Portal SAT | Variable | Consulta vigencia de e.firma en el SAT | VIGENTE → pasa, INFORMATIVA | VENCIDO/REVOCADO → falla, **CRITICA**; Error/CAPTCHA → None, MEDIA |
| **V10.2** | RFC — Portal SAT | Variable | Consulta validación de RFC en el SAT | RFC válido → pasa, INFORMATIVA | No encontrado → falla, **CRITICA**; Error → None, MEDIA |
| **V10.3** | INE — Lista Nominal | Variable | Consulta Lista Nominal del INE | Encontrado → pasa, INFORMATIVA | No encontrado → falla, **CRITICA**; Error → None, MEDIA |

---

## 4. Resumen Estadístico

| Severidad Base | Códigos | Cantidad |
|---|---|---|
| **CRITICA** | V1.1, V1.2, V1.3, V3.1, V3.2, V4.1, V4.3, V4.5, V9.1 | 9 |
| **MEDIA** | V2.1, V2.2, V2.4, V3.3, V3.4, V3.5, V4.2, V4.4, V4.6, V5.1, V5.3, V6.1, V6.2, V7.1, V7.2, V7.3, V7.4, V8.2, V8.4, V9.2 | 20 |
| **INFORMATIVA** | V2.3, V5.2, V5.4, V8.1, V8.3 | 5 |
| **Variable** (portales) | V10.1, V10.2, V10.3 | 3 |
| | **Total** | **37** |

---

## 5. Parámetros Configurables

Todos en `Colorado/cross_validation/core/config.py`:

| Parámetro | Valor actual | Descripción |
|---|---|---|
| `UMBRAL_SIMILITUD_NOMBRE` | 0.85 | Umbral para considerar dos nombres como iguales |
| `UMBRAL_SIMILITUD_DIRECCION` | 0.75 | Umbral para considerar dos direcciones como iguales |
| `UMBRAL_CONFIABILIDAD_BAJA` | 70.0 | % bajo el cual un campo se marca como baja confiabilidad |
| `MESES_VIGENCIA_DOMICILIO` | 3 | Máximo de meses de antigüedad para comprobante de domicilio |
| `MESES_VIGENCIA_CSF` | 3 | Máximo de meses de antigüedad para CSF |
| `MESES_VIGENCIA_EDO_CTA` | 3 | Máximo de meses de antigüedad para estado de cuenta |

---

## 6. Escenarios de Dictamen — Ejemplos

### Ejemplo 1: APROBADO
- 0 hallazgos CRITICA fallidos
- 1 hallazgo MEDIA fallido (V3.3 — comprobante domicilio de hace 4 meses)
- → ≤2 medios fallidos, 0 críticos → **APROBADO**

### Ejemplo 2: APROBADO CON OBSERVACIONES
- 0 hallazgos CRITICA fallidos
- 4 hallazgos MEDIA fallidos (V2.1, V3.3, V7.2, V6.2)
- → 0 críticos, >2 medios → **APROBADO CON OBSERVACIONES**

### Ejemplo 3: RECHAZADO
- 1 hallazgo CRITICA fallido (V1.1 — RFC inconsistente)
- 2 hallazgos MEDIA fallidos
- → ≥1 crítico fallido → **RECHAZADO** (sin importar los medios)

### Ejemplo 4: RECHAZADO por escalado
- V2.2 escala de MEDIA→CRITICA (similitud domicilio < 50%)
- → Ahora cuenta como 1 CRITICA fallido → **RECHAZADO**

---

## 7. Notas para Modificación

Al modificar las reglas, considerar:

1. **Cambiar severidad de una validación:** Modificar el `Severidad.X` en el archivo `bloqueN_*.py` correspondiente.
2. **Cambiar umbrales de dictamen:** Modificar `_calcular_dictamen()` en `engine.py` (ej: cambiar el `> 2` medios por otro valor).
3. **Agregar/quitar documentos mínimos:** Editar `DOCS_MINIMOS` en `core/config.py`.
4. **Cambiar meses de vigencia:** Editar `MESES_VIGENCIA_*` en `core/config.py`.
5. **Cambiar umbrales de escalado:** Modificar las condiciones dentro de cada bloque (ej: el 50% de V2.2, el 60% de V2.4).
6. **Actualizar tests:** Tras cualquier cambio, revisar `tests/test_engine.py` que tiene tests específicos para `_calcular_dictamen`.
