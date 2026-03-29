"""
Motor de validación cruzada.
Orquesta todos los bloques y genera el reporte final.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import logging
from typing import Any

from ..models.schemas import (
    ComparacionCampo,
    DatosClave,
    Dictamen,
    DomicilioClave,
    ExpedienteEmpresa,
    Hallazgo,
    PersonaClave,
    ReporteValidacion,
    ResumenGlobal,
    Severidad,
)
from .data_loader import cargar_expediente, listar_empresas
from .validators import TODOS_LOS_BLOQUES
from .validators.bloque10_portales import validar_portales as _validar_portales
from .validators.bloque11_comparacion_fuentes import validar as _validar_comparacion_fuentes
from .validators.base import obtener_datos, obtener_reforma
from .text_utils import get_valor, get_valor_str, normalizar_texto
from .persistence import guardar_validacion

logger = logging.getLogger("cross_validation.engine")

# Keywords para detectar facultad de apertura / operación de cuentas bancarias
_KEYWORDS_PODER_BANCARIO = [
    "ABRIR CUENTAS",
    "APERTURA DE CUENTAS",
    "OPERACION DE CUENTAS",
    "OPERACIONES BANCARIAS",
    "CUENTAS BANCARIAS",
    "INSTITUCIONES DE CREDITO",
    "INSTITUCIONES BANCARIAS",
    "CONTRATAR SERVICIOS BANCARIOS",
    "SERVICIOS FINANCIEROS",
]


def _calcular_dictamen(hallazgos: list[Hallazgo]) -> tuple[Dictamen, int, int, int, int]:
    """
    Calcula el dictamen según las reglas:
    - APROBADO: 0 críticos fallidos, máximo 2 medios fallidos
    - APROBADO CON OBSERVACIONES: 0 críticos fallidos, más de 2 medios fallidos
    - RECHAZADO: 1+ críticos fallidos
    """
    criticos = sum(
        1 for h in hallazgos
        if h.pasa is False and h.severidad == Severidad.CRITICA
    )
    medios = sum(
        1 for h in hallazgos
        if h.pasa is False and h.severidad == Severidad.MEDIA
    )
    informativos = sum(
        1 for h in hallazgos
        if h.severidad == Severidad.INFORMATIVA and h.pasa is not True
    )
    pasan = sum(1 for h in hallazgos if h.pasa is True)

    if criticos > 0:
        dictamen = Dictamen.RECHAZADO
    elif medios > 2:
        dictamen = Dictamen.APROBADO_CON_OBSERVACIONES
    else:
        dictamen = Dictamen.APROBADO

    return dictamen, criticos, medios, informativos, pasan


def _generar_recomendaciones(hallazgos: list[Hallazgo]) -> list[str]:
    """Genera recomendaciones priorizadas basadas en los hallazgos."""
    recomendaciones = []

    criticos = [h for h in hallazgos if h.pasa is False and h.severidad == Severidad.CRITICA]
    medios = [h for h in hallazgos if h.pasa is False and h.severidad == Severidad.MEDIA]

    # Recomendaciones por hallazgos críticos
    for haz in criticos:
        # V9.1 individuales: "Falta: Poder notarial", "Falta: INE..." → Solicitar
        if haz.nombre.startswith("Falta:"):
            nombre_doc = haz.nombre.replace("Falta: ", "")
            recomendaciones.append(f"Solicitar documento faltante: {nombre_doc}")
            continue

        if "RFC" in haz.nombre.upper() or "V1.1" in haz.codigo:
            recomendaciones.append("URGENTE: Verificar y corregir discrepancia de RFC entre documentos")
        elif "RAZON SOCIAL" in haz.nombre.upper() or "V1.2" in haz.codigo:
            recomendaciones.append("URGENTE: Verificar razón social — posible persona moral incorrecta")
        elif "ESTATUS" in haz.nombre.upper() or "V1.3" in haz.codigo:
            recomendaciones.append("URGENTE: La empresa NO está activa en el SAT — no puede operar")
        elif "FIEL" in haz.nombre.upper() and "VENC" in haz.mensaje.upper():
            recomendaciones.append("URGENTE: Renovar FIEL antes de continuar el onboarding")
        elif "INE" in haz.nombre.upper() and "VENC" in haz.mensaje.upper():
            recomendaciones.append("URGENTE: INE del apoderado vencida — solicitar INE vigente")
        elif "APODERADO" in haz.nombre.upper():
            recomendaciones.append("URGENTE: Verificar identidad del apoderado legal")
        elif "PODER" in haz.nombre.upper() or "PODERDANTE" in haz.nombre.upper():
            recomendaciones.append("URGENTE: Verificar que el poder notarial corresponda a esta empresa")
        elif "FALTA" in haz.nombre.upper() or "V9.1" in haz.codigo:
            # V9.1 resumen: "Faltan 3/7 documentos: ..."
            msg = haz.mensaje
            if msg.startswith("Documento FALTANTE: "):
                msg = msg.replace("Documento FALTANTE: ", "")
            recomendaciones.append(f"Solicitar documentos faltantes: {msg}")
        elif "DOMICILIO" in haz.nombre.upper() and "DISTINTO" in haz.mensaje.upper():
            recomendaciones.append("URGENTE: Domicilios completamente distintos — verificar ubicación real")

    # Recomendaciones por hallazgos medios
    for haz in medios[:5]:  # Limitar a 5
        if "CP" in haz.nombre.upper():
            recomendaciones.append("Verificar código postal entre CSF y comprobante de domicilio")
        elif "CAMPO POR CAMPO" in haz.nombre.upper():
            recomendaciones.append("Verificar campos discrepantes del domicilio en documentos originales")
        elif "DOMICILIO" in haz.nombre.upper():
            recomendaciones.append("Validar domicilio fiscal con comprobante actualizado")
        elif "APODERADO EN ESTRUCTURA" in haz.nombre.upper():
            recomendaciones.append(
                "Verificar que el representante legal aparezca en el Acta Constitutiva")
        elif "PODERES" in haz.nombre.upper():
            recomendaciones.append(
                "Verificar que el Acta Constitutiva integre poderes del representante legal "
                "o solicitar Poder Notarial independiente")
        elif "REGISTRO" in haz.nombre.upper() or "INSCRIPCION" in haz.nombre.upper():
            recomendaciones.append(
                "Verificar que el Acta Constitutiva cuente con sello del Registro Público "
                "(RPP/RPC)")
        elif "ESTRUCTURA" in haz.nombre.upper():
            recomendaciones.append("Verificar estructura accionaria manualmente")
        elif "CAPITAL" in haz.nombre.upper():
            recomendaciones.append("Verificar monto de capital social en documento original")
        elif "CLABE" in haz.nombre.upper():
            recomendaciones.append("Solicitar estado de cuenta con CLABE legible")
        elif "TITULAR" in haz.nombre.upper():
            recomendaciones.append("Solicitar estado de cuenta con titular legible")
        elif "FOLIO" in haz.nombre.upper():
            recomendaciones.append("Verificar folio mercantil en el Registro Público de Comercio")
        elif "COMPLEMENT" in haz.nombre.upper():
            recomendaciones.append(f"Solicitar documentos complementarios: {haz.mensaje}")

    # Recomendaciones por hallazgos de portales (Bloque 10)
    portales_criticos = [h for h in criticos if h.bloque == 10]
    portales_medios = [h for h in medios if h.bloque == 10]
    portales_na = [h for h in hallazgos if h.bloque == 10 and h.pasa is None]

    for haz in portales_criticos:
        if "V10.1" in haz.codigo:
            if "VENCIDO" in haz.mensaje.upper():
                recomendaciones.append("URGENTE: La e.firma (FIEL) está VENCIDA según el portal del SAT — renovar antes de continuar")
            elif "REVOCADO" in haz.mensaje.upper():
                recomendaciones.append("URGENTE: La e.firma (FIEL) está REVOCADA según el portal del SAT — gestionar nueva e.firma")
            else:
                recomendaciones.append("URGENTE: La e.firma (FIEL) NO se pudo validar en el portal del SAT")
        elif "V10.2" in haz.codigo:
            recomendaciones.append("URGENTE: El RFC NO fue validado satisfactoriamente en el portal del SAT")
        elif "V10.3" in haz.codigo:
            recomendaciones.append("URGENTE: La INE del apoderado NO aparece en la Lista Nominal del INE")

    for haz in portales_na:
        if "CAPTCHA" in haz.mensaje.upper():
            recomendaciones.append(
                f"VERIFICACIÓN MANUAL REQUERIDA para {haz.codigo}: "
                f"el CAPTCHA no pudo resolverse automáticamente. "
                f"Realizar la consulta de forma manual en el portal correspondiente."
            )
        elif "ERROR" in haz.mensaje.upper() or "SIN DATOS" in haz.mensaje.upper():
            recomendaciones.append(
                f"VERIFICACIÓN MANUAL REQUERIDA para {haz.codigo}: "
                f"{haz.mensaje[:80]}. "
                f"Realizar la consulta de forma manual en el portal correspondiente."
            )

    # Deduplicar
    return list(dict.fromkeys(recomendaciones))


# ═══════════════════════════════════════════════════════════════════
#  EXTRACCIÓN DE DATOS CLAVE
# ═══════════════════════════════════════════════════════════════════

def _extraer_nombre_ine(datos: dict) -> str:
    """Extrae nombre completo de la INE (misma lógica que bloque4)."""
    nombre = get_valor_str(datos, "nombre_completo")
    if nombre:
        return nombre
    first = get_valor_str(datos, "FirstName")
    last = get_valor_str(datos, "LastName")
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if last:
        return last
    nombre_s = get_valor_str(datos, "nombre")
    apellidos = get_valor_str(datos, "apellidos")
    if nombre_s and apellidos:
        return f"{nombre_s} {apellidos}"
    return nombre_s or apellidos or ""


def _extraer_datos_clave(exp: ExpedienteEmpresa) -> DatosClave:
    """
    Extrae los datos clave de la persona moral desde el expediente:
    - Razón social
    - Apoderados
    - Representante legal
    - Accionistas
    - Consejo de administración
    """
    # ── Razón social: priorizar CSF (fuente oficial) ──
    csf = obtener_datos(exp, "csf")
    razon = get_valor_str(csf, "razon_social") if csf else ""
    if not razon:
        acta = obtener_datos(exp, "acta_constitutiva")
        razon = get_valor_str(acta, "denominacion_social") if acta else ""
    if not razon:
        razon = exp.razon_social

    # ── RFC ──
    rfc = get_valor_str(csf, "rfc") if csf else ""
    if not rfc:
        rfc = exp.rfc

    # ── Apoderado(s) desde Poder Notarial + INE ──
    apoderados: list[PersonaClave] = []
    representante: PersonaClave | None = None

    poder = obtener_datos(exp, "poder")
    ine = obtener_datos(exp, "ine")

    if poder:
        nombre_poder = get_valor_str(poder, "nombre_apoderado")
        tipo_poder = get_valor_str(poder, "tipo_poder")
        facultades = get_valor_str(poder, "facultades")
        fac_txt = tipo_poder or facultades or ""

        if nombre_poder:
            apoderados.append(PersonaClave(
                nombre=nombre_poder,
                rol="apoderado",
                fuente="poder_notarial",
                tipo_persona="fisica",
                facultades=fac_txt if fac_txt else None,
            ))

    # Si hay INE pero no se extrajo nombre del poder, usar INE como respaldo
    if ine and not apoderados:
        nombre_ine = _extraer_nombre_ine(ine)
        if nombre_ine:
            apoderados.append(PersonaClave(
                nombre=nombre_ine,
                rol="apoderado",
                fuente="ine",
                tipo_persona="fisica",
            ))

    # El primer apoderado es el representante legal principal
    if apoderados:
        rep = apoderados[0]
        representante = PersonaClave(
            nombre=rep.nombre,
            rol="representante_legal",
            fuente=rep.fuente,
            tipo_persona="fisica",
            facultades=rep.facultades,
        )

    # ── Accionistas desde Acta Constitutiva y Reforma ──
    accionistas: list[PersonaClave] = []
    _nombres_vistos: set[str] = set()

    # Función helper para agregar accionistas sin duplicados
    def _agregar_accionistas(estructura: list, fuente: str) -> None:
        if not isinstance(estructura, list):
            return
        for socio in estructura:
            if not isinstance(socio, dict):
                continue
            nombre = socio.get("nombre", "")
            if not nombre or nombre.upper() in _nombres_vistos:
                continue
            _nombres_vistos.add(nombre.upper())

            tipo_raw = (socio.get("tipo") or "").lower()
            es_moral = "moral" in tipo_raw or any(
                kw in nombre.lower()
                for kw in ("s.a", "s.c", "s. de r.l", "sapi", "s.a.p.i")
            )

            try:
                pct = float(socio.get("porcentaje", 0))
            except (ValueError, TypeError):
                pct = None

            accionistas.append(PersonaClave(
                nombre=nombre,
                rol="accionista",
                fuente=fuente,
                tipo_persona="moral" if es_moral else "fisica",
                porcentaje=pct if pct else None,
            ))

    # Reforma tiene prioridad (datos más recientes)
    reforma = obtener_reforma(exp)
    if reforma:
        est_reforma = get_valor(reforma, "estructura_accionaria")
        if isinstance(est_reforma, list) and est_reforma:
            _agregar_accionistas(est_reforma, "reforma_estatutos")

    # Complementar con acta constitutiva
    acta = obtener_datos(exp, "acta_constitutiva")
    if acta:
        est_acta = get_valor(acta, "estructura_accionaria")
        if isinstance(est_acta, list) and est_acta:
            _agregar_accionistas(est_acta, "acta_constitutiva")

    # ── Consejo de administración desde Reforma ──
    consejo: list[PersonaClave] = []
    if reforma:
        consejo_raw = get_valor(reforma, "consejo_administracion")
        if isinstance(consejo_raw, list):
            for miembro in consejo_raw:
                if isinstance(miembro, dict):
                    nombre_m = miembro.get("nombre", "")
                    cargo = miembro.get("cargo", "")
                elif isinstance(miembro, str):
                    nombre_m = miembro
                    cargo = ""
                else:
                    continue
                if nombre_m:
                    consejo.append(PersonaClave(
                        nombre=nombre_m,
                        rol="consejero",
                        fuente="reforma_estatutos",
                        tipo_persona="fisica",
                        facultades=cargo if cargo else None,
                    ))

    # ── Detectar poder para abrir cuentas bancarias ──
    poder_bancario: bool | None = None
    if poder:
        tipo_poder = get_valor_str(poder, "tipo_poder")
        facultades_txt = get_valor_str(poder, "facultades")
        texto_completo = normalizar_texto(
            f"{tipo_poder or ''} {facultades_txt or ''}"
        )
        if texto_completo.strip():
            poder_bancario = any(
                kw in texto_completo for kw in _KEYWORDS_PODER_BANCARIO
            )

    # ── Campos adicionales para PLD (Arizona) ──
    # Giro mercantil del CSF
    giro = get_valor_str(csf, "giro_mercantil") if csf else ""
    if not giro:
        giro = get_valor_str(csf, "actividad_economica") if csf else ""
    
    # Fecha de constitución del Acta
    if not acta:
        acta = obtener_datos(exp, "acta_constitutiva")
    fecha_const = get_valor_str(acta, "fecha_constitucion") if acta else ""
    if not fecha_const:
        fecha_const = get_valor_str(acta, "fecha_escritura") if acta else ""
    
    # Número de serie FIEL
    fiel = obtener_datos(exp, "fiel")
    serie_fiel = get_valor_str(fiel, "numero_serie_certificado") if fiel else ""
    if not serie_fiel:
        serie_fiel = get_valor_str(fiel, "no_serie") if fiel else ""
    
    # Domicilio fiscal (CSF primero, luego comprobante)
    domicilio_obj: DomicilioClave | None = None
    dom_fuente = ""
    dom_raw = None
    
    if csf:
        dom_raw = get_valor(csf, "domicilio_fiscal")
        dom_fuente = "csf"
    
    if not dom_raw:
        comp_dom = obtener_datos(exp, "comprobante_domicilio")
        if comp_dom:
            dom_raw = comp_dom  # El comprobante de domicilio ES el domicilio
            dom_fuente = "comprobante_domicilio"
    
    if isinstance(dom_raw, dict):
        domicilio_obj = DomicilioClave(
            calle=get_valor_str(dom_raw, "calle") or get_valor_str(dom_raw, "vialidad") or "",
            numero_exterior=get_valor_str(dom_raw, "numero_exterior") or get_valor_str(dom_raw, "no_exterior") or "",
            numero_interior=get_valor_str(dom_raw, "numero_interior") or get_valor_str(dom_raw, "no_interior") or "",
            colonia=get_valor_str(dom_raw, "colonia") or "",
            codigo_postal=get_valor_str(dom_raw, "codigo_postal") or get_valor_str(dom_raw, "cp") or "",
            municipio=get_valor_str(dom_raw, "municipio") or get_valor_str(dom_raw, "municipio_delegacion") or get_valor_str(dom_raw, "delegacion") or "",
            estado=get_valor_str(dom_raw, "estado") or get_valor_str(dom_raw, "entidad_federativa") or "",
            fuente=dom_fuente,
        )

    return DatosClave(
        razon_social=razon,
        rfc=rfc,
        apoderados=apoderados,
        representante_legal=representante,
        accionistas=accionistas,
        consejo_administracion=consejo,
        poder_cuenta_bancaria=poder_bancario,
        giro_mercantil=giro,
        fecha_constitucion=fecha_const,
        numero_serie_fiel=serie_fiel,
        domicilio=domicilio_obj,
    )


async def validar_empresa(
    empresa_id: str,
    *,
    portales: bool = True,
    modulos_portales: set[str] | None = None,
    headless: bool = True,
) -> ReporteValidacion:
    """
    Ejecuta la validación cruzada completa para una empresa.

    Args:
        empresa_id: UUID de la empresa en BD.
        portales: Si True, ejecuta bloque 10 (validación contra portales). Default: True.
        modulos_portales: Subconjunto de módulos portal {'fiel', 'rfc', 'ine'}.
        headless: Si True, navegador sin ventana visible (solo aplica con portales).
    """
    exp = await cargar_expediente(empresa_id)

    # ── Bloques 1-9: validaciones síncronas ──
    hallazgos: list[Hallazgo] = []
    for bloque_fn in TODOS_LOS_BLOQUES:
        try:
            resultados = bloque_fn(exp)
            hallazgos.extend(resultados)
        except Exception as e:
            hallazgos.append(Hallazgo(
                codigo="ERR",
                nombre=f"Error en {bloque_fn.__module__.split('.')[-1]}",
                bloque=0,
                bloque_nombre="ERROR INTERNO",
                pasa=False,
                severidad=Severidad.CRITICA,
                mensaje=f"Error al ejecutar validador: {str(e)}",
                detalles={"excepcion": str(e), "modulo": bloque_fn.__module__},
            ))

    # ── Bloque 10: validación contra portales gubernamentales (async) ──
    if portales:
        try:
            hallazgos_portales = await _validar_portales(
                exp,
                modulos=modulos_portales,
                headless=headless,
            )
            hallazgos.extend(hallazgos_portales)
        except Exception as e:
            hallazgos.append(Hallazgo(
                codigo="V10.0",
                nombre="Error en validación de portales",
                bloque=10,
                bloque_nombre="VALIDACIÓN EN PORTALES GUBERNAMENTALES",
                pasa=None,
                severidad=Severidad.MEDIA,
                mensaje=f"Error general al consultar portales: {str(e)}",
                detalles={"excepcion": str(e)},
            ))

    # ── Bloque 11: comparación Manual vs OCR (condicional) ──
    comparacion_fuentes: list[ComparacionCampo] = []
    if "formulario_manual" in exp.documentos:
        try:
            hallazgos_b11, comparacion_fuentes = _validar_comparacion_fuentes(exp)
            hallazgos.extend(hallazgos_b11)
        except Exception as e:
            hallazgos.append(Hallazgo(
                codigo="V11.0",
                nombre="Error en comparación Manual vs OCR",
                bloque=11,
                bloque_nombre="COMPARACIÓN MANUAL VS OCR",
                pasa=None,
                severidad=Severidad.MEDIA,
                mensaje=f"Error general al comparar fuentes: {str(e)}",
                detalles={"excepcion": str(e)},
            ))

    # Calcular dictamen
    dictamen, criticos, medios, informativos, pasan = _calcular_dictamen(hallazgos)

    # Generar recomendaciones
    recomendaciones = _generar_recomendaciones(hallazgos)

    # Extraer datos clave de la persona moral
    datos_clave = _extraer_datos_clave(exp)

    reporte = ReporteValidacion(
        empresa_id=exp.empresa_id,
        rfc=exp.rfc,
        razon_social=exp.razon_social,
        fecha_analisis=datetime.now(),
        documentos_presentes=exp.doc_types_presentes,
        hallazgos=hallazgos,
        dictamen=dictamen,
        total_criticos=criticos,
        total_medios=medios,
        total_informativos=informativos,
        total_pasan=pasan,
        recomendaciones=recomendaciones,
        datos_clave=datos_clave,
        comparacion_fuentes=comparacion_fuentes,
    )

    # ── Persistir en BD ──
    try:
        # Si se corrieron portales sin especificar módulos, se ejecutaron todos
        modulos_efectivos = modulos_portales
        if portales and not modulos_efectivos:
            modulos_efectivos = {"fiel", "rfc", "ine"}

        vid = await guardar_validacion(
            reporte,
            portales_ejecutados=portales,
            modulos_portales=modulos_efectivos,
        )
        logger.info("Validación persistida: %s → %s", exp.rfc, vid)
    except Exception as e:
        logger.warning("No se pudo persistir validación de %s: %s", exp.rfc, e)

    return reporte


async def validar_todas(
    *,
    portales: bool = True,
    modulos_portales: set[str] | None = None,
    headless: bool = True,
) -> ResumenGlobal:
    """
    Ejecuta la validación cruzada para TODAS las empresas.
    Genera un resumen global con tabla de dictámenes y hallazgos frecuentes.
    """
    empresas = await listar_empresas()
    reportes: list[ReporteValidacion] = []

    for emp in empresas:
        try:
            reporte = await validar_empresa(
                emp["id"],
                portales=portales,
                modulos_portales=modulos_portales,
                headless=headless,
            )
            reportes.append(reporte)
        except Exception as e:
            # Crear reporte de error
            reportes.append(ReporteValidacion(
                empresa_id=emp["id"],
                rfc=emp["rfc"],
                razon_social=emp["razon_social"],
                fecha_analisis=datetime.now(),
                documentos_presentes=emp.get("doc_types", []),
                hallazgos=[],
                dictamen=Dictamen.RECHAZADO,
                total_criticos=0,
                total_medios=0,
                total_informativos=0,
                total_pasan=0,
                recomendaciones=[f"Error al procesar: {str(e)}"],
            ))

    # Tabla de dictámenes
    tabla_dictamenes = [
        {
            "rfc": r.rfc,
            "razon_social": r.razon_social,
            "dictamen": r.dictamen.value,
            "criticos": r.total_criticos,
            "medios": r.total_medios,
            "informativos": r.total_informativos,
        }
        for r in reportes
    ]

    # Hallazgos más frecuentes
    contador: Counter[str] = Counter()
    for r in reportes:
        for haz in r.hallazgos:
            if haz.pasa is False:
                contador[f"{haz.codigo} {haz.nombre}"] += 1

    hallazgos_frecuentes = [
        {"hallazgo": nombre, "frecuencia": count}
        for nombre, count in contador.most_common(10)
    ]

    # Recomendaciones globales
    rec_global: list[str] = []
    aprobados = sum(1 for r in reportes if r.dictamen == Dictamen.APROBADO)
    con_obs = sum(1 for r in reportes if r.dictamen == Dictamen.APROBADO_CON_OBSERVACIONES)
    rechazados = sum(1 for r in reportes if r.dictamen == Dictamen.RECHAZADO)

    rec_global.append(
        f"De {len(reportes)} empresas: {aprobados} aprobadas, "
        f"{con_obs} con observaciones, {rechazados} rechazadas"
    )

    if hallazgos_frecuentes:
        top = hallazgos_frecuentes[0]
        rec_global.append(
            f"Hallazgo más frecuente: {top['hallazgo']} "
            f"(en {top['frecuencia']}/{len(reportes)} empresas)"
        )

    if rechazados > 0:
        rec_global.append(
            "Priorizar la resolución de hallazgos críticos en empresas rechazadas"
        )

    return ResumenGlobal(
        fecha_analisis=datetime.now(),
        total_empresas=len(reportes),
        reportes=reportes,
        tabla_dictamenes=tabla_dictamenes,
        hallazgos_frecuentes=hallazgos_frecuentes,
        recomendaciones_globales=rec_global,
    )
