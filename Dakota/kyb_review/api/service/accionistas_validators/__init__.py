"""
Módulo de validadores especializados para extracción de datos KYB.

Incluye:
- accionistas_validator: Limpieza y deduplicación de accionistas
- rfc_validator: Validación de RFC según SAT/CNBV
- alertas_estructura: Generación de alertas PLD
"""

from .accionistas_validator import (
    es_nombre_persona_valido,
    deduplicar_accionistas,
    filtrar_entradas_basura,
    calcular_confiabilidad_estructura,
    limpiar_y_deduplicar,
    generar_alertas_estructura,
    PALABRAS_PROHIBIDAS_EXACTAS,
    FRASES_PROHIBIDAS,
)

from .rfc_validator import (
    validar_rfc,
    normalizar_rfc,
    inferir_tipo_persona_por_rfc,
    detectar_tipo_persona,
    validar_consistencia_rfc_tipo,
    validar_rfcs_estructura,
    generar_alertas_rfc,
    es_rfc_generico,
    TipoRFC,
    ResultadoValidacionRFC,
    RFC_PM_PATTERN,
    RFC_PF_PATTERN,
    RFCS_GENERICOS,
)

from .alertas_estructura import (
    generar_todas_alertas,
    alertas_a_lista_strings,
    detectar_estructura_multicapa,
    detectar_shell_company,
    detectar_estructura_circular,
    detectar_cambios_frecuentes,
    detectar_sin_inscripcion_rpc,
    detectar_acta_antigua,
    detectar_discrepancia_denominacion,
    detectar_requiere_perforacion,
    detectar_jurisdiccion_alto_riesgo,
    detectar_documentacion_incompleta,
    detectar_prestanombre_posible,
    detectar_capital_inconsistente,
    Alerta,
    TipoAlerta,
    SeveridadAlerta,
    UMBRAL_PROPIETARIO_REAL,
    UMBRAL_BENEFICIARIO_CONTROLADOR,
    JURISDICCIONES_ALTO_RIESGO,
)

__all__ = [
    # Accionistas validator
    'es_nombre_persona_valido',
    'deduplicar_accionistas',
    'filtrar_entradas_basura',
    'calcular_confiabilidad_estructura',
    'limpiar_y_deduplicar',
    'generar_alertas_estructura',
    'PALABRAS_PROHIBIDAS_EXACTAS',
    'FRASES_PROHIBIDAS',
    # RFC validator
    'validar_rfc',
    'normalizar_rfc',
    'inferir_tipo_persona_por_rfc',
    'detectar_tipo_persona',
    'validar_consistencia_rfc_tipo',
    'validar_rfcs_estructura',
    'generar_alertas_rfc',
    'es_rfc_generico',
    'TipoRFC',
    'ResultadoValidacionRFC',
    'RFC_PM_PATTERN',
    'RFC_PF_PATTERN',
    'RFCS_GENERICOS',
    # Alertas estructura
    'generar_todas_alertas',
    'alertas_a_lista_strings',
    'detectar_estructura_multicapa',
    'detectar_shell_company',
    'detectar_estructura_circular',
    'detectar_cambios_frecuentes',
    'detectar_sin_inscripcion_rpc',
    'detectar_acta_antigua',
    'detectar_discrepancia_denominacion',
    'detectar_requiere_perforacion',
    'detectar_jurisdiccion_alto_riesgo',
    'detectar_documentacion_incompleta',
    'detectar_prestanombre_posible',
    'detectar_capital_inconsistente',
    'Alerta',
    'TipoAlerta',
    'SeveridadAlerta',
    'UMBRAL_PROPIETARIO_REAL',
    'UMBRAL_BENEFICIARIO_CONTROLADOR',
    'JURISDICCIONES_ALTO_RIESGO',
]
