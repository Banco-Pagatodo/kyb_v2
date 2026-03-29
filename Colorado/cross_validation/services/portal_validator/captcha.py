"""
Estrategias de resolución de CAPTCHA.

Soporta múltiples modos (configurables vía PORTAL_CAPTCHA_STRATEGY):
  - "manual"      : Muestra la imagen y espera input del usuario (default)
  - "ocr"         : Tesseract OCR con preprocesamiento OpenCV
  - "azure_ocr"   : Azure Computer Vision (Read OCR) con confidence score
  - "gpt4_vision" : Azure OpenAI GPT-4o con visión
  - "cascada"     : ★ RECOMENDADA — Azure CV → GPT-4o → Tesseract (fallback)
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re as _re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("portal_validator.captcha")


# ═══════════════════════════════════════════════════════════════════
#  PREPROCESAMIENTO AVANZADO DE IMAGEN (OpenCV)
# ═══════════════════════════════════════════════════════════════════

def _preprocess_captcha(img_bytes: bytes) -> dict[str, bytes]:
    """
    Genera múltiples variantes preprocesadas de la imagen CAPTCHA
    usando OpenCV + PIL para maximizar la precisión de cualquier OCR.

    Retorna dict con nombre_variante → bytes PNG.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("OpenCV no disponible, usando preprocesamiento PIL básico")
        return _preprocess_captcha_pil(img_bytes)

    from PIL import Image, ImageEnhance, ImageOps

    variantes: dict[str, bytes] = {}

    # Decodificar imagen con OpenCV
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        logger.warning("No se pudo decodificar la imagen CAPTCHA")
        return {"raw": img_bytes}

    h, w = img.shape[:2]

    # ── Variante 1: Upscale 4x + Denoise + Umbral adaptativo ──
    try:
        up = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, h=30)
        thresh = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        kernel = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        _, buf = cv2.imencode(".png", cleaned)
        variantes["adaptive_thresh"] = buf.tobytes()
    except Exception as e:
        logger.debug(f"Preprocesamiento adaptive_thresh falló: {e}")

    # ── Variante 2: Upscale 4x + Escala de grises + Contraste alto ──
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        upscaled = pil_img.resize((w * 4, h * 4), Image.LANCZOS)
        gray_pil = upscaled.convert("L")
        gray_pil = ImageEnhance.Contrast(gray_pil).enhance(3.0)
        gray_pil = ImageEnhance.Sharpness(gray_pil).enhance(2.0)
        buf2 = io.BytesIO()
        gray_pil.save(buf2, format="PNG")
        variantes["gray_contrast"] = buf2.getvalue()
    except Exception as e:
        logger.debug(f"Preprocesamiento gray_contrast falló: {e}")

    # ── Variante 3: Upscale 4x + Binarización OTSU ──
    try:
        up = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buf = cv2.imencode(".png", otsu)
        variantes["otsu"] = buf.tobytes()
    except Exception as e:
        logger.debug(f"Preprocesamiento otsu falló: {e}")

    # ── Variante 4: Upscale 4x color original mejorado (para GPT-4o) ──
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        upscaled = pil_img.resize((w * 4, h * 4), Image.LANCZOS)
        upscaled = ImageEnhance.Contrast(upscaled).enhance(1.5)
        upscaled = ImageEnhance.Sharpness(upscaled).enhance(1.5)
        buf4 = io.BytesIO()
        upscaled.save(buf4, format="PNG")
        variantes["color_4x"] = buf4.getvalue()
    except Exception as e:
        logger.debug(f"Preprocesamiento color_4x falló: {e}")

    # ── Variante 5: Inversión + contraste (fondo oscuro) ──
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        inv = ImageOps.invert(
            pil_img.resize((w * 4, h * 4), Image.LANCZOS).convert("L")
        )
        inv = ImageEnhance.Contrast(inv).enhance(2.5)
        buf5 = io.BytesIO()
        inv.save(buf5, format="PNG")
        variantes["inverted"] = buf5.getvalue()
    except Exception as e:
        logger.debug(f"Preprocesamiento inverted falló: {e}")

    # ── Variante 6: Denoise agresivo + CLAHE (ecualización local) ──
    try:
        up = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, h=20)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        _, buf = cv2.imencode(".png", enhanced)
        variantes["clahe"] = buf.tobytes()
    except Exception as e:
        logger.debug(f"Preprocesamiento clahe falló: {e}")

    if not variantes:
        variantes["raw"] = img_bytes

    logger.debug(
        f"Preprocesamiento generó {len(variantes)} variantes: "
        f"{list(variantes.keys())}"
    )
    return variantes


def _preprocess_captcha_pil(img_bytes: bytes) -> dict[str, bytes]:
    """Fallback de preprocesamiento usando solo PIL (sin OpenCV)."""
    from PIL import Image, ImageEnhance, ImageOps

    variantes: dict[str, bytes] = {}

    try:
        raw_img = Image.open(io.BytesIO(img_bytes))
        w, h = raw_img.size

        # Upscale 4x + contraste
        up = raw_img.resize((w * 4, h * 4), Image.LANCZOS)
        gray = up.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(3.0)
        gray = ImageEnhance.Sharpness(gray).enhance(2.0)
        buf = io.BytesIO()
        gray.save(buf, format="PNG")
        variantes["gray_contrast"] = buf.getvalue()

        # Color mejorado
        up = ImageEnhance.Contrast(up).enhance(1.5)
        up = ImageEnhance.Sharpness(up).enhance(1.5)
        buf2 = io.BytesIO()
        up.save(buf2, format="PNG")
        variantes["color_4x"] = buf2.getvalue()

        # Invertida
        inv = ImageOps.invert(raw_img.resize((w * 4, h * 4), Image.LANCZOS).convert("L"))
        inv = ImageEnhance.Contrast(inv).enhance(2.5)
        buf3 = io.BytesIO()
        inv.save(buf3, format="PNG")
        variantes["inverted"] = buf3.getvalue()

    except Exception as e:
        logger.debug(f"Preprocesamiento PIL falló: {e}")
        variantes["raw"] = img_bytes

    return variantes


def _clean(text: str) -> str:
    """Limpia texto OCR — solo deja alfanuméricos."""
    return _re.sub(r"[^A-Za-z0-9]", "", text.strip())


# ═══════════════════════════════════════════════════════════════════
#  INTERFAZ PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

async def resolver_captcha(
    page: Any,
    captcha_img_selector: str,
    captcha_input_selector: str,
    strategy: str = "manual",
) -> bool:
    """
    Detecta y resuelve un CAPTCHA en la página.

    Args:
        page: Playwright page object.
        captcha_img_selector: CSS selector de la imagen del CAPTCHA.
        captcha_input_selector: CSS selector del input donde escribir la respuesta.
        strategy: "manual"|"ocr"|"azure_ocr"|"gpt4_vision"|"cascada"

    Returns:
        True si se ingresó una respuesta, False si no se pudo resolver.
    """
    try:
        captcha_element = await page.query_selector(captcha_img_selector)
        if not captcha_element:
            logger.info("No se detectó CAPTCHA en la página")
            return True  # No hay CAPTCHA, continuar

        logger.info(f"CAPTCHA detectado, usando estrategia: {strategy}")

        # Obtener la imagen del CAPTCHA
        img_bytes = await captcha_element.screenshot()

        if strategy == "manual":
            respuesta = await _resolver_manual(img_bytes)
        elif strategy == "ocr":
            respuesta = await _resolver_ocr(img_bytes)
        elif strategy == "azure_ocr":
            respuesta = await _resolver_azure_ocr(img_bytes)
        elif strategy == "gpt4_vision":
            respuesta = await _resolver_gpt4_vision(img_bytes)
        elif strategy == "cascada":
            respuesta = await _resolver_cascada(img_bytes)
        else:
            logger.error(f"Estrategia de CAPTCHA no reconocida: {strategy}")
            return False

        if not respuesta:
            logger.warning("No se obtuvo respuesta para el CAPTCHA")
            return False

        # Ingresar la respuesta
        await page.fill(captcha_input_selector, respuesta)
        logger.info(f"Respuesta CAPTCHA ingresada: '{respuesta}'")
        return True

    except Exception as e:
        logger.error(f"Error al resolver CAPTCHA: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
#  ESTRATEGIA: MANUAL
# ═══════════════════════════════════════════════════════════════════

async def _resolver_manual(img_bytes: bytes) -> str:
    """Guarda imagen temporal y pide resolución manual al usuario."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="captcha_")
    tmp.write(img_bytes)
    tmp.close()
    tmp_path = tmp.name

    logger.info(f"CAPTCHA guardado en: {tmp_path}")
    print("\n" + "=" * 50)
    print("  ⚠️ CAPTCHA DETECTADO")
    print(f"  Imagen guardada en: {tmp_path}")
    print("  Abre la imagen y escribe el texto del CAPTCHA.")
    print("=" * 50)

    loop = asyncio.get_event_loop()
    respuesta = await loop.run_in_executor(
        None,
        lambda: input("  → Texto del CAPTCHA: ").strip(),
    )

    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    return respuesta


# ═══════════════════════════════════════════════════════════════════
#  ESTRATEGIA: OCR (Tesseract + OpenCV)
# ═══════════════════════════════════════════════════════════════════

async def _resolver_ocr(img_bytes: bytes) -> str:
    """Resuelve con Tesseract OCR + preprocesamiento OpenCV agresivo."""
    try:
        import pytesseract
    except ImportError:
        logger.error("Instala pytesseract: pip install pytesseract")
        return ""

    loop = asyncio.get_event_loop()

    def _ocr() -> str:
        from PIL import Image

        variantes = _preprocess_captcha(img_bytes)

        config_7 = (
            "--oem 3 --psm 7 -c tessedit_char_whitelist="
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        )
        config_8 = (
            "--oem 3 --psm 8 -c tessedit_char_whitelist="
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        )

        # Orden de prioridad para Tesseract
        orden = [
            "adaptive_thresh", "otsu", "gray_contrast",
            "clahe", "inverted", "color_4x", "raw",
        ]

        best = ""
        for nombre in orden:
            if nombre not in variantes:
                continue
            img_data = variantes[nombre]
            for config in [config_7, config_8]:
                try:
                    pil = Image.open(io.BytesIO(img_data))
                    t = _clean(pytesseract.image_to_string(pil, config=config))
                    if t and len(t) >= 4:
                        logger.info(f"Tesseract [{nombre}] resolvió: '{t}'")
                        return t
                    if len(t) > len(best):
                        best = t
                except Exception as e:
                    logger.debug(f"Tesseract [{nombre}] error: {e}")

        return best

    respuesta = await loop.run_in_executor(None, _ocr)
    logger.info(f"OCR resultado: '{respuesta}'")
    return respuesta


# ═══════════════════════════════════════════════════════════════════
#  ESTRATEGIA: AZURE COMPUTER VISION (con confidence score)
# ═══════════════════════════════════════════════════════════════════

async def _resolver_azure_ocr(
    img_bytes: bytes,
    min_confidence: float = 0.7,
    *,
    strict: bool = False,
    variantes_pre: dict[str, bytes] | None = None,
    solo_v4: bool = False,
) -> str:
    """
    Azure Computer Vision Read OCR con verificación de confidence score.

    Args:
        img_bytes: Bytes de la imagen CAPTCHA original.
        min_confidence: Umbral mínimo de confianza (0.0-1.0).
        strict: Si True, retorna "" cuando ningún resultado alcanza el umbral.
                Si False (default), retorna el mejor resultado aunque sea bajo.
        variantes_pre: Variantes ya preprocesadas (evita recalcular).
        solo_v4: Si True, solo usa Image Analysis v4.0 (más rápido, sin v3.2).

    Returns:
        Texto limpio del CAPTCHA, o "" si no hay resultado confiable.
    """
    endpoint = os.getenv("AZURE_CV_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_CV_KEY", "")

    if not endpoint or not api_key:
        logger.error(
            "Azure CV no configurado. Establece AZURE_CV_ENDPOINT y AZURE_CV_KEY."
        )
        return ""

    try:
        import httpx
    except ImportError:
        logger.error("Instala httpx: pip install httpx")
        return ""

    if len(img_bytes) < 100:
        logger.warning(f"Imagen CAPTCHA muy pequeña ({len(img_bytes)} bytes)")
        return ""

    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/octet-stream",
    }

    variantes = variantes_pre or _preprocess_captcha(img_bytes)

    # Solo las 3 variantes más útiles para evitar rate-limit (429)
    orden = ["gray_contrast", "color_4x", "adaptive_thresh"]
    variantes_ordenadas = [
        (n, variantes[n]) for n in orden if n in variantes
    ]
    if not variantes_ordenadas:
        variantes_ordenadas = [(k, v) for k, v in list(variantes.items())[:2]]

    best_text = ""
    best_conf = 0.0

    async with httpx.AsyncClient(timeout=30) as client:

        # ══════════════════════════════════════════════════════════
        #  ENFOQUE 1: Image Analysis v4.0 (modelos más nuevos)
        # ══════════════════════════════════════════════════════════
        v4_url = f"{endpoint}/computervision/imageanalysis:analyze"
        v4_params = {"features": "read", "api-version": "2024-02-01"}

        for i, (nombre, img_data) in enumerate(variantes_ordenadas):
            if i > 0:
                await asyncio.sleep(0.5)  # Rate-limit: 500ms entre llamadas
            try:
                resp = await client.post(
                    v4_url, headers=headers, params=v4_params, content=img_data
                )

                if resp.status_code == 200:
                    data = resp.json()
                    blocks = data.get("readResult", {}).get("blocks", [])

                    # Juntar todos los words de todas las líneas
                    all_text = ""
                    all_conf = 0.0
                    word_count = 0
                    for block in blocks:
                        for line in block.get("lines", []):
                            for word in line.get("words", []):
                                raw = word.get("text", "")
                                conf = word.get("confidence", 0)
                                all_text += raw
                                all_conf += conf
                                word_count += 1

                    text = _clean(all_text)
                    avg_conf = all_conf / max(word_count, 1)
                    logger.info(
                        f"Azure CV v4.0 [{nombre}]: "
                        f"'{all_text}' → '{text}' "
                        f"(avg confidence: {avg_conf:.3f}, words: {word_count})"
                    )
                    if text and len(text) >= 4 and avg_conf >= min_confidence:
                        logger.info(
                            f"Azure CV v4.0 ✓ [{nombre}]: '{text}' "
                            f"(conf: {avg_conf:.3f} >= {min_confidence})"
                        )
                        return text
                    if text and len(text) >= 4 and avg_conf > best_conf:
                        best_text = text
                        best_conf = avg_conf

                elif resp.status_code == 401:
                    logger.error("Azure CV: clave de API inválida (401)")
                    return ""
                elif resp.status_code == 404:
                    logger.info("Azure CV v4.0 no disponible, saltando a v3.2")
                    break
                elif resp.status_code == 429:
                    logger.warning(f"Azure CV v4.0 [{nombre}]: rate-limited (429), esperando 2s...")
                    await asyncio.sleep(2)
                else:
                    logger.debug(
                        f"Azure CV v4.0 [{nombre}]: HTTP {resp.status_code}"
                    )

            except Exception as e:
                logger.debug(f"Azure CV v4.0 [{nombre}] error: {e}")

        # ══════════════════════════════════════════════════════════
        #  ENFOQUE 2 (fallback): Read API v3.2
        #  Solo se usa si no se pidió solo_v4 (cascada lo salta)
        # ══════════════════════════════════════════════════════════
        if not solo_v4:
            read_url = f"{endpoint}/vision/v3.2/read/analyze"

            for i, (nombre, img_data) in enumerate(variantes_ordenadas[:2]):
                if i > 0:
                    await asyncio.sleep(0.5)
                try:
                    resp = await client.post(
                        read_url, headers=headers, content=img_data
                    )
                    if resp.status_code == 429:
                        logger.warning("Azure CV v3.2: rate-limited (429)")
                        break
                    if resp.status_code not in (200, 202):
                        logger.debug(
                            f"Azure CV v3.2 [{nombre}]: HTTP {resp.status_code}"
                        )
                        continue

                    operation_url = resp.headers.get("Operation-Location", "")
                    if not operation_url:
                        continue

                    for _ in range(10):
                        await asyncio.sleep(1)
                        result_resp = await client.get(
                            operation_url,
                            headers={"Ocp-Apim-Subscription-Key": api_key},
                        )
                        result_data = result_resp.json()
                        status = result_data.get("status", "")

                        if status == "succeeded":
                            all_text = ""
                            all_conf = 0.0
                            word_count = 0
                            for rr in result_data.get("analyzeResult", {}).get(
                                "readResults", []
                            ):
                                for line in rr.get("lines", []):
                                    for word in line.get("words", []):
                                        all_text += word.get("text", "")
                                        all_conf += word.get("confidence", 0)
                                        word_count += 1

                            text = _clean(all_text)
                            avg_conf = all_conf / max(word_count, 1)
                            logger.info(
                                f"Azure CV v3.2 [{nombre}]: "
                                f"'{all_text}' → '{text}' "
                                f"(avg confidence: {avg_conf:.3f})"
                            )
                            if text and len(text) >= 4 and avg_conf >= min_confidence:
                                logger.info(
                                    f"Azure CV v3.2 ✓ [{nombre}]: "
                                    f"'{text}' (conf: {avg_conf:.3f})"
                                )
                                return text
                            if text and len(text) >= 4 and avg_conf > best_conf:
                                best_text = text
                                best_conf = avg_conf
                            break

                        if status == "failed":
                            break

                except Exception as e:
                    logger.debug(f"Azure CV v3.2 [{nombre}] error: {e}")

    # Si ninguna variante alcanzó el umbral:
    if best_text:
        if strict:
            # En modo estricto, NO retornar resultados bajo umbral
            logger.info(
                f"Azure CV (strict): descartando '{best_text}' "
                f"(conf: {best_conf:.3f} < {min_confidence})"
            )
            return ""
        else:
            # En modo normal, retornar el mejor resultado disponible
            logger.warning(
                f"Azure CV: mejor resultado bajo umbral: '{best_text}' "
                f"(conf: {best_conf:.3f} < {min_confidence}). "
                f"Retornando de todas formas."
            )
            return best_text

    logger.warning("Azure CV no pudo resolver el CAPTCHA")
    return ""


# ═══════════════════════════════════════════════════════════════════
#  ESTRATEGIA: GPT-4o VISION
# ═══════════════════════════════════════════════════════════════════

async def _resolver_gpt4_vision(
    img_bytes: bytes,
    variantes_pre: dict[str, bytes] | None = None,
) -> str:
    """
    GPT-4o Vision con imagen preprocesada (upscale 4x + contraste).

    Envía la variante color_4x para máxima legibilidad con el modelo
    de visión, que entiende mejor las imágenes a color aumentadas.
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    deployment = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    if not endpoint or not api_key:
        logger.error(
            "Azure OpenAI no configurado. "
            "Establece AZURE_OPENAI_ENDPOINT y AZURE_OPENAI_API_KEY."
        )
        return ""

    try:
        import httpx
    except ImportError:
        logger.error("Instala httpx: pip install httpx")
        return ""

    if len(img_bytes) < 100:
        logger.warning(f"Imagen CAPTCHA muy pequeña ({len(img_bytes)} bytes)")
        return ""

    # Usar variante color_4x preprocesada para mejor lectura
    variantes = variantes_pre or _preprocess_captcha(img_bytes)
    img_enviar = variantes.get("color_4x", img_bytes)
    img_b64 = base64.b64encode(img_enviar).decode()

    url = (
        f"{endpoint}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={api_version}"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un lector experto de CAPTCHAs. Tu tarea es leer el texto "
                    "exacto que aparece en la imagen CAPTCHA.\n"
                    "REGLAS CRÍTICAS:\n"
                    "1. El CAPTCHA es SENSIBLE a mayúsculas y minúsculas (case-sensitive)\n"
                    "2. Distingue cuidadosamente entre:\n"
                    "   - 0 (cero) vs O (o mayúscula) vs o (o minúscula)\n"
                    "   - 1 (uno) vs l (L minúscula) vs I (i mayúscula)\n"
                    "   - 5 (cinco) vs S (s mayúscula) vs s (s minúscula)\n"
                    "   - 8 (ocho) vs B (b mayúscula)\n"
                    "   - 2 (dos) vs Z (z mayúscula) vs z (z minúscula)\n"
                    "   - 6 (seis) vs G (g mayúscula) vs b (b minúscula)\n"
                    "   - 9 (nueve) vs g (g minúscula) vs q (q minúscula)\n"
                    "3. Los CAPTCHAs típicamente tienen 5-6 caracteres\n"
                    "4. Responde ÚNICAMENTE con los caracteres exactos\n"
                    "5. Sin espacios, sin explicaciones, sin comillas\n"
                    "6. Si una letra es mayúscula, escríbela en MAYÚSCULA\n"
                    "7. Si una letra es minúscula, escríbela en minúscula"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Lee el texto EXACTO de este CAPTCHA. "
                            "Es case-sensitive (mayúsculas ≠ minúsculas). "
                            "Responde SOLO con los caracteres exactos."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        "max_tokens": 30,
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )

            if resp.status_code == 401:
                logger.error("GPT-4o Vision: clave de API inválida (401)")
                return ""
            if resp.status_code == 404:
                logger.error(
                    f"GPT-4o Vision: deployment no encontrado. "
                    f"Verifica AZURE_DEPLOYMENT_NAME: {deployment}"
                )
                return ""
            if resp.status_code != 200:
                logger.error(
                    f"GPT-4o Vision error: HTTP {resp.status_code} — "
                    f"{resp.text[:300]}"
                )
                return ""

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error("GPT-4o Vision: respuesta sin choices")
                return ""

            raw_text = choices[0].get("message", {}).get("content", "").strip()
            clean = _clean(raw_text)
            logger.info(f"GPT-4o Vision raw: '{raw_text}' → limpio: '{clean}'")
            return clean

    except Exception as e:
        logger.error(f"GPT-4o Vision error: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════
#  ★ ESTRATEGIA: CASCADA (Azure CV → GPT-4o → Tesseract)
# ═══════════════════════════════════════════════════════════════════

async def _resolver_cascada(img_bytes: bytes) -> str:
    """
    Estrategia en cascada optimizada:

    Flujo:
      1. Preprocesar imagen UNA sola vez
      2. Azure CV v4.0 (strict=True, solo 3 variantes, con delays)
         → Si conf >= 0.8 → retornar directo (fast exit)
      3. GPT-4o Vision (siempre se ejecuta si Azure no superó umbral)
         → GPT-4o es mejor con case-sensitivity
      4. Tesseract como último recurso
    """
    logger.info("=" * 60)
    logger.info("  CASCADA: Iniciando estrategia combinada")
    logger.info("=" * 60)

    # Preprocesar una sola vez para todas las estrategias
    variantes = _preprocess_captcha(img_bytes)
    logger.info(f"CASCADA: {len(variantes)} variantes generadas: {list(variantes.keys())}")

    # ── Paso 1: Azure Computer Vision (strict, solo v4.0, 3 variantes) ──
    logger.info("CASCADA [1/3]: Azure Computer Vision (conf >= 0.8)...")
    resultado_azure = ""
    try:
        resultado_azure = await _resolver_azure_ocr(
            img_bytes,
            min_confidence=0.8,
            strict=True,
            variantes_pre=variantes,
            solo_v4=True,
        )
    except Exception as e:
        logger.warning(f"CASCADA [Azure CV] error: {e}")

    if resultado_azure and len(resultado_azure) >= 4:
        logger.info(
            f"CASCADA ✓ Azure CV (conf >= 0.8): '{resultado_azure}'"
        )
        return resultado_azure

    logger.info("CASCADA: Azure CV no alcanzó umbral, pasando a GPT-4o...")

    # ── Paso 2: GPT-4o Vision (siempre se ejecuta como fallback) ──
    logger.info("CASCADA [2/3]: GPT-4o Vision...")
    resultado_gpt = ""
    try:
        resultado_gpt = await _resolver_gpt4_vision(
            img_bytes, variantes_pre=variantes
        )
    except Exception as e:
        logger.warning(f"CASCADA [GPT-4o] error: {e}")

    if resultado_gpt and len(resultado_gpt) >= 4:
        logger.info(f"CASCADA ✓ GPT-4o: '{resultado_gpt}'")
        return resultado_gpt

    # ── Paso 3: Tesseract como último recurso ──
    logger.info("CASCADA [3/3]: Tesseract (last resort)...")
    try:
        resultado_ocr = await _resolver_ocr(img_bytes)
        if resultado_ocr and len(resultado_ocr) >= 4:
            logger.info(f"CASCADA ✓ Tesseract: '{resultado_ocr}'")
            return resultado_ocr
    except Exception as e:
        logger.debug(f"CASCADA [Tesseract] error: {e}")

    logger.warning("CASCADA ✗ Ningún método pudo resolver el CAPTCHA")
    return ""
