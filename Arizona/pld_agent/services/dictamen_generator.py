"""
Generador del Dictamen PLD/FT — Banco PagaTodo.

Funciones principales:
  - generar_dictamen()           → orquesta todo
  - construir_json_dictamen()    → JSON estructurado para BD
  - determinar_grado_riesgo()    → reglas de decisión del grado
  - redactar_justificacion_descarte() → texto para homónimos descartados
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

from ..models.dictamen_schemas import (
    AccionistaDictamen,
    AdministradorDictamen,
    DictamenPLDFT,
    PersonaRelacionada,
    PropietarioRealDictamen,
    RepresentanteLegalDictamen,
    ScreeningSeccion,
)
from ..models.schemas import VerificacionCompletitud

logger = logging.getLogger("arizona.dictamen")

# Actividades de mayor riesgo (catálogo de referencia PLD)
_ACTIVIDADES_ALTO_RIESGO = {
    "casino", "juego", "apuesta", "joyeria", "joyería",
    "inmobiliaria", "bienes raíces", "bienes raices",
    "criptoactivo", "cripto", "activo virtual",
    "casa de cambio", "cambio de divisas", "money exchange",
    "factoring", "factoraje",
    "sofom", "sofipo", "sofico", "fintech",
    "intermediación crediticia", "intermediacion crediticia",
    "blindaje", "arma", "armamento",
    "donataria", "organización civil", "organizacion civil",
}

# Países con sanciones o alto riesgo PLD (GAFI lista gris/negra)
_PAISES_SANCIONADOS = {
    "irán", "iran", "corea del norte", "siria", "myanmar",
    "afganistán", "afganistan", "yemen", "libia", "somalia",
}


# ═══════════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

def generar_dictamen(
    etapa1: VerificacionCompletitud,
    screening_resumen: dict[str, Any] | None,
    estructura_accionaria: dict[str, Any] | None,
    screening_bc_resumen: dict[str, Any] | None = None,
    resultado_mer: Any | None = None,
    expediente: Any | None = None,
    tiempo_pipeline_ms: int | None = None,
) -> DictamenPLDFT:
    """
    Toma TODA la información recopilada por Dakota, Colorado, Arizona
    y produce el DictamenPLDFT completo (JSON listo para BD y para .txt).

    Args:
        tiempo_pipeline_ms: tiempo total del pipeline medido externamente (BUG-16).
    """
    t0 = time.monotonic()

    rfc = etapa1.rfc
    razon_social = etapa1.razon_social
    hoy = date.today()
    dictamen_id = f"DICT-PLD-{rfc}-{hoy.strftime('%Y%m%d')}-001"

    # ── Recopilar datos de persona moral ─────────────────────────
    dc = _datos_clave(etapa1, expediente)
    domicilio_str = _construir_domicilio(dc, expediente)
    actividad = _extraer_actividad(dc, expediente)
    fecha_const = dc.get("fecha_constitucion") if dc else None

    # BUG-12: razón social con tipo societario
    razon_social = _enriquecer_razon_social(razon_social, expediente)
    # BUG-13: cláusula de exclusión de extranjeros
    clausula_ext = _extraer_clausula_extranjeros(expediente)
    # BUG-17: folio mercantil
    folio_mercantil = _extraer_folio_mercantil(expediente)
    # BUG-18: datos notariales del acta
    datos_notariales = _extraer_datos_notariales_acta(expediente)
    # BUG-09: perfil transaccional
    perfil_transaccional = _extraer_perfil_transaccional(expediente)
    # BUG-11: vigencia documentos
    vigencia_documentos = _construir_vigencia_documentos(expediente, hoy)
    # BUG-14: detalle del poder notarial
    detalle_poder_notarial = _extraer_detalle_poder(expediente)
    # Inferir uso de cuenta y tipo de producto dinámicamente
    uso_cuenta = _inferir_uso_cuenta(actividad, expediente)
    tipo_producto = _inferir_tipo_producto(expediente)

    persona_moral = {
        "razon_social": razon_social,
        "rfc": rfc,
        "fecha_constitucion": str(fecha_const) if fecha_const else None,
        "actividad_economica": actividad,
        "domicilio": domicilio_str,
        "uso_cuenta": uso_cuenta,
        "folio_mercantil": folio_mercantil,
        "clausula_extranjeros": clausula_ext,
        "datos_notariales_acta": datos_notariales,
    }

    # ── Screening PM (razón social) ──────────────────────────────
    screening_pm = _screening_seccion_para_rol(
        screening_resumen, roles={"empresa", "razon_social"}
    )

    # ── Actividad económica ──────────────────────────────────────
    act_mayor_riesgo = _es_actividad_alto_riesgo(actividad)

    # Congruencia info vs docs (BUG-01): excluir V2.2 (domicilio) que tiene su propio campo.
    # Solo evaluar V2.x que NO sean V2.2 (domicilio ya se valida aparte).
    hallazgos_co = etapa1.hallazgos_colorado or []
    congruencia_docs = not any(
        str(h.get("codigo", "")).startswith("V2")
        and str(h.get("codigo", "")) != "V2.2"
        and h.get("pasa") is False
        for h in hallazgos_co
    )

    # ── Domicilio (BUG-02): comparación campo-por-campo ───────────────
    concuerda_domicilio_docs = _verificar_domicilio_campo_por_campo(expediente)
    # Fallback a Colorado V2.2 si no se pudo verificar campo-por-campo
    if concuerda_domicilio_docs is None:
        concuerda_domicilio_docs = not any(
            str(h.get("codigo", "")) == "V2.2" and h.get("pasa") is False
            for h in hallazgos_co
        )
    obs_domicilio = "Sin observaciones"
    if not concuerda_domicilio_docs:
        v22 = next(
            (h for h in hallazgos_co if str(h.get("codigo", "")) == "V2.2"),
            None,
        )
        if v22:
            obs_domicilio = v22.get("mensaje", "Discrepancia de domicilio detectada")

    # ── Estructura accionaria ────────────────────────────────────
    accionistas_dict = []
    accionistas_raw = (estructura_accionaria or {}).get("accionistas", [])
    # BUG-07: construir mapa de CURP desde personas identificadas (enriquecidas con INE)
    curp_map: dict[str, str] = {}
    for p in etapa1.personas_identificadas:
        curp_val = getattr(p, '_curp_ine', None)
        if curp_val:
            curp_map[" ".join(p.nombre.upper().split())] = curp_val

    for i, acc in enumerate(accionistas_raw, 1):
        nombre = acc.get("nombre", "")
        tipo = "PM" if acc.get("tipo_persona") == "moral" else "PF"
        pct = float(acc.get("porcentaje", 0) or 0)
        rfc_acc = acc.get("rfc") or acc.get("curp") or None
        # BUG-07: enriquecer con CURP del INE si no hay RFC/CURP
        if not rfc_acc:
            rfc_acc = curp_map.get(" ".join(nombre.upper().split()))
        coincidencia = _coincidencia_persona(screening_resumen, nombre, "accionista")

        accionistas_dict.append(AccionistaDictamen(
            numero=i,
            nombre_razon_social=nombre,
            porcentaje_accionario=f"{pct:.1f}%",
            rfc_curp=rfc_acc,
            tipo_persona=tipo,
            coincidencia_listas=coincidencia,
            screening_detalle=_screening_detalle_persona(screening_resumen, nombre),
        ))

    screening_accionistas = _screening_seccion_para_rol(
        screening_resumen, roles={"accionista"}
    )

    # ── Propietarios reales ──────────────────────────────────────
    prop_reales_raw = (estructura_accionaria or {}).get("propietarios_reales", [])
    propietarios_dict = []
    for i, pr in enumerate(prop_reales_raw, 1):
        nombre = pr.get("nombre", "")
        # BUG-07: enriquecer con CURP
        rfc_curp_pr = pr.get("rfc") or curp_map.get(" ".join(nombre.upper().split()))
        coincidencia_pr = _coincidencia_persona(
            screening_bc_resumen or screening_resumen, nombre, "beneficiario_controlador"
        )
        propietarios_dict.append(PropietarioRealDictamen(
            numero=i,
            nombre=nombre,
            tipo_control="Tenencia Accionaria",
            rfc_curp=rfc_curp_pr,
            coincidencia_listas=coincidencia_pr,
            screening_detalle=_screening_detalle_persona(
                screening_bc_resumen or screening_resumen, nombre
            ),
        ))

    screening_propietarios = _screening_seccion_para_rol(
        screening_bc_resumen or screening_resumen,
        roles={"beneficiario_controlador", "propietario_real"},
    )

    # ── Representantes legales (BUG-03: deduplicar) ────────────────
    representantes_dict = []
    rep_nombres_vistos: set[str] = set()
    for i, p in enumerate(etapa1.personas_identificadas, 1):
        if p.rol in ("apoderado", "representante_legal"):
            key = " ".join(p.nombre.upper().split())
            if key in rep_nombres_vistos:
                continue
            rep_nombres_vistos.add(key)
            # BUG-07: enriquecer con CURP del INE
            rfc_curp_rep = getattr(p, '_curp_ine', None)
            coincidencia_rep = _coincidencia_persona(screening_resumen, p.nombre, p.rol)
            representantes_dict.append(RepresentanteLegalDictamen(
                numero=len(representantes_dict) + 1,
                nombre=p.nombre,
                rfc_curp=rfc_curp_rep,
                coincidencia_listas=coincidencia_rep,
            ))

    screening_representantes = _screening_seccion_para_rol(
        screening_resumen, roles={"apoderado", "representante_legal"}
    )

    # ── Administración ───────────────────────────────────────────
    admin_dict = []
    for p in etapa1.personas_identificadas:
        if p.rol in ("administrador", "consejero"):
            coincidencia_adm = _coincidencia_persona(screening_resumen, p.nombre, p.rol)
            admin_dict.append(AdministradorDictamen(
                numero=len(admin_dict) + 1,
                nombre=p.nombre,
                puesto=p.rol.replace("_", " ").title(),
                rfc_curp=None,
                coincidencia_listas=coincidencia_adm,
            ))

    screening_admin = _screening_seccion_para_rol(
        screening_resumen, roles={"administrador", "consejero"}
    )

    # ── Grado de riesgo ──────────────────────────────────────────
    grado_riesgo = determinar_grado_riesgo(
        screening_resumen=screening_resumen,
        screening_bc_resumen=screening_bc_resumen,
        actividad_economica=actividad,
        fecha_constitucion=str(fecha_const) if fecha_const else None,
        resultado_mer=resultado_mer,
    )

    # ── Conclusiones ─────────────────────────────────────────────
    senales_alerta = _hay_senales_alerta(screening_resumen, screening_bc_resumen)
    detalle_senales = _detalle_senales(screening_resumen, screening_bc_resumen)

    # BUG-15: DDR también se activa ante actividad de mayor riesgo
    edd = grado_riesgo == "alto" or senales_alerta or act_mayor_riesgo
    presentar_ccc = _debe_presentar_ccc(screening_resumen, screening_bc_resumen)

    # BUG-10: incorporar hallazgos de Colorado a las observaciones
    obs_colorado = _observaciones_desde_colorado(hallazgos_co)
    if senales_alerta:
        obs_oficial = detalle_senales or "Señales de alerta detectadas"
        if obs_colorado:
            obs_oficial += f"; Hallazgos Colorado: {obs_colorado}"
    elif obs_colorado:
        obs_oficial = f"Hallazgos Colorado: {obs_colorado}"
    else:
        obs_oficial = "Sin más observaciones"

    conclusiones = {
        "senales_alerta": senales_alerta,
        "detalle_senales": detalle_senales,
        "observaciones_oficial": obs_oficial,
        "confirma_grado_riesgo": True,
        "grado_riesgo_final": grado_riesgo,
        "debida_diligencia_reforzada": edd,
        "detalle_edd": _detalle_edd(grado_riesgo, screening_resumen, screening_bc_resumen) if edd else None,
        "presentar_ccc": presentar_ccc,
        "fecha_sesion_ccc": None,
        "recomendaciones_ccc": None,
    }

    # ── MER info para metadata ───────────────────────────────────
    puntaje_mer = None
    grado_mer = None
    if resultado_mer:
        puntaje_mer = getattr(resultado_mer, "puntaje_total", None)
        grado_mer = getattr(resultado_mer, "grado_riesgo", None)
        if hasattr(grado_mer, "value"):
            grado_mer = grado_mer.value

    # BUG-16: preferir tiempo externo del pipeline completo
    elapsed_ms = tiempo_pipeline_ms if tiempo_pipeline_ms is not None else int((time.monotonic() - t0) * 1000)

    total_screened = 0
    total_coincidencias = 0
    if screening_resumen:
        total_screened = screening_resumen.get("total_personas", 0)
        total_coincidencias = screening_resumen.get("personas_con_coincidencias", 0)

    metadata = {
        "agente_version": "2.3",
        "pipeline_id": dictamen_id,
        "tiempo_procesamiento_ms": elapsed_ms,
        "fuentes_datos": ["Dakota", "Colorado", "Arizona"],
        "listas_consultadas_total": [
            "CatPLD69BPerson", "CatPLDLockedPerson", "TraPLDBlackListEntry",
        ],
        "total_personas_screened": total_screened,
        "total_coincidencias": total_coincidencias,
        "puntaje_mer": puntaje_mer,
        "grado_mer": grado_mer,
    }

    # ── Construir DictamenPLDFT ──────────────────────────────────
    return DictamenPLDFT(
        dictamen_id=dictamen_id,
        fecha_elaboracion=hoy,
        tipo_producto=tipo_producto,
        grado_riesgo_inicial=grado_riesgo,
        persona_moral=persona_moral,
        screening_persona_moral=screening_pm,
        actividad_economica=actividad or "",
        congruencia_info_docs=congruencia_docs,
        actividades_no_declaradas=False,
        actividades_mayor_riesgo=act_mayor_riesgo,
        detalle_act_mayor_riesgo=(
            f"Actividad clasificada como mayor riesgo: {actividad}"
            if act_mayor_riesgo else None
        ),
        domicilio=domicilio_str,
        concuerda_domicilio_docs=concuerda_domicilio_docs,
        concuerda_domicilio_actividad=True,
        observaciones_domicilio=obs_domicilio,
        estructura_accionaria=accionistas_dict,
        screening_accionistas=screening_accionistas,
        propietarios_reales=propietarios_dict,
        screening_propietarios=screening_propietarios,
        representantes_legales=representantes_dict,
        screening_representantes=screening_representantes,
        administracion=admin_dict,
        screening_administracion=screening_admin,
        uso_cuenta=uso_cuenta,
        congruencia_perfil_actividad=True,
        conclusiones=conclusiones,
        metadata=metadata,
        # BUG-09, 11, 14: campos nuevos
        perfil_transaccional=perfil_transaccional,
        vigencia_documentos=vigencia_documentos,
        detalle_poder_notarial=detalle_poder_notarial,
    )


# ═══════════════════════════════════════════════════════════════════
#  GRADO DE RIESGO
# ═══════════════════════════════════════════════════════════════════

def determinar_grado_riesgo(
    *,
    screening_resumen: dict[str, Any] | None,
    screening_bc_resumen: dict[str, Any] | None = None,
    actividad_economica: str | None,
    fecha_constitucion: str | None,
    resultado_mer: Any | None = None,
) -> str:
    """
    Determina el grado de riesgo: 'bajo', 'medio', 'alto'.

    Reglas (en orden de prioridad):
      1. Match confirmado LPB/UIF, OFAC, ONU → 'alto'
      2. Match confirmado 69-B EFOS definitivo → 'alto'
      3. PEP confirmado → mínimo 'medio'
      4. Actividad de alto riesgo → mínimo 'medio'
      5. MER ALTO → 'alto'; MER MEDIO → 'medio'
      6. Default 'bajo'
    """
    # 1-2. Match confirmado en listas críticas
    for resumen in (screening_resumen, screening_bc_resumen):
        if not resumen:
            continue
        if resumen.get("tiene_coincidencias_criticas") or resumen.get("coincidencias_confirmadas", 0) > 0:
            return "alto"

    grado = "bajo"

    # 3. PEP
    for resumen in (screening_resumen, screening_bc_resumen):
        if _tiene_pep(resumen):
            grado = "medio"

    # 4. Actividad de alto riesgo
    if _es_actividad_alto_riesgo(actividad_economica):
        if grado == "bajo":
            grado = "medio"

    # 5. MER
    if resultado_mer:
        grado_mer = getattr(resultado_mer, "grado_riesgo", None)
        if hasattr(grado_mer, "value"):
            grado_mer = grado_mer.value
        if grado_mer == "ALTO":
            return "alto"
        if grado_mer == "MEDIO" and grado == "bajo":
            grado = "medio"

    return grado


# ═══════════════════════════════════════════════════════════════════
#  JUSTIFICACIÓN DE DESCARTE
# ═══════════════════════════════════════════════════════════════════

def redactar_justificacion_descarte(coincidencia: dict[str, Any]) -> str:
    """
    Genera texto de justificación para el descarte de un posible homónimo.
    """
    nombre_sujeto = coincidencia.get("persona", {}).get("nombre", "N/D")
    nombre_lista = coincidencia.get("nombre_en_lista", "N/D")
    score = coincidencia.get("score", 0)
    nivel = coincidencia.get("nivel_coincidencia", "HOMONIMO")
    tabla = coincidencia.get("tabla_origen", "N/D")

    rfc_sujeto = coincidencia.get("persona", {}).get("rfc", "N/D")
    rfc_lista = coincidencia.get("rfc_en_lista", "N/D")
    match_rfc = coincidencia.get("match_rfc", False)
    match_curp = coincidencia.get("match_curp", False)
    explicacion = coincidencia.get("explicacion_score", "")

    partes = [
        f"Se identificó coincidencia parcial en {tabla}.",
        f"Nombre consultado: {nombre_sujeto}.",
        f"Nombre en lista: {nombre_lista}.",
        f"Score de similitud: {score} puntos ({nivel}).",
    ]

    diferencias: list[str] = []
    if not match_rfc and rfc_sujeto and rfc_lista:
        diferencias.append(f"RFC del sujeto ({rfc_sujeto}) difiere del listado ({rfc_lista})")
    if not match_curp:
        diferencias.append("CURP no coincide o no disponible")

    if diferencias:
        partes.append("Diferencias: " + "; ".join(diferencias) + ".")
        partes.append("Se descarta la coincidencia por tratarse de un posible homónimo.")
    else:
        partes.append("No se pudo descartar completamente. Requiere revisión manual.")

    return " ".join(partes)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS INTERNOS
# ═══════════════════════════════════════════════════════════════════

def _datos_clave(
    etapa1: VerificacionCompletitud,
    expediente: Any | None,
) -> dict[str, Any]:
    """Obtiene datos_clave de Colorado (desde expediente o resumen)."""
    if expediente and hasattr(expediente, "datos_clave") and expediente.datos_clave:
        return expediente.datos_clave
    # Fallback: intentar desde resumen_colorado de etapa1
    rc = etapa1.resumen_colorado or {}
    return rc.get("datos_clave", {}) or {}


def _construir_domicilio(dc: dict, expediente: Any | None) -> str:
    """Construye cadena de domicilio completo."""
    dom = {}
    if dc and isinstance(dc, dict) and dc.get("domicilio"):
        d = dc["domicilio"]
        if isinstance(d, dict):
            dom = d
        elif isinstance(d, str):
            return d

    # BUG-08: buscar en documentos OCR con campos completos (incluye numero_interior)
    if not dom and expediente:
        docs = getattr(expediente, "documentos", {})
        # Primero: intentar domicilio_fiscal del CSF (cadena completa ya formateada)
        csf = docs.get("csf", {})
        if isinstance(csf, dict):
            df = csf.get("domicilio_fiscal")
            if isinstance(df, dict) and "valor" in df:
                df = df["valor"]
            if df and str(df).strip() not in ("", "N/A", "None"):
                return str(df).strip()

        # Segundo: campos individuales del comprobante de domicilio o CSF
        _dom_keys = (
            "calle", "numero_exterior", "numero_interior", "colonia",
            "codigo_postal", "municipio_delegacion", "alcaldia",
            "entidad_federativa", "estado", "ciudad",
        )
        for doc_type in ("domicilio", "csf"):
            doc = docs.get(doc_type, {})
            if isinstance(doc, dict):
                dom_fields: dict[str, str] = {}
                for k in _dom_keys:
                    v = doc.get(k)
                    if isinstance(v, dict) and "valor" in v:
                        v = v["valor"]
                    if v and str(v).strip() not in ("", "N/A", "None"):
                        dom_fields[k] = str(v).strip()
                if dom_fields:
                    dom = dom_fields
                    break

    if not dom:
        return "N/D"

    partes = []
    calle = dom.get("calle", "")
    num_ext = dom.get("numero_exterior", "")
    num_int = dom.get("numero_interior", "")
    if calle:
        s = calle
        if num_ext:
            s += f" {num_ext}"
        if num_int:
            s += f", INT. {num_int}"
        partes.append(s)
    col = dom.get("colonia", "")
    if col:
        partes.append(f"col. {col}")
    mpio = dom.get("municipio_delegacion", dom.get("alcaldia", dom.get("municipio", "")))
    ef = dom.get("entidad_federativa", dom.get("estado", ""))
    if mpio or ef:
        partes.append(f"{mpio}, {ef}".strip(", "))
    cp = dom.get("codigo_postal", dom.get("cp", ""))
    if cp:
        partes.append(f"C.P. {cp}")
    return ", ".join(partes) if partes else "N/D"


def _extraer_actividad(dc: dict, expediente: Any | None) -> str | None:
    """Extrae la actividad económica del expediente."""
    if dc:
        v = dc.get("giro_mercantil")
        if v and str(v).strip() not in ("", "N/A", "None"):
            return str(v).strip()
    if expediente:
        for doc_type in ("csf", "acta_constitutiva"):
            doc = getattr(expediente, "documentos", {}).get(doc_type, {})
            for campo in ("actividad_economica", "objeto_social", "giro_mercantil"):
                v = doc.get(campo)
                if isinstance(v, dict) and "valor" in v:
                    v = v["valor"]
                if v and str(v).strip() not in ("", "N/A", "None"):
                    return str(v).strip()
    return None


def _es_actividad_alto_riesgo(actividad: str | None) -> bool:
    """Verifica si la actividad pertenece al catálogo de alto riesgo."""
    if not actividad:
        return False
    act_lower = actividad.lower()
    return any(kw in act_lower for kw in _ACTIVIDADES_ALTO_RIESGO)


def _tiene_pep(resumen: dict[str, Any] | None) -> bool:
    """Verifica si algún resultado de screening tiene PEP."""
    if not resumen:
        return False
    for r in resumen.get("resultados", []):
        for c in r.get("coincidencias", []):
            tipo = (c.get("tipo_lista") or "").upper()
            tabla = (c.get("tabla_origen") or "").upper()
            cat = (c.get("categoria") or "").upper()
            if "PEP" in tipo or "PEP" in tabla or "PEP" in cat:
                return True
    return False


def _hay_senales_alerta(
    screening: dict | None,
    screening_bc: dict | None,
) -> bool:
    """Determina si hay señales de alerta finales."""
    for resumen in (screening, screening_bc):
        if not resumen:
            continue
        if resumen.get("tiene_coincidencias_criticas"):
            return True
        if resumen.get("coincidencias_confirmadas", 0) > 0:
            return True
        if resumen.get("coincidencias_probables", 0) > 0:
            return True
    return False


def _detalle_senales(screening: dict | None, screening_bc: dict | None) -> str | None:
    """Construye detalle de señales de alerta."""
    detalles: list[str] = []
    for label, resumen in (("Screening general", screening), ("Screening BC", screening_bc)):
        if not resumen:
            continue
        conf = resumen.get("coincidencias_confirmadas", 0)
        prob = resumen.get("coincidencias_probables", 0)
        if conf:
            detalles.append(f"{label}: {conf} coincidencia(s) confirmada(s)")
        if prob:
            detalles.append(f"{label}: {prob} coincidencia(s) probable(s)")
    return "; ".join(detalles) if detalles else None


def _debe_presentar_ccc(screening: dict | None, screening_bc: dict | None) -> bool:
    """Determina si se debe presentar al Comité de Comunicación y Control."""
    for resumen in (screening, screening_bc):
        if not resumen:
            continue
        if resumen.get("tiene_coincidencias_criticas"):
            return True
        if resumen.get("coincidencias_confirmadas", 0) > 0:
            return True
    return False


def _detalle_edd(grado: str, screening: dict | None, screening_bc: dict | None) -> str:
    """Construye detalle de medidas de EDD."""
    medidas = []
    if grado == "alto":
        medidas.append("Monitoreo transaccional reforzado (frecuencia mensual)")
    if _tiene_pep(screening) or _tiene_pep(screening_bc):
        medidas.append("Autorización de alta dirección para PEP")
    if screening and screening.get("coincidencias_probables", 0) > 0:
        medidas.append("Revisión manual de coincidencias probables antes de activación")
    if not medidas:
        medidas.append("Monitoreo reforzado por grado de riesgo elevado")
    return "; ".join(medidas)


def _screening_seccion_para_rol(
    resumen: dict[str, Any] | None,
    roles: set[str],
) -> ScreeningSeccion:
    """Construye ScreeningSeccion agregando resultados de personas del rol indicado."""
    if not resumen:
        return ScreeningSeccion()

    coincidencia = False
    confirma = False
    datos_lista_parts: list[str] = []
    justificaciones: list[str] = []

    for r in resumen.get("resultados", []):
        persona = r.get("persona", {})
        rol = persona.get("rol", "")
        if rol not in roles:
            continue
        if r.get("tiene_coincidencias"):
            coincidencia = True
            for c in r.get("coincidencias", []):
                nivel = c.get("nivel_coincidencia", "")
                if nivel == "CONFIRMADO":
                    confirma = True
                    datos_lista_parts.append(
                        f"{persona.get('nombre')}: {c.get('tabla_origen')} "
                        f"(score {c.get('score', 0)}, {nivel})"
                    )
                else:
                    justificaciones.append(redactar_justificacion_descarte(c))

    return ScreeningSeccion(
        coincidencia_listas=coincidencia,
        datos_lista="; ".join(datos_lista_parts) if datos_lista_parts else None,
        confirma_coincidencia=confirma,
        justificacion_descarte="; ".join(justificaciones) if justificaciones and not confirma else None,
    )


def _coincidencia_persona(
    resumen: dict[str, Any] | None,
    nombre: str,
    rol: str,
) -> str:
    """Retorna 'NO' o 'SÍ — [detalle]' para una persona específica."""
    if not resumen:
        return "NO"
    nombre_upper = nombre.upper().strip()
    for r in resumen.get("resultados", []):
        persona = r.get("persona", {})
        if persona.get("nombre", "").upper().strip() == nombre_upper:
            if r.get("tiene_coincidencias"):
                coincidencias = r.get("coincidencias", [])
                if coincidencias:
                    c0 = coincidencias[0]
                    return f"SÍ — {c0.get('tabla_origen', 'N/D')} (score {c0.get('score', 0)}, {c0.get('nivel_coincidencia', 'N/D')})"
                return "SÍ"
            return "NO"
    return "NO"


def _screening_detalle_persona(resumen: dict | None, nombre: str) -> dict[str, Any] | None:
    """Retorna el detalle de screening para una persona."""
    if not resumen:
        return None
    nombre_upper = nombre.upper().strip()
    for r in resumen.get("resultados", []):
        persona = r.get("persona", {})
        if persona.get("nombre", "").upper().strip() == nombre_upper:
            return {
                "listas_consultadas": r.get("listas_consultadas", []),
                "matches": r.get("coincidencias", []),
                "score_maximo": r.get("score_maximo", 0),
                "clasificacion": "LIMPIO" if not r.get("tiene_coincidencias") else r.get("nivel_riesgo", "N/D"),
            }
    return None


def sanitizar_nombre_archivo(razon_social: str) -> str:
    """
    Sanitiza razón social para nombre de archivo:
    minúsculas, underscores, sin caracteres especiales.
    """
    # Normalizar unicode, quitar acentos
    nfkd = unicodedata.normalize("NFKD", razon_social)
    solo_ascii = nfkd.encode("ascii", "ignore").decode("ascii")
    # Minúsculas, reemplazar espacios
    lower = solo_ascii.lower().strip()
    # Solo alfanuméricos y underscores
    clean = re.sub(r"[^a-z0-9]+", "_", lower)
    clean = clean.strip("_")
    return f"dictamen_{clean}.txt"


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES AUXILIARES DE EXTRACCIÓN DE DATOS (BUG-02, 09–14, 17, 18)
# ═══════════════════════════════════════════════════════════════════

def _val(doc: dict, campo: str) -> str:
    """Extrae valor de un campo OCR (puede ser dict con 'valor' o plano)."""
    v = doc.get(campo)
    if isinstance(v, dict) and "valor" in v:
        v = v["valor"]
    if v is None or str(v).strip() in ("", "N/A", "None"):
        return ""
    return str(v).strip()


def _verificar_domicilio_campo_por_campo(expediente: Any | None) -> bool | None:
    """BUG-02: Compara domicilio campo-por-campo entre CSF y comprobante de domicilio.
    Retorna True si todos los campos clave coinciden, False si hay diferencia,
    o None si no se pudo verificar (faltan documentos)."""
    if not expediente:
        return None
    docs = getattr(expediente, "documentos", {})
    csf = docs.get("csf", {})
    dom = docs.get("domicilio", {})
    if not csf or not dom:
        return None

    campos = ("codigo_postal", "colonia", "calle", "numero_exterior")
    for campo in campos:
        v_csf = _val(csf, campo).upper()
        v_dom = _val(dom, campo).upper()
        if not v_csf or not v_dom:
            continue
        # normalizar: quitar "AV.", "AVENIDA", puntuación
        v_csf_n = re.sub(r"\b(AVENIDA|AV\.?|CALLE|CLL\.?)\b", "", v_csf).strip(" .,")
        v_dom_n = re.sub(r"\b(AVENIDA|AV\.?|CALLE|CLL\.?)\b", "", v_dom).strip(" .,")
        if v_csf_n != v_dom_n:
            return False
    return True


def _extraer_perfil_transaccional(expediente: Any | None) -> dict[str, Any]:
    """BUG-09: Extrae datos del estado de cuenta para perfil transaccional."""
    resultado: dict[str, Any] = {}
    if not expediente:
        return resultado
    docs = getattr(expediente, "documentos", {})
    ec = docs.get("estado_cuenta", {})
    if not ec:
        return resultado
    for campo in ("banco", "numero_cuenta", "clabe", "periodo",
                   "saldo_inicial", "saldo_final", "total_depositos", "total_retiros"):
        v = _val(ec, campo)
        if v:
            resultado[campo] = v
    return resultado


def _inferir_uso_cuenta(actividad: str | None, expediente: Any | None) -> str:
    """Infiere el uso de cuenta a partir de la actividad económica y datos transaccionales.

    Analiza el objeto social, giro mercantil, actividad económica del CSF
    y los parágrafos del estado de cuenta para construir una descripción
    dinámica del uso previsto de la cuenta.
    """
    usos: list[str] = []

    # ── 1. Extraer textos relevantes de los documentos ───────────
    textos: list[str] = []
    if actividad:
        textos.append(actividad.upper())

    if expediente:
        docs = getattr(expediente, "documentos", {})

        # Objeto social del acta constitutiva
        acta = docs.get("acta_constitutiva", {})
        for campo in ("objeto_social", "actividad_economica", "giro_mercantil"):
            v = _val(acta, campo)
            if v:
                textos.append(v.upper())

        # Actividad del CSF
        csf = docs.get("csf", {})
        for campo in ("actividad_economica", "regimen_fiscal"):
            v = _val(csf, campo)
            if v:
                textos.append(v.upper())

        # Parágrafos del estado de cuenta (pueden tener descripciones de mvtos)
        ec = docs.get("estado_cuenta", {})
        for campo in ("parrafo", "tipo_cuenta", "producto"):
            v = _val(ec, campo)
            if v:
                textos.append(v.upper())

    texto_combinado = " ".join(textos)
    if not texto_combinado:
        return "No determinado — sin datos suficientes para inferir uso de cuenta"

    # ── 2. Detectar patrones de uso ──────────────────────────────
    patrones = [
        (r"PAGO\b.*\bPROVEEDOR|PROVEEDUR", "PAGO DE PROVEEDORES"),
        (r"PAGO\b.*\bTERCERO|TRANSFERENCIA.*TERCERO", "PAGO A TERCEROS"),
        (r"N[OÓ]MINA|SUELDO|SALARIO|REMUNERACI", "DISPERSIÓN DE NÓMINA"),
        (r"COBRAN|COBRANZA|RECAUDACI", "COBRANZA Y RECAUDACIÓN"),
        (r"INVERSION|INVERSI[OÓ]N|RENDIMIENTO", "INVERSIÓN Y RENDIMIENTOS"),
        (r"IMPORT|EXPORT|COMERCIO EXTERIOR|ADUANA", "OPERACIONES DE COMERCIO EXTERIOR"),
        (r"ARRENDAMIENTO|RENTA\b", "COBRO Y PAGO DE ARRENDAMIENTOS"),
        (r"CONSTRUCCI[OÓ]N|OBRA|INFRAESTRUCTURA", "PAGOS DE OBRA Y CONSTRUCCIÓN"),
        (r"TECNOLOG[IÍ]A|SOFTWARE|SISTEMA|DESARROLLO\b.*\bTECN", "SERVICIOS TECNOLÓGICOS"),
        (r"CONSULTOR[IÍ]A|ASESOR[IÍ]A|SERVICIO.*PROFESIONAL", "PAGO DE SERVICIOS PROFESIONALES"),
        (r"COMPRA.*VENTA|COMERCIALIZ|MERCANTIL", "COMPRAVENTA DE BIENES Y MERCANCÍAS"),
        (r"INMOBILI|BIENES\s*RA[IÍ]CES", "OPERACIONES INMOBILIARIAS"),
        (r"TRANSPORT|LOG[IÍ]STIC|FLETE", "PAGOS DE TRANSPORTE Y LOGÍSTICA"),
        (r"AGROPECUARI|AGR[IÍ]COL|GANADER", "OPERACIONES AGROPECUARIAS"),
        (r"FARMAC[EÉ]UTIC|SALUD|M[EÉ]DIC|HOSPITAL", "SERVICIOS DE SALUD"),
        (r"EDUCACI[OÓ]N|ESCUELA|CAPACITACI", "SERVICIOS EDUCATIVOS"),
        (r"RESTAURANTE|ALIMENTO|COMIDA|BEBIDA", "PAGOS DE ALIMENTOS Y BEBIDAS"),
        (r"SEGURO|ASEGURADOR|P[OÓ]LIZA", "PAGO DE PRIMAS Y SEGUROS"),
        (r"FINANC|CR[EÉ]DITO|PR[EÉ]STAMO", "OPERACIONES FINANCIERAS Y CREDITICIAS"),
    ]

    for regex, desc in patrones:
        if re.search(regex, texto_combinado):
            usos.append(desc)

    # Siempre agregar "PAGO A TERCEROS" y "PAGO DE PROVEEDORES" si hay
    # actividad comercial genérica y no se detectó nada más específico
    if not usos:
        usos.append("OPERACIONES PROPIAS DEL GIRO")

    return " Y ".join(usos[:3])


def _inferir_tipo_producto(expediente: Any | None) -> str:
    """Infiere el tipo de producto bancario a partir del estado de cuenta."""
    if not expediente:
        return "Cuenta empresarial"
    docs = getattr(expediente, "documentos", {})
    ec = docs.get("estado_cuenta", {})
    if not ec:
        return "Cuenta empresarial"

    # Buscar en parágrafos del estado de cuenta
    for campo in ec.values():
        texto = ""
        if isinstance(campo, dict) and "parrafo" in campo:
            texto = str(campo["parrafo"]).upper()
        elif isinstance(campo, dict) and "valor" in campo:
            texto = str(campo["valor"]).upper()
        elif isinstance(campo, str):
            texto = campo.upper()

        if "CHEQ" in texto or "CH EQ" in texto:
            return "Cuenta de cheques empresarial"
        if "INVERSIÓN" in texto or "INVERSION" in texto:
            return "Cuenta de inversión"

    # Analizar CLABE para determinar tipo (dígitos 5-6 indican tipo de producto)
    clabe = _val(ec, "clabe")
    if clabe and len(clabe) >= 6:
        # Tipo genérico basado en existencia de CLABE
        return "Cuenta empresarial con CLABE"

    return "Cuenta empresarial"


def _construir_vigencia_documentos(
    expediente: Any | None,
    fecha_analisis: date,
) -> list[dict[str, Any]]:
    """BUG-11: Construye lista de vigencia de cada documento relevante."""
    vigencias: list[dict[str, Any]] = []
    if not expediente:
        return vigencias
    docs = getattr(expediente, "documentos", {})

    # Documentos cuya antigüedad importa (máx 3 meses para CSF/domicilio/estado_cuenta)
    docs_con_vigencia = {
        "csf": ("Constancia de Situación Fiscal", "fecha_emision", 3),
        "domicilio": ("Comprobante de domicilio", "fecha_emision", 3),
        "estado_cuenta": ("Estado de cuenta bancario", "periodo", 3),
        "fiel": ("e.Firma (FIEL)", "vigencia_hasta", None),
        "ine": ("INE del representante", None, None),
    }
    for doc_type, (nombre, campo_fecha, max_meses) in docs_con_vigencia.items():
        doc = docs.get(doc_type, {})
        if not doc:
            vigencias.append({"documento": nombre, "vigente": None, "detalle": "No presentado"})
            continue
        fecha_str = _val(doc, campo_fecha) if campo_fecha else ""
        vigente: bool | None = None
        detalle = ""
        if fecha_str:
            try:
                fd = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
                if max_meses:
                    from dateutil.relativedelta import relativedelta
                    limite = fecha_analisis - relativedelta(months=max_meses)
                    vigente = fd >= limite
                    detalle = f"Fecha: {fd.isoformat()}"
                    if not vigente:
                        detalle += f" (excede {max_meses} meses)"
                elif campo_fecha == "vigencia_hasta":
                    vigente = fd >= fecha_analisis
                    detalle = f"Vigente hasta: {fd.isoformat()}"
                    if not vigente:
                        detalle += " (EXPIRADA)"
            except (ValueError, TypeError):
                detalle = f"Fecha no parseable: {fecha_str}"
        else:
            detalle = "Sin fecha de emisión disponible"
        vigencias.append({"documento": nombre, "vigente": vigente, "detalle": detalle})
    return vigencias


def _enriquecer_razon_social(razon_social: str, expediente: Any | None) -> str:
    """BUG-12: Agrega tipo societario si no lo tiene (S.A.P.I. DE C.V., etc.)."""
    if not expediente:
        return razon_social
    rs_upper = razon_social.upper()
    # Si ya tiene tipo societario, no modificar
    if any(t in rs_upper for t in ("S.A.", "S.A.P.I.", "S. DE R.L.", "S.C.", "A.C.")):
        return razon_social
    docs = getattr(expediente, "documentos", {})
    # Buscar tipo societario completo en FIEL, poder, acta
    for doc_type in ("fiel", "poder", "acta_constitutiva"):
        doc = docs.get(doc_type, {})
        if not doc:
            continue
        for campo in ("razon_social", "nombre_poderdante", "denominacion_social"):
            v = _val(doc, campo).upper()
            if v and rs_upper in v and len(v) > len(rs_upper):
                return v
    return razon_social


def _extraer_clausula_extranjeros(expediente: Any | None) -> str | None:
    """BUG-13: Extrae cláusula de exclusión de extranjeros del acta."""
    if not expediente:
        return None
    docs = getattr(expediente, "documentos", {})
    acta = docs.get("acta_constitutiva", {})
    if not acta:
        return None
    v = _val(acta, "clausula_extranjeros")
    return v if v else None


def _extraer_detalle_poder(expediente: Any | None) -> dict[str, Any]:
    """BUG-14: Extrae detalle del poder notarial."""
    resultado: dict[str, Any] = {}
    if not expediente:
        return resultado
    docs = getattr(expediente, "documentos", {})
    poder = docs.get("poder", {})
    if not poder:
        return resultado
    for campo in ("tipo_poder", "facultades", "nombre_notario", "numero_notaria",
                   "estado_notaria", "numero_escritura", "fecha_otorgamiento",
                   "nombre_apoderado", "nombre_poderdante"):
        v = _val(poder, campo)
        if v:
            resultado[campo] = v
    return resultado


def _extraer_folio_mercantil(expediente: Any | None) -> str | None:
    """BUG-17: Extrae folio mercantil del acta constitutiva."""
    if not expediente:
        return None
    docs = getattr(expediente, "documentos", {})
    acta = docs.get("acta_constitutiva", {})
    v = _val(acta, "folio_mercantil")
    return v if v else None


def _extraer_datos_notariales_acta(expediente: Any | None) -> dict[str, Any]:
    """BUG-18: Extrae datos notariales del acta constitutiva."""
    resultado: dict[str, Any] = {}
    if not expediente:
        return resultado
    docs = getattr(expediente, "documentos", {})
    acta = docs.get("acta_constitutiva", {})
    if not acta:
        return resultado
    for campo in ("nombre_notario", "numero_notaria", "estado_notaria",
                   "numero_escritura_poliza", "fecha_expedicion", "fecha_constitucion"):
        v = _val(acta, campo)
        if v:
            resultado[campo] = v
    return resultado


def _observaciones_desde_colorado(hallazgos_co: list[dict]) -> str | None:
    """BUG-10: Construye observaciones a partir de hallazgos de Colorado."""
    obs: list[str] = []
    for h in hallazgos_co:
        if h.get("pasa") is False:
            sev = h.get("severidad", "")
            msg = h.get("mensaje", "")
            codigo = h.get("codigo", "")
            if msg:
                obs.append(f"[{codigo}] {msg}")
    return "; ".join(obs) if obs else None
