"""
Clase base para validadores de portales gubernamentales.

Proporciona:
  - Gestión de navegador Playwright (async, headless configurable)
  - Reintentos automáticos (máx 3 intentos por registro)
  - Delays aleatorios entre consultas (3-8 s)
  - Logging detallado a archivo y consola
  - Screenshots de evidencia
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re as _re
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# ── Logging ────────────────────────────────────────────────────────
_PKG_ROOT = Path(__file__).resolve().parents[2]  # cross_validation/

LOG_DIR = Path(os.getenv(
    "PORTAL_LOG_DIR",
    str(_PKG_ROOT / "logs"),
))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_screenshot_env = os.getenv("PORTAL_SCREENSHOT_DIR")
SCREENSHOT_DIR = Path(_screenshot_env) if _screenshot_env else Path(tempfile.mkdtemp(prefix="portal_screenshots_"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Restringir permisos de directorios sensibles (owner-only en Linux/Mac).
for _dir in (LOG_DIR, SCREENSHOT_DIR):
    try:
        _dir.chmod(0o700)
    except OSError:
        pass  # Windows no soporta permisos POSIX

_log_file = LOG_DIR / f"portal_validator_{datetime.now():%Y%m%d_%H%M%S}.log"


# ── Filtro de sanitización de logs ────────────────────────────────
_RFC_PATTERN = _re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b")
_CURP_PATTERN = _re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z\d]{2}\b")


class _SanitizeFilter(logging.Filter):
    """Enmascara RFC y CURP en registros de log para proteger datos personales."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _RFC_PATTERN.sub(lambda m: m.group()[:4] + "******", record.msg)
            record.msg = _CURP_PATTERN.sub(lambda m: m.group()[:4] + "**************", record.msg)
        return True


# Configurar logger propio en vez de logging.basicConfig() que afecta al root.
_portal_handler_file = logging.FileHandler(_log_file, encoding="utf-8")
_portal_handler_stream = logging.StreamHandler()
_portal_formatter = logging.Formatter(
    "%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s"
)
_portal_handler_file.setFormatter(_portal_formatter)
_portal_handler_stream.setFormatter(_portal_formatter)

logger = logging.getLogger("portal_validator")
if not logger.handlers:  # evitar duplicar handlers en reloads
    logger.setLevel(logging.INFO)
    logger.addFilter(_SanitizeFilter())
    logger.addHandler(_portal_handler_file)
    logger.addHandler(_portal_handler_stream)


# ── Modelos de resultado ──────────────────────────────────────────

class EstadoValidacion(str, Enum):
    """Estado resultante de una validación contra portal."""
    ENCONTRADO = "ENCONTRADO"
    NO_ENCONTRADO = "NO ENCONTRADO"
    VIGENTE = "VIGENTE"
    VENCIDO = "VENCIDO"
    REVOCADO = "REVOCADO"
    VALIDO = "VÁLIDO"
    INVALIDO = "INVÁLIDO"
    ERROR = "ERROR"
    CAPTCHA_NO_RESUELTO = "CAPTCHA NO RESUELTO"
    SIN_DATOS = "SIN DATOS"


@dataclass
class ResultadoPortal:
    """Resultado de una consulta a un portal gubernamental."""
    modulo: str                              # "INE", "FIEL", "RFC"
    empresa: str                             # Razón social
    rfc: str                                 # RFC de la empresa
    identificador: str                       # Dato consultado (CURP, No. serie, RFC)
    estado: EstadoValidacion                 # Resultado
    detalle: str = ""                        # Mensaje descriptivo
    fecha_consulta: datetime = field(default_factory=datetime.now)
    intentos: int = 1                        # Intentos realizados
    screenshot: str = ""                     # Ruta del screenshot de evidencia
    datos_extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modulo": self.modulo,
            "empresa": self.empresa,
            "rfc": self.rfc,
            "identificador": self.identificador,
            "estado": self.estado.value,
            "detalle": self.detalle,
            "fecha_consulta": self.fecha_consulta.strftime("%Y-%m-%d %H:%M:%S"),
            "intentos": self.intentos,
            "screenshot": self.screenshot,
            **self.datos_extra,
        }


# ── Configuración ─────────────────────────────────────────────────

MAX_REINTENTOS = int(os.getenv("PORTAL_MAX_RETRIES", "2"))
DELAY_MIN = float(os.getenv("PORTAL_DELAY_MIN", "0.5"))
DELAY_MAX = float(os.getenv("PORTAL_DELAY_MAX", "1.5"))
HEADLESS = os.getenv("PORTAL_HEADLESS", "true").lower() in ("true", "1", "yes")
NAVEGACION_TIMEOUT = int(os.getenv("PORTAL_NAV_TIMEOUT", "15000"))  # ms
CAPTCHA_STRATEGY = os.getenv("PORTAL_CAPTCHA_STRATEGY", "cascada")  # manual | ocr | azure_ocr | gpt4_vision | cascada


# ── Clase base ────────────────────────────────────────────────────

class PortalValidatorBase(ABC):
    """Clase base abstracta para validadores de portales."""

    portal_nombre: str = ""
    portal_url: str = ""

    def __init__(self) -> None:
        self._browser = None
        self._context = None
        self._page = None
        self._owns_browser = True  # True si este validador creó el browser
        self._pw = None
        self.logger = logging.getLogger(f"portal_validator.{self.portal_nombre}")

    # ── Ciclo de vida del navegador ───────────────────────────────

    async def iniciar_navegador(self, *, headless: bool | None = None) -> None:
        """Inicia Playwright y abre un navegador con parches stealth."""
        from playwright.async_api import async_playwright

        try:
            from playwright_stealth import Stealth
            _has_stealth = True
        except ModuleNotFoundError:
            _has_stealth = False

        _headless = headless if headless is not None else HEADLESS
        self._headless_flag = _headless
        stealth_label = "ON" if _has_stealth else "OFF (playwright_stealth no instalado)"
        self.logger.info(f"Iniciando navegador (headless={_headless}, stealth={stealth_label})")
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._owns_browser = True
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="es-MX",
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(NAVEGACION_TIMEOUT)

        # Aplicar parches stealth (elimina navigator.webdriver, etc.)
        if _has_stealth:
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)

    async def usar_navegador_compartido(self, browser) -> None:
        """Crea un context + page a partir de un browser externo (no lo cierra)."""
        try:
            from playwright_stealth import Stealth
            _has_stealth = True
        except ModuleNotFoundError:
            _has_stealth = False

        self._browser = browser
        self._owns_browser = False
        self._context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="es-MX",
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(NAVEGACION_TIMEOUT)
        if _has_stealth:
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)
        self.logger.info("Usando navegador compartido (context propio)")

    async def cerrar_navegador(self) -> None:
        """Cierra context/page. Solo cierra el browser si lo creó este validador."""
        if self._context:
            await self._context.close()
        if self._owns_browser and self._browser:
            self.logger.info("Cerrando navegador")
            await self._browser.close()
        if self._owns_browser and self._pw:
            await self._pw.stop()
        self._context = None
        self._page = None
        if self._owns_browser:
            self._browser = None
            self._pw = None
            self._limpiar_screenshots()

    @staticmethod
    def _limpiar_screenshots() -> None:
        """Elimina todos los screenshots de la carpeta temporal."""
        if not SCREENSHOT_DIR.exists():
            return
        for archivo in SCREENSHOT_DIR.glob("*.png"):
            try:
                archivo.unlink()
            except OSError:
                pass
        logger.info("Screenshots temporales eliminados de %s", SCREENSHOT_DIR)

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("Navegador no iniciado. Llama a iniciar_navegador() primero.")
        return self._page

    # ── Screenshot ────────────────────────────────────────────────

    async def capturar_screenshot(self, nombre: str) -> str:
        """Captura un screenshot de evidencia y devuelve la ruta."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"{self.portal_nombre}_{nombre}_{ts}.png"
        ruta = SCREENSHOT_DIR / nombre_archivo
        await self.page.screenshot(path=str(ruta), full_page=True)
        self.logger.info(f"Screenshot guardado: {ruta}")
        return str(ruta)

    # ── Delay aleatorio ───────────────────────────────────────────

    async def delay_aleatorio(self) -> None:
        """Espera un tiempo aleatorio entre DELAY_MIN y DELAY_MAX segundos."""
        t = random.uniform(DELAY_MIN, DELAY_MAX)
        self.logger.debug(f"Delay aleatorio: {t:.1f}s")
        await asyncio.sleep(t)

    # ── Método principal con reintentos ───────────────────────────

    async def validar_con_reintentos(
        self,
        datos: dict[str, Any],
        empresa: str,
        rfc: str,
    ) -> ResultadoPortal:
        """Ejecuta la validación con reintentos automáticos.

        Reintenta si ocurre una excepción O si el resultado es CAPTCHA_NO_RESUELTO / ERROR
        (porque un nuevo intento genera una imagen CAPTCHA distinta).
        """
        ultimo_error = ""
        ultimo_resultado: ResultadoPortal | None = None

        _REINTENTAR_ESTADOS = {
            EstadoValidacion.CAPTCHA_NO_RESUELTO,
            EstadoValidacion.ERROR,
        }

        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                self.logger.info(
                    f"[{self.portal_nombre}] Intento {intento}/{MAX_REINTENTOS} "
                    f"— {empresa} ({rfc})"
                )
                resultado = await self._ejecutar_validacion(datos, empresa, rfc)
                resultado.intentos = intento
                self.logger.info(
                    f"[{self.portal_nombre}] Resultado: {resultado.estado.value} "
                    f"— {resultado.detalle[:80]}"
                )

                # Si es estado definitivo (no CAPTCHA_NO_RESUELTO/ERROR), retornar
                if resultado.estado not in _REINTENTAR_ESTADOS:
                    return resultado

                # Si el portal devolvió HTTP 5xx, no reintentar
                # (el portal está caído, no se resolverá en segundos)
                http_status = resultado.datos_extra.get("http_status", 0)
                if http_status >= 500:
                    self.logger.info(
                        f"[{self.portal_nombre}] Portal caído (HTTP {http_status}), "
                        f"no se reintenta."
                    )
                    return resultado

                # Estado reintentable — guardar y seguir
                ultimo_resultado = resultado
                ultimo_error = resultado.detalle

                if intento < MAX_REINTENTOS:
                    self.logger.info(
                        f"[{self.portal_nombre}] Reintentando ({resultado.estado.value})..."
                    )
                    await self.delay_aleatorio()
                    # Recargar la página para obtener un CAPTCHA nuevo
                    try:
                        await self.page.goto(
                            self.portal_url, wait_until="domcontentloaded"
                        )
                    except Exception:
                        pass

            except Exception as e:
                ultimo_error = str(e)
                self.logger.warning(
                    f"[{self.portal_nombre}] Error en intento {intento}: {ultimo_error}"
                )
                if intento < MAX_REINTENTOS:
                    await self.delay_aleatorio()

                    # Recargar la página para un nuevo intento limpio
                    try:
                        await self.page.goto(self.portal_url, wait_until="domcontentloaded")
                    except Exception:
                        pass

        # Todos los intentos fallaron — devolver el último resultado o crear uno
        if ultimo_resultado is not None:
            ultimo_resultado.intentos = MAX_REINTENTOS
            return ultimo_resultado

        screenshot = ""
        try:
            screenshot = await self.capturar_screenshot(f"error_{rfc}")
        except Exception:
            pass

        return ResultadoPortal(
            modulo=self.portal_nombre,
            empresa=empresa,
            rfc=rfc,
            identificador=rfc,
            estado=EstadoValidacion.ERROR,
            detalle=f"Falló tras {MAX_REINTENTOS} intentos: {ultimo_error}",
            intentos=MAX_REINTENTOS,
            screenshot=screenshot,
        )

    # ── Método abstracto ─────────────────────────────────────────

    @abstractmethod
    async def _ejecutar_validacion(
        self,
        datos: dict[str, Any],
        empresa: str,
        rfc: str,
    ) -> ResultadoPortal:
        """Implementa la lógica específica de validación contra el portal."""
        ...
