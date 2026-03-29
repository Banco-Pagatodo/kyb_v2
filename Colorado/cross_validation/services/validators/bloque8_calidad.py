"""
BLOQUE 8: CALIDAD DE EXTRACCIÓN
V8.1 — Campos con confiabilidad baja
V8.2 — Campos no encontrados
V8.3 — Parsing de nombres corporativos
V8.4 — Titular del estado de cuenta corrupto
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor, get_valor_str, get_confiabilidad, normalizar_texto
from ...core.config import UMBRAL_CONFIABILIDAD_BAJA
from .base import h, obtener_datos

_B = 8
_BN = "CALIDAD DE EXTRACCIÓN"

# Campos internos/metadatos a ignorar
_CAMPOS_INTERNOS = {
    "_estructura_accionaria_status", "_suma_porcentajes",
    "_estructura_confiabilidad", "_porcentajes_validos",
    "_nota_estructura", "_alertas_accionarias",
    "_reextraccion_llm_aplicada", "_estructura_enriquecida_por_fallback",
    "_persistencia", "_nombres_parseados",
    "_validation", "_processing_time",
}

# Campos críticos vs informativos para V8.2
# Si falta cualquiera de estos, el expediente no permite identificar
# al cliente o a su representante → CRITICA (DCG).
_CAMPOS_CRITICOS = {
    # Identidad corporativa
    "rfc", "razon_social", "denominacion_social",
    # Representante legal
    "nombre_apoderado", "nombre_poderdante",
    # Vigencia de documentos
    "vigencia_hasta", "DateOfExpiration",
    # Estatus fiscal
    "estatus_padron",
    # Domicilio fiscal completo
    "domicilio_fiscal", "codigo_postal",
    # Fecha de constitución
    "fecha_constitucion", "fecha_otorgamiento",
}


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.extend(_v8_1_confiabilidad_baja(exp))
    resultado.extend(_v8_2_campos_no_encontrados(exp))
    resultado.append(_v8_3_parsing_nombres(exp))
    resultado.append(_v8_4_titular_corrupto(exp))
    return resultado


def _v8_1_confiabilidad_baja(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """V8.1 — Campos con confiabilidad baja en todos los documentos."""
    alertas: list[str] = []

    for doc_type, datos in exp.documentos.items():
        for campo, valor in datos.items():
            if campo.startswith("_") or campo in _CAMPOS_INTERNOS:
                continue
            if not isinstance(valor, dict):
                continue
            conf = valor.get("confiabilidad", 100.0)
            try:
                conf_f = float(conf)
            except (ValueError, TypeError):
                continue
            if conf_f < UMBRAL_CONFIABILIDAD_BAJA and conf_f > 0:
                alertas.append(f"{doc_type}.{campo}: {conf_f}%")

    if not alertas:
        return [h("V8.1", "Confiabilidad de campos", _B, _BN, True,
                  Severidad.INFORMATIVA,
                  "Todos los campos extraídos tienen confiabilidad ≥ 70%")]

    # Limitar a 15 alertas para no saturar
    mostrar = alertas[:15]
    restantes = len(alertas) - len(mostrar)
    msg = "Campos con confiabilidad < 70%:\n  " + "\n  ".join(mostrar)
    if restantes > 0:
        msg += f"\n  ... y {restantes} más"

    return [h("V8.1", "Confiabilidad de campos", _B, _BN, False,
              Severidad.INFORMATIVA, msg,
              total_alertas=len(alertas), campos=alertas[:15])]


def _v8_2_campos_no_encontrados(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    """V8.2 — Campos no encontrados (campos_no_encontrados)."""
    alertas_criticas: list[str] = []
    alertas_info: list[str] = []

    for doc_type, datos in exp.documentos.items():
        no_encontrados = get_valor(datos, "campos_no_encontrados")
        if isinstance(no_encontrados, list):
            for campo in no_encontrados:
                campo_str = str(campo)
                if campo_str in _CAMPOS_CRITICOS:
                    alertas_criticas.append(f"{doc_type}.{campo_str}")
                else:
                    alertas_info.append(f"{doc_type}.{campo_str}")

    resultados = []

    if alertas_criticas:
        resultados.append(h("V8.2", "Campos críticos faltantes", _B, _BN, False,
                            Severidad.CRITICA,
                            "Campos críticos no encontrados (impiden identificar "
                            "al cliente o a su representante):\n  " +
                            "\n  ".join(alertas_criticas),
                            campos=alertas_criticas))
    elif alertas_info:
        resultados.append(h("V8.2", "Campos faltantes", _B, _BN, True,
                            Severidad.INFORMATIVA,
                            f"{len(alertas_info)} campos no críticos faltantes",
                            campos=alertas_info[:10]))
    else:
        resultados.append(h("V8.2", "Campos faltantes", _B, _BN, True,
                            Severidad.INFORMATIVA,
                            "No se reportaron campos faltantes"))

    return resultados


def _v8_3_parsing_nombres(exp: ExpedienteEmpresa) -> Hallazgo:
    """V8.3 — Parsing de nombres corporativos."""
    alertas: list[str] = []

    for doc_type, datos in exp.documentos.items():
        parseados = get_valor(datos, "_nombres_parseados")
        if not isinstance(parseados, dict):
            continue

        confianza = parseados.get("confianza_parsing")
        if confianza is not None:
            try:
                conf_f = float(confianza)
            except (ValueError, TypeError):
                continue
            if conf_f < 0.7:
                # Verificar si es persona moral (ignorar)
                tipo = parseados.get("tipo_persona", "")
                if tipo == "moral":
                    continue  # Ignorar parsing de personas morales
                alertas.append(
                    f"{doc_type}: confianza {conf_f:.0%}, "
                    f"apellido='{parseados.get('primer_apellido', '')}'"
                )

    if not alertas:
        return h("V8.3", "Parsing de nombres", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 "Parsing de nombres sin alertas (personas morales ignoradas)")

    return h("V8.3", "Parsing de nombres", _B, _BN, False,
             Severidad.INFORMATIVA,
             "Parsing de nombres con baja confianza:\n  " + "\n  ".join(alertas),
             alertas=alertas)


def _v8_4_titular_corrupto(exp: ExpedienteEmpresa) -> Hallazgo:
    """V8.4 — Titular del estado de cuenta corrupto."""
    edo = obtener_datos(exp, "estado_cuenta")
    if not edo:
        return h("V8.4", "Titular estado de cuenta", _B, _BN, None,
                 Severidad.MEDIA, "No se encontró estado de cuenta")

    titular = get_valor_str(edo, "titular")
    if not titular:
        return h("V8.4", "Titular estado de cuenta", _B, _BN, None,
                 Severidad.MEDIA, "No se pudo extraer el titular")

    # Verificar corrupción
    problemas: list[str] = []
    if "\n" in titular or "\r" in titular:
        problemas.append("Contiene saltos de línea")
    if len(titular) > 60:
        problemas.append(f"Demasiado largo ({len(titular)} caracteres)")
    norm = normalizar_texto(titular)
    for basura in ["BENEFICIARIO", "DATO NO CERTIFICADO", "ESTE DOCUMENTO",
                    "ESTIMADO CLIENTE", "INFORMACION CONFIDENCIAL"]:
        if basura in norm:
            problemas.append(f"Contiene texto genérico: '{basura}'")
            break

    if not problemas:
        return h("V8.4", "Titular estado de cuenta", _B, _BN, True,
                 Severidad.MEDIA, f"Titular legible: '{titular}'",
                 titular=titular)

    # Si tiene saltos de línea, verificar si la primera línea es usable
    if "\n" in titular or "\r" in titular:
        primera_linea = titular.split("\n")[0].split("\r")[0].strip()
        if primera_linea and len(primera_linea) >= 5 and len(primera_linea) <= 60:
            norm_pl = normalizar_texto(primera_linea)
            es_basura = any(b in norm_pl for b in [
                "BENEFICIARIO", "DATO NO CERTIFICADO", "ESTE DOCUMENTO",
                "ESTIMADO CLIENTE", "INFORMACION CONFIDENCIAL",
            ])
            if not es_basura:
                return h("V8.4", "Titular estado de cuenta", _B, _BN, True,
                         Severidad.INFORMATIVA,
                         f"Titular con formato irregular pero primera línea legible: "
                         f"'{primera_linea}'",
                         titular=titular[:80], primera_linea=primera_linea,
                         problemas=problemas)

    return h("V8.4", "Titular estado de cuenta", _B, _BN, False,
             Severidad.MEDIA,
             f"Titular posiblemente corrupto: {', '.join(problemas)}",
             titular=titular[:80], problemas=problemas)
