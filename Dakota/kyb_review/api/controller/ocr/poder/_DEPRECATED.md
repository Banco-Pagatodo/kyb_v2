# ⚠️ DEPRECATED — NO USAR

Este directorio contiene módulos **legacy** del pipeline OCR basado en Tesseract
para extracción de Poderes Notariales.

**Reemplazado por:** Azure Document Intelligence + OpenAI LLM  
(ver `api/controller/docs.py` → `analyze_poder()`)

Los siguientes archivos ya **no se importan** desde ningún módulo activo:
- `main.py`
- `comparator.py`
- `llm_extractor.py`
- `normalizer.py`
- `ocr_processor.py`
- `reconciler.py`
- `user_input.py`
- `utils/`

**Acción recomendada:** Eliminar este directorio completo en la próxima limpieza de código.
