"""
Calculador determinista MER PLD/FT v7.0 — Personas Morales.

Toda la aritmética y clasificación se ejecuta aquí, en código Python.
El LLM NUNCA hace multiplicaciones, sumas ni clasificaciones.

Arquitectura de dos capas:
  CAPA 1 (este módulo):  busca en catálogos, asigna valores, multiplica,
                          suma y clasifica.  Si un factor no puede resolverse,
                          lo marca ``requiere_llm=True``.
  CAPA 2 (LLM):          solo interviene en factores ``requiere_llm``; el
                          código recalcula con ``aplicar_resoluciones_llm()``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from . import mer_catalogos as cat

logger = logging.getLogger("arizona.mer_calculator")

# ═══════════════════════════════════════════════════════════════════
#  Constantes (espejo de mer_catalogos, centralizadas para claridad)
# ═══════════════════════════════════════════════════════════════════

PESOS = cat.PESOS

UMBRALES_PM = {
    "BAJO":  (85, 142),
    "MEDIO": (143, 199),
    "ALTO":  (200, 255),
}

# ═══════════════════════════════════════════════════════════════════
#  Estructuras de resultado
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FactorCalc:
    """Resultado del cálculo de un factor individual."""
    numero: int
    nombre: str
    valor: Optional[int]
    peso: float
    puntaje: Optional[float]
    dato_cliente: str
    dato_asumido: bool = False
    requiere_llm: bool = False
    nota: str = ""


@dataclass
class ResultadoCalc:
    """Resultado completo del cálculo determinista MER."""
    factores: list[FactorCalc] = field(default_factory=list)
    puntaje_total: Optional[float] = None
    grado_riesgo: Optional[str] = None
    factores_pendientes_llm: list[FactorCalc] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    observaciones: list[str] = field(default_factory=list)
    recomendaciones: list[str] = field(default_factory=list)
    calculo_completo: bool = False


# ═══════════════════════════════════════════════════════════════════
#  Helpers de parseo
# ═══════════════════════════════════════════════════════════════════

def _parse_fecha(texto: str | None) -> date | None:
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _es_cdmx(entidad: str) -> bool:
    e = cat._normalizar(entidad)
    return e in ("ciudad de mexico", "cdmx", "df", "distrito federal")


# ═══════════════════════════════════════════════════════════════════
#  Funciones de asignación de valor por factor
# ═══════════════════════════════════════════════════════════════════

def _valor_tipo_persona(tipo: str) -> int:
    """Factor 1: Tipo de persona. PM / Sindicatos → siempre 3."""
    t = tipo.strip().upper()
    if any(kw in t for kw in ("MORAL", "SINDICATO", "PM", "SAPI",
                               "SA DE CV", "SC DE", "AC", "SOFOM")):
        return 3
    if "PFAE" in t:
        return 2
    if "FISICA" in t or "FÍSICA" in t:
        return 1
    return 3  # flujo PM → default 3


def _valor_antiguedad(fecha_const: date, fecha_eval: date) -> int:
    """Factor 3: Antigüedad."""
    anios = (fecha_eval - fecha_const).days / 365.25
    if anios > 3:
        return 1
    if anios >= 1.1:
        return 2
    return 3


def _valor_producto(nombre: str) -> Optional[int]:
    """Factor 6: Productos y servicios. None → requiere LLM."""
    n = nombre.strip().upper()
    mapa = {
        "YA GANASTE": 1,
        "BASICA DE NOMINA": 1, "BÁSICA DE NÓMINA": 1,
        "ADQUIRENCIA": 2,
        "FUNDADORES": 2,
        "UTIL": 3, "ÚTIL": 3,
        "CORPORATIVA": 3,
    }
    for clave, valor in mapa.items():
        if clave in n:
            return valor
    return None


# ═══════════════════════════════════════════════════════════════════
#  Función principal de cálculo determinista
# ═══════════════════════════════════════════════════════════════════

def calcular_mer_pm(
    *,
    # Datos obligatorios
    tipo_societario: str = "PERSONA MORAL",
    pais_constitucion: str = "México",
    fecha_constitucion: str | None = None,
    actividad_economica: str | None = None,
    entidad_federativa: str | None = None,
    alcaldia_cdmx: str | None = None,
    producto: str = "corporativa",
    # Screening (Etapa 2)
    coincidencia_lpb: bool = False,
    coincidencia_listas_negativas: bool = False,
    pep: str = "NO",
    # Transaccionales (opcionales)
    monto_recibido: float | None = None,
    monto_enviado: float | None = None,
    ops_recibidas: int | None = None,
    ops_enviadas: int | None = None,
    origen_recursos: str | None = None,
    destino_recursos: str | None = None,
    # Control
    fecha_evaluacion: date | None = None,
) -> ResultadoCalc:
    """
    Cálculo 100 % determinista de la MER para Persona Moral.

    Retorna un ``ResultadoCalc`` con todos los factores calculados.
    Si algún factor no puede resolverse con los catálogos, queda
    marcado ``requiere_llm=True`` y ``puntaje=None``.
    """
    if fecha_evaluacion is None:
        fecha_evaluacion = date.today()

    resultado = ResultadoCalc()
    factores: list[FactorCalc] = []

    # ─── Factor 1: Tipo de persona ───────────────────────────────
    val_1 = _valor_tipo_persona(tipo_societario)
    factores.append(FactorCalc(
        numero=1, nombre="Tipo de persona",
        valor=val_1, peso=PESOS["tipo_persona"],
        puntaje=val_1 * PESOS["tipo_persona"] * 100,
        dato_cliente=tipo_societario,
    ))

    # ─── Factor 2: Nacionalidad ──────────────────────────────────
    val_2 = cat.obtener_riesgo_pais(pais_constitucion)
    factores.append(FactorCalc(
        numero=2, nombre="Nacionalidad",
        valor=val_2, peso=PESOS["nacionalidad"],
        puntaje=val_2 * PESOS["nacionalidad"] * 100,
        dato_cliente=pais_constitucion,
    ))
    if val_2 == 300:
        resultado.observaciones.append(
            f"⚠️ ALERTA CRÍTICA: País ({pais_constitucion}) en Lista Negra GAFI."
        )
    elif val_2 == 200:
        resultado.observaciones.append(
            f"⚠️ País ({pais_constitucion}) en Lista Gris GAFI — debida diligencia reforzada."
        )

    # ─── Factor 3: Antigüedad ───────────────────────────────────
    fecha = _parse_fecha(fecha_constitucion)
    if fecha:
        anios = (fecha_evaluacion - fecha).days / 365.25
        val_3 = _valor_antiguedad(fecha, fecha_evaluacion)
        dato_3 = f"{anios:.1f} años (constituida {fecha_constitucion})"
        factores.append(FactorCalc(
            numero=3, nombre="Antigüedad (fecha de constitución)",
            valor=val_3, peso=PESOS["antiguedad"],
            puntaje=val_3 * PESOS["antiguedad"] * 100,
            dato_cliente=dato_3,
        ))
    else:
        factores.append(FactorCalc(
            numero=3, nombre="Antigüedad (fecha de constitución)",
            valor=2, peso=PESOS["antiguedad"],
            puntaje=2 * PESOS["antiguedad"] * 100,
            dato_cliente="No proporcionada",
            dato_asumido=True,
            nota="Sin fecha de constitución. Valor medio (2) aplicado.",
        ))
        resultado.observaciones.append(
            "⚠️ Fecha de constitución no proporcionada; asumido riesgo medio (2)."
        )

    # ─── Factor 4: Actividad económica ──────────────────────────
    if actividad_economica:
        val_4 = cat.buscar_actividad(actividad_economica)
        if val_4 is not None:
            factores.append(FactorCalc(
                numero=4, nombre="Giro o actividad económica",
                valor=val_4, peso=PESOS["actividad"],
                puntaje=val_4 * PESOS["actividad"] * 100,
                dato_cliente=f"{actividad_economica} (Grupo {val_4})",
                nota=f"Encontrada en catálogo CNBV → Grupo {val_4}",
            ))
            if val_4 == 3:
                resultado.observaciones.append(
                    f"Actividad económica Grupo 3 (riesgo alto): {actividad_economica}."
                )
        else:
            # No encontrada → marcar para LLM
            factores.append(FactorCalc(
                numero=4, nombre="Giro o actividad económica",
                valor=None, peso=PESOS["actividad"],
                puntaje=None,
                dato_cliente=actividad_economica,
                requiere_llm=True,
                nota="Actividad no encontrada en catálogo CNBV. Requiere clasificación por LLM.",
            ))
    else:
        factores.append(FactorCalc(
            numero=4, nombre="Giro o actividad económica",
            valor=None, peso=PESOS["actividad"],
            puntaje=None,
            dato_cliente="No proporcionada",
            requiere_llm=True,
            nota="Actividad no proporcionada. Requiere clasificación por LLM.",
        ))

    # ─── Factor 5: Ubicación geográfica ─────────────────────────
    if entidad_federativa:
        if _es_cdmx(entidad_federativa) and alcaldia_cdmx:
            val_5_raw = cat.obtener_riesgo_alcaldia(alcaldia_cdmx)
            val_5 = round(val_5_raw)
            dato_5 = f"CDMX — {alcaldia_cdmx} (riesgo {val_5_raw})"
        elif _es_cdmx(entidad_federativa):
            val_5 = 3
            dato_5 = "CDMX (zona riesgo 3)"
        else:
            val_5 = cat.obtener_riesgo_entidad(entidad_federativa)
            dato_5 = f"{entidad_federativa} (zona riesgo {val_5})"
        factores.append(FactorCalc(
            numero=5, nombre="Ubicación geográfica del domicilio",
            valor=val_5, peso=PESOS["ubicacion"],
            puntaje=val_5 * PESOS["ubicacion"] * 100,
            dato_cliente=dato_5,
        ))
    else:
        factores.append(FactorCalc(
            numero=5, nombre="Ubicación geográfica del domicilio",
            valor=2, peso=PESOS["ubicacion"],
            puntaje=2 * PESOS["ubicacion"] * 100,
            dato_cliente="No proporcionada — asumido zona 2",
            dato_asumido=True,
            nota="Sin entidad federativa. Valor medio (2) aplicado.",
        ))
        resultado.observaciones.append(
            "⚠️ Entidad federativa no proporcionada; asumido zona 2."
        )

    # ─── Factor 6: Productos y servicios ─────────────────────────
    val_6 = _valor_producto(producto) if producto else None
    if val_6 is not None:
        factores.append(FactorCalc(
            numero=6, nombre="Productos y servicios",
            valor=val_6, peso=PESOS["producto"],
            puntaje=val_6 * PESOS["producto"] * 100,
            dato_cliente=producto,
        ))
    else:
        factores.append(FactorCalc(
            numero=6, nombre="Productos y servicios",
            valor=None, peso=PESOS["producto"],
            puntaje=None,
            dato_cliente=producto or "No proporcionado",
            requiere_llm=True,
            nota="Producto no reconocido en catálogo.",
        ))

    # ─── Factores 7-8: Volumen de operación (montos) ────────────
    for num, key, monto, nombre in [
        (7, "monto_recibido", monto_recibido, "Volumen — monto recursos recibidos"),
        (8, "monto_enviado",  monto_enviado,  "Volumen — monto recursos enviados"),
    ]:
        if monto is not None:
            val = cat.obtener_riesgo_monto_pm(monto)
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=val, peso=PESOS[key],
                puntaje=val * PESOS[key] * 100,
                dato_cliente=f"${monto:,.0f} MXN",
            ))
        else:
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=1, peso=PESOS[key],
                puntaje=1 * PESOS[key] * 100,
                dato_cliente="No proporcionado",
                dato_asumido=True,
                nota="Sin monto declarado. Valor mínimo (1) aplicado. Recalificar a 3 meses.",
            ))

    # ─── Factores 9-10: Frecuencia de operación ────────────────
    for num, key, ops, nombre in [
        (9,  "ops_recibidas", ops_recibidas, "Frecuencia — operaciones recibidas"),
        (10, "ops_enviadas",  ops_enviadas,  "Frecuencia — operaciones enviadas"),
    ]:
        if ops is not None:
            val = cat.obtener_riesgo_ops_pm(ops)
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=val, peso=PESOS[key],
                puntaje=val * PESOS[key] * 100,
                dato_cliente=f"{ops:,} operaciones",
            ))
        else:
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=1, peso=PESOS[key],
                puntaje=1 * PESOS[key] * 100,
                dato_cliente="No proporcionado",
                dato_asumido=True,
                nota="Sin frecuencia declarada. Valor mínimo (1) aplicado. Recalificar a 3 meses.",
            ))

    # ─── Factores 11-12: Origen y destino de recursos ───────────
    for num, key, dato, nombre in [
        (11, "origen_recursos",  origen_recursos,  "Origen de los recursos"),
        (12, "destino_recursos", destino_recursos, "Destino de los recursos"),
    ]:
        if dato is not None:
            val = cat.obtener_riesgo_origen_destino(dato)
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=val, peso=PESOS[key],
                puntaje=val * PESOS[key] * 100,
                dato_cliente=dato,
            ))
        else:
            factores.append(FactorCalc(
                numero=num, nombre=nombre,
                valor=2, peso=PESOS[key],
                puntaje=2 * PESOS[key] * 100,
                dato_cliente="No proporcionado",
                dato_asumido=True,
                nota="Asumido 'Otros' (valor 2). Confirmar con cliente.",
            ))

    # ─── Factor 13: Lista de Personas Bloqueadas ────────────────
    val_13 = 300 if coincidencia_lpb else 0
    factores.append(FactorCalc(
        numero=13, nombre="Coincidencia en Lista de Personas Bloqueadas",
        valor=val_13, peso=PESOS["lpb"],
        puntaje=val_13 * PESOS["lpb"] * 100,
        dato_cliente="Sí" if coincidencia_lpb else "No (verificado Etapa 2)",
    ))
    if coincidencia_lpb:
        resultado.observaciones.append(
            "🔴 ALERTA CRÍTICA: Coincidencia en LPB. "
            "RECHAZAR apertura y notificar a la UIF."
        )
        resultado.recomendaciones.append(
            "BLOQUEO AUTOMÁTICO: Rechazar apertura independientemente del puntaje."
        )

    # ─── Factor 14: Listas/Noticias negativas ───────────────────
    val_14 = 300 if coincidencia_listas_negativas else 0
    factores.append(FactorCalc(
        numero=14, nombre="Coincidencia en Listas/Noticias negativas",
        valor=val_14, peso=PESOS["listas_negativas"],
        puntaje=val_14 * PESOS["listas_negativas"] * 100,
        dato_cliente="Sí" if coincidencia_listas_negativas else "No (verificado Etapa 2)",
    ))
    if coincidencia_listas_negativas:
        resultado.observaciones.append(
            "🔴 ALERTA: Coincidencia en Listas / Noticias negativas."
        )

    # ─── Factor 15: PEP ─────────────────────────────────────────
    pep_upper = pep.strip().upper() if isinstance(pep, str) else str(pep).upper()
    if pep_upper == "NACIONAL":
        val_15 = 130
        dato_15 = "PEP Nacional"
    elif pep_upper in ("EXTRANJERO", "EXTRANJERA"):
        val_15 = 200
        dato_15 = "PEP Extranjera"
    else:
        val_15 = 0
        dato_15 = "No (verificado Etapa 2)"
    factores.append(FactorCalc(
        numero=15, nombre="Persona Políticamente Expuesta (PEP)",
        valor=val_15, peso=PESOS["pep"],
        puntaje=val_15 * PESOS["pep"] * 100,
        dato_cliente=dato_15,
    ))
    if val_15 > 0:
        resultado.observaciones.append(
            f"⚠️ {dato_15}. Requiere aprobación de funcionario autorizado."
        )

    # ═══════════════════════════════════════════════════════════════
    #  Compilar resultado
    # ═══════════════════════════════════════════════════════════════
    resultado.factores = factores
    resultado.factores_pendientes_llm = [f for f in factores if f.requiere_llm]

    if not resultado.factores_pendientes_llm:
        _clasificar(resultado, coincidencia_lpb, coincidencia_listas_negativas)
    else:
        resultado.calculo_completo = False
        resultado.grado_riesgo = "PENDIENTE"

    # ─── Alertas estructurales ──────────────────────────────────
    tipo_upper = tipo_societario.strip().upper()
    if "SAPI" in tipo_upper:
        resultado.alertas.append(
            "SAPI detectada. Estructura con flexibilidad en transmisión de acciones. "
            "Verificar beneficiarios controladores y monitorear cambios accionarios."
        )

    datos_asumidos = [f for f in factores if f.dato_asumido]
    if datos_asumidos:
        resultado.alertas.append(
            f"{len(datos_asumidos)} de 15 factores evaluados con datos asumidos. "
            "Calificación provisional sujeta a recalificación con datos reales."
        )

    # ─── Recomendaciones según grado ─────────────────────────────
    if resultado.calculo_completo:
        grado = resultado.grado_riesgo
        if grado == "ALTO" or coincidencia_lpb:
            resultado.recomendaciones.extend([
                "Aplicar medidas de debida diligencia reforzada (EDD).",
                "Realizar visita domiciliaria al cliente.",
                "Investigar actividad económica en fuentes abiertas.",
                "Requerir aprobación de funcionarios autorizados.",
                "Programar monitoreo intensificado posterior a la apertura.",
            ])
        elif grado == "MEDIO":
            resultado.recomendaciones.extend([
                "Entrevista de conocimiento del cliente para confirmar datos "
                "transaccionales esperados y origen/destino de recursos.",
                "Monitoreo trimestral de operaciones durante el primer año.",
            ])
        else:
            resultado.recomendaciones.append(
                "Seguimiento estándar — sin medidas adicionales requeridas."
            )

        if "SAPI" in tipo_upper:
            resultado.recomendaciones.append(
                "Verificar cambios en estructura accionaria semestralmente."
            )

    return resultado


# ═══════════════════════════════════════════════════════════════════
#  Clasificación interna
# ═══════════════════════════════════════════════════════════════════

def _clasificar(
    resultado: ResultadoCalc,
    coincidencia_lpb: bool,
    coincidencia_listas: bool,
) -> None:
    """Suma puntajes y clasifica. Modifica resultado in-place."""
    resultado.puntaje_total = round(
        sum(f.puntaje for f in resultado.factores), 2
    )
    resultado.calculo_completo = True

    total = resultado.puntaje_total
    if total > 255 or coincidencia_lpb or coincidencia_listas:
        resultado.grado_riesgo = "ALTO"
    elif total >= UMBRALES_PM["ALTO"][0]:
        resultado.grado_riesgo = "ALTO"
    elif total >= UMBRALES_PM["MEDIO"][0]:
        resultado.grado_riesgo = "MEDIO"
    elif total >= UMBRALES_PM["BAJO"][0]:
        resultado.grado_riesgo = "BAJO"
    else:
        resultado.grado_riesgo = "BAJO"


# ═══════════════════════════════════════════════════════════════════
#  Serialización a dict (para pasar al LLM si hay pendientes)
# ═══════════════════════════════════════════════════════════════════

def resultado_a_dict(resultado: ResultadoCalc) -> dict:
    """Convierte el resultado a un dict serializable."""
    return {
        "calculo_completo": resultado.calculo_completo,
        "puntaje_total": resultado.puntaje_total,
        "grado_riesgo": resultado.grado_riesgo,
        "factores": [
            {
                "numero": f.numero,
                "nombre": f.nombre,
                "valor": f.valor,
                "peso": f.peso,
                "puntaje": f.puntaje,
                "dato_cliente": f.dato_cliente,
                "dato_asumido": f.dato_asumido,
                "requiere_llm": f.requiere_llm,
                "nota": f.nota,
            }
            for f in resultado.factores
        ],
        "factores_pendientes_llm": [
            {
                "numero": f.numero,
                "nombre": f.nombre,
                "dato_cliente": f.dato_cliente,
                "nota": f.nota,
                "opciones_validas": _opciones_para_factor(f.numero),
            }
            for f in resultado.factores_pendientes_llm
        ],
        "alertas": resultado.alertas,
        "observaciones": resultado.observaciones,
        "recomendaciones": resultado.recomendaciones,
    }


def _opciones_para_factor(numero: int) -> list[dict]:
    if numero == 4:
        return [
            {"valor": 1, "descripcion": "Actividad de riesgo bajo (Grupo 1)"},
            {"valor": 2, "descripcion": "Actividad de riesgo medio (Grupo 2)"},
            {"valor": 3, "descripcion": "Actividad de riesgo alto (Grupo 3)"},
        ]
    if numero == 5:
        return [
            {"valor": 1, "descripcion": "Zona geográfica de riesgo 1"},
            {"valor": 2, "descripcion": "Zona geográfica de riesgo 2"},
            {"valor": 3, "descripcion": "Zona geográfica de riesgo 3"},
        ]
    if numero == 6:
        return [
            {"valor": 1, "descripcion": "Ya Ganaste / Básica de Nómina"},
            {"valor": 2, "descripcion": "Adquirencia / Fundadores"},
            {"valor": 3, "descripcion": "Útil / Corporativa"},
        ]
    if numero in (11, 12):
        return [
            {"valor": 1, "descripcion": "Nómina / Sueldos y Salarios"},
            {"valor": 2, "descripcion": "Otros"},
            {"valor": 3, "descripcion": "Actividades vulnerables"},
        ]
    return []


# ═══════════════════════════════════════════════════════════════════
#  Aplicar resoluciones del LLM y RECALCULAR
# ═══════════════════════════════════════════════════════════════════

def aplicar_resoluciones_llm(
    resultado: ResultadoCalc,
    resoluciones: dict[int, int],
    coincidencia_lpb: bool = False,
    coincidencia_listas: bool = False,
) -> ResultadoCalc:
    """
    Recibe resoluciones del LLM ``{numero_factor: valor}`` y recalcula.
    El LLM solo dice el VALOR (1, 2 o 3); el código hace la aritmética.
    """
    for factor in resultado.factores:
        if factor.requiere_llm and factor.numero in resoluciones:
            factor.valor = resoluciones[factor.numero]
            factor.puntaje = factor.valor * factor.peso * 100
            factor.requiere_llm = False
            factor.nota += f" → Resuelto por LLM: valor {factor.valor}"

    resultado.factores_pendientes_llm = [
        f for f in resultado.factores if f.requiere_llm
    ]

    if not resultado.factores_pendientes_llm:
        _clasificar(resultado, coincidencia_lpb, coincidencia_listas)

    return resultado
