"""
Módulo de Análisis con IA — Azure OpenAI GPT-4o.

Proporciona análisis inteligente de los resultados de screening PLD/AML.
Esto es lo que convierte a Arizona en un verdadero AGENTE de IA:
- Interpreta las coincidencias encontradas
- Evalúa el contexto y riesgo real
- Distingue homónimos de matches reales con razonamiento
- Genera recomendaciones específicas por persona
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger("arizona.llm_analysis")

# ── Cargar .env ──────────────────────────────────────────────────
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

# ── Configuración Azure OpenAI ──────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")


SYSTEM_PROMPT = """\
Eres un analista experto en Prevención de Lavado de Dinero (PLD/AML) y \
Financiamiento al Terrorismo (FT) en México. Tu trabajo es analizar los \
resultados de screening contra listas negras y emitir una evaluación \
profesional de riesgo.

Marco regulatorio que conoces:
- LFPIORPI (Ley Federal para la Prevención e Identificación de Operaciones con Recursos de Procedencia Ilícita)
- DCG CNBV (Disposiciones de Carácter General en materia de PLD/FT)
- CFF Art. 69-B (EFOS/EDOS)
- CFF Art. 32-B Ter (Beneficiarios Controladores)
- Lista OFAC (SDN List del Departamento del Tesoro de EE.UU.)
- Listas UIF/SHCP de personas bloqueadas

REGLAS ABSOLUTAS:
1. Tu análisis SÓLO debe basarse en los DATOS REALES que te proporcione el screening.
2. Si una lista aparece como "fallida" (error de conexión), NO PUEDES inferir \
nada sobre esa lista. NO sabes si la persona está o no en ella.
3. NUNCA uses tu conocimiento general para suponer que alguien aparece \
o no en una lista. NO eres una lista negra. Eres un ANALISTA de datos.
4. Si NO hay coincidencias reales (datos devueltos por SQL), NO puedes \
hablar de homónimos. Un homónimo es cuando HAY una coincidencia de nombre \
y debes evaluar si es o no la misma persona. Sin datos, no hay homónimos.
5. Si todas las listas fallaron, tu ÚNICO trabajo es señalar que el \
screening NO pudo completarse y que NO se puede emitir ninguna evaluación.

Responde siempre en español. Sé conciso pero completo. \
Usa un tono profesional y regulatorio. \
NUNCA inventes datos que no están en el screening.\
"""


def _build_screening_prompt(datos_screening: dict[str, Any]) -> str:
    """Construye el prompt con los datos de screening para el LLM."""
    partes = [
        "Analiza los siguientes resultados de screening PLD/AML contra listas negras.",
        "Cada persona fue buscada en 3 tablas de SQL Server:",
        "  - CatPLD69BPerson: Lista 69-B del SAT (EFOS/EDOS)",
        "  - CatPLDLockedPerson: Personas Bloqueadas por UIF/SHCP",
        "  - TraPLDBlackListEntry: Lista Negra Consolidada (OFAC, PEP, SAT69)",
        "",
        "=" * 60,
        "RESULTADOS DEL SCREENING",
        "=" * 60,
    ]

    for i, res in enumerate(datos_screening.get("resultados", []), 1):
        persona = res.get("persona", {})
        partes.append(f"\n--- PERSONA {i} ---")
        partes.append(f"Nombre: {persona.get('nombre', 'N/D')}")
        partes.append(f"CURP: {persona.get('curp', 'N/D')}")
        partes.append(f"RFC: {persona.get('rfc', 'N/D')}")
        partes.append(f"Tipo: {persona.get('tipo_persona', 'N/D')}")
        partes.append(f"Rol declarado: {persona.get('rol', 'N/D')}")
        partes.append(f"Score máximo: {res.get('score_maximo', 0)}")
        partes.append(f"Nivel de riesgo: {res.get('nivel_riesgo', 'N/D')}")
        partes.append(f"Listas exitosas: {', '.join(res.get('listas_exitosas', []))}")
        partes.append(f"Listas fallidas: {', '.join(res.get('listas_fallidas', []))}")

        coincidencias = res.get("coincidencias", [])
        if coincidencias:
            partes.append(f"\nCoincidencias encontradas: {len(coincidencias)}")
            for j, c in enumerate(coincidencias, 1):
                partes.append(f"\n  Coincidencia #{j}:")
                partes.append(f"    Tabla SQL origen: {c.get('tabla_origen', 'N/D')}")
                partes.append(f"    Tipo lista: {c.get('tipo_lista', 'N/D')}")
                partes.append(f"    Fuente: {c.get('fuente', 'N/D')}")
                partes.append(f"    Nombre en lista: {c.get('nombre_en_lista', 'N/D')}")
                partes.append(f"    RFC en lista: {c.get('rfc_en_lista', 'N/D')}")
                partes.append(f"    CURP en lista: {c.get('curp_en_lista', 'N/D')}")
                partes.append(f"    Score: {c.get('score', 0)} ({c.get('nivel_coincidencia', 'N/D')})")
                partes.append(f"    Similitud nombre: {c.get('match_nombre', 0)*100:.1f}%")
                partes.append(f"    Match RFC: {c.get('match_rfc', False)}")
                partes.append(f"    Match CURP: {c.get('match_curp', False)}")
                partes.append(f"    Categoría: {c.get('categoria', 'N/D')}")
                partes.append(f"    Situación: {c.get('situacion', 'N/D')}")
                partes.append(f"    Info adicional: {c.get('informacion_adicional', 'N/D')}")
                partes.append(f"    Scoring: {c.get('explicacion_score', [])}")
        else:
            partes.append("\nSin coincidencias.")

    partes.append("\n" + "=" * 60)
    partes.append(
        "Por favor genera tu análisis profesional PLD/AML con:\n"
        "1. EVALUACIÓN DE RIESGO por persona (ALTO / MEDIO / BAJO)\n"
        "2. ANÁLISIS DE HOMÓNIMOS: ¿Es probable que sea la misma persona o un homónimo?\n"
        "3. RAZONAMIENTO: Justifica tu evaluación con los datos disponibles\n"
        "4. RECOMENDACIONES ESPECÍFICAS para el oficial de cumplimiento\n"
        "5. CONCLUSIÓN GENERAL del screening\n"
    )

    return "\n".join(partes)


def analizar_screening_con_ia(
    datos_screening: dict[str, Any],
) -> str:
    """
    Envía los resultados del screening a Azure OpenAI GPT-4o para
    obtener un análisis inteligente de riesgo PLD/AML.

    Args:
        datos_screening: Dict con los resultados del screening
            (resumen completo con resultados por persona)

    Returns:
        Texto con el análisis de IA. Si falla, retorna un mensaje
        indicando que el análisis de IA no pudo completarse.
    """
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
        msg = (
            "⚠️  Análisis de IA no disponible: faltan credenciales Azure OpenAI.\n"
            "    Configure AZURE_OPENAI_ENDPOINT y AZURE_OPENAI_API_KEY."
        )
        logger.warning(msg)
        return msg

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )

        user_prompt = _build_screening_prompt(datos_screening)

        logger.info(
            "Enviando resultados de screening a GPT-4o para análisis PLD/AML..."
        )

        response = client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,  # Bajo para análisis regulatorio preciso
            max_tokens=2000,
        )

        analysis = response.choices[0].message.content or ""
        logger.info("Análisis de IA completado correctamente.")
        return analysis.strip()

    except ImportError:
        msg = (
            "⚠️  Análisis de IA no disponible: librería 'openai' no instalada.\n"
            "    Instalar con: pip install openai"
        )
        logger.error(msg)
        return msg
    except Exception as e:
        msg = (
            f"⚠️  Error al obtener análisis de IA: {e}\n"
            "    El screening se completó pero el análisis inteligente falló.\n"
            "    Se recomienda revisión manual por analista PLD."
        )
        logger.error(msg)
        return msg


def serializar_resultado_para_llm(resultado: Any) -> dict[str, Any]:
    """
    Convierte un ResultadoScreening / ResumenScreening a dict
    para enviar al LLM.
    """
    from .blacklist_screening import ResumenScreening, ResultadoScreening

    if isinstance(resultado, ResumenScreening):
        return {
            "total_personas": resultado.total_personas,
            "personas_con_coincidencias": resultado.personas_con_coincidencias,
            "screening_incompleto": resultado.screening_incompleto,
            "resultados": [
                _serializar_resultado_individual(r)
                for r in resultado.resultados
            ],
        }
    elif isinstance(resultado, ResultadoScreening):
        return {
            "total_personas": 1,
            "personas_con_coincidencias": 1 if resultado.tiene_coincidencias else 0,
            "screening_incompleto": resultado.screening_incompleto,
            "resultados": [_serializar_resultado_individual(resultado)],
        }
    else:
        return resultado  # ya es dict


def _serializar_resultado_individual(r: Any) -> dict[str, Any]:
    """Serializa un ResultadoScreening individual para el LLM."""
    return {
        "persona": {
            "nombre": r.persona.nombre,
            "rfc": r.persona.rfc,
            "curp": r.persona.curp,
            "tipo_persona": r.persona.tipo_persona,
            "rol": r.persona.rol,
        },
        "tiene_coincidencias": r.tiene_coincidencias,
        "score_maximo": r.score_maximo,
        "nivel_riesgo": r.nivel_riesgo.value,
        "listas_exitosas": r.listas_exitosas,
        "listas_fallidas": r.listas_fallidas,
        "coincidencias": [
            {
                "tabla_origen": c.tabla_origen,
                "tipo_lista": c.tipo_lista.value,
                "fuente": c.fuente,
                "nombre_en_lista": c.nombre_en_lista,
                "rfc_en_lista": c.rfc_en_lista,
                "curp_en_lista": c.curp_en_lista,
                "score": c.score,
                "nivel_coincidencia": c.nivel_coincidencia.value,
                "match_nombre": c.match_nombre,
                "match_rfc": c.match_rfc,
                "match_curp": c.match_curp,
                "categoria": c.categoria,
                "situacion": c.situacion,
                "informacion_adicional": c.informacion_adicional,
                "explicacion_score": c.explicacion_score,
            }
            for c in r.coincidencias
        ],
    }
