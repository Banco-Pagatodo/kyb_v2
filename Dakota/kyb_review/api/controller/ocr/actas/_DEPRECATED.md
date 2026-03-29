# ⚠️ DEPRECATED — NO USAR

Este directorio contiene módulos **legacy** del pipeline OCR basado en Tesseract.

**Reemplazado por:** Azure Document Intelligence + OpenAI LLM  
(ver `api/controller/docs.py` → `analyze_constitutiva()`)

Los siguientes archivos ya **no se importan** desde ningún módulo activo:
- `main.py`
- `cleaner_agent.py`
- `comparator.py`
- `equivalences_agent.py`
- `llm_extractor.py`
- `normalizer.py`
- `reconciler.py`
- `user_input.py`
- `enderezar_pdf_gui.py`
- `utils/file_selector.py`
- `utils/tesseract_check.py`

> **NOTA:** `equivalencias.py` en este directorio (no en esta subcarpeta) SÍ se usa activamente para la tabla `NUMEROS_PALABRAS`.

**Acción recomendada:** Eliminar este directorio completo en la próxima limpieza de código.
