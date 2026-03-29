"""
Módulo 1 — Validación de INE (Lista Nominal)
Portal: https://listanominal.ine.mx/scpln/

El portal tiene 4 formularios para distintos modelos de credencial:
  Modelo E/F/G/H (vigentes):  CIC (9 dígitos)  + Identificador del Ciudadano (9)
  Modelo D       (2013):      CIC (9 dígitos)  + OCR (13)
  Modelo A/B/C   (no vigentes): Clave Elector (18) + Emisión (2) + OCR (13)
  Robo/Extravío:              Folio de reporte (18)

Todos usan Google reCAPTCHA v2 ("No soy un robot").

Campos que Dakota extrae de la INE:
  - DocumentNumber  (podría ser CIC 9 dígitos o clave de elector 18 chars)
  - Seccion, AnioRegistro, Emision
  - curp, nombre_completo
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from .base import (
    EstadoValidacion,
    PortalValidatorBase,
    ResultadoPortal,
    logger,
    CAPTCHA_STRATEGY,
)
from ..text_utils import get_valor_str


# Selectores JSF (colons escapados con backslash en CSS, usamos attr selector)
# Modelo E/F/G/H — posición Y≈1230
_SEL_CIC_EFG = '#cic'                      # maxLength=9
_SEL_ID_CIUDADANO = '#idCiudadano'          # maxLength=9

# Modelo D — posición Y≈1832
# Comparten id "cic" y "ocr" con otros modelos; están en otra sección
# ⇒ usamos nth-match

# Modelo A/B/C — posición Y≈2434
_SEL_CLAVE_ELECTOR = '#claveElector'        # maxLength=18
_SEL_NUM_EMISION = '#numeroEmision'         # maxLength=2
_SEL_OCR = '#ocr'                           # maxLength=13


# Tiempo máximo (segundos) para esperar que stealth pase Cloudflare solo
_CF_STEALTH_WAIT = int(os.getenv("PORTAL_CF_STEALTH_WAIT", "15"))


class INEValidator(PortalValidatorBase):
    """Validador de INE contra la Lista Nominal del INE."""

    portal_nombre = "INE"
    portal_url = "https://listanominal.ine.mx/scpln/"

    # reCAPTCHA v2 sitekey (extraída de los iframes del portal)
    _RECAPTCHA_SITEKEY = "6LdAe1sUAAAAACrdhVFHK5KmZ5TA8ZJ0iWQ6i64b"

    # ── Cloudflare Turnstile handling ─────────────────────────────

    async def _detectar_cloudflare(self) -> bool:
        """Devuelve True si la página actual es el challenge de Cloudflare Turnstile."""
        try:
            # Verificar presencia de elementos específicos de Turnstile
            # (no solo texto, para evitar falsos positivos)
            has_turnstile = await self.page.evaluate("""
                () => {
                    // Buscar iframe de Cloudflare challenges
                    const cfIframes = document.querySelectorAll(
                        'iframe[src*="challenges.cloudflare.com"]'
                    );
                    if (cfIframes.length > 0) return true;

                    // Buscar widget Turnstile
                    const widget = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
                    if (widget) return true;

                    // Buscar texto específico de challenge page
                    const body = document.body.innerText.toLowerCase();
                    const isChallenge = (
                        body.includes('verifica que eres un ser humano') &&
                        body.includes('cloudflare')
                    );
                    return isChallenge;
                }
            """)
            return bool(has_turnstile)
        except Exception:
            return False

    async def _superar_cloudflare(self) -> bool:
        """
        Intenta superar Cloudflare Turnstile con playwright-stealth.

        Espera hasta _CF_STEALTH_WAIT segundos a que el navegador
        pase el challenge automáticamente.

        Returns:
            True si se superó Cloudflare.
        """
        self.logger.info(
            f"Esperando que stealth supere Cloudflare ({_CF_STEALTH_WAIT}s)..."
        )

        for tick in range(_CF_STEALTH_WAIT):
            await asyncio.sleep(1)
            if not await self._detectar_cloudflare():
                self.logger.info(f"Stealth superó Cloudflare en {tick + 1}s ✓")
                return True

        self.logger.warning("Stealth no pudo superar Cloudflare Turnstile")
        return False

    async def _navegar_portal(self, headless_flag: bool) -> str | None:
        """
        Navega al portal INE manejando Cloudflare Turnstile automáticamente.

        Usa playwright-stealth para intentar superar el challenge.

        Returns:
            None si se accedió correctamente.
            str con mensaje de error si Cloudflare bloqueó.
        """
        # Usar domcontentloaded para no quedar atrapado en networkidle
        await self.page.goto(
            self.portal_url, wait_until="domcontentloaded", timeout=30000
        )
        await asyncio.sleep(2)  # Dar tiempo al JS de Cloudflare

        if await self._detectar_cloudflare():
            self.logger.info("Cloudflare Turnstile detectado en portal INE")
            ok = await self._superar_cloudflare()
            if not ok:
                return (
                    "Cloudflare Turnstile bloqueó el acceso al portal INE. "
                    "Stealth no pudo resolver el challenge."
                )
            # Esperar a que la página real cargue completamente
            await asyncio.sleep(3)

        return None

    async def _ejecutar_validacion(
        self,
        datos: dict[str, Any],
        empresa: str,
        rfc: str,
    ) -> ResultadoPortal:
        """Ejecuta la consulta contra el portal de Lista Nominal."""

        # ── Extraer datos de la INE ──
        doc_number = get_valor_str(datos, "DocumentNumber")
        seccion = get_valor_str(datos, "Seccion")
        emision = get_valor_str(datos, "Emision") or get_valor_str(datos, "AnioRegistro")
        curp = get_valor_str(datos, "curp")
        nombre = get_valor_str(datos, "nombre_completo")
        # Campos adicionales que Dakota podría tener
        cic = get_valor_str(datos, "CIC") or get_valor_str(datos, "cic")
        id_ciudadano = get_valor_str(datos, "IdCiudadano") or get_valor_str(datos, "id_ciudadano")
        ocr = get_valor_str(datos, "OCR") or get_valor_str(datos, "ocr")
        clave_elector = get_valor_str(datos, "ClaveElector") or get_valor_str(datos, "clave_elector")

        if not doc_number and not cic and not clave_elector:
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=curp or "SIN_DATOS",
                estado=EstadoValidacion.SIN_DATOS,
                detalle="No se encontró CIC, Clave de Elector ni DocumentNumber en la INE",
            )

        # ── Determinar qué modelo usar ──
        modelo, campos = self._determinar_modelo(
            doc_number, cic, id_ciudadano, ocr, clave_elector, emision,
        )

        # Sin datos suficientes para consultar el portal
        if modelo == "SIN_DATOS":
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador="SIN_DATOS",
                estado=EstadoValidacion.SIN_DATOS,
                detalle="No se encontraron datos suficientes (CIC, Clave de Elector ni DocumentNumber) para consultar el portal INE",
            )

        identificador = f"{modelo} | {campos.get('id_campo', doc_number or cic or clave_elector)}"
        self.logger.info(
            f"Consultando INE — {nombre} | Modelo: {modelo} | "
            f"Datos: {campos}"
        )

        # ── Navegar al portal (con manejo de Cloudflare) ──
        _headless_flag = getattr(self, '_headless_flag', True)

        cf_error = await self._navegar_portal(headless_flag=_headless_flag)
        if cf_error:
            screenshot = await self.capturar_screenshot(f"ine_cloudflare_{rfc}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ERROR,
                detalle=cf_error,
                screenshot=screenshot,
            )
        await self.delay_aleatorio()

        # ── Llenar formulario según modelo ──
        try:
            if modelo == "E-H":
                await self._llenar_modelo_efgh(campos)
            elif modelo == "D":
                await self._llenar_modelo_d(campos)
            elif modelo == "A-C":
                await self._llenar_modelo_abc(campos)
            else:
                raise RuntimeError(f"Modelo no soportado: {modelo}")

        except Exception as e:
            self.logger.warning(f"Error llenando formulario INE ({modelo}): {e}")
            screenshot = await self.capturar_screenshot(f"ine_form_error_{rfc}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ERROR,
                detalle=f"Error llenando formulario modelo {modelo}: {e}",
                screenshot=screenshot,
            )

        # ── Resolver reCAPTCHA v2 ──
        recaptcha_ok = await self._resolver_recaptcha(modelo)

        if not recaptcha_ok:
            screenshot = await self.capturar_screenshot(f"ine_recaptcha_{rfc}")
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.CAPTCHA_NO_RESUELTO,
                detalle=(
                    "No se pudo resolver el reCAPTCHA del portal INE. "
                    "Usa --visible para resolverlo manualmente."
                ),
                screenshot=screenshot,
            )

        # ── Enviar consulta ──
        try:
            # Cada sección tiene su propio botón Consultar
            buttons = await self.page.query_selector_all('button[type="submit"]')
            btn_index = {"E-H": 0, "D": 1, "A-C": 2}.get(modelo, 0)
            if btn_index < len(buttons):
                await buttons[btn_index].click()
            else:
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_load_state("networkidle", timeout=45000)
            await asyncio.sleep(3)

        except Exception as e:
            self.logger.warning(f"Error al enviar consulta INE: {e}")

        # ── Leer resultado ──
        screenshot = await self.capturar_screenshot(f"ine_resultado_{rfc}")
        page_text = await self.page.inner_text("body")
        page_text_upper = page_text.upper()

        if any(kw in page_text_upper for kw in [
            "ENCONTRADO EN LA LISTA NOMINAL",
            "SÍ SE ENCUENTRA", "SI SE ENCUENTRA",
            "DATO LOCALIZADO", "VIGENTE",
            "CREDENCIAL VIGENTE",
        ]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.ENCONTRADO,
                detalle=f"INE de {nombre} encontrada en la Lista Nominal",
                screenshot=screenshot,
                datos_extra={"nombre": nombre, "curp": curp, "modelo": modelo},
            )

        if any(kw in page_text_upper for kw in [
            "NO SE ENCONTR", "NO ENCONTRADO", "NO FUE LOCALIZADO",
            "SIN RESULTADOS", "NO APARECE", "NO VIGENTE",
            "NO SE HA ENCONTRADO",
        ]):
            return ResultadoPortal(
                modulo=self.portal_nombre,
                empresa=empresa,
                rfc=rfc,
                identificador=identificador,
                estado=EstadoValidacion.NO_ENCONTRADO,
                detalle=f"INE de {nombre} NO encontrada en la Lista Nominal",
                screenshot=screenshot,
                datos_extra={"nombre": nombre, "curp": curp, "modelo": modelo},
            )

        fragmento = page_text[:300].replace("\n", " ").strip()
        return ResultadoPortal(
            modulo=self.portal_nombre,
            empresa=empresa,
            rfc=rfc,
            identificador=identificador,
            estado=EstadoValidacion.ERROR,
            detalle=f"No se pudo interpretar la respuesta. Fragmento: {fragmento[:150]}",
            screenshot=screenshot,
        )

    # ── Helpers para determinar modelo y llenar formularios ──

    def _determinar_modelo(
        self,
        doc_number: str,
        cic: str,
        id_ciudadano: str,
        ocr: str,
        clave_elector: str,
        emision: str,
    ) -> tuple[str, dict[str, str]]:
        """
        Determina el modelo de credencial basándose en los datos disponibles
        y retorna (modelo, dict_de_campos).
        """
        # Si tenemos CIC explícito (9 dígitos)
        if cic and len(cic.strip()) <= 9:
            if id_ciudadano:
                return "E-H", {
                    "cic": cic.strip().zfill(9),
                    "idCiudadano": id_ciudadano.strip().zfill(9),
                    "id_campo": f"CIC:{cic}",
                }
            if ocr:
                return "D", {
                    "cic": cic.strip().zfill(9),
                    "ocr": ocr.strip(),
                    "id_campo": f"CIC:{cic}",
                }

        # Si DocumentNumber tiene 9 dígitos, podría ser CIC
        dn_clean = re.sub(r"\D", "", doc_number) if doc_number else ""
        if len(dn_clean) == 9:
            if id_ciudadano:
                return "E-H", {
                    "cic": dn_clean,
                    "idCiudadano": id_ciudadano.strip().zfill(9),
                    "id_campo": f"CIC:{dn_clean}",
                }

        # Si tenemos clave de elector (18 chars) y emisión
        ce = clave_elector or doc_number
        if ce and len(ce.strip()) == 18:
            # Limpiar emisión: puede venir como "E005821" → extraer 2 dígitos
            em_clean = ""
            if emision:
                # Intentar extraer un número de 2 dígitos
                m = re.search(r"(\d{2})", emision)
                if m:
                    em_clean = m.group(1)

            # OCR: si no lo tenemos explícito, intentamos con otros campos
            ocr_val = ocr or ""

            if em_clean and ocr_val:
                return "A-C", {
                    "claveElector": ce.strip(),
                    "numeroEmision": em_clean,
                    "ocr": ocr_val.strip(),
                    "id_campo": f"CE:{ce[:8]}...",
                }
            elif em_clean:
                # Sin OCR, intentar igualmente
                return "A-C", {
                    "claveElector": ce.strip(),
                    "numeroEmision": em_clean,
                    "ocr": "",
                    "id_campo": f"CE:{ce[:8]}...",
                }

        # Fallback: usar DocumentNumber como CIC (rellenar con ceros)
        if doc_number:
            dn = re.sub(r"\D", "", doc_number)[:9].zfill(9)
            return "E-H", {
                "cic": dn,
                "idCiudadano": "000000000",
                "id_campo": f"DN:{doc_number[:12]}",
            }

        # Sin datos suficientes — señalizar para que el caller maneje el caso
        return "SIN_DATOS", {"cic": "", "idCiudadano": "", "id_campo": "SIN_DATOS"}

    async def _llenar_modelo_efgh(self, campos: dict[str, str]) -> None:
        """Llena el formulario de modelo E/F/G/H."""
        # Scroll al primer formulario
        await self.page.evaluate("window.scrollTo(0, 1100)")
        await asyncio.sleep(0.5)

        # Los campos CIC y idCiudadano están en el primer formulario
        # Hay múltiples inputs con id="cic" (uno por sección), usamos el primero
        cic_inputs = await self.page.query_selector_all('#cic')
        if cic_inputs:
            await cic_inputs[0].fill(campos["cic"])

        id_inputs = await self.page.query_selector_all('#idCiudadano')
        if id_inputs:
            await id_inputs[0].fill(campos["idCiudadano"])

    async def _llenar_modelo_d(self, campos: dict[str, str]) -> None:
        """Llena el formulario de modelo D."""
        await self.page.evaluate("window.scrollTo(0, 1700)")
        await asyncio.sleep(0.5)

        cic_inputs = await self.page.query_selector_all('#cic')
        if len(cic_inputs) > 1:
            await cic_inputs[1].fill(campos["cic"])
        elif cic_inputs:
            await cic_inputs[0].fill(campos["cic"])

        ocr_inputs = await self.page.query_selector_all('#ocr')
        if ocr_inputs:
            await ocr_inputs[0].fill(campos["ocr"])

    async def _llenar_modelo_abc(self, campos: dict[str, str]) -> None:
        """Llena el formulario de modelo A/B/C."""
        await self.page.evaluate("window.scrollTo(0, 2300)")
        await asyncio.sleep(0.5)

        ce_input = await self.page.query_selector('#claveElector')
        if ce_input:
            await ce_input.fill(campos["claveElector"])

        em_input = await self.page.query_selector('#numeroEmision')
        if em_input and campos.get("numeroEmision"):
            await em_input.fill(campos["numeroEmision"])

        ocr_inputs = await self.page.query_selector_all('#ocr')
        # El OCR del modelo A-C es el segundo con ese id
        if campos.get("ocr"):
            idx = 1 if len(ocr_inputs) > 1 else 0
            if ocr_inputs:
                await ocr_inputs[idx].fill(campos["ocr"])

    async def _resolver_recaptcha(self, modelo: str) -> bool:
        """
        Resuelve Google reCAPTCHA v2 con estrategia manual.
        Pide al usuario clicar el checkbox (requiere --visible).
        """
        strategy = CAPTCHA_STRATEGY

        # ── Estrategia manual ──
        # El reCAPTCHA está en iframes. Necesitamos que el usuario lo resuelva.
        recaptcha_frames = [
            f for f in self.page.frames
            if "recaptcha/api2/anchor" in f.url
        ]

        if not recaptcha_frames:
            self.logger.warning("No se encontraron iframes de reCAPTCHA")
            return True  # Quizá no hay reCAPTCHA

        # Determinar cuál iframe corresponde al modelo
        frame_idx = {"E-H": 0, "D": 1, "A-C": 2}.get(modelo, 0)
        if frame_idx >= len(recaptcha_frames):
            frame_idx = 0
        target_frame = recaptcha_frames[frame_idx]

        print("\n" + "=" * 60)
        print("  ⚠️  RECAPTCHA DETECTADO (Google reCAPTCHA v2)")
        print("  Necesitas marcar la casilla 'No soy un robot' manualmente.")
        print("  Si ejecutaste con --visible, haz clic en la casilla ahora.")
        print("  Si es headless, cancela y usa --visible.")
        print("=" * 60)

        # Intentar clicar el checkbox progamaticamente (a veces funciona)
        try:
            checkbox = await target_frame.query_selector('#recaptcha-anchor')
            if checkbox:
                await checkbox.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        # Esperar a que el usuario resuelva (hasta 120 segundos)
        self.logger.info("Esperando resolución de reCAPTCHA (máx. 120s)...")
        for _ in range(60):
            try:
                # Verificar si se resolvió: el textarea g-recaptcha-response tiene valor
                resp_idx = {"E-H": 0, "D": 1, "A-C": 2}.get(modelo, 0)
                suffix = f"-{resp_idx}" if resp_idx > 0 else ""
                textarea_sel = f'#g-recaptcha-response{suffix}'
                textarea = await self.page.query_selector(textarea_sel)
                if textarea:
                    val = await textarea.evaluate("el => el.value")
                    if val and len(val) > 10:
                        self.logger.info("reCAPTCHA resuelto ✓")
                        return True
            except Exception:
                pass
            await asyncio.sleep(2)

        self.logger.warning("Timeout esperando resolución de reCAPTCHA")
        return False
