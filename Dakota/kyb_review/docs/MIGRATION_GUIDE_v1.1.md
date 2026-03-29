# Migration Guide — v1.0.3 → v1.1.0

**Date:** 19 de Febrero de 2026
**Compatibility:** Fully backward compatible — no breaking changes

---

## Overview

Version 1.1.0 is a bug fix release. **No breaking changes** to the API contract,
data models, or environment configuration. Existing integrations continue working
without modification.

This guide documents behavioral changes that may affect downstream consumers.

---

## 1. Behavioral Changes

### 1.1 CSF Accepted as Comprobante de Domicilio

**Before (v1.0.3):**

```
POST /docs/domicilio   ← upload a CSF file
Response:
  is_correct: false
  should_reject: true
  reasoning: "Detected CSF, expected comprobante_domicilio"
```

**After (v1.1.0):**

```
POST /docs/domicilio   ← upload a CSF file
Response:
  is_correct: true
  should_reject: false
  reasoning: "CSF accepted as alternative for comprobante_domicilio"
```

**Why:** Mexican banking regulation accepts CSF as valid address proof.
The system now reflects this standard industry practice.

**Action required:** If your system relies on rejecting CSF at the domicilio endpoint,
update your business rules accordingly. Most integrations will benefit from this
change without modifications.

### 1.2 Improved Reforma de Estatutos Classification

**Before:** Some Reforma files were misclassified as Acta Constitutiva or Poder Notarial.

**After:** 5 new discriminant keywords improve detection accuracy. False negative
indicators that appeared in legitimate Reforma documents have been removed.

**Action required:** None. Previously rejected Reforma documents will now be
accepted correctly.

### 1.3 Graduated Bonus Scoring

**Before:** Flat bonus scale regardless of absolute discriminant count.

**After:** Graduated bonus based on number of discriminants found:

| Discriminants | Bonus |
|---------------|-------|
| ≥ 7 | +0.40 |
| ≥ 5 | +0.30 |
| ≥ 3 | +0.20 |
| ≥ 2 | +0.10 |

**Action required:** If you store or display confidence scores, expect slightly
different values. The thresholds (`CONFIDENCE_THRESHOLD=0.40`, `REJECTION_THRESHOLD=0.20`)
remain unchanged.

---

## 2. Type Safety Improvements

### 2.1 LLM Response Handling

`validation_wrapper.py` now safely converts `confiabilidad_promedio_openai` to `float`.
Previously, string responses from GPT-4o caused `TypeError` and HTTP 500.

**Action required:** None. Eliminates intermittent 500 errors transparently.

### 2.2 Metrics Null Safety

`metrics.py` now filters `None` values from score lists before aggregation.
Previously, incomplete OCR extractions caused `TypeError` in the metrics endpoint.

**Action required:** None. The `/metrics` endpoint now returns valid responses
consistently.

---

## 3. API Contract

### Unchanged Endpoints

All endpoints retain the same request/response schemas:

| Endpoint | Method | Status |
|----------|--------|--------|
| `/docs/csf` | POST | Unchanged |
| `/docs/acta` | POST | Unchanged |
| `/docs/poder` | POST | Unchanged |
| `/docs/domicilio` | POST | Behavior change (see §1.1) |
| `/docs/ine` | POST | Unchanged |
| `/docs/ine_reverso` | POST | Unchanged |
| `/docs/estado_cuenta` | POST | Unchanged |
| `/docs/fiel` | POST | Unchanged |
| `/docs/reforma` | POST | Improved accuracy (see §1.2) |
| `/metrics` | GET | Bug fix (see §2.2) |

### Response Schema

The `IdentificationResult` response remains unchanged:

```json
{
  "is_correct": true,
  "expected_type": "comprobante_domicilio",
  "reasoning": "CSF accepted as alternative for comprobante_domicilio",
  "should_reject": false
}
```

No new fields were added to the API response. The `accepted_as_alternative`
logic is entirely internal to `document_identifier.py`.

---

## 4. Deployment Checklist

- [ ] Pull latest code from main branch
- [ ] Verify Python 3.12+ environment
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Confirm 131/131 tests passing
- [ ] Deploy with existing `compose.yml` or `compose.prod.yml` (no changes)
- [ ] No database migrations required
- [ ] No environment variable changes required
- [ ] No dependency changes required

---

## 5. Rollback Plan

If rollback is needed, revert to the previous commit. No data or configuration
cleanup is required since no schema or infrastructure changes were made.

```bash
git revert HEAD
docker compose -f compose.prod.yml up -d --build
```

---

## 6. FAQ

**Q: Will existing uploaded documents need reprocessing?**
A: No. The fixes only affect future classification requests.

**Q: Does the CSF-as-domicilio change affect the CSF endpoint?**
A: No. CSF uploaded to `/docs/csf` behaves exactly as before.

**Q: Are there new dependencies?**
A: No. Same `pyproject.toml` / `requirements.txt`.

**Q: Will confidence scores change for documents that were already passing?**
A: Slightly, due to the graduated bonus scale. However, documents that
previously passed validation will continue to pass. The thresholds are unchanged.
