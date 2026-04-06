"""
Bloque 10 — Validación contra Portales Gubernamentales

Ejecuta validaciones automáticas contra portales oficiales mexicanos:
  V10.1  FIEL  → Portal de Certificados del SAT (vigencia de e.firma)
  V10.2  RFC   → Portal de Validación de RFC del SAT
  V10.3  INE   → Lista Nominal del INE (vigencia de identificación)

Este bloque es ASÍNCRONO (requiere Playwright) a diferencia de los
bloques 1-9 que son síncronos. Se invoca opcionalmente desde engine.py
cuando el usuario pasa --portales.

NOTA Windows: Playwright requiere ProactorEventLoop para lanzar Chromium
(asyncio.create_subprocess_exec). Uvicorn usa SelectorEventLoop, así que
este módulo ejecuta las validaciones en un hilo dedicado con su propio
ProactorEventLoop para evitar NotImplementedError.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys
from typing import Any

from ...models.schemas import ExpedienteEmpresa, Hallazgo, Severidad
from ..portal_validator.base import EstadoValidacion, ResultadoPortal
from ..portal_validator.fiel_validator import FIELValidator
from ..portal_validator.rfc_validator import RFCValidator
from ..portal_validator.ine_validator import INEValidator
from ..text_utils import get_valor_str

logger = logging.getLogger("cross_validation.bloque10")

BLOQUE = 10
BLOQUE_NOMBRE = "VALIDACIÓN EN PORTALES GUBERNAMENTALES"

# ── Mapeo de EstadoValidacion → pasa ─────────────────────────────

_ESTADO_PASA: dict[EstadoValidacion, bool | None] = {
    EstadoValidacion.VIGENTE: True,
    EstadoValidacion.ENCONTRADO: True,
    EstadoValidacion.VALIDO: True,
    EstadoValidacion.VENCIDO: False,
    EstadoValidacion.REVOCADO: False,
    EstadoValidacion.NO_ENCONTRADO: False,
    EstadoValidacion.INVALIDO: False,
    EstadoValidacion.ERROR: None,
    EstadoValidacion.CAPTCHA_NO_RESUELTO: None,
    EstadoValidacion.SIN_DATOS: None,
}

_ESTADO_SEVERIDAD: dict[EstadoValidacion, Severidad] = {
    EstadoValidacion.VIGENTE: Severidad.INFORMATIVA,
    EstadoValidacion.ENCONTRADO: Severidad.INFORMATIVA,
    EstadoValidacion.VALIDO: Severidad.INFORMATIVA,
    EstadoValidacion.VENCIDO: Severidad.CRITICA,
    EstadoValidacion.REVOCADO: Severidad.CRITICA,
    EstadoValidacion.NO_ENCONTRADO: Severidad.CRITICA,
    EstadoValidacion.INVALIDO: Severidad.CRITICA,
    EstadoValidacion.ERROR: Severidad.MEDIA,
    EstadoValidacion.CAPTCHA_NO_RESUELTO: Severidad.MEDIA,
    EstadoValidacion.SIN_DATOS: Severidad.MEDIA,
}

# Códigos con severidad fija por obligación regulatoria (DCG).
# Estos códigos NUNCA se rebajan a INFORMATIVA al pasar ni a MEDIA
# en caso de error/captcha.  Las DCG exigen identificar y verificar
# al cliente; un RFC no validado impide integrar el expediente.
_SEVERIDAD_OBLIGATORIA: dict[str, Severidad] = {
    "V10.2": Severidad.CRITICA,   # RFC — Portal SAT
}


def _resultado_a_hallazgo(
    resultado: ResultadoPortal,
    codigo: str,
    nombre: str,
) -> Hallazgo:
    """Convierte un ResultadoPortal en un Hallazgo del bloque 10."""
    estado = resultado.estado
    pasa = _ESTADO_PASA.get(estado)

    # Severidad fija por DCG prevalece sobre el mapeo dinámico
    if codigo in _SEVERIDAD_OBLIGATORIA:
        severidad = _SEVERIDAD_OBLIGATORIA[codigo]
    else:
        severidad = _ESTADO_SEVERIDAD.get(estado, Severidad.MEDIA)
        # Solo para códigos NO obligatorios: rebajar a INFORMATIVA si pasa
        if pasa is True:
            severidad = Severidad.INFORMATIVA

    # Si falló, agregar indicación de verificación manual
    _manual = (
        " ⚠️ SE REQUIERE VERIFICACIÓN MANUAL EN EL PORTAL"
        if pasa is None
        else ""
    )

    mensaje = (
        f"Portal {resultado.modulo}: {estado.value} — {resultado.detalle}{_manual}"
        if resultado.detalle
        else f"Portal {resultado.modulo}: {estado.value}{_manual}"
    )

    detalles: dict[str, Any] = {
        "modulo_portal": resultado.modulo,
        "identificador": resultado.identificador,
        "estado_portal": estado.value,
        "intentos": resultado.intentos,
    }
    if resultado.screenshot:
        detalles["screenshot"] = resultado.screenshot
    if resultado.datos_extra:
        detalles.update(resultado.datos_extra)

    return Hallazgo(
        codigo=codigo,
        nombre=nombre,
        bloque=BLOQUE,
        bloque_nombre=BLOQUE_NOMBRE,
        pasa=pasa,
        severidad=severidad,
        mensaje=mensaje,
        detalles=detalles,
    )


def _sin_datos_hallazgo(codigo: str, nombre: str, motivo: str) -> Hallazgo:
    """Genera un hallazgo SIN_DATOS cuando faltan datos para consultar un portal."""
    severidad = _SEVERIDAD_OBLIGATORIA.get(codigo, Severidad.MEDIA)
    return Hallazgo(
        codigo=codigo,
        nombre=nombre,
        bloque=BLOQUE,
        bloque_nombre=BLOQUE_NOMBRE,
        pasa=None,
        severidad=severidad,
        mensaje=f"Sin datos suficientes para consultar portal: {motivo} ⚠️ SE REQUIERE VERIFICACIÓN MANUAL EN EL PORTAL",
        detalles={"motivo": motivo},
    )


def _preparar_datos_fiel(exp: ExpedienteEmpresa) -> dict[str, Any] | None:
    """Extrae datos de FIEL del expediente."""
    fiel = exp.documentos.get("fiel") or exp.documentos.get("FIEL")
    if not fiel:
        return None
    return fiel


def _preparar_datos_rfc(exp: ExpedienteEmpresa) -> dict[str, Any]:
    """Prepara datos para validación de RFC."""
    csf = exp.documentos.get("constancia_situacion_fiscal") or exp.documentos.get("csf") or {}
    return {
        "rfc": exp.rfc,
        "razon_social": exp.razon_social,
        **csf,
    }


def _preparar_datos_ine(exp: ExpedienteEmpresa) -> dict[str, Any] | None:
    """Extrae datos de INE del expediente."""
    ine = (
        exp.documentos.get("ine")
        or exp.documentos.get("ine_front")
        or exp.documentos.get("INE")
    )
    if not ine:
        return None
    return ine


async def validar_portales(
    exp: ExpedienteEmpresa,
    *,
    modulos: set[str] | None = None,
    headless: bool = True,
) -> list[Hallazgo]:
    """
    Ejecuta las validaciones contra portales gubernamentales y devuelve
    una lista de Hallazgos del bloque 10.

    En Windows, Playwright requiere ProactorEventLoop para lanzar Chromium
    via asyncio.create_subprocess_exec. Uvicorn usa SelectorEventLoop, así
    que esta función detecta el tipo de loop y, si es necesario, ejecuta
    las validaciones en un hilo dedicado con su propio ProactorEventLoop.
    """
    # ── Detectar si necesitamos ProactorEventLoop ──
    _needs_thread = False
    if sys.platform == "win32":
        try:
            loop = asyncio.get_running_loop()
            if not isinstance(loop, asyncio.ProactorEventLoop):
                _needs_thread = True
                logger.info(
                    "Bloque 10: SelectorEventLoop detectado en Windows → "
                    "ejecutando portales en hilo con ProactorEventLoop"
                )
        except RuntimeError:
            pass

    if _needs_thread:
        # Ejecutar en un hilo dedicado con ProactorEventLoop
        return await asyncio.get_running_loop().run_in_executor(
            None,
            _run_portales_in_thread,
            exp, modulos, headless,
        )

    # Si ya estamos en ProactorEventLoop (o Linux/Mac), ejecutar directo
    return await _validar_portales_impl(exp, modulos=modulos, headless=headless)


def _run_portales_in_thread(
    exp: ExpedienteEmpresa,
    modulos: set[str] | None,
    headless: bool,
) -> list[Hallazgo]:
    """Wrapper síncrono que crea un ProactorEventLoop en este hilo."""
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            _validar_portales_impl(exp, modulos=modulos, headless=headless)
        )
    finally:
        loop.close()


async def _ejecutar_portal(
    validator,
    datos: dict[str, Any] | None,
    codigo: str,
    nombre: str,
    exp: ExpedienteEmpresa,
    headless: bool,
    sin_datos_motivo: str | None = None,
    *,
    browser=None,
) -> Hallazgo:
    """Helper genérico para ejecutar un portal y devolver un Hallazgo.

    Si ``browser`` se provee, el validador reutiliza ese browser en vez
    de lanzar uno propio (ahorra ~6-8s por portal).
    Si ``datos`` es ``None`` genera un hallazgo SIN_DATOS con ``sin_datos_motivo``.
    """
    if datos is None:
        return _sin_datos_hallazgo(codigo, nombre, sin_datos_motivo or "Sin datos")

    try:
        if browser is not None:
            await validator.usar_navegador_compartido(browser)
        else:
            await validator.iniciar_navegador(headless=headless)
        resultado = await validator.validar_con_reintentos(
            datos=datos,
            empresa=exp.razon_social,
            rfc=exp.rfc,
        )
        return _resultado_a_hallazgo(resultado, codigo, nombre)
    except Exception as e:
        err_msg = str(e) or f"{type(e).__name__} (sin detalle — verificar que Playwright esté instalado)"
        logger.error(f"Error en {nombre}: {err_msg}")
        severidad = _SEVERIDAD_OBLIGATORIA.get(codigo, Severidad.MEDIA)
        return Hallazgo(
            codigo=codigo,
            nombre=nombre,
            bloque=BLOQUE,
            bloque_nombre=BLOQUE_NOMBRE,
            pasa=None,
            severidad=severidad,
            mensaje=f"Error al consultar portal {nombre.split('—')[0].strip()}: {err_msg} ⚠️ SE REQUIERE VERIFICACIÓN MANUAL EN EL PORTAL",
            detalles={"error": err_msg, "modulo_portal": codigo.split(".")[-1]},
        )
    finally:
        await validator.cerrar_navegador()


async def _validar_portales_impl(
    exp: ExpedienteEmpresa,
    *,
    modulos: set[str] | None = None,
    headless: bool = True,
) -> list[Hallazgo]:
    """Implementación real de la validación de portales.

    Lanza UN solo browser Chromium y lo comparte entre los 3 portales
    (cada uno crea su propio BrowserContext) para ahorrar ~12-16s.
    """
    from playwright.async_api import async_playwright

    mods = modulos or {"fiel", "rfc", "ine"}
    hallazgos: list[Hallazgo] = []

    logger.info(
        f"Bloque 10 — Portales gubernamentales para {exp.razon_social} "
        f"({exp.rfc}) — Módulos: {', '.join(sorted(mods))}"
    )

    _headless = headless
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=_headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    try:
        # ── Lanzar portales en paralelo con asyncio.gather ──
        tareas: list[asyncio.Task] = []

        if "fiel" in mods:
            datos_fiel = _preparar_datos_fiel(exp)
            tareas.append(asyncio.ensure_future(_ejecutar_portal(
                FIELValidator(), datos_fiel, "V10.1", "FIEL — Portal SAT",
                exp, _headless,
                sin_datos_motivo="No se encontró documento FIEL en el expediente",
                browser=browser,
            )))

        if "rfc" in mods:
            datos_rfc = _preparar_datos_rfc(exp)
            tareas.append(asyncio.ensure_future(_ejecutar_portal(
                RFCValidator(), datos_rfc, "V10.2", "RFC — Portal SAT",
                exp, _headless,
                browser=browser,
            )))

        if "ine" in mods:
            datos_ine = _preparar_datos_ine(exp)
            tareas.append(asyncio.ensure_future(_ejecutar_portal(
                INEValidator(), datos_ine, "V10.3", "INE — Lista Nominal",
                exp, _headless,
                sin_datos_motivo="No se encontró documento INE en el expediente",
                browser=browser,
            )))

        hallazgos = list(await asyncio.gather(*tareas))

    finally:
        await browser.close()
        await pw.stop()

    logger.info(
        f"Bloque 10 completado — {len(hallazgos)} hallazgos: "
        + ", ".join(f"{h.codigo}={'✅' if h.pasa else '❌' if h.pasa is False else '⚪'}" for h in hallazgos)
    )

    return hallazgos
