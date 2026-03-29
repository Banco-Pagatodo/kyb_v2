"""
API REST para el agente PLD.
"""
from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from ..services.data_loader import cargar_expediente_pld, listar_empresas_pld
from ..services.etapa1_completitud import ejecutar_etapa1
from ..services.etapa4_propietarios_reales import extraer_estructura_para_reporte
from ..services.report_generator import (
    generar_reporte_etapa1,
    generar_reporte_completo,
    generar_reporte_unificado,
)
from ..services.persistence import (
    guardar_resultado_completo,
    obtener_analisis_pld,
    obtener_dictamen_pld,
)
from ..services.blacklist_screening import (
    ejecutar_screening_completo,
    generar_reporte_screening,
)
from ..services.mer_engine import construir_solicitud_mer, calcular_riesgo_mer
from ..services.dictamen_generator import generar_dictamen, sanitizar_nombre_archivo
from ..services.dictamen_txt import generar_txt_dictamen
from ..models.schemas import VerificacionCompletitud

router = APIRouter(prefix="/api/v1/pld", tags=["PLD / AML — Arizona"])


def _validar_uuid(empresa_id: str) -> str:
    """Valida que empresa_id sea un UUID válido; lanza 400 si no."""
    try:
        _uuid.UUID(empresa_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"empresa_id '{empresa_id}' no es un UUID válido",
        )
    return empresa_id


def _serializar_resumen_screening(resumen) -> dict:
    """Serializa un ResumenScreening a dict con nombres de campos correctos."""
    return {
        "total_personas": resumen.total_personas,
        "personas_con_coincidencias": resumen.personas_con_coincidencias,
        "coincidencias_confirmadas": resumen.coincidencias_confirmadas,
        "coincidencias_probables": resumen.coincidencias_probables,
        "coincidencias_posibles": resumen.coincidencias_posibles,
        "homonimos_descartados": resumen.homonimos_descartados,
        "tiene_coincidencias_criticas": resumen.tiene_coincidencias_criticas,
        "requiere_escalamiento": resumen.requiere_escalamiento,
        "screening_incompleto": resumen.screening_incompleto,
        "errores_conexion": resumen.errores_conexion,
        "resultados": [
            {
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
                "listas_consultadas": r.listas_consultadas,
                "listas_exitosas": r.listas_exitosas,
                "listas_fallidas": r.listas_fallidas,
                "screening_incompleto": r.screening_incompleto,
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
                        "subcategoria": c.subcategoria,
                        "situacion": c.situacion,
                        "informacion_adicional": c.informacion_adicional,
                        "explicacion_score": c.explicacion_score,
                    }
                    for c in r.coincidencias
                ],
            }
            for r in resumen.resultados
        ],
    }


def _construir_personas_bc(
    estructura_accionaria: dict | None,
    resultado_etapa1: VerificacionCompletitud,
) -> list[dict]:
    """
    Construye la lista de beneficiarios controladores para screening.

    Prioridad:
      1. Propietarios reales (PF ≥ 25 %) de la estructura accionaria.
      2. Si no hay ≥ 25 %, busca administradores/consejeros de Etapa 1.
      3. Último recurso: apoderado / representante legal.
    """
    personas: list[dict] = []
    ya_incluido: set[str] = set()

    # ── 1. Propietarios reales PF ≥ 25 % ────────────────────────
    if estructura_accionaria:
        for pr in estructura_accionaria.get("propietarios_reales", []):
            nombre = (pr.get("nombre") or "").strip()
            if not nombre:
                continue
            # Solo personas físicas
            tipo = pr.get("tipo_participacion", "")
            # Los propietarios reales ya fueron filtrados como ≥25% en Etapa 4
            # Verificar que no sean PM (las PM requieren look-through)
            accionistas = estructura_accionaria.get("accionistas", [])
            acc_match = next(
                (a for a in accionistas if (a.get("nombre") or "").strip().upper() == nombre.upper()),
                None,
            )
            if acc_match and acc_match.get("tipo_persona") == "moral":
                continue  # PM — no screeneamos la PM, sino sus PFs (pendiente look-through)

            key = nombre.upper()
            if key not in ya_incluido:
                ya_incluido.add(key)
                personas.append({
                    "nombre": nombre,
                    "rfc": pr.get("rfc") or "",
                    "tipo_persona": "fisica",
                    "rol": "beneficiario_controlador",
                    "fuente": "estructura_accionaria",
                    "requiere_screening": True,
                })

    # ── 2. Fallback: administradores / consejeros ────────────────
    if not personas:
        for p in resultado_etapa1.personas_identificadas:
            if p.rol in ("administrador", "consejero"):
                key = p.nombre.upper().strip()
                if key not in ya_incluido:
                    ya_incluido.add(key)
                    personas.append({
                        "nombre": p.nombre,
                        "rfc": "",
                        "tipo_persona": p.tipo_persona,
                        "rol": "beneficiario_controlador",
                        "fuente": p.fuente,
                        "requiere_screening": True,
                    })

    # ── 3. Último recurso: representante legal / apoderado ───────
    if not personas:
        for p in resultado_etapa1.personas_identificadas:
            if p.rol in ("apoderado", "representante_legal"):
                key = p.nombre.upper().strip()
                if key not in ya_incluido:
                    ya_incluido.add(key)
                    personas.append({
                        "nombre": p.nombre,
                        "rfc": "",
                        "tipo_persona": p.tipo_persona,
                        "rol": "beneficiario_controlador",
                        "fuente": p.fuente,
                        "requiere_screening": True,
                    })

    return personas


@router.get("/empresas")
async def list_empresas():
    """Lista empresas con su estado de documentación y validación cruzada."""
    return await listar_empresas_pld()


@router.post("/etapa1/{empresa_id}", response_model=VerificacionCompletitud)
async def etapa1_completitud(empresa_id: str):
    """
    Ejecuta la Etapa 1 PLD — Verificación de completitud documental.
    Devuelve JSON con items verificados, personas identificadas y resultado.
    """
    _validar_uuid(empresa_id)
    try:
        expediente = await cargar_expediente_pld(empresa_id)
        resultado = ejecutar_etapa1(expediente)
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en Etapa 1 PLD: {str(e)}")


@router.post("/etapa1/{empresa_id}/reporte", response_class=PlainTextResponse)
async def etapa1_reporte_texto(empresa_id: str):
    """
    Ejecuta Etapa 1 y devuelve reporte de texto formateado.
    """
    _validar_uuid(empresa_id)
    try:
        expediente = await cargar_expediente_pld(empresa_id)
        resultado = ejecutar_etapa1(expediente)
        texto = generar_reporte_etapa1(resultado)
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en Etapa 1 PLD: {str(e)}")


@router.get("/health")
async def health():
    """Health check del servicio PLD."""
    return {"status": "ok", "service": "pld-agent-arizona", "version": "0.2.0"}


# ═══════════════════════════════════════════════════════════════════
#  ETAPA 2 — SCREENING CONTRA LISTAS NEGRAS
# ═══════════════════════════════════════════════════════════════════

@router.post("/etapa2/{empresa_id}")
async def etapa2_screening(empresa_id: str):
    """
    Ejecuta la Etapa 2 PLD — Screening contra listas negras/PEPs.
    
    Requiere que Etapa 1 se haya ejecutado primero (necesita personas_identificadas).
    Devuelve JSON con resumen de coincidencias y nivel de riesgo.
    """
    _validar_uuid(empresa_id)
    try:
        # Primero ejecutar Etapa 1 para obtener personas identificadas
        expediente = await cargar_expediente_pld(empresa_id)
        resultado_etapa1 = ejecutar_etapa1(expediente)
        
        if not resultado_etapa1.personas_identificadas:
            return {
                "empresa_id": empresa_id,
                "rfc": resultado_etapa1.rfc,
                "razon_social": resultado_etapa1.razon_social,
                "etapa": "ETAPA_2_SCREENING",
                "resultado": "SIN_PERSONAS",
                "mensaje": "No se identificaron personas para screening en Etapa 1",
            }
        
        # Convertir PersonaIdentificada a dict para el servicio de screening
        personas_dict = [p.model_dump() for p in resultado_etapa1.personas_identificadas]
        
        # Ejecutar screening
        resumen = ejecutar_screening_completo(personas_dict)
        
        # Serializar para respuesta
        resumen_dict = _serializar_resumen_screening(resumen)
        
        return {
            "empresa_id": empresa_id,
            "rfc": resultado_etapa1.rfc,
            "razon_social": resultado_etapa1.razon_social,
            **resumen_dict,
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en Etapa 2 Screening: {str(e)}")


@router.post("/etapa2/{empresa_id}/reporte", response_class=PlainTextResponse)
async def etapa2_reporte_texto(empresa_id: str):
    """
    Ejecuta Etapa 2 screening y devuelve reporte de texto formateado.
    """
    _validar_uuid(empresa_id)
    try:
        # Ejecutar Etapa 1 primero
        expediente = await cargar_expediente_pld(empresa_id)
        resultado_etapa1 = ejecutar_etapa1(expediente)
        
        if not resultado_etapa1.personas_identificadas:
            return PlainTextResponse(
                content=f"ETAPA 2 - SCREENING\n{'='*50}\n\n"
                        f"Empresa: {resultado_etapa1.razon_social}\n"
                        f"RFC: {resultado_etapa1.rfc}\n\n"
                        "Sin personas identificadas para screening.\n",
                media_type="text/plain; charset=utf-8",
            )
        
        # Ejecutar screening
        personas_dict = [p.model_dump() for p in resultado_etapa1.personas_identificadas]
        resumen = ejecutar_screening_completo(personas_dict)
        
        resumen_dict = {
            "total_personas": resumen.total_personas,
            "personas_con_coincidencias": resumen.personas_con_coincidencias,
            "coincidencias_confirmadas": resumen.coincidencias_confirmadas,
            "coincidencias_probables": resumen.coincidencias_probables,
            "tiene_coincidencias_criticas": resumen.tiene_coincidencias_criticas,
            "requiere_escalamiento": resumen.requiere_escalamiento,
        }
        
        # Generar reporte texto
        texto = generar_reporte_screening(
            resumen, resultado_etapa1.rfc, resultado_etapa1.razon_social
        )
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reporte Etapa 2: {str(e)}")


@router.post("/etapa2/{empresa_id}/descargar")
async def etapa2_descargar_reporte(empresa_id: str):
    """
    Ejecuta Etapa 2 screening y devuelve el reporte como archivo descargable (.txt).
    """
    _validar_uuid(empresa_id)
    try:
        expediente = await cargar_expediente_pld(empresa_id)
        resultado_etapa1 = ejecutar_etapa1(expediente)

        if not resultado_etapa1.personas_identificadas:
            raise HTTPException(
                status_code=404,
                detail="No se identificaron personas para screening en Etapa 1",
            )

        personas_dict = [p.model_dump() for p in resultado_etapa1.personas_identificadas]
        resumen = ejecutar_screening_completo(personas_dict)

        texto = generar_reporte_screening(
            resumen, resultado_etapa1.rfc, resultado_etapa1.razon_social
        )

        rfc = resultado_etapa1.rfc or "SIN_RFC"
        filename = f"screening_listas_{rfc}.txt"

        return Response(
            content=texto.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando descarga de Etapa 2: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
#  REPORTE CONSOLIDADO: ETAPA 1 + ETAPA 2 + COLORADO
# ═══════════════════════════════════════════════════════════════════

@router.post("/reporte/{empresa_id}", response_class=PlainTextResponse)
async def reporte_completo(empresa_id: str):
    """
    Genera reporte consolidado PLD que incluye:
    - Etapa 1: Verificación de completitud documental
    - Etapa 2: Screening contra listas negras (LPB, OFAC, PEPs, 69-B)
    - Validación cruzada con Colorado
    - Evaluación pre-dictamen
    
    Este endpoint ejecuta ambas etapas y devuelve un reporte de texto unificado.
    """
    _validar_uuid(empresa_id)
    try:
        # 1. Ejecutar Etapa 1
        expediente = await cargar_expediente_pld(empresa_id)
        resultado_etapa1 = ejecutar_etapa1(expediente)
        
        # 2. Ejecutar Etapa 2 si hay personas identificadas
        screening_resumen: dict | None = None
        if resultado_etapa1.personas_identificadas:
            personas_dict = [p.model_dump() for p in resultado_etapa1.personas_identificadas]
            resumen = ejecutar_screening_completo(personas_dict)
            
            screening_resumen = _serializar_resumen_screening(resumen)
        
        # 3. Extraer estructura accionaria
        estructura_accionaria = extraer_estructura_para_reporte(expediente)
        
        # 4. Generar reporte consolidado
        texto = generar_reporte_completo(
            etapa1=resultado_etapa1,
            screening_resumen=screening_resumen,
            colorado_detalle=None,  # Futuro: agregar detalle extra de Colorado
            estructura_accionaria=estructura_accionaria,
        )
        
        return PlainTextResponse(content=texto, media_type="text/plain; charset=utf-8")
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reporte consolidado: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
#  REPORTE UNIFICADO PLD — Arizona
# ═══════════════════════════════════════════════════════════════════

@router.post("/completo/{empresa_id}", response_class=PlainTextResponse)
async def reporte_unificado(empresa_id: str):
    """
    Ejecuta el pipeline PLD de Arizona:

      1. Etapa 1 — Completitud documental
      2. Etapa 2 — Screening contra listas negras
      3. Estructura accionaria y propietarios reales

    Evalúa todos los bloques y emite un dictamen:
      APROBADO / APROBADO CON OBSERVACIONES / RECHAZADO

    Devuelve un reporte de texto con formato idéntico al de Colorado.
    """
    _validar_uuid(empresa_id)
    import logging
    log = logging.getLogger("arizona.pld.router")

    try:
        import time as _time
        _t0_pipeline = _time.monotonic()

        expediente = await cargar_expediente_pld(empresa_id)
        resultado_etapa1 = ejecutar_etapa1(expediente)

        screening_resumen: dict | None = None
        if resultado_etapa1.personas_identificadas:
            personas_dict = [p.model_dump() for p in resultado_etapa1.personas_identificadas]
            resumen = ejecutar_screening_completo(personas_dict)
            screening_resumen = _serializar_resumen_screening(resumen)

        estructura_accionaria = extraer_estructura_para_reporte(expediente)

        # ── Etapa 4: Screening de beneficiarios controladores ────
        screening_bc_resumen: dict | None = None
        try:
            bc_personas = _construir_personas_bc(estructura_accionaria, resultado_etapa1)
            if bc_personas:
                resumen_bc = ejecutar_screening_completo(bc_personas)
                screening_bc_resumen = _serializar_resumen_screening(resumen_bc)
                log.info(
                    "Screening BC: %d personas, %d con coincidencias",
                    resumen_bc.total_personas,
                    resumen_bc.personas_con_coincidencias,
                )
        except Exception as exc:
            log.warning("Error en screening de beneficiarios controladores: %s", exc)

        # ── Etapa 5: Matriz de Riesgo MER ────────────────────────
        resultado_mer = None
        try:
            solicitud_mer = construir_solicitud_mer(expediente, screening_resumen)
            resultado_mer = calcular_riesgo_mer(solicitud_mer)
        except Exception as exc:
            log.warning("No se pudo calcular MER: %s", exc)

        resultado = generar_reporte_unificado(
            etapa1=resultado_etapa1,
            screening_resumen=screening_resumen,
            estructura_accionaria=estructura_accionaria,
            resultado_mer=resultado_mer,
            screening_bc_resumen=screening_bc_resumen,
        )

        # ── Generar Dictamen PLD/FT ──────────────────────────────
        dictamen_obj = None
        dictamen_json = None
        dictamen_texto = None
        try:
            dictamen_obj = generar_dictamen(
                etapa1=resultado_etapa1,
                screening_resumen=screening_resumen,
                estructura_accionaria=estructura_accionaria,
                screening_bc_resumen=screening_bc_resumen,
                resultado_mer=resultado_mer,
                expediente=expediente,
                tiempo_pipeline_ms=int((_time.monotonic() - _t0_pipeline) * 1000),
            )
            dictamen_json = dictamen_obj.model_dump(mode="json")
            dictamen_texto = generar_txt_dictamen(dictamen_obj)
        except Exception as exc:
            log.warning("No se pudo generar dictamen PLD/FT: %s", exc)

        # ── Persistir análisis + dictamen en una sola transacción ─
        try:
            if dictamen_obj is not None:
                await guardar_resultado_completo(
                    resultado,
                    dictamen_json=dictamen_json,
                    dictamen_txt=dictamen_texto,
                    grado_riesgo=dictamen_obj.grado_riesgo_inicial,
                    screening_ejecutado=screening_resumen is not None,
                    screening_results=screening_resumen,
                )

            # Guardar .txt en disco
            import pathlib
            if dictamen_texto:
                ruta_txt = pathlib.Path(__file__).resolve().parents[2] / "dictamen_pld.txt"
                ruta_txt.write_text(dictamen_texto, encoding="utf-8")
                log.info(
                    "Dictamen PLD/FT generado: %s | riesgo=%s | archivo=%s",
                    dictamen_obj.dictamen_id, dictamen_obj.grado_riesgo_inicial, ruta_txt,
                )
        except Exception as exc:
            log.warning("No se pudo guardar análisis+dictamen PLD en BD: %s", exc)

        # Guardar reporte.txt en disco
        try:
            import pathlib as _pl
            ruta_reporte = _pl.Path(__file__).resolve().parents[2] / "reporte.txt"
            ruta_reporte.write_text(resultado.texto, encoding="utf-8")
            log.info("Reporte PLD guardado: %s", ruta_reporte)
        except Exception as exc:
            log.warning("No se pudo guardar reporte.txt: %s", exc)

        return PlainTextResponse(content=resultado.texto, media_type="text/plain; charset=utf-8")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Error en reporte unificado: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en reporte unificado: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
#  CONSULTAS DE ANÁLISIS PLD PERSISTIDOS
# ═══════════════════════════════════════════════════════════════════

@router.get("/analisis/{empresa_id}")
async def get_analisis_pld(empresa_id: str):
    """
    Obtiene el análisis PLD guardado para una empresa (un registro por empresa).
    """
    _validar_uuid(empresa_id)
    try:
        registro = await obtener_analisis_pld(empresa_id)
        
        if not registro:
            raise HTTPException(
                status_code=404,
                detail=f"No hay análisis PLD para empresa {empresa_id}",
            )
        
        return registro
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dictamen/{empresa_id}")
async def get_dictamen_pld(empresa_id: str):
    """Obtiene el dictamen PLD/FT guardado para una empresa."""
    _validar_uuid(empresa_id)
    try:
        registro = await obtener_dictamen_pld(empresa_id)
        if not registro:
            raise HTTPException(
                status_code=404,
                detail=f"No hay dictamen PLD/FT para empresa {empresa_id}",
            )
        return registro
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dictamen/{empresa_id}/txt", response_class=PlainTextResponse)
async def get_dictamen_txt(empresa_id: str):
    """Obtiene el dictamen PLD/FT en formato texto plano."""
    _validar_uuid(empresa_id)
    try:
        registro = await obtener_dictamen_pld(empresa_id)
        if not registro:
            raise HTTPException(
                status_code=404,
                detail=f"No hay dictamen PLD/FT para empresa {empresa_id}",
            )
        txt = registro.get("dictamen_txt", "")
        if not txt:
            raise HTTPException(
                status_code=404,
                detail="Dictamen existe pero no tiene formato texto",
            )
        return PlainTextResponse(content=txt, media_type="text/plain; charset=utf-8")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
