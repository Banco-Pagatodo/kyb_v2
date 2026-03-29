"""
BLOQUE 6: DATOS BANCARIOS
V6.1 — Titular del estado de cuenta = empresa
V6.2 — CLABE válida
"""
from __future__ import annotations

import re

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor_str, comparar_razones_sociales, normalizar_texto, es_titular_corrupto
from .base import h, obtener_datos

_B = 6
_BN = "DATOS BANCARIOS"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v6_1_titular_es_empresa(exp))
    resultado.append(_v6_2_clabe_valida(exp))
    return resultado


def _v6_1_titular_es_empresa(exp: ExpedienteEmpresa) -> Hallazgo:
    """V6.1 — Titular del estado de cuenta = empresa."""
    edo = obtener_datos(exp, "estado_cuenta")
    if not edo:
        return h("V6.1", "Titular = empresa", _B, _BN, None, Severidad.INFORMATIVA,
                 "No se encontró estado de cuenta en el expediente — "
                 "no es requisito normativo para integración de expediente")

    titular = get_valor_str(edo, "titular")
    if not titular:
        return h("V6.1", "Titular = empresa", _B, _BN, None, Severidad.INFORMATIVA,
                 "No se pudo extraer el titular del estado de cuenta")

    # Obtener la razón social de referencia
    csf = obtener_datos(exp, "csf")
    razon_ref = ""
    if csf:
        razon_ref = get_valor_str(csf, "razon_social")
    if not razon_ref:
        razon_ref = exp.razon_social

    # Si el titular parece corrupto, intentar recuperar la primera línea
    if es_titular_corrupto(titular):
        # Intentar primera línea: "ALMIRANTE CAPITAL\nPERÍODO" → "ALMIRANTE CAPITAL"
        primera_linea = titular.split("\n")[0].split("\r")[0].strip()
        if primera_linea and not es_titular_corrupto(primera_linea):
            coincide, sim, desc = comparar_razones_sociales(primera_linea, razon_ref)
            if coincide:
                return h("V6.1", "Titular = empresa", _B, _BN, True, Severidad.MEDIA,
                         f"Titular coincide con la empresa (primera línea: '{primera_linea}', {desc}). "
                         f"Nota: texto extraído contenía formato irregular.",
                         titular=titular, primera_linea=primera_linea,
                         empresa=razon_ref, similitud=sim, recuperado=True)

        # Primera línea no ayudó — reportar como corrupto
        razones: list[str] = []
        if "\n" in titular or "\r" in titular:
            razones.append("contiene saltos de línea")
        if len(titular) > 60:
            razones.append(f"demasiado largo ({len(titular)} caracteres)")
        norm = normalizar_texto(titular)
        for palabra in ["BENEFICIARIO", "DATO NO CERTIFICADO", "ESTE DOCUMENTO",
                        "PARA EFECTOS", "ESTIMADO CLIENTE"]:
            if palabra in norm:
                razones.append(f"parece disclaimer bancario (contiene '{palabra}')")
                break

        causa = "; ".join(razones) if razones else "formato no válido"
        titular_preview = titular.replace("\n", " ").replace("\r", "")[:80]
        return h("V6.1", "Titular = empresa", _B, _BN, False, Severidad.MEDIA,
                 f"Titular NO legible — {causa}. "
                 f"Texto extraído: '{titular_preview}'. "
                 f"Requiere re-extracción del documento original.",
                 titular=titular, corrupto=True)

    # Titular limpio — comparar directamente
    coincide, sim, desc = comparar_razones_sociales(titular, razon_ref)

    if coincide:
        return h("V6.1", "Titular = empresa", _B, _BN, True, Severidad.MEDIA,
                 f"Titular coincide con la empresa ({desc})",
                 titular=titular, empresa=razon_ref, similitud=sim)

    return h("V6.1", "Titular = empresa", _B, _BN, False, Severidad.MEDIA,
             f"Titular '{titular}' no coincide con '{razon_ref}' ({sim:.0%})",
             titular=titular, empresa=razon_ref, similitud=sim)


def _v6_2_clabe_valida(exp: ExpedienteEmpresa) -> Hallazgo:
    """V6.2 — CLABE válida (18 dígitos)."""
    edo = obtener_datos(exp, "estado_cuenta")
    if not edo:
        return h("V6.2", "CLABE válida", _B, _BN, None, Severidad.INFORMATIVA,
                 "No se encontró estado de cuenta en el expediente — "
                 "no es requisito normativo para integración de expediente")

    clabe = get_valor_str(edo, "clabe")
    if not clabe:
        return h("V6.2", "CLABE válida", _B, _BN, None, Severidad.INFORMATIVA,
                 "No se pudo extraer la CLABE del estado de cuenta")

    # Extraer solo dígitos
    digitos = re.sub(r"\D", "", clabe)

    # Enmascarar CLABE para no exponer dato financiero sensible
    def _mask(c: str) -> str:
        if len(c) >= 8:
            return c[:3] + "*" * (len(c) - 7) + c[-4:]
        return "*" * len(c)

    if len(digitos) == 18:
        return h("V6.2", "CLABE válida", _B, _BN, True, Severidad.MEDIA,
                 f"CLABE con formato válido: {_mask(digitos)} (18 dígitos)",
                 clabe_masked=_mask(digitos))

    return h("V6.2", "CLABE válida", _B, _BN, False, Severidad.MEDIA,
             f"CLABE con formato incorrecto: {len(digitos)} dígitos (esperado 18)",
             clabe_masked=_mask(digitos), digitos_encontrados=len(digitos))
