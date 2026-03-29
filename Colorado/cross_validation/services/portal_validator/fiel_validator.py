"""
Módulo 2 — Validación de FIEL (Certificado de Firma Electrónica)
Portal: https://portalsat.plataforma.sat.gob.mx/RecuperacionDeCertificados/
        faces/consultaCertificados.xhtml

IDs JSF del formulario (confirmados por diagnóstico):
  consultaCertificados:entradaRFC        — RFC (maxLength=13)
  consultaCertificados:todos:0           — Radio "todos" (todos los certificados)
  consultaCertificados:todos:1           — Radio "ultimo" (solo el más reciente)
  consultaCertificados:botonRFC          — Botón Buscar por RFC
  consultaCertificados:numeroDeSerie     — Número de serie (maxLength=20)
  consultaCertificados:botonNumSerie     — Botón Buscar por serie
  consultaCertificados:verCaptchaRFC     — Input CAPTCHA (myFaces)
  La imagen CAPTCHA se genera dinámicamente (myFaces CAPTCHARenderer).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from .base import (
    EstadoValidacion,
    PortalValidatorBase,
    ResultadoPortal,
    logger,
    CAPTCHA_STRATEGY,
)
from .captcha import resolver_captcha
from ..text_utils import get_valor_str

# ── Selectores JSF exactos (usar attr selector para escapar colons) ──
_RFC_INPUT = '[id="consultaCertificados:entradaRFC"]'
_SERIE_INPUT = '[id="consultaCertificados:numeroDeSerie"]'
_CAPTCHA_IMG = 'img[src*="CAPTCHARenderer"], img[src*="captcha"], img[src*="myFaces"]'
_CAPTCHA_INPUT = '[id="consultaCertificados:verCaptchaRFC"]'
_BTN_BUSCAR_RFC = '[id="consultaCertificados:botonRFC"]'
_BTN_BUSCAR_SERIE = '[id="consultaCertificados:botonNumSerie"]'
_RADIO_TODOS = '[id="consultaCertificados:todos:0"]'
_RADIO_ULTIMO = '[id="consultaCertificados:todos:1"]'


class FIELValidator(PortalValidatorBase):
    """Validador de FIEL contra el portal de Certificados del SAT."""

    portal_nombre = "FIEL"
    portal_url = (
        "https://portalsat.plataforma.sat.gob.mx/"
        "RecuperacionDeCertificados/faces/consultaCertificados.xhtml"
    )

    async def _ejecutar_validacion(
        self,
        datos: dict[str, Any],
        empresa: str,
        rfc: str,
    ) -> ResultadoPortal:
        """Ejecuta la consulta contra el portal de certificados del SAT."""

        # ── Extraer datos de FIEL ──
        num_serie = get_valor_str(datos, "numero_serie_certificado")
        rfc_fiel = get_valor_str(datos, "rfc") or rfc
        vigencia_hasta = get_valor_str(datos, "vigencia_hasta")

        if not num_serie:
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador="SIN_CERTIFICADO",
                estado=EstadoValidacion.SIN_DATOS,
                detalle="No se encontró número de serie del certificado FIEL",
            )

        # Limpiar número de serie (solo dígitos, 20 chars)
        num_serie_limpio = re.sub(r"\D", "", num_serie)[:20]
        identificador = f"Serie:{num_serie_limpio}"

        self.logger.info(
            f"Consultando FIEL — {empresa} | Serie: {num_serie_limpio} | "
            f"RFC: {rfc_fiel}"
        )

        # ── Navegar al portal ──
        response = await self.page.goto(self.portal_url, wait_until="networkidle")
        await self.delay_aleatorio()

        # ── Detectar portal caído (503, 500, etc.) ──
        if response and response.status >= 500:
            page_text = await self.page.inner_text("body")
            screenshot = await self.capturar_screenshot(f"fiel_http{response.status}_{rfc}")
            msg = (
                f"Portal SAT no disponible (HTTP {response.status}). "
                f"Reintentar más tarde."
            )
            if "service unavailable" in page_text.lower() or "maintenance" in page_text.lower():
                msg = (
                    f"Portal SAT en mantenimiento (HTTP {response.status}). "
                    f"El servicio de certificados del SAT está temporalmente fuera de servicio."
                )
            self.logger.warning(f"FIEL portal caído: HTTP {response.status}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ERROR,
                detalle=msg,
                screenshot=screenshot,
                datos_extra={"http_status": response.status},
            )

        # ── Llenar formulario con IDs JSF exactos ──
        try:
            # Estrategia: buscar por número de serie (más preciso)
            serie_input = await self.page.query_selector(_SERIE_INPUT)
            if serie_input:
                await serie_input.fill(num_serie_limpio)
                self.logger.info(f"Número de serie ingresado: {num_serie_limpio}")
                usar_busqueda_serie = True
            else:
                # Fallback: buscar por RFC
                rfc_input = await self.page.query_selector(_RFC_INPUT)
                if rfc_input:
                    await rfc_input.fill(rfc_fiel.strip())
                    # Seleccionar radio "ultimo" para obtener el más reciente
                    radio = await self.page.query_selector(_RADIO_ULTIMO)
                    if radio:
                        await radio.click()
                    self.logger.info(f"RFC ingresado: {rfc_fiel}")
                    usar_busqueda_serie = False
                else:
                    raise RuntimeError("No se encontró campo de serie ni de RFC")

        except Exception as e:
            self.logger.warning(f"Error llenando formulario FIEL: {e}")
            screenshot = await self.capturar_screenshot(f"fiel_form_error_{rfc}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ERROR,
                detalle=f"Error llenando formulario: {e}",
                screenshot=screenshot,
            )

        # ── Resolver CAPTCHA (myFaces CAPTCHA) ──
        # El input del CAPTCHA es: consultaCertificados:verCaptchaRFC
        # La imagen se genera via myFaces CAPTCHARenderer
        # Intentar selectores específicos para la imagen CAPTCHA
        captcha_img_selectors = [
            'img[src*="CAPTCHARenderer"]',
            'img[src*="captcha"]',
            'img[src*="myFaces"]',
            'img[src*="CAPTCHA"]',
        ]
        captcha_img_sel = _CAPTCHA_IMG  # default compuesto

        # Buscar el selector que encuentre un elemento válido con contenido
        for sel in captcha_img_selectors:
            elem = await self.page.query_selector(sel)
            if elem:
                bbox = await elem.bounding_box()
                if bbox and bbox["width"] > 20 and bbox["height"] > 10:
                    captcha_img_sel = sel
                    self.logger.info(
                        f"CAPTCHA imagen encontrada con selector: {sel} "
                        f"({bbox['width']:.0f}x{bbox['height']:.0f})"
                    )
                    break

        # ── Guardar imagen CAPTCHA para diagnóstico ──
        try:
            from .base import SCREENSHOT_DIR
            from datetime import datetime as _dt
            captcha_elem = await self.page.query_selector(captcha_img_sel)
            if captcha_elem:
                captcha_img_bytes = await captcha_elem.screenshot()
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                captcha_path = SCREENSHOT_DIR / f"CAPTCHA_fiel_{rfc}_{ts}.png"
                captcha_path.write_bytes(captcha_img_bytes)
                self.logger.info(f"[DIAG] CAPTCHA guardado: {captcha_path}")
        except Exception as e:
            self.logger.debug(f"No se pudo guardar CAPTCHA: {e}")

        captcha_resuelto = await resolver_captcha(
            self.page,
            captcha_img_selector=captcha_img_sel,
            captcha_input_selector=_CAPTCHA_INPUT,
            strategy=CAPTCHA_STRATEGY,
        )

        if not captcha_resuelto:
            screenshot = await self.capturar_screenshot(f"fiel_captcha_{rfc}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                detalle="No se pudo resolver el CAPTCHA del portal SAT",
                screenshot=screenshot,
            )

        # ── Enviar consulta (botón correcto según tipo de búsqueda) ──
        try:
            btn_selector = _BTN_BUSCAR_SERIE if usar_busqueda_serie else _BTN_BUSCAR_RFC
            submit_btn = await self.page.query_selector(btn_selector)
            if submit_btn:
                await submit_btn.click()
            else:
                self.logger.warning(f"Botón no encontrado: {btn_selector}, usando Enter")
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(2)

        except Exception as e:
            self.logger.warning(f"Error al enviar consulta FIEL: {e}")

        # ── Leer resultado ──
        # NOTA: En JSF la página no navega — el formulario (incl. CAPTCHA input)
        # sigue visible incluso tras un submit exitoso. Por eso verificamos
        # resultados PRIMERO, y solo si no hay resultados, verificamos recarga.
        screenshot = await self.capturar_screenshot(f"fiel_resultado_{rfc}")
        page_text = await self.page.inner_text("body")
        page_text_upper = page_text.upper()

        # ── Diagnóstico: loguear URL actual y fragmento de texto ──
        current_url = self.page.url
        self.logger.info(
            f"[DIAG] URL post-submit: {current_url}"
        )
        page_fragment = page_text[:500].replace("\n", " | ").strip()
        self.logger.info(f"[DIAG] Texto página (500 chars): {page_fragment}")

        # Extraer estado del certificado
        resultado_datos: dict[str, Any] = {
            "numero_serie": num_serie_limpio,
            "vigencia_local": vigencia_hasta,
        }

        # ── Detectar estado ──
        # Primero: verificar mensajes CAPTCHA explícitos del portal
        if any(kw in page_text_upper for kw in [
            "CÓDIGO INCORRECTO", "CODIGO INCORRECTO",
            "INTÉNTELO NUEVAMENTE", "INTENTELO NUEVAMENTE",
            "CAPTCHA INCORRECTO",
        ]):
            self.logger.info("[DIAG] Portal reportó CAPTCHA incorrecto explícitamente")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                detalle="CAPTCHA incorrecto — el portal rechazó el texto.",
                screenshot=screenshot,
            )

        if any(kw in page_text_upper for kw in ["VIGENTE", "ACTIVO"]):
            # Intentar extraer fecha de vigencia del portal
            fecha_portal = self._extraer_fecha_vigencia(page_text)
            if fecha_portal:
                resultado_datos["vigencia_portal"] = fecha_portal

            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.VIGENTE,
                detalle=(
                    f"Certificado FIEL vigente. "
                    f"Serie: {num_serie_limpio}"
                    + (f" | Vigencia portal: {fecha_portal}" if fecha_portal else "")
                ),
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        if any(kw in page_text_upper for kw in ["REVOCADO", "CANCELADO"]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.REVOCADO,
                detalle=f"Certificado FIEL REVOCADO. Serie: {num_serie_limpio}",
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        if any(kw in page_text_upper for kw in ["VENCIDO", "EXPIRADO", "CADUC"]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.VENCIDO,
                detalle=f"Certificado FIEL VENCIDO. Serie: {num_serie_limpio}",
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        if any(kw in page_text_upper for kw in [
            "NO SE ENCONTR", "NO EXISTE", "SIN RESULTADO",
            "NO SE LOCALIZ", "DATO NO ENCONTRADO",
        ]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.NO_ENCONTRADO,
                detalle=f"Certificado FIEL no encontrado en el SAT. Serie: {num_serie_limpio}",
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        # ── Verificar si el CAPTCHA fue rechazado (recarga silenciosa) ──
        # Solo llegamos aquí si no se detectó ningún resultado arriba.
        # En JSF, CAPTCHA rechazado → la página recarga con input vacío.
        captcha_input_post = await self.page.query_selector(_CAPTCHA_INPUT)
        if captcha_input_post:
            val_post = await captcha_input_post.get_attribute("value") or ""
            if not val_post.strip():
                return ResultadoPortal(
                    modulo=self.portal_nombre,
                    empresa=empresa,
                    rfc=rfc,
                    identificador=identificador,
                    estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                    detalle="CAPTCHA incorrecto (página recargó). Se reintentará.",
                    screenshot=screenshot,
                )

        # No se pudo determinar
        fragmento = page_text[:300].replace("\n", " ").strip()
        return ResultadoPortal(
            modulo=self.portal_nombre,
            empresa=empresa,
            rfc=rfc,
            identificador=identificador,
            estado=EstadoValidacion.ERROR,
            detalle=f"No se pudo interpretar respuesta. Fragmento: {fragmento[:150]}",
            screenshot=screenshot,
            datos_extra=resultado_datos,
        )

    @staticmethod
    def _extraer_fecha_vigencia(texto: str) -> str:
        """Intenta extraer una fecha de vigencia del texto de la página."""
        # Patrones comunes: "Vigencia: 15/05/2027", "Válido hasta: 2027-05-15"
        patrones = [
            r"vigencia[:\s]*(\d{2}/\d{2}/\d{4})",
            r"vigencia[:\s]*(\d{4}-\d{2}-\d{2})",
            r"v[áa]lido\s+hasta[:\s]*(\d{2}/\d{2}/\d{4})",
            r"v[áa]lido\s+hasta[:\s]*(\d{4}-\d{2}-\d{2})",
            r"fecha\s+de\s+fin[:\s]*(\d{2}/\d{2}/\d{4})",
            r"fecha\s+de\s+fin[:\s]*(\d{4}-\d{2}-\d{2})",
        ]
        for patron in patrones:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""
