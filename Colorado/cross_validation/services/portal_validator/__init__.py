"""
Módulo portal_validator — Validación masiva contra portales oficiales mexicanos.

Sub-módulos:
  base.py            — Clase base con retry, delays, logging
  captcha.py         — Estrategias de resolución de CAPTCHA
  ine_validator.py   — Módulo 1: Lista Nominal del INE
  fiel_validator.py  — Módulo 2: Certificados FIEL del SAT
  rfc_validator.py   — Módulo 3: Validación de RFC en el SAT
  report.py          — Generación de reportes Excel/CSV
  engine.py          — Orquestador de validación masiva
"""


def ejecutar_validacion_portales(*args, **kwargs):
    """Lazy import para evitar carga circular al iniciar el paquete."""
    from .engine import ejecutar_validacion_portales as _run
    return _run(*args, **kwargs)


__all__ = ["ejecutar_validacion_portales"]
