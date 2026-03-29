"""
Paquete de validadores. Cada bloque implementa un conjunto de validaciones.

Bloques 1-9: Síncronos (validación cruzada documental)
Bloque 5B: Validación de reformas y estructura accionaria avanzada (PLD)
Bloque 10: Asíncrono (validación contra portales gubernamentales)
           Se invoca por separado desde engine.py cuando --portales está activo.
Bloque 11: Comparación Manual vs OCR (condicional — solo si existe formulario_manual)
           Se invoca por separado desde engine.py, no está en TODOS_LOS_BLOQUES.
"""
from .bloque1_identidad import validar as validar_identidad
from .bloque2_domicilio import validar as validar_domicilio
from .bloque3_vigencia import validar as validar_vigencia
from .bloque4_apoderado import validar as validar_apoderado
from .bloque5_estructura import validar as validar_estructura
from .bloque5b_reformas import validar as validar_reformas
from .bloque6_bancarios import validar as validar_bancarios
from .bloque7_notarial import validar as validar_notarial
from .bloque8_calidad import validar as validar_calidad
from .bloque9_completitud import validar as validar_completitud

# Bloque 10 es async y se importa directamente en engine.py
# from .bloque10_portales import validar_portales

# Bloque 11 es condicional y se importa directamente en engine.py
from .bloque11_comparacion_fuentes import validar as validar_comparacion_fuentes

# Funciones de estructura accionaria exportadas para Arizona
from .bloque5b_reformas import (
    determinar_estructura_vigente,
    EstructuraVigente,
    AlertaEstructura,
    UMBRAL_PROPIETARIO_REAL,
    UMBRAL_BENEFICIARIO_CONTROLADOR,
)

TODOS_LOS_BLOQUES = [
    validar_identidad,
    validar_domicilio,
    validar_vigencia,
    validar_apoderado,
    validar_estructura,
    validar_reformas,  # Bloque 5B: Reformas y estructura PLD
    validar_bancarios,
    validar_notarial,
    validar_calidad,
    validar_completitud,
]
