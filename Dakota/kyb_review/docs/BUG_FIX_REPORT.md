# Bug Fix Report — KYB Document Validation v1.1.0

**Date:** 19 de Febrero de 2026
**Author:** Automated CI/CD Pipeline + Engineering
**Environment:** Python 3.12 · FastAPI · Azure Document Intelligence · Azure OpenAI GPT-4o
**Test Suite:** pytest — 131 tests (46 unit + 85 integration)

---

## Executive Summary

During comprehensive integration testing of the KYB Document Validation System,
**5 critical bugs** were identified across 3 modules. All bugs have been fixed
and validated with **131/131 tests passing** (100% success rate).

The bugs fell into three categories:

| Category | Count | Severity |
|----------|-------|----------|
| Runtime TypeError | 2 | **P0 — Production Blocker** |
| Business Logic | 2 | **P1 — High** |
| Scoring Model | 1 | **P2 — Medium** |

**Risk assessment:** No breaking changes to the API contract. All fixes are
backward compatible. No database or infrastructure changes required.

---

## Bug #1 — TypeError in Validation Wrapper

| Field | Value |
|-------|-------|
| **Severity** | P0 — Production Blocker |
| **File** | `api/service/validation_wrapper.py` (line 196) |
| **Error** | `TypeError: unsupported operand type(s) for +: 'float' and 'str'` |
| **Root Cause** | Azure OpenAI GPT-4o occasionally returns `confiabilidad_promedio_openai` as a string (e.g., `"0.85"`) instead of float (`0.85`). The code assumed always float. |
| **Impact** | ALL document validation endpoints returned HTTP 500 when the LLM responded with string-typed confidence values. |
| **Fix Applied** | Wrapped value in `float()` with `try/except` fallback to `0.0`. |
| **Tests Affected** | 3+ integration tests across CSF, Acta, Domicilio endpoints. |

### Code Change

```python
# BEFORE
overall_confidence = (
    confiabilidad_promedio_openai + campo_confidence
) / 2

# AFTER
try:
    confiabilidad_promedio_openai = float(confiabilidad_promedio_openai)
except (ValueError, TypeError):
    confiabilidad_promedio_openai = 0.0

overall_confidence = (
    confiabilidad_promedio_openai + campo_confidence
) / 2
```

---

## Bug #2 — TypeError in Metrics Service

| Field | Value |
|-------|-------|
| **Severity** | P0 — Production Blocker |
| **File** | `api/service/metrics.py` (line 545) |
| **Error** | `TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'` |
| **Root Cause** | `get_low_confidence_fields()` collected field scores into a list, but incomplete OCR extractions left `None` values. `sum()` fails on `None`. |
| **Impact** | `/metrics` endpoint returned HTTP 500. |
| **Fix Applied** | Filter `None` values before calling `sum()`. Guard against empty lists. |

### Code Change

```python
# BEFORE
return sum(scores) / len(scores)

# AFTER
valid_scores = [s for s in scores if s is not None]
if not valid_scores:
    return 0.0
return sum(valid_scores) / len(valid_scores)
```

---

## Bug #3 — CSF Rejected as Comprobante de Domicilio

| Field | Value |
|-------|-------|
| **Severity** | P1 — High |
| **File** | `api/service/document_identifier.py` |
| **Root Cause** | CSF (Constancia de Situación Fiscal) uploaded to `/domicilio` was rejected. Mexican banking KYB practice accepts CSF as valid address proof, per CNBV regulations. |
| **Impact** | Valid customer documents rejected, requiring manual override. |
| **Fix Applied** | Introduced `ACCEPTED_ALTERNATIVES` dictionary mapping `DocumentType.COMPROBANTE_DOMICILIO → {DocumentType.CSF}`. When the expected type appears in the mapping and the detected type is in its set of alternatives, `is_correct=True` and `should_reject=False`. |

### Business Rule

> La Constancia de Situación Fiscal (CSF) emitida por el SAT contiene
> el domicilio fiscal del contribuyente. Las instituciones financieras
> mexicanas aceptan rutinariamente la CSF como comprobante de domicilio
> válido durante el proceso de KYB.

### Side Effect Handled

Removing CSF from the "wrong document type" tests for domicilio required updating:
- `test_domicilio_wrong_document_type` parametrize list
- `_CROSS_MATRIX` cross-validation entries

---

## Bug #4 — Reforma de Estatutos Misclassification

| Field | Value |
|-------|-------|
| **Severity** | P1 — High |
| **File** | `api/service/document_identifier.py` |
| **Root Cause** | Reforma shared many keywords with Acta Constitutiva and Poder Notarial. Insufficient unique discriminants + excessive negative indicators caused misclassification. |
| **Impact** | 2/2 Reforma test files failed; one classified as Acta, the other as Poder. |
| **Fix Applied** | Added 5 unique discriminants; removed 8 false-negative keywords. |

### Discriminants Added

| Keyword | Rationale |
|---------|-----------|
| `ASAMBLEA GENERAL EXTRAORDINARIA` | Reforma requires extraordinary assembly |
| `PARA QUEDAR COMO SIGUE` | Standard clause for article modification |
| `MODIFICACION A LOS ESTATUTOS` | Explicit naming of the process |
| `RATIFICACION DEL CONSEJO` | Common in Reforma + board restructuring |
| `PROTOCOLIZACION DEL ACTA DE ASAMBLEA` | Full phrase uniquely Reforma |

### False Negatives Removed

| Keyword | Why Removed |
|---------|-------------|
| `LOS COMPARECIENTES CONSTITUYEN` | Appears in Reforma minutes |
| `PRIMER EJERCICIO SOCIAL` | Referenced in modified articles |
| `PODERDANTE` | Legal representative granting power |
| `CREDENCIAL PARA VOTAR` | ID of witnesses/notaries |
| `DURACION DE LA SOCIEDAD` | Modified article may reference |
| `NOVENTA Y NUEVE ANOS` | Duration clause in modified text |
| `OTORGA PODER A FAVOR DE` | Delegated authority in assembly |
| `CONFIERE PODER A FAVOR DE` | Same pattern as above |

---

## Bug #5 — Bonus Scoring Scale

| Field | Value |
|-------|-------|
| **Severity** | P2 — Medium |
| **File** | `api/service/document_identifier.py` |
| **Root Cause** | Flat bonus didn't account for absolute discriminant count. Documents with 40+ keywords could match 7+ discriminants yet receive the same bonus as a document matching 2. |
| **Impact** | Uneven confidence scores; some correct documents near the threshold. |
| **Fix Applied** | Graduated bonus scale based on absolute count. |

### Graduated Scale

| Discriminants Found | Bonus |
|---------------------|-------|
| ≥ 7 | +0.40 |
| ≥ 5 | +0.30 |
| ≥ 3 | +0.20 |
| ≥ 2 | +0.10 |
| < 2 | +0.00 |

### Confidence Formula

```
positive_score = found_discriminants / total_discriminants
penalty        = min(negative_count × 0.15, 0.60)
bonus          = graduated_bonus(found_discriminants)
confidence     = clamp(positive_score − penalty + bonus, 0.0, 1.0)
```

Thresholds: `CONFIDENCE_THRESHOLD = 0.40` · `REJECTION_THRESHOLD = 0.20`

---

## Verification

### Test Execution

```
============ 131 passed in 34.21s ============
  Unit Tests (document_identifier.py):       25/25  ✓
  Unit Tests (document_identifier_agent.py):  21/21  ✓
  Integration Tests (endpoints):              85/85  ✓
```

### Regression Analysis

- No regressions introduced.
- All 9 document types validated end-to-end.
- Cross-validation matrix (wrong document type tests) updated and passing.

---

## Appendix: Files Modified

| File | Lines Changed | Type |
|------|---------------|------|
| `api/service/validation_wrapper.py` | ~6 | Type safety |
| `api/service/metrics.py` | ~5 | Null safety |
| `api/service/document_identifier.py` | ~45 | Business logic + scoring |
| `tests/test_integration_endpoints.py` | ~4 | Test alignment |
| **Total** | **~60 lines** | |
