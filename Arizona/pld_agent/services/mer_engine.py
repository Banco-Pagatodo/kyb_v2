"""
Motor de cálculo MER PLD/FT v7.0 — Personas Morales.

Implementa la fórmula:
    PUNTAJE TOTAL = Σ (Valor_de_riesgo_i × Peso_i × 100)

Consulta opcionalmente el índice RAG ``kyb-mer-search`` para enriquecer
las observaciones con contexto cualitativo del manual MER.

La clasificación de actividad económica (Factor 4) usa un LLM cuando
el catálogo CNBV no tiene un match exacto/parcial: se envían las 65
actividades de Grupo 2 y 3, y el LLM razona semánticamente cuál aplica.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..models.mer_schemas import (
    FactorRiesgo,
    GradoRiesgo,
    ResultadoMER,
    SolicitudMER,
    TipoPersona,
    TipoPEP,
)
from ..models.schemas import ExpedientePLD
from . import mer_catalogos as cat
from .mer_calculator import calcular_mer_pm, aplicar_resoluciones_llm as _aplicar_llm
from .mer_search import consultar_mer

logger = logging.getLogger("arizona.mer_engine")


# ═══════════════════════════════════════════════════════════════════
#  Helpers internos
# ═══════════════════════════════════════════════════════════════════

def _parse_fecha(texto: str | None) -> date | None:
    """Intenta parsear una fecha en formatos comunes."""
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _antiguedad_anos(fecha_const: date) -> float:
    """Calcula los años transcurridos desde la fecha de constitución."""
    hoy = date.today()
    delta = hoy - fecha_const
    return delta.days / 365.25


def _valor_antiguedad(anos: float) -> int:
    """Valor de riesgo por antigüedad para PM."""
    if anos > 3:
        return 1
    if anos >= 1.1:
        return 2
    return 3


def _es_cdmx(entidad: str) -> bool:
    """Verifica si la entidad es Ciudad de México."""
    e = cat._normalizar(entidad)
    return e in ("ciudad de mexico", "cdmx", "df", "distrito federal")


# ═══════════════════════════════════════════════════════════════════
#  Extracción de campo desde expediente (replica lógica de etapa1)
# ═══════════════════════════════════════════════════════════════════

def _get_valor_exp(datos: dict[str, Any], campo: str) -> str | None:
    """Extrae un valor de datos_extraidos, desenrollando formato enriquecido."""
    if not datos:
        return None
    field = datos.get(campo)
    if field is None:
        return None
    if isinstance(field, dict) and "valor" in field:
        v = field.get("valor")
        if v is not None and str(v).strip() not in ("", "N/A", "None"):
            return str(v).strip()
        return None
    if isinstance(field, str) and field.strip() not in ("", "N/A", "None"):
        return field.strip()
    return None


def _buscar_domicilio(expediente: ExpedientePLD, campo: str) -> str | None:
    """Busca un campo de domicilio en CSF → domicilio anidado → comprobante."""
    csf = expediente.documentos.get("csf", {})
    # domicilio anidado dentro de CSF
    dom_anidado = csf.get("domicilio")
    if isinstance(dom_anidado, dict) and "valor" in dom_anidado:
        dom_anidado = dom_anidado.get("valor")
    if isinstance(dom_anidado, dict):
        v = _get_valor_exp(dom_anidado, campo)
        if v:
            return v
    # campo directo en CSF
    v = _get_valor_exp(csf, campo)
    if v:
        return v
    # comprobante de domicilio o estado_cuenta
    for alt in ("domicilio", "estado_cuenta"):
        alt_datos = expediente.documentos.get(alt, {})
        v = _get_valor_exp(alt_datos, campo)
        if v:
            return v
    return None


def construir_solicitud_mer(
    expediente: ExpedientePLD,
    screening_resumen: dict[str, Any] | None = None,
) -> SolicitudMER:
    """
    Construye una SolicitudMER a partir de los datos del expediente PLD.

    Extrae automáticamente los campos disponibles (razón social, actividad
    económica, entidad federativa, fecha de constitución, etc.) y mapea
    los resultados de screening a los flags MER (LPB, listas negativas, PEP).

    Los campos transaccionales (montos, operaciones, origen/destino) quedan
    como None ya que no están disponibles en el expediente documental.
    """
    dc = expediente.datos_clave  # dict de Colorado, puede ser None

    # ── Razón social ─────────────────────────────────────────────
    razon = expediente.razon_social

    # ── País de constitución (default México) ────────────────────
    pais = _buscar_domicilio(expediente, "pais") or "México"

    # ── Fecha de constitución ────────────────────────────────────
    fecha_const: str | None = None
    if dc and isinstance(dc, dict):
        v = dc.get("fecha_constitucion")
        if v and str(v).strip() not in ("", "N/A", "None"):
            fecha_const = str(v).strip()
    if not fecha_const:
        acta = expediente.documentos.get("acta_constitutiva", {})
        fecha_const = _get_valor_exp(acta, "fecha_constitucion")
    if not fecha_const:
        csf = expediente.documentos.get("csf", {})
        fecha_const = _get_valor_exp(csf, "fecha_inicio_operaciones")

    # ── Actividad económica / giro ───────────────────────────────
    actividad: str | None = None
    if dc and isinstance(dc, dict):
        v = dc.get("giro_mercantil")
        if v and str(v).strip() not in ("", "N/A", "None"):
            actividad = str(v).strip()
    if not actividad:
        csf = expediente.documentos.get("csf", {})
        actividad = _get_valor_exp(csf, "actividad_economica")
    if not actividad:
        acta = expediente.documentos.get("acta_constitutiva", {})
        actividad = _get_valor_exp(acta, "objeto_social")

    # ── Entidad federativa ───────────────────────────────────────
    entidad = _buscar_domicilio(expediente, "entidad_federativa")

    # ── Alcaldía (solo relevante si CDMX) ────────────────────────
    alcaldia: str | None = None
    if entidad and _es_cdmx(entidad):
        alcaldia = _buscar_domicilio(expediente, "municipio_alcaldia")

    # ── Producto (default corporativa para PM) ───────────────────
    producto = "corporativa"

    # ── Screening → flags MER ────────────────────────────────────
    coincidencia_lpb = False
    coincidencia_listas = False
    pep = TipoPEP.NO

    if screening_resumen and isinstance(screening_resumen, dict):
        coincidencia_lpb = bool(screening_resumen.get("tiene_coincidencias_criticas"))
        # Revisar resultados individuales para detectar PEP o listas negativas
        for r in screening_resumen.get("resultados", []):
            if not r.get("tiene_coincidencias"):
                continue
            for c in r.get("coincidencias", []):
                tipo = (c.get("tipo_lista") or "").upper()
                tabla = (c.get("tabla_origen") or "").upper()
                if "PEP" in tipo or "PEP" in tabla:
                    pep = TipoPEP.NACIONAL
                if "OFAC" in tipo or "69" in tabla or "LISTA_NEGRA" in tipo:
                    coincidencia_listas = True

    return SolicitudMER(
        nombre_razon_social=razon,
        pais_constitucion=pais,
        fecha_constitucion=fecha_const,
        actividad_economica=actividad,
        entidad_federativa=entidad,
        alcaldia=alcaldia,
        producto=producto,
        coincidencia_lpb=coincidencia_lpb,
        coincidencia_listas_negativas=coincidencia_listas,
        pep=pep,
    )


# ═══════════════════════════════════════════════════════════════════
#  Motor principal — delega al calculador determinista
# ═══════════════════════════════════════════════════════════════════

def calcular_riesgo_mer(solicitud: SolicitudMER) -> ResultadoMER:
    """
    Calcula el grado de riesgo MER para una Persona Moral.

    CAPA 1 (código determinista):
      Delega a ``mer_calculator.calcular_mer_pm()`` que busca en catálogos,
      asigna valores, multiplica, suma y clasifica.

    CAPA 2 (LLM, solo si hay factores pendientes):
      Si la actividad económica no se encontró en el catálogo CNBV, el
      calculador marca el factor como ``requiere_llm``.  Aquí se intenta
      resolver via RAG y heurísticas; si no se logra, se aplica el valor
      por defecto Grupo 2 (principio de prudencia).

    El LLM NUNCA hace multiplicaciones, sumas ni clasificaciones.
    """
    # ── Paso 1: cálculo determinista ─────────────────────────────
    pep_str = solicitud.pep.value if isinstance(solicitud.pep, TipoPEP) else str(solicitud.pep)

    calc = calcular_mer_pm(
        tipo_societario=solicitud.nombre_razon_social,  # para detectar SAPI, SC, etc.
        pais_constitucion=solicitud.pais_constitucion or "México",
        fecha_constitucion=solicitud.fecha_constitucion,
        actividad_economica=solicitud.actividad_economica,
        entidad_federativa=solicitud.entidad_federativa,
        alcaldia_cdmx=solicitud.alcaldia,
        producto=solicitud.producto or "corporativa",
        coincidencia_lpb=solicitud.coincidencia_lpb,
        coincidencia_listas_negativas=solicitud.coincidencia_listas_negativas,
        pep=pep_str,
        monto_recibido=solicitud.monto_recibido,
        monto_enviado=solicitud.monto_enviado,
        ops_recibidas=solicitud.ops_recibidas,
        ops_enviadas=solicitud.ops_enviadas,
        origen_recursos=solicitud.origen_recursos,
        destino_recursos=solicitud.destino_recursos,
    )

    # ── Paso 2: resolver factores pendientes (si los hay) ────────
    if calc.factores_pendientes_llm:
        resoluciones: dict[int, int] = {}
        for fp in calc.factores_pendientes_llm:
            if fp.numero == 4:
                # Actividad no encontrada → clasificar con LLM
                val_resuelto, justificacion = _resolver_actividad_por_rag(
                    solicitud.actividad_economica
                )
                resoluciones[4] = val_resuelto
                fp.nota += f" → LLM: {justificacion}"
            elif fp.numero == 6:
                # Producto no reconocido → default Corporativa (3)
                resoluciones[6] = 3
            else:
                # Otros factores pendientes → valor por defecto medio
                resoluciones[fp.numero] = 2

        _aplicar_llm(
            calc, resoluciones,
            coincidencia_lpb=solicitud.coincidencia_lpb,
            coincidencia_listas=solicitud.coincidencia_listas_negativas,
        )

    # ── Paso 3: mapear a ResultadoMER (esquema Pydantic) ────────
    factores_pydantic = [
        FactorRiesgo(
            numero=f.numero,
            nombre=f.nombre,
            dato_cliente=f.dato_cliente,
            valor_riesgo=f.valor if f.valor is not None else 0,
            peso=f.peso,
            puntaje=f.puntaje if f.puntaje is not None else 0.0,
            dato_asumido=f.dato_asumido,
            nota=f.nota,
        )
        for f in calc.factores
    ]

    grado = calc.grado_riesgo or "BAJO"
    puntaje = calc.puntaje_total if calc.puntaje_total is not None else 0.0

    # ── RAG para contexto cualitativo (best-effort) ──────────────
    contexto_mer: list[str] = []
    try:
        queries_rag: list[str] = []
        # Solo consultar si hay situaciones de riesgo
        act_factor = next((f for f in calc.factores if f.numero == 4), None)
        if act_factor and act_factor.valor == 3 and solicitud.actividad_economica:
            queries_rag.append(
                f"actividad vulnerable riesgo alto {solicitud.actividad_economica}"
            )
        if grado == "ALTO":
            queries_rag.append("debida diligencia reforzada persona moral alto riesgo")
        if solicitud.coincidencia_lpb:
            queries_rag.append("lista de personas bloqueadas procedimiento bloqueo")

        for q in queries_rag[:2]:
            hits = consultar_mer(q, top=2)
            for h in hits:
                if h.get("content"):
                    contexto_mer.append(h["content"][:500])
    except Exception as exc:
        logger.debug("RAG MER no disponible: %s", exc)

    return ResultadoMER(
        empresa=solicitud.nombre_razon_social,
        tipo_persona=TipoPersona.PM,
        factores=factores_pydantic,
        puntaje_total=round(puntaje, 2),
        grado_riesgo=GradoRiesgo(grado),
        observaciones=calc.observaciones,
        recomendaciones=calc.recomendaciones,
        contexto_mer=contexto_mer,
        alertas=calc.alertas,
        calculo_completo=calc.calculo_completo,
    )


def _resolver_actividad_por_rag(actividad: str | None) -> tuple[int, str]:
    """
    Clasifica una actividad económica que NO se encontró en el catálogo CNBV
    usando el LLM para razonamiento semántico.

    Estrategia:
      1. Envía al LLM las ~65 actividades de riesgo medio/alto del catálogo.
      2. El LLM evalúa si la actividad del cliente es semánticamente
         equivalente a alguna de ellas.
      3. Si no coincide con ninguna → Grupo 1 (la mayoría del catálogo).

    Returns:
        Tupla (grupo_riesgo: int, justificacion: str)
    """
    if not actividad:
        return 2, "Actividad no proporcionada. Asumido riesgo medio (Grupo 2)."

    # ── Obtener actividades de riesgo medio y alto del catálogo ────
    catalogo = cat.obtener_actividades_riesgo_alto_medio()
    grupo_3 = catalogo["grupo_3"]
    grupo_2 = catalogo["grupo_2"]

    # ── Construir prompt para el LLM ──────────────────────────────
    prompt_sistema = (
        "Eres un analista experto en PLD/AML y clasificación de actividades "
        "económicas según el catálogo CNBV de México para la Matriz de "
        "Evaluación de Riesgos (MER).\n\n"
        "Tu trabajo es determinar el GRUPO DE RIESGO (1, 2 o 3) de una "
        "actividad económica comparándola semánticamente con el catálogo.\n\n"
        "REGLAS:\n"
        "- Grupo 3 (ALTO): Actividades financieras, cambio de divisas, "
        "casas de bolsa, notarías, joyería, vehículos, armas, construcción "
        "de gran escala, centros nocturnos, sindicatos, casinos.\n"
        "- Grupo 2 (MEDIO): Seguridad privada, bares, motocicletas, "
        "arrendadoras financieras, artículos de plata, organizaciones "
        "políticas.\n"
        "- Grupo 1 (BAJO): Todo lo demás (manufactura, comercio general, "
        "servicios profesionales, agricultura, educación, salud, etc.).\n\n"
        "IMPORTANTE: No te limites a buscar palabras exactas. Razona sobre "
        "la NATURALEZA de la actividad. Por ejemplo:\n"
        "- 'Servicios relacionados con la intermediación crediticia' → es "
        "una actividad financiera de intermediación → Grupo 3\n"
        "- 'Venta de autos seminuevos' → equivale a compraventa de "
        "automóviles usados → Grupo 3\n"
        "- 'Tienda de abarrotes' → comercio general → Grupo 1\n\n"
        "Responde EXCLUSIVAMENTE con un JSON válido (sin markdown, sin "
        "backticks) con esta estructura:\n"
        '{"grupo": <1|2|3>, "justificacion": "<razón breve>", '
        '"actividad_catalogo_equivalente": "<nombre de la actividad del '
        'catálogo que más se asemeja, o null si es Grupo 1>"}'
    )

    prompt_usuario = (
        f"Actividad del cliente: \"{actividad}\"\n\n"
        f"Actividades del catálogo CNBV Grupo 3 (riesgo ALTO):\n"
    )
    for a in grupo_3:
        prompt_usuario += f"  - {a}\n"
    prompt_usuario += f"\nActividades del catálogo CNBV Grupo 2 (riesgo MEDIO):\n"
    for a in grupo_2:
        prompt_usuario += f"  - {a}\n"
    prompt_usuario += (
        "\n¿A qué grupo de riesgo pertenece la actividad del cliente? "
        "Si no coincide con ninguna de las anteriores, es Grupo 1 (bajo)."
    )

    # ── Llamar al LLM ─────────────────────────────────────────────
    try:
        grupo, justificacion = _llamar_llm_clasificacion(
            prompt_sistema, prompt_usuario
        )
        logger.info(
            "Actividad '%s' clasificada por LLM → Grupo %d: %s",
            actividad, grupo, justificacion,
        )
        return grupo, justificacion
    except Exception as exc:
        logger.warning(
            "LLM no disponible para clasificar actividad '%s': %s. "
            "Aplicando fallback por keywords.",
            actividad, exc,
        )
        return _fallback_keywords(actividad)


def _llamar_llm_clasificacion(
    prompt_sistema: str, prompt_usuario: str
) -> tuple[int, str]:
    """
    Llama a Azure OpenAI para clasificar la actividad económica.
    Retorna (grupo, justificacion).
    """
    # Cargar credenciales
    _service_root = Path(__file__).resolve().parent.parent
    _project_root = _service_root.parent.parent
    for env_path in [
        _service_root / ".env",
        _project_root / ".env",
        _project_root / "Dakota" / "kyb_review" / ".env",
        _project_root / "Dakota" / "kyb_review" / "api" / "service" / ".env",
        Path.cwd() / ".env",
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            break

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    deployment = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

    if not endpoint or not api_key:
        raise RuntimeError("Credenciales Azure OpenAI no configuradas")

    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": prompt_usuario},
        ],
        temperature=0.0,
        max_tokens=300,
    )

    contenido = (response.choices[0].message.content or "").strip()

    # Parsear JSON de la respuesta
    # Limpiar posibles backticks markdown
    contenido_limpio = re.sub(r"^```(?:json)?\s*", "", contenido)
    contenido_limpio = re.sub(r"\s*```$", "", contenido_limpio)

    try:
        resultado = json.loads(contenido_limpio)
    except json.JSONDecodeError:
        # Intentar extraer grupo con regex como fallback
        match = re.search(r'"grupo"\s*:\s*(\d)', contenido)
        if match:
            grupo = int(match.group(1))
            return grupo, f"Clasificado por LLM (respuesta parcial): {contenido[:200]}"
        raise ValueError(f"No se pudo parsear respuesta del LLM: {contenido[:300]}")

    grupo = int(resultado.get("grupo", 2))
    justificacion = resultado.get("justificacion", "Sin justificación")
    equivalente = resultado.get("actividad_catalogo_equivalente")

    if equivalente:
        justificacion = f"{justificacion} [Equivalente catálogo: {equivalente}]"

    # Validar rango
    if grupo not in (1, 2, 3):
        grupo = 2

    return grupo, justificacion


def _fallback_keywords(actividad: str) -> tuple[int, str]:
    """
    Fallback por keywords cuando el LLM no está disponible.
    Retorna (grupo, justificacion).
    """
    texto = actividad.upper()

    alto_riesgo_keywords = [
        "FACTORING", "ARRENDADORA", "SOFOM", "CASA DE CAMBIO",
        "TRANSMISORA DE DINERO", "ACTIVOS VIRTUALES", "CRIPTO",
        "INTERMEDIACION CREDITICIA", "INTERMEDIACIÓN CREDITICIA",
        "FINANCIERA NO BANCARIA", "CONTROLADORAS FINANCIERAS",
        "CAJA DE AHORROS", "SOCIEDAD FINANCIERA", "CASA DE BOLSA",
        "NOTARI", "JOYERI", "CASINO", "CENTRO NOCTURNO",
        "COMPRA VENTA DE ARMAS", "SINDICAT", "MONTEPIO",
    ]
    for kw in alto_riesgo_keywords:
        if kw in texto:
            return 3, f"Clasificado por keywords (fallback): contiene '{kw}'"

    bajo_riesgo_keywords = [
        "AGRÍCOLA", "AGRICOLA", "GANADERÍA", "GANADERIA",
        "EDUCACIÓN", "EDUCACION", "SALUD", "MANUFACTURERA",
        "TIENDA", "ABARROTES", "PAPELERÍA", "PAPELERIA",
        "FARMACIA", "CONSULTORIO", "ESCUELA",
    ]
    for kw in bajo_riesgo_keywords:
        if kw in texto:
            return 1, f"Clasificado por keywords (fallback): contiene '{kw}'"

    return 2, "No clasificada → Grupo 2 por principio de prudencia (fallback)"


# ═══════════════════════════════════════════════════════════════════
#  Generador de reporte texto
# ═══════════════════════════════════════════════════════════════════

def generar_reporte_mer(resultado: ResultadoMER) -> str:
    """Genera un reporte de texto legible con el desglose MER completo."""
    lineas: list[str] = []
    w = lineas.append

    w("=" * 80)
    w("  EVALUACIÓN DE RIESGO MER PLD/FT v7.0 — BANCO PAGATODO")
    w("  Metodología de Evaluación de Riesgos — Personas Morales")
    w("=" * 80)
    w("")
    w(f"  Empresa:        {resultado.empresa}")
    w(f"  Tipo de persona: Persona Moral")
    w(f"  Fecha de evaluación: {date.today().strftime('%d/%m/%Y')}")
    w("")

    # ── Tabla de factores ────────────────────────────────────────
    w("─" * 80)
    w(f"  {'#':<3} {'Factor':<45} {'Valor':>6} {'Peso':>6} {'Puntaje':>8}")
    w("─" * 80)

    for f in resultado.factores:
        w(f"  {f.numero:<3} {f.nombre:<45} {f.valor_riesgo:>6.0f} {f.peso:>6.2f} {f.puntaje:>8.1f}")
        w(f"      └─ {f.dato_cliente}")

    w("─" * 80)
    w(f"  {'PUNTAJE TOTAL':<56} {resultado.puntaje_total:>8.1f}")
    w("─" * 80)

    # ── Clasificación ────────────────────────────────────────────
    w("")
    w("  ┌─────────────────────────────────────────────────────┐")
    w(f"  │  CLASIFICACIÓN:  {resultado.grado_riesgo.value:<34}│")

    emoji = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(resultado.grado_riesgo.value, "⚪")
    w(f"  │  {emoji}  Grado de riesgo: {resultado.grado_riesgo.value:<25}│")
    w(f"  │  Puntaje: {resultado.puntaje_total:<40.1f}│")
    w("  │                                                     │")
    w("  │  Rangos PM:  BAJO 85-142 │ MEDIO 143-199 │ ALTO 200+ │")
    w("  └─────────────────────────────────────────────────────┘")

    # ── Observaciones ────────────────────────────────────────────
    if resultado.observaciones:
        w("")
        w("  OBSERVACIONES:")
        w("  " + "─" * 50)
        for obs in resultado.observaciones:
            w(f"  • {obs}")

    # ── Recomendaciones ──────────────────────────────────────────
    if resultado.recomendaciones:
        w("")
        w("  RECOMENDACIONES DE DEBIDA DILIGENCIA:")
        w("  " + "─" * 50)
        for rec in resultado.recomendaciones:
            w(f"  • {rec}")

    # ── Contexto MER (RAG) ───────────────────────────────────────
    if resultado.contexto_mer:
        w("")
        w("  REFERENCIAS DEL MANUAL MER:")
        w("  " + "─" * 50)
        for i, ctx in enumerate(resultado.contexto_mer, 1):
            w(f"  [{i}] {ctx[:300]}...")

    w("")
    w("=" * 80)
    w("  Fin del reporte MER — Banco PagaTodo, S.A.")
    w("=" * 80)

    return "\n".join(lineas)
