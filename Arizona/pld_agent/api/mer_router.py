"""
API REST para el módulo Compliance MER PLD/FT v7.0.

Endpoints:
  POST /api/v1/compliance/mer          → Calcula grado de riesgo (JSON)
  POST /api/v1/compliance/mer/reporte  → Calcula y devuelve reporte texto
  POST /api/v1/compliance/mer/consulta → Consulta el manual MER vía RAG
  GET  /api/v1/compliance/catalogos/actividades?q=...  → Busca actividad
  GET  /api/v1/compliance/catalogos/paises              → Lista países + riesgo
  GET  /api/v1/compliance/catalogos/entidades           → Lista entidades + zona
  GET  /api/v1/compliance/catalogos/productos           → Lista productos
  GET  /api/v1/compliance/catalogos/origen-destino      → Lista origen/destino
  GET  /api/v1/compliance/health                        → Health check
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..models.mer_schemas import ResultadoMER, SolicitudMER
from ..services.mer_engine import calcular_riesgo_mer, generar_reporte_mer
from ..services.mer_search import consultar_mer
from ..services import mer_catalogos as cat

mer_router = APIRouter(
    prefix="/api/v1/compliance",
    tags=["Compliance — MER PLD/FT v7.0"],
)


# ═══════════════════════════════════════════════════════════════════
#  Evaluación de riesgo MER
# ═══════════════════════════════════════════════════════════════════

@mer_router.post("/mer", response_model=ResultadoMER)
async def evaluar_riesgo_mer(solicitud: SolicitudMER):
    """
    Calcula el grado de riesgo MER para una Persona Moral.

    Recibe los 15 factores y devuelve JSON con desglose completo,
    puntaje total, clasificación y observaciones.
    """
    try:
        resultado = calcular_riesgo_mer(solicitud)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en cálculo MER: {e}")


@mer_router.post("/mer/reporte", response_class=PlainTextResponse)
async def reporte_mer_texto(solicitud: SolicitudMER):
    """
    Calcula el grado de riesgo MER y devuelve un reporte de texto
    con tabla de desglose, clasificación y recomendaciones.
    """
    try:
        resultado = calcular_riesgo_mer(solicitud)
        texto = generar_reporte_mer(resultado)
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reporte MER: {e}")


# ═══════════════════════════════════════════════════════════════════
#  Consulta RAG al manual MER
# ═══════════════════════════════════════════════════════════════════

@mer_router.post("/mer/consulta")
async def consultar_manual_mer(
    query: str = Query(description="Pregunta sobre la MER PLD/FT"),
    top: int = Query(default=5, ge=1, le=10),
):
    """
    Busca en el índice kyb-mer-search fragmentos del manual MER
    relevantes a la consulta.
    """
    try:
        resultados = consultar_mer(query, top=top)
        return {"query": query, "resultados": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en consulta MER: {e}")


# ═══════════════════════════════════════════════════════════════════
#  Catálogos de referencia
# ═══════════════════════════════════════════════════════════════════

@mer_router.get("/catalogos/actividades")
async def buscar_actividad(
    q: str = Query(description="Nombre o código CNBV de la actividad económica"),
):
    """Busca una actividad económica en el catálogo CNBV y devuelve su grupo de riesgo."""
    valor = cat.buscar_actividad(q)
    if valor is None:
        return {
            "query": q,
            "encontrada": False,
            "mensaje": "Actividad no encontrada en catálogo CNBV.",
        }
    grupo = {1: "GRUPO 1 (riesgo bajo)", 2: "GRUPO 2 (riesgo medio)", 3: "GRUPO 3 (riesgo alto)"}
    return {
        "query": q,
        "encontrada": True,
        "valor_riesgo": valor,
        "grupo": grupo.get(valor, f"Grupo {valor}"),
    }


@mer_router.get("/catalogos/paises")
async def listar_paises():
    """Devuelve la lista completa de países con su ponderación de riesgo."""
    paises: list[dict] = []
    for p in sorted(cat.PAISES_LISTA_NEGRA):
        paises.append({"pais": p, "valor": 300, "lista": "Lista Negra"})
    for p in sorted(cat.PAISES_LISTA_GRIS):
        paises.append({"pais": p, "valor": 200, "lista": "Lista Gris"})
    paises.append({"pais": "Otros (GAFI)", "valor": 1, "lista": "GAFI"})
    return paises


@mer_router.get("/catalogos/entidades")
async def listar_entidades():
    """Devuelve las entidades federativas con su zona de riesgo."""
    entidades = {}
    for nombre, valor in cat.ENTIDAD_RIESGO.items():
        if nombre not in entidades:
            entidades[nombre] = valor
    return [
        {"entidad": e, "zona_riesgo": v}
        for e, v in sorted(entidades.items())
    ]


@mer_router.get("/catalogos/alcaldias")
async def listar_alcaldias():
    """Devuelve las alcaldías de CDMX con su riesgo total."""
    return [
        {"alcaldia": a, "riesgo_total": v}
        for a, v in sorted(cat.ALCALDIA_RIESGO.items())
    ]


@mer_router.get("/catalogos/productos")
async def listar_productos():
    """Devuelve los productos bancarios con su valor de riesgo."""
    return [
        {"producto": p, "valor_riesgo": v}
        for p, v in cat.PRODUCTOS.items()
    ]


@mer_router.get("/catalogos/origen-destino")
async def listar_origen_destino():
    """Devuelve el catálogo de origen/destino de recursos con su factor de riesgo."""
    seen: dict[str, int] = {}
    for nombre, valor in cat.ORIGEN_DESTINO_RIESGO.items():
        if nombre not in seen:
            seen[nombre] = valor
    return [
        {"concepto": c, "valor_riesgo": v}
        for c, v in sorted(seen.items())
    ]


@mer_router.get("/health")
async def health():
    """Health check del módulo Compliance MER."""
    return {
        "status": "ok",
        "module": "compliance-mer-pld",
        "version": "1.0.0",
        "mer_version": "7.0",
    }
