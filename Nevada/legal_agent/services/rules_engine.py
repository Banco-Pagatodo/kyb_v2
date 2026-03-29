"""
Motor de reglas determinista para el Dictamen Jurídico.

Aplica las reglas del documento "BPT — Reglas para elaboración de dictamen"
sobre los datos del expediente para determinar si cada sección del dictamen
puede completarse y si hay inconsistencias.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..models.schemas import (
    AccionistaDJ,
    ActividadGiro,
    ApoderadoDJ,
    DatosEscritura,
    ExpedienteLegal,
    FacultadesApoderado,
    MiembroAdministracion,
    RegimenAdministracion,
    ReglaEvaluada,
    ResultadoReglas,
    TenenciaAccionaria,
)

logger = logging.getLogger("nevada.rules")

# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

_KEYWORDS_EXTRANJERO_PM = ["ltd", "s.l.", "s.l.u.", "limited company", "limited", "inc.", "inc", "corp.", "llc"]


def _es_extranjero_pm(nombre: str) -> bool:
    """Detecta si una persona moral es extranjera por su denominación."""
    lower = nombre.lower().strip()
    return any(kw in lower for kw in _KEYWORDS_EXTRANJERO_PM)


def _get_doc(exp: ExpedienteLegal, doc_type: str) -> dict[str, Any]:
    """Obtiene datos de un documento, vacío si no existe."""
    return exp.documentos.get(doc_type, {})


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, dict) and "valor" in val:
        return str(val["valor"]).strip() if val["valor"] is not None else ""
    return str(val).strip()


def _unwrap(val: Any) -> Any:
    """Desenvuelve valores OCR del formato {valor, pagina, parrafo, confiabilidad}."""
    if isinstance(val, dict) and "valor" in val:
        return val["valor"]
    return val


# ═══════════════════════════════════════════════════════════════════
#  Regla 1: Denominación Social
# ═══════════════════════════════════════════════════════════════════

def _evaluar_denominacion(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que la denominación social esté disponible."""
    acta = _get_doc(exp, "acta_constitutiva")
    csf = _get_doc(exp, "csf")

    denom_acta = _safe_str(
        acta.get("denominacion_social")
        or acta.get("denominacion_razon_social")
        or acta.get("razon_social")
    )
    denom_csf = _safe_str(
        csf.get("razon_social")
        or csf.get("denominacion_razon_social")
    )

    if not denom_acta and not denom_csf:
        return ReglaEvaluada(
            codigo="R1", nombre="Denominación Social",
            cumple=False,
            detalle="No se encontró denominación social en acta constitutiva ni CSF.",
            severidad="CRITICA", fuente_documento="acta_constitutiva",
        )

    # Verificar posible cambio de denominación
    if denom_acta and denom_csf:
        # Normalizar para comparar
        norm_acta = re.sub(r"\s+", " ", denom_acta.upper())
        norm_csf = re.sub(r"\s+", " ", denom_csf.upper())
        if norm_acta != norm_csf:
            # Posible cambio de denominación — buscar reforma
            reforma = _get_doc(exp, "reforma")
            if reforma:
                return ReglaEvaluada(
                    codigo="R1", nombre="Denominación Social",
                    cumple=True,
                    detalle=(
                        f"Posible cambio de denominación detectado. "
                        f"Acta: '{denom_acta}' vs CSF: '{denom_csf}'. "
                        f"Escritura de reforma disponible."
                    ),
                    severidad="INFORMATIVA", fuente_documento="reforma",
                )
            return ReglaEvaluada(
                codigo="R1", nombre="Denominación Social",
                cumple=False,
                detalle=(
                    f"Posible cambio de denominación: Acta='{denom_acta}' vs CSF='{denom_csf}'. "
                    f"No se encontró escritura de reforma que soporte el cambio."
                ),
                severidad="MEDIA", fuente_documento="acta_constitutiva",
            )

    return ReglaEvaluada(
        codigo="R1", nombre="Denominación Social",
        cumple=True,
        detalle=f"Denominación: '{denom_acta or denom_csf}'.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 2: Datos de Constitución
# ═══════════════════════════════════════════════════════════════════

def _evaluar_constitucion(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica datos de la escritura constitutiva."""
    acta = _get_doc(exp, "acta_constitutiva")

    campos_requeridos = {
        "numero_escritura": acta.get("numero_escritura_poliza") or acta.get("numero_escritura"),
        "fecha_escritura": acta.get("fecha_constitucion") or acta.get("fecha_expedicion"),
        "numero_notario": acta.get("numero_notaria") or acta.get("numero_notario"),
        "nombre_notario": acta.get("nombre_notario"),
    }

    faltantes = [k for k, v in campos_requeridos.items() if not _safe_str(v)]

    if not acta:
        return ReglaEvaluada(
            codigo="R2", nombre="Datos de Constitución",
            cumple=False,
            detalle="No se encontró acta constitutiva en el expediente.",
            severidad="CRITICA", fuente_documento="acta_constitutiva",
        )

    if faltantes:
        return ReglaEvaluada(
            codigo="R2", nombre="Datos de Constitución",
            cumple=False,
            detalle=f"Campos faltantes en acta constitutiva: {', '.join(faltantes)}.",
            severidad="MEDIA", fuente_documento="acta_constitutiva",
        )

    return ReglaEvaluada(
        codigo="R2", nombre="Datos de Constitución",
        cumple=True,
        detalle="Datos de constitución completos.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 3: Folio Mercantil Electrónico
# ═══════════════════════════════════════════════════════════════════

def _evaluar_folio_mercantil(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica la existencia del FME."""
    acta = _get_doc(exp, "acta_constitutiva")
    fme = _safe_str(
        acta.get("folio_mercantil")
        or acta.get("folio_mercantil_electronico")
        or acta.get("fme")
        or acta.get("registro_publico_comercio")
    )

    if not fme:
        return ReglaEvaluada(
            codigo="R3", nombre="Folio Mercantil Electrónico",
            cumple=False,
            detalle="No se encontró Folio Mercantil Electrónico (FME) / RPP.",
            severidad="MEDIA", fuente_documento="acta_constitutiva",
        )

    return ReglaEvaluada(
        codigo="R3", nombre="Folio Mercantil Electrónico",
        cumple=True,
        detalle=f"FME: {fme}.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 4: Actividad / Giro
# ═══════════════════════════════════════════════════════════════════

def _evaluar_actividad(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que el objeto/giro de la empresa esté disponible."""
    acta = _get_doc(exp, "acta_constitutiva")
    csf = _get_doc(exp, "csf")

    objeto = _safe_str(
        acta.get("objeto_social")
        or acta.get("objeto")
        or csf.get("actividad_economica")
        or csf.get("giro_mercantil")
    )

    if not objeto:
        return ReglaEvaluada(
            codigo="R4", nombre="Actividad / Giro",
            cumple=False,
            detalle="No se encontró objeto social ni actividad económica.",
            severidad="MEDIA", fuente_documento="acta_constitutiva",
        )

    return ReglaEvaluada(
        codigo="R4", nombre="Actividad / Giro",
        cumple=True,
        detalle=f"Actividad identificada: '{objeto[:120]}...'." if len(objeto) > 120 else f"Actividad: '{objeto}'.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 5: Tenencia Accionaria
# ═══════════════════════════════════════════════════════════════════

def _evaluar_tenencia(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que la estructura accionaria esté disponible."""
    acta = _get_doc(exp, "acta_constitutiva")
    ea_raw = _unwrap(acta.get("estructura_accionaria"))
    # estructura_accionaria puede ser lista directa o dict con key "valor"
    accionistas = ea_raw if isinstance(ea_raw, list) else (ea_raw or [])

    if not accionistas:
        return ReglaEvaluada(
            codigo="R5", nombre="Tenencia Accionaria",
            cumple=False,
            detalle="No se identificaron accionistas en el acta constitutiva.",
            severidad="CRITICA", fuente_documento="acta_constitutiva",
        )

    # Verificar que sumen ~100%
    total = sum(
        float(a.get("porcentaje", 0) or a.get("participacion", 0) or 0)
        for a in accionistas
        if isinstance(a, dict)
    )

    if total < 90 or total > 110:
        return ReglaEvaluada(
            codigo="R5", nombre="Tenencia Accionaria",
            cumple=False,
            detalle=f"Porcentajes de accionistas suman {total:.1f}% (esperado ~100%).",
            severidad="MEDIA", fuente_documento="acta_constitutiva",
        )

    return ReglaEvaluada(
        codigo="R5", nombre="Tenencia Accionaria",
        cumple=True,
        detalle=f"{len(accionistas)} accionistas identificados, total {total:.1f}%.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 6: Régimen de Administración
# ═══════════════════════════════════════════════════════════════════

def _evaluar_administracion(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que el régimen de administración esté identificado."""
    acta = _get_doc(exp, "acta_constitutiva")

    admin = (
        acta.get("consejo_administracion")
        or acta.get("administracion")
        or acta.get("administrador_unico")
        or acta.get("organo_administracion")
    )

    if not admin:
        return ReglaEvaluada(
            codigo="R6", nombre="Régimen de Administración",
            cumple=False,
            detalle="No se identificó régimen de administración en la constitutiva.",
            severidad="MEDIA", fuente_documento="acta_constitutiva",
        )

    return ReglaEvaluada(
        codigo="R6", nombre="Régimen de Administración",
        cumple=True,
        detalle="Régimen de administración identificado.",
        severidad="INFORMATIVA", fuente_documento="acta_constitutiva",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 7: Representante Legal / Apoderado
# ═══════════════════════════════════════════════════════════════════

def _evaluar_apoderado(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que exista poder notarial e INE del representante."""
    poder = _get_doc(exp, "poder")
    ine = _get_doc(exp, "ine")

    if not poder:
        return ReglaEvaluada(
            codigo="R7", nombre="Representante Legal / Apoderado",
            cumple=False,
            detalle="No se encontró poder notarial en el expediente.",
            severidad="CRITICA", fuente_documento="poder",
        )

    if not ine:
        return ReglaEvaluada(
            codigo="R7", nombre="Representante Legal / Apoderado",
            cumple=False,
            detalle="No se encontró INE del representante legal.",
            severidad="CRITICA", fuente_documento="ine",
        )

    nombre_poder = _safe_str(
        poder.get("apoderado")
        or poder.get("nombre_apoderado")
        or poder.get("representante_legal")
    )
    nombre_ine = _safe_str(
        ine.get("nombre_completo")
        or ine.get("nombre")
    )

    if not nombre_poder:
        return ReglaEvaluada(
            codigo="R7", nombre="Representante Legal / Apoderado",
            cumple=False,
            detalle="No se identificó nombre del apoderado en el poder notarial.",
            severidad="MEDIA", fuente_documento="poder",
        )

    return ReglaEvaluada(
        codigo="R7", nombre="Representante Legal / Apoderado",
        cumple=True,
        detalle=f"Apoderado: '{nombre_poder}'. INE: '{nombre_ine}'.",
        severidad="INFORMATIVA", fuente_documento="poder",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 8: Facultades para firma
# ═══════════════════════════════════════════════════════════════════

def _evaluar_facultades_firma(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Evalúa si el apoderado puede firmar el contrato de apertura.

    Según el manual de BPT:
    - Puede firmar SI: tiene facultades de administración Y/O apertura de cuentas.
    - Puede firmar SI: tiene facultades de delegación/sustitución Y/O nombrar
      personas que giren contra las cuentas.
    - No puede firmar en cualquier otro caso.
    """
    poder = _get_doc(exp, "poder")
    if not poder:
        return ReglaEvaluada(
            codigo="R8", nombre="Facultades para Firma de Contrato",
            cumple=False,
            detalle="Sin poder notarial, no se puede evaluar facultades.",
            severidad="MEDIA", fuente_documento="poder",
        )

    texto_fac = _safe_str(poder.get("facultades")).lower()
    tipo_poder = _safe_str(poder.get("tipo_poder")).lower()
    texto_total = texto_fac + " " + tipo_poder

    # ── Palabras clave del manual BPT ──
    # Administración
    kw_admin = [
        "actos de administración", "actos de administracion",
        "segundo párrafo del artículo 2554", "segundo parrafo del articulo 2554",
        "sin limitación alguna", "sin limitacion alguna",
        "administrar los bienes", "firmar todo tipo de contratos",
        "general para actos de administración", "general para actos de administracion",
    ]
    tiene_admin = any(kw in texto_total for kw in kw_admin)

    # Apertura de cuentas
    kw_apertura = [
        "cuentas bancarias", "abrir y cancelar cuentas",
        "apertura y cancelación", "apertura y cancelacion",
        "apertura de cuentas", "cuentas en entidades financieras",
        "girar contra ellas", "nombrar firmantes", "firmas autorizadas",
        "abrir y cerrar", "operar toda clase de cuentas",
        "designar a las personas que giren contra ellas",
    ]
    tiene_apertura = any(kw in texto_total for kw in kw_apertura)

    # Delegación/sustitución
    kw_delegacion = [
        "delegación", "delegacion", "sustitución", "sustitucion",
        "delegar", "sustituir", "revocar poderes",
        "otorgar y revocar poderes", "facultad para otorgar",
    ]
    tiene_delegacion = any(kw in texto_total for kw in kw_delegacion)

    # Regla BPT: puede firmar si admin O apertura O (delegación + nombrar firmantes)
    puede_firmar = tiene_admin or tiene_apertura or tiene_delegacion

    kw_encontradas = []
    if tiene_admin:
        kw_encontradas.append("administración")
    if tiene_apertura:
        kw_encontradas.append("apertura_cuentas")
    if tiene_delegacion:
        kw_encontradas.append("delegación")

    return ReglaEvaluada(
        codigo="R8", nombre="Facultades para Firma de Contrato",
        cumple=puede_firmar,
        detalle=(
            f"Admin={tiene_admin}, Apertura={tiene_apertura}, "
            f"Delegación={tiene_delegacion} → {'Sí' if puede_firmar else 'No'} puede firmar. "
            f"Palabras clave: {', '.join(kw_encontradas) or 'ninguna'}."
        ),
        severidad="INFORMATIVA" if puede_firmar else "MEDIA",
        fuente_documento="poder",
    )


# ═══════════════════════════════════════════════════════════════════
#  Regla 9: Consistencia con PLD
# ═══════════════════════════════════════════════════════════════════

def _evaluar_consistencia_pld(exp: ExpedienteLegal) -> ReglaEvaluada:
    """Verifica que exista dictamen PLD y no haya alertas críticas."""
    if not exp.analisis_pld:
        return ReglaEvaluada(
            codigo="R9", nombre="Consistencia con Dictamen PLD",
            cumple=False,
            detalle="No se encontró análisis PLD (Arizona) en el expediente.",
            severidad="MEDIA",
        )

    screening = exp.analisis_pld.get("screening") or {}
    resultado_screening = screening.get("resultado_global", "")

    if "COINCIDENCIA_CRITICA" in str(resultado_screening).upper():
        return ReglaEvaluada(
            codigo="R9", nombre="Consistencia con Dictamen PLD",
            cumple=False,
            detalle=f"Screening PLD con coincidencia crítica: {resultado_screening}.",
            severidad="CRITICA",
        )

    return ReglaEvaluada(
        codigo="R9", nombre="Consistencia con Dictamen PLD",
        cumple=True,
        detalle=f"PLD: {exp.analisis_pld.get('resultado', 'N/A')}, Screening: {resultado_screening or 'limpio'}.",
        severidad="INFORMATIVA",
    )


# ═══════════════════════════════════════════════════════════════════
#  Extractores de datos (para el LLM)
# ═══════════════════════════════════════════════════════════════════

def extraer_datos_constitucion(exp: ExpedienteLegal) -> DatosEscritura:
    """Extrae datos de la escritura constitutiva (proemio).

    Según manual BPT: los datos de la escritura aparecen en el proemio.
    Incluye número de escritura, fecha, notario, FME.
    """
    acta = _get_doc(exp, "acta_constitutiva")
    return DatosEscritura(
        escritura_numero=_safe_str(acta.get("numero_escritura_poliza") or acta.get("numero_escritura")),
        escritura_fecha=_safe_str(acta.get("fecha_constitucion") or acta.get("fecha_expedicion")),
        numero_notario=_safe_str(acta.get("numero_notaria") or acta.get("numero_notario")),
        nombre_notario=_safe_str(acta.get("nombre_notario")),
        residencia_notario=_safe_str(acta.get("estado_notaria") or acta.get("residencia_notario")),
        folio_mercantil=_safe_str(acta.get("folio_mercantil") or acta.get("folio_mercantil_electronico") or acta.get("fme")),
        fecha_folio_mercantil=_safe_str(acta.get("fecha_folio_mercantil")),
        lugar_folio_mercantil=_safe_str(acta.get("lugar_folio_mercantil")),
        volumen_tomo=_safe_str(acta.get("volumen") or acta.get("tomo")),
    )


def extraer_datos_ultimos_estatutos(exp: ExpedienteLegal) -> DatosEscritura:
    """Extrae datos de última reforma o constitutiva si no hay reforma.

    Según manual BPT: buscar "Antecedentes", "Acta que se protocoliza"
    y "Orden del día" para identificar cambios.
    """
    reforma = _get_doc(exp, "reforma")
    if reforma:
        # Intentar extraer antecedentes y orden del día del texto
        antecedentes = _safe_str(reforma.get("antecedentes") or reforma.get("antecedentes_resumen"))
        orden_dia = _safe_str(reforma.get("orden_del_dia"))

        return DatosEscritura(
            escritura_numero=_safe_str(reforma.get("numero_escritura_poliza") or reforma.get("numero_escritura")),
            escritura_fecha=_safe_str(reforma.get("fecha_constitucion") or reforma.get("fecha_expedicion")),
            numero_notario=_safe_str(reforma.get("numero_notaria") or reforma.get("numero_notario")),
            nombre_notario=_safe_str(reforma.get("nombre_notario")),
            residencia_notario=_safe_str(reforma.get("estado_notaria") or reforma.get("residencia_notario")),
            folio_mercantil=_safe_str(reforma.get("folio_mercantil") or reforma.get("folio_mercantil_electronico")),
            fecha_folio_mercantil=_safe_str(reforma.get("fecha_folio_mercantil")),
            lugar_folio_mercantil=_safe_str(reforma.get("lugar_folio_mercantil")),
            volumen_tomo=_safe_str(reforma.get("volumen") or reforma.get("tomo")),
            antecedentes_resumen=antecedentes or None,
            orden_del_dia=orden_dia or None,
        )
    return extraer_datos_constitucion(exp)


def extraer_actividad(exp: ExpedienteLegal) -> ActividadGiro:
    """Extrae actividad/giro de la empresa.

    Según manual BPT: solo considerar el primer inciso del objeto social.
    Siempre usar la escritura más reciente. Si una reforma modificó el objeto,
    indicar el instrumento.
    """
    acta = _get_doc(exp, "acta_constitutiva")
    csf = _get_doc(exp, "csf")
    reforma = _get_doc(exp, "reforma")

    fuente = "acta_constitutiva"

    # Objeto social del acta constitutiva
    objeto_acta = _safe_str(acta.get("objeto_social") or acta.get("objeto"))
    # Giro mercantil del CSF (fuente complementaria)
    giro_csf = _safe_str(csf.get("actividad_economica") or csf.get("giro_mercantil"))

    objeto = objeto_acta or giro_csf

    sufrio_mod = bool(reforma and (
        reforma.get("objeto_social") or reforma.get("objeto")
    ))

    observaciones = None
    instrumento = None

    if sufrio_mod:
        objeto_reforma = _safe_str(reforma.get("objeto_social") or reforma.get("objeto"))
        if objeto_reforma:
            objeto = objeto_reforma
            fuente = "reforma"
            instrumento = _safe_str(reforma.get("numero_escritura") or reforma.get("numero_escritura_poliza"))
            observaciones = (
                f"El objeto social fue modificado mediante instrumento {instrumento}. "
                f"Se tomó el objeto de la última reforma."
            )
    elif giro_csf and not objeto_acta:
        fuente = "csf"
        observaciones = "Objeto social no encontrado en acta; se tomó actividad económica del CSF."

    # Manual BPT: solo considerar el primer inciso del objeto social
    if objeto and len(objeto) > 300:
        # Recortar al primer inciso (buscar punto o salto de línea)
        corte = re.search(r"[.;]\s*(?:[a-z]\)|[IiVv]+\.-|\()", objeto)
        if corte:
            objeto = objeto[:corte.start() + 1].strip()

    return ActividadGiro(
        actividad_giro=objeto or None,
        sufrio_modificaciones=sufrio_mod,
        observaciones=observaciones,
        instrumento_cambio=instrumento,
        fuente_documento=fuente,
    )


def extraer_tenencia(exp: ExpedienteLegal) -> TenenciaAccionaria:
    """Extrae tenencia accionaria usando clausula_extranjeros del OCR.

    Según manual BPT:
    - Usar última escritura. Si no hay cambios, constitutiva.
    - Accionistas extranjeros: PM con LTD, S.L., etc. PF con pasaporte.
    - Debe coincidir con dictamen PLD (Arizona).
    """
    acta = _get_doc(exp, "acta_constitutiva")
    reforma = _get_doc(exp, "reforma")

    # Usar reforma si tiene estructura accionaria, sino constitutiva
    fuente = reforma if (reforma and reforma.get("estructura_accionaria")) else acta
    ea_raw = _unwrap(fuente.get("estructura_accionaria"))
    raw_acc = ea_raw if isinstance(ea_raw, list) else []

    # Cláusula de extranjeros del OCR
    clausula = _safe_str(acta.get("clausula_extranjeros")).upper()
    es_exclusion = "EXCLUSION" in clausula or "EXCLUSIÓN" in clausula

    accionistas: list[AccionistaDJ] = []
    hay_ext = False
    for a in raw_acc:
        if not isinstance(a, dict):
            continue
        nombre = _safe_str(a.get("nombre") or a.get("nombre_completo") or "")
        if not nombre:
            continue
        pct = float(a.get("porcentaje", 0) or a.get("participacion", 0) or 0)
        # Tipo de persona (fisica/moral) del OCR
        tipo_p = _safe_str(a.get("tipo") or a.get("_tipo_detectado") or "fisica").lower()
        if tipo_p not in ("fisica", "moral"):
            tipo_p = "fisica"
        # Extranjero: si NO hay cláusula de exclusión, evaluar por nombre
        if es_exclusion:
            es_ext = False
        else:
            es_ext = _es_extranjero_pm(nombre)
        if es_ext:
            hay_ext = True
        accionistas.append(AccionistaDJ(
            nombre=nombre,
            porcentaje=pct,
            es_extranjero=es_ext,
            tipo_persona=tipo_p,
        ))

    return TenenciaAccionaria(accionistas=accionistas, hay_extranjeros=hay_ext)


def extraer_administracion(exp: ExpedienteLegal) -> RegimenAdministracion:
    """Extrae régimen de administración.

    Según manual BPT: viene en la sección de 'Transitorios' de la constitutiva.
    Buscar: 'confiar la administración de la sociedad a un consejo
    de administración' o 'administrador único'.
    """
    acta = _get_doc(exp, "acta_constitutiva")
    reforma = _get_doc(exp, "reforma")

    # Usar reforma si tiene datos de administración, sino constitutiva
    fuente = reforma if (reforma and (
        reforma.get("consejo_administracion") or reforma.get("administracion")
        or reforma.get("administrador_unico")
    )) else acta

    consejo = fuente.get("consejo_administracion") or fuente.get("administracion") or []
    admin_unico = fuente.get("administrador_unico")

    if admin_unico and isinstance(admin_unico, str):
        return RegimenAdministracion(
            tipo="administrador_unico",
            miembros=[MiembroAdministracion(nombre=admin_unico, cargo="Administrador Único")],
        )

    if isinstance(consejo, list) and consejo:
        miembros = []
        for m in consejo:
            if isinstance(m, dict):
                miembros.append(MiembroAdministracion(
                    nombre=_safe_str(m.get("nombre") or m.get("nombre_completo") or ""),
                    cargo=_safe_str(m.get("cargo") or m.get("puesto") or ""),
                ))
            elif isinstance(m, str):
                miembros.append(MiembroAdministracion(nombre=m))
        return RegimenAdministracion(tipo="consejo_administracion", miembros=miembros)

    # Fallback: revisar en transitorios (texto libre)
    if isinstance(consejo, str) and consejo:
        return RegimenAdministracion(
            tipo="consejo_administracion",
            miembros=[MiembroAdministracion(nombre=consejo)],
        )

    return RegimenAdministracion()


def extraer_apoderados(exp: ExpedienteLegal) -> list[ApoderadoDJ]:
    """Extrae apoderados del poder notarial, analizando el texto de facultades.

    Usa las palabras clave definidas en el manual de reglas BPT para cada tipo
    de facultad, identificando artículos legales, verbos y frases clave.
    """
    poder = _get_doc(exp, "poder")
    ine = _get_doc(exp, "ine")
    if not poder:
        return []

    nombre = _safe_str(
        poder.get("apoderado") or poder.get("nombre_apoderado")
        or poder.get("representante_legal")
        or ine.get("nombre_completo") or ine.get("nombre")
    )

    if not nombre:
        return []

    # ── Datos del poder notarial ──
    poder_escritura = _safe_str(poder.get("numero_escritura") or poder.get("numero_escritura_poliza"))
    poder_fecha = _safe_str(poder.get("fecha_otorgamiento") or poder.get("fecha_expedicion"))
    poder_notario = _safe_str(poder.get("nombre_notario"))
    poder_notaria = _safe_str(poder.get("numero_notaria"))
    poder_estado = _safe_str(poder.get("estado_notaria"))
    poderdante = _safe_str(poder.get("nombre_poderdante") or poder.get("poderdante"))
    tipo_poder = _safe_str(poder.get("tipo_poder"))

    # ── Texto completo para búsqueda de palabras clave ──
    facs_raw = poder.get("facultades") or {}
    texto_facs = _safe_str(facs_raw).lower()
    texto_tipo = tipo_poder.lower()
    texto_total = texto_facs + " " + texto_tipo

    # ── Detección de facultades con palabras clave del manual BPT ──
    kw_encontradas: list[str] = []

    # 7.1 Administración
    kw_admin = [
        "actos de administración", "actos de administracion",
        "segundo párrafo del artículo 2554", "segundo parrafo del articulo 2554",
        "sin limitación alguna", "sin limitacion alguna",
        "administrar los bienes de la sociedad",
        "firmar todo tipo de contratos y convenios",
        "general para actos de administración", "general para actos de administracion",
        "representación administrativa", "representacion administrativa",
    ]
    tiene_admin = any(kw in texto_total for kw in kw_admin)
    if tiene_admin:
        for kw in kw_admin:
            if kw in texto_total:
                kw_encontradas.append(f"admin: {kw}")
                break

    # 7.2 Dominio
    kw_dominio = [
        "actos de dominio", "riguroso dominio",
        "tercer párrafo del artículo 2554", "tercer parrafo del articulo 2554",
        "enajenar los bienes", "obligarse solidariamente", "otorgar garantías",
        "otorgar garantias",
    ]
    tiene_dominio = any(kw in texto_total for kw in kw_dominio)
    if tiene_dominio:
        for kw in kw_dominio:
            if kw in texto_total:
                kw_encontradas.append(f"dominio: {kw}")
                break

    # 7.3 Títulos de crédito
    kw_titulos = [
        "títulos de crédito", "titulos de credito",
        "artículo 9 de la ley general de títulos",
        "articulo 9 de la ley general de titulos",
        "suscribir", "endosar", "emitir",
        "poder cambiario",
    ]
    tiene_titulos = any(kw in texto_total for kw in kw_titulos)
    if tiene_titulos:
        for kw in kw_titulos:
            if kw in texto_total:
                kw_encontradas.append(f"títulos: {kw}")
                break

    # 7.4 Apertura de cuentas
    kw_apertura = [
        "apertura y cancelación", "apertura y cancelacion",
        "cuentas bancarias", "cuentas en entidades financieras",
        "girar contra ellas", "nombrar firmantes", "firmas autorizadas",
        "abrir y cancelar cuentas", "apertura de cuentas",
        "abrir y cerrar", "operar toda clase de cuentas",
        "designar a las personas que giren contra ellas",
    ]
    tiene_apertura = any(kw in texto_total for kw in kw_apertura)
    if tiene_apertura:
        for kw in kw_apertura:
            if kw in texto_total:
                kw_encontradas.append(f"apertura: {kw}")
                break

    # 7.5 Delegación / sustitución
    kw_delegacion = [
        "delegación", "delegacion",
        "sustitución", "sustitucion",
        "delegar", "sustituir",
        "otorgar y revocar poderes", "revocar poderes",
        "facultad para otorgar", "con o sin facultades de sustitución",
    ]
    tiene_delegacion = any(kw in texto_total for kw in kw_delegacion)
    if tiene_delegacion:
        for kw in kw_delegacion:
            if kw in texto_total:
                kw_encontradas.append(f"delegación: {kw}")
                break

    # Limitaciones
    limitaciones = None
    m_lim = re.search(
        r"(?:con\s+)?limitaci[oó]n\s+(?:a\s+)?(.+?)(?:\.\s|$)",
        texto_facs, re.IGNORECASE,
    )
    if m_lim:
        limitaciones = m_lim.group(0).strip().rstrip(".")

    # Especiales
    especiales = None
    if "especial" in texto_tipo or "especial" in texto_facs:
        especiales_parts = []
        if "fideicomiso" in texto_total:
            especiales_parts.append("Constituir fideicomisos")
        if "amparo" in texto_total:
            especiales_parts.append("Juicio de amparo")
        if "pleitos y cobranzas" in texto_total:
            especiales_parts.append("Pleitos y cobranzas")
        if especiales_parts:
            especiales = ", ".join(especiales_parts)
        else:
            especiales = "Sí (ver poder)"

    facultades = FacultadesApoderado(
        administracion=tiene_admin,
        dominio=tiene_dominio,
        titulos_credito=tiene_titulos,
        apertura_cuentas=tiene_apertura,
        delegacion_sustitucion=tiene_delegacion,
        especiales=especiales,
        palabras_clave_encontradas=kw_encontradas,
    )

    # Regla BPT: puede firmar si admin O apertura O delegación+nombrar
    puede_firmar = tiene_admin or tiene_apertura or tiene_delegacion
    # Puede designar web banking si puede firmar + delegación/nombrar firmantes
    puede_designar = puede_firmar and (tiene_delegacion or tiene_apertura)

    # Régimen de firmas
    regimen = "individual"
    if "mancomunad" in texto_total:
        regimen = "mancomunado"
    elif "individual" in texto_total or "separadamente" in texto_total:
        regimen = "individual"
    # Detección de firma_a/firma_b/firma_c
    if "firma \"a\"" in texto_total or "firma a" in texto_total.replace("\"", ""):
        regimen_detalle = regimen
        if "firma \"b\"" in texto_total or "firma \"c\"" in texto_total:
            regimen_detalle = "mancomunado"
        regimen = regimen_detalle

    # Vigencia
    vigencia = None
    m_vig = re.search(r"vigencia[:\s]+([^.;]+)", texto_total, re.IGNORECASE)
    if m_vig:
        vigencia = m_vig.group(1).strip()

    # Nacionalidad
    nacionalidad: str = "mexicana"
    if exp.dictamen_pld:
        dj_pld = exp.dictamen_pld.get("dictamen") or {}
        rep_pld = dj_pld.get("representante_legal") or {} if isinstance(dj_pld, dict) else {}
        nac_pld = rep_pld.get("nacionalidad", "").upper()
        if "EXTRAN" in nac_pld:
            nacionalidad = "extranjero"

    return [ApoderadoDJ(
        nombre=nombre,
        facultades=facultades,
        limitaciones=limitaciones,
        regimen_firmas=regimen,
        vigencia=vigencia,
        nacionalidad=nacionalidad,
        puede_firmar_contrato=puede_firmar,
        puede_designar_web_banking=puede_designar,
        poder_escritura_numero=poder_escritura or None,
        poder_fecha=poder_fecha or None,
        poder_notario=poder_notario or None,
        poder_notaria=poder_notaria or None,
        poder_estado=poder_estado or None,
        poderdante=poderdante or None,
        tipo_poder_completo=tipo_poder or None,
    )]


# ═══════════════════════════════════════════════════════════════════
#  Punto de entrada principal
# ═══════════════════════════════════════════════════════════════════

def evaluar_reglas(exp: ExpedienteLegal) -> ResultadoReglas:
    """
    Evalúa todas las reglas del dictamen jurídico sobre el expediente.

    Returns:
        ResultadoReglas con el detalle de cada regla y el dictamen sugerido.
    """
    reglas = [
        _evaluar_denominacion(exp),
        _evaluar_constitucion(exp),
        _evaluar_folio_mercantil(exp),
        _evaluar_actividad(exp),
        _evaluar_tenencia(exp),
        _evaluar_administracion(exp),
        _evaluar_apoderado(exp),
        _evaluar_facultades_firma(exp),
        _evaluar_consistencia_pld(exp),
    ]

    criticas = sum(1 for r in reglas if not r.cumple and r.severidad == "CRITICA")
    medias = sum(1 for r in reglas if not r.cumple and r.severidad == "MEDIA")

    if criticas > 0:
        dictamen = "NO_FAVORABLE"
    elif medias > 2:
        dictamen = "FAVORABLE_CON_CONDICIONES"
    else:
        dictamen = "FAVORABLE"

    pasan = sum(1 for r in reglas if r.cumple)
    total = len(reglas)

    resumen = (
        f"{pasan}/{total} reglas cumplidas. "
        f"Críticas fallidas: {criticas}, Medias fallidas: {medias}. "
        f"Dictamen sugerido: {dictamen}."
    )

    logger.info("[RULES] %s", resumen)

    return ResultadoReglas(
        reglas=reglas,
        total_criticas_fallidas=criticas,
        total_medias_fallidas=medias,
        dictamen_sugerido=dictamen,
        resumen=resumen,
    )
