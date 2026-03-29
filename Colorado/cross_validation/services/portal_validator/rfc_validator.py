"""
Módulo 3 — Validación de RFC
Portal: https://agsc.siat.sat.gob.mx/PTSC/ValidaRFC/index.jsf

IDs JSF confirmados por diagnóstico:
  formMain:captchaInput     — Input para texto del CAPTCHA (maxLength=5)
  formMain:j_idt59          — Botón "Aceptar"
  captchaSession            — Imagen del CAPTCHA (img id)
  formMain:captcha_img2     — Imagen para recargar CAPTCHA

FLUJO DE 2 PASOS:
  Paso 1: Página inicial solo tiene CAPTCHA → llenar y dar clic Aceptar
  Paso 2: Se revela el campo RFC → llenar y enviar → leer resultado
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

# ── Selectores JSF exactos ──
_CAPTCHA_IMG = '#captchaSession'
_CAPTCHA_INPUT = '[id="formMain:captchaInput"]'
_BTN_ACEPTAR = '[id="formMain:j_idt59"]'
_RFC_INPUT = '[id="formMain:valRFC"]'
_BTN_CONSULTAR = '[id="formMain:consulta"]'


class RFCValidator(PortalValidatorBase):
    """Validador de RFC ante el portal del SAT."""

    portal_nombre = "RFC"
    portal_url = "https://agsc.siat.sat.gob.mx/PTSC/ValidaRFC/index.jsf"

    async def _ejecutar_validacion(
        self,
        datos: dict[str, Any],
        empresa: str,
        rfc: str,
    ) -> ResultadoPortal:
        """Consulta el portal del SAT para verificar un RFC (flujo 2 pasos)."""

        rfc_limpio = rfc.strip().upper() if rfc else ""

        if not rfc_limpio or len(rfc_limpio) < 12:
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=rfc_limpio or "SIN_RFC",
                estado=EstadoValidacion.SIN_DATOS,
                detalle="RFC ausente o con formato inválido",
            )

        identificador = rfc_limpio
        self.logger.info(f"Consultando RFC — {empresa} | RFC: {rfc_limpio}")

        # ══════════════════════════════════════════════════════════
        #  PASO 1: Resolver CAPTCHA en la página inicial
        # ══════════════════════════════════════════════════════════
        response = await self.page.goto(self.portal_url, wait_until="networkidle")
        await self.delay_aleatorio()

        # ── Detectar portal caído ──
        if response and response.status >= 500:
            screenshot = await self.capturar_screenshot(f"rfc_http{response.status}_{rfc_limpio}")
            self.logger.warning(f"RFC portal caído: HTTP {response.status}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ERROR,
                detalle=f"Portal SAT no disponible (HTTP {response.status}). Reintentar más tarde.",
                screenshot=screenshot,
                datos_extra={"http_status": response.status},
            )

        # Resolver CAPTCHA con selectores exactos
        captcha_resuelto = await resolver_captcha(
            self.page,
            captcha_img_selector=_CAPTCHA_IMG,
            captcha_input_selector=_CAPTCHA_INPUT,
            strategy=CAPTCHA_STRATEGY,
        )

        if not captcha_resuelto:
            screenshot = await self.capturar_screenshot(f"rfc_captcha_{rfc_limpio}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                detalle="No se pudo resolver el CAPTCHA del portal SAT RFC",
                screenshot=screenshot,
            )

        # Hacer clic en Aceptar
        try:
            btn = await self.page.query_selector(_BTN_ACEPTAR)
            if btn:
                await btn.click()
            else:
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            self.logger.warning(f"Error enviando CAPTCHA: {e}")

        # ══════════════════════════════════════════════════════════
        #  PASO 2: Llenar RFC en la página que se revela
        # ══════════════════════════════════════════════════════════
        # Después del CAPTCHA, puede aparecer:
        #   a) Un campo de texto para RFC
        #   b) Un mensaje de error (CAPTCHA incorrecto)
        #   c) La misma página (CAPTCHA no validado → recarga silenciosa)

        # Verificar si el CAPTCHA fue rechazado (explícito o recarga silenciosa)
        page_text_check = await self.page.inner_text("body")
        page_text_check_upper = page_text_check.upper()

        # Detección explícita de rechazo
        if any(kw in page_text_check_upper for kw in [
            "CÓDIGO INCORRECTO", "CAPTCHA INCORRECTO", "INTENTE NUEVAMENTE",
            "IMAGEN NO COINCIDE", "CÓDIGO NO COINCIDE",
            "NO ES CORRECTO",  # SAT: "El código que escribió no es correcto"
            "INTÉNTELO NUEVAMENTE",  # SAT: "inténtelo nuevamente"
        ]):
            screenshot = await self.capturar_screenshot(f"rfc_captcha_fail_{rfc_limpio}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                detalle="CAPTCHA incorrecto. El portal rechazó el texto ingresado.",
                screenshot=screenshot,
            )

        # Detección de recarga silenciosa: si el CAPTCHA sigue visible
        # significa que el portal rechazó y recargó la misma página
        captcha_sigue = await self.page.query_selector(_CAPTCHA_IMG)
        captcha_input_sigue = await self.page.query_selector(_CAPTCHA_INPUT)
        if captcha_sigue and captcha_input_sigue:
            # Verificar si el input de CAPTCHA está vacío (se recargó)
            val_captcha = await captcha_input_sigue.get_attribute("value") or ""
            if not val_captcha.strip():
                screenshot = await self.capturar_screenshot(f"rfc_captcha_reload_{rfc_limpio}")
                return ResultadoPortal(
                    modulo=self.portal_nombre,
                    empresa=empresa,
                    rfc=rfc,
                    identificador=identificador,
                    estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                    detalle="CAPTCHA incorrecto (página recargó). Se reintentará.",
                    screenshot=screenshot,
                )

        # Buscar campo de RFC que ahora debería ser visible
        try:
            # Usar selector exacto del campo RFC del SAT
            rfc_input = await self.page.wait_for_selector(
                _RFC_INPUT, timeout=10000,
            )
            if not rfc_input:
                # Fallback: buscar cualquier input visible con atributos de RFC
                rfc_input = await self.page.query_selector(
                    'input[type="text"]:not([id="formMain:captchaInput"])'
                )

            if rfc_input:
                await rfc_input.fill(rfc_limpio)
                self.logger.info(f"RFC ingresado en paso 2: {rfc_limpio}")
            else:
                self.logger.info("No se encontró campo de RFC en paso 2, verificando resultado...")

        except Exception as e:
            self.logger.warning(f"Error buscando campo RFC en paso 2: {e}")

        await self.delay_aleatorio()

        # Hacer clic en «Consultar RFC» (selector exacto)
        try:
            btn_consultar = await self.page.query_selector(_BTN_CONSULTAR)
            if btn_consultar and await btn_consultar.is_visible():
                await btn_consultar.click()
                self.logger.info("Botón 'Consultar RFC' clickeado")
            else:
                # Fallback: buscar por texto
                fallback = await self.page.query_selector(
                    'button:has-text("Consultar")'
                )
                if fallback:
                    await fallback.click()
                    self.logger.info("Botón fallback 'Consultar' clickeado")
                else:
                    await self.page.keyboard.press("Enter")
                    self.logger.info("No se encontró botón Consultar, Enter presionado")

            await self.page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)

        except Exception as e:
            self.logger.warning(f"Error en submit paso 2: {e}")

        # ── Capturar screenshot del resultado ──
        screenshot = await self.capturar_screenshot(f"rfc_resultado_{rfc_limpio}")

        # ── Interpretar resultado ──
        page_text = await self.page.inner_text("body")
        page_text_upper = page_text.upper()

        # DEBUG: dump full page text for diagnosing result parsing issues
        self.logger.debug(f"RFC resultado page_text (len={len(page_text)}):\n{page_text[:2000]}")

        resultado_datos: dict[str, Any] = {"rfc_consultado": rfc_limpio}

        # Extraer razón social si aparece
        razon = self._extraer_razon_social(page_text)
        if razon:
            resultado_datos["razon_social_portal"] = razon

        # Extraer régimen fiscal si aparece
        regimen = self._extraer_regimen(page_text)
        if regimen:
            resultado_datos["regimen_fiscal"] = regimen

        # ── RFC válido y registrado ──
        if any(kw in page_text_upper for kw in [
            "RFC VÁLIDO", "RFC VALIDO",
            "REGISTRADO EN EL PADRÓN", "REGISTRADO EN EL PADRON",
            "INSCRITO", "ES UN RFC VÁLIDO", "VÁLIDO Y ACTIVO",
            "ES VÁLIDO", "ESTÁ REGISTRADO",
            "SUSCEPTIBLE DE RECIBIR FACTURAS",  # SAT: "RFC válido, y susceptible de recibir facturas"
        ]):
            # Extraer mensaje exacto del SAT si existe
            msg_elem = await self.page.query_selector(
                '[id="formMain:messageConsultaRFCExito"] .ui-messages-info-summary'
            )
            msg_sat = ""
            if msg_elem:
                msg_sat = (await msg_elem.inner_text()).strip()
            detalle = msg_sat or f"RFC {rfc_limpio} es válido y registrado ante el SAT"
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.VALIDO,
                detalle=detalle,
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        # ── RFC con formato correcto pero no registrado ──
        if any(kw in page_text_upper for kw in [
            "NO REGISTRADO", "NO INSCRITO", "NO SE ENCUENTRA",
            "NO EXISTE EN EL PADRÓN", "NO EXISTE EN EL PADRON",
        ]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.NO_ENCONTRADO,
                detalle=f"RFC {rfc_limpio} tiene formato correcto pero NO está registrado",
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        # ── RFC con formato incorrecto ──
        if any(kw in page_text_upper for kw in [
            "NO VÁLIDO", "NO VALIDO", "FORMATO INCORRECTO",
            "ESTRUCTURA INCORRECTA", "INVÁLIDO", "INVALIDO",
        ]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.INVALIDO,
                detalle=f"RFC {rfc_limpio} tiene formato inválido",
                screenshot=screenshot,
                datos_extra=resultado_datos,
            )

        # ── Error o respuesta no reconocida ──
        current_url = self.page.url
        self.logger.warning(
            f"RFC: respuesta no reconocida. URL={current_url} "
            f"page_text_len={len(page_text)}"
        )
        fragmento = page_text[:500].replace("\n", " ").strip()
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
    def _extraer_razon_social(texto: str) -> str:
        """Intenta extraer la razón social de la respuesta del portal."""
        patrones = [
            r"raz[oó]n\s+social[:\s]*(.+?)(?:\n|$)",
            r"nombre[:\s]*(.+?)(?:\n|$)",
            r"denominaci[oó]n[:\s]*(.+?)(?:\n|$)",
        ]
        for patron in patrones:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if len(val) > 3:
                    return val
        return ""

    @staticmethod
    def _extraer_regimen(texto: str) -> str:
        """Intenta extraer el régimen fiscal de la respuesta."""
        patrones = [
            r"r[eé]gimen[:\s]*(.+?)(?:\n|$)",
            r"tipo\s+de\s+contribuyente[:\s]*(.+?)(?:\n|$)",
        ]
        for patron in patrones:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if len(val) > 3:
                    return val
        return ""
