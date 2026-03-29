"""
BLOQUE 5: ESTRUCTURA SOCIETARIA
V5.1 — Estructura accionaria completa
V5.2 — Evolución accionaria (constitutiva vs reforma)
V5.3 — Capital social extraído
V5.4 — Cláusula de exclusión de extranjeros
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import get_valor, get_valor_str, get_confiabilidad, normalizar_texto
from .base import h, obtener_datos, obtener_reforma

_B = 5
_BN = "ESTRUCTURA SOCIETARIA"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v5_1_estructura_completa(exp))
    resultado.append(_v5_2_evolucion_accionaria(exp))
    resultado.append(_v5_3_capital_social(exp))
    resultado.append(_v5_4_clausula_extranjeros(exp))
    return resultado


def _v5_1_estructura_completa(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.1 — Estructura accionaria completa."""
    acta = obtener_datos(exp, "acta_constitutiva")
    if not acta:
        return h("V5.1", "Estructura accionaria completa", _B, _BN, None,
                 Severidad.MEDIA, "No se encontró Acta Constitutiva en el expediente")

    estructura = get_valor(acta, "estructura_accionaria")
    status = get_valor_str(acta, "_estructura_accionaria_status")
    suma = get_valor(acta, "_suma_porcentajes")
    confiabilidad = get_valor(acta, "_estructura_confiabilidad")

    if not estructura or not isinstance(estructura, list):
        return h("V5.1", "Estructura accionaria completa", _B, _BN, False,
                 Severidad.MEDIA,
                 "No se encontró estructura accionaria en el Acta Constitutiva",
                 status=status)

    n_socios = len(estructura)

    # Evaluar status
    if status == "Verificada":
        # Verificar suma de porcentajes
        if suma is not None:
            try:
                suma_f = float(suma)
            except (ValueError, TypeError):
                suma_f = 0.0
            if 99.0 <= suma_f <= 101.0:
                return h("V5.1", "Estructura accionaria completa", _B, _BN, True,
                         Severidad.MEDIA,
                         f"Estructura verificada: {n_socios} socios, suma {suma_f}%",
                         socios=n_socios, suma=suma_f, status=status,
                         confiabilidad=confiabilidad,
                         accionistas=estructura)
            else:
                return h("V5.1", "Estructura accionaria completa", _B, _BN, False,
                         Severidad.CRITICA,
                         f"Suma de porcentajes NO cuadra: {suma_f}% (esperado ~100%)",
                         socios=n_socios, suma=suma_f, status=status,
                         accionistas=estructura)
        return h("V5.1", "Estructura accionaria completa", _B, _BN, True,
                 Severidad.MEDIA,
                 f"Estructura verificada: {n_socios} socios",
                 socios=n_socios, status=status,
                 accionistas=estructura)

    elif status == "Estructura_Implicita":
        return h("V5.1", "Estructura accionaria completa", _B, _BN, False,
                 Severidad.MEDIA,
                 f"Estructura implícita: {n_socios} socios identificados pero sin "
                 "distribución individual de acciones",
                 socios=n_socios, status=status, confiabilidad=confiabilidad,
                 accionistas=estructura)

    elif status in ("Parcial", "No_Confiable"):
        return h("V5.1", "Estructura accionaria completa", _B, _BN, False,
                 Severidad.MEDIA,
                 f"Estructura {status}: {n_socios} socios, requiere verificación manual",
                 socios=n_socios, status=status, suma=suma,
                 accionistas=estructura)

    return h("V5.1", "Estructura accionaria completa", _B, _BN, None,
             Severidad.MEDIA,
             f"Status desconocido: '{status}', {n_socios} socios",
             socios=n_socios, status=status, suma=suma,
             accionistas=estructura)


def _v5_2_evolucion_accionaria(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.2 — Evolución accionaria (constitutiva vs reforma)."""
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)

    if not acta or not reforma:
        return h("V5.2", "Evolución accionaria", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No hay acta y reforma para comparar evolución")

    est_acta = get_valor(acta, "estructura_accionaria")
    est_reforma = get_valor(reforma, "estructura_accionaria")

    if not isinstance(est_acta, list) or not isinstance(est_reforma, list):
        return h("V5.2", "Evolución accionaria", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No se puede comparar estructura (datos incompletos)")

    nombres_acta = {
        normalizar_texto(s.get("nombre", ""))
        for s in est_acta
        if isinstance(s, dict) and s.get("nombre")
    }
    nombres_reforma = {
        normalizar_texto(s.get("nombre", ""))
        for s in est_reforma
        if isinstance(s, dict) and s.get("nombre")
    }

    nuevos = nombres_reforma - nombres_acta
    salieron = nombres_acta - nombres_reforma
    permanecen = nombres_acta & nombres_reforma

    msg_parts = [f"Fundadores: {len(nombres_acta)}, Actuales: {len(nombres_reforma)}"]
    if permanecen:
        msg_parts.append(f"Permanecen: {len(permanecen)}")
    if nuevos:
        msg_parts.append(f"Nuevos: {', '.join(nuevos)}")
    if salieron:
        msg_parts.append(f"Salieron: {', '.join(salieron)}")

    # Extraer fecha de la reforma para el reporte
    fecha_reforma = get_valor_str(reforma, "fecha_otorgamiento")

    return h("V5.2", "Evolución accionaria", _B, _BN, True,
             Severidad.INFORMATIVA,
             " | ".join(msg_parts),
             fundadores=list(nombres_acta), actuales=list(nombres_reforma),
             nuevos=list(nuevos), salieron=list(salieron),
             accionistas_acta=est_acta, accionistas_reforma=est_reforma,
             fecha_reforma=fecha_reforma)


def _v5_3_capital_social(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.3 — Capital social extraído."""
    # Priorizar reforma sobre acta
    reforma = obtener_reforma(exp)
    acta = obtener_datos(exp, "acta_constitutiva")

    fuente = ""
    capital = None
    confiab = 0.0

    if reforma:
        capital = get_valor(reforma, "capital_social")
        confiab = get_confiabilidad(reforma, "capital_social")
        fuente = "reforma"

    if capital is None and acta:
        capital = get_valor(acta, "capital_social")
        confiab = get_confiabilidad(acta, "capital_social")
        fuente = "acta_constitutiva"

    if capital is None:
        return h("V5.3", "Capital social", _B, _BN, None, Severidad.MEDIA,
                 "No se encontró capital social en ningún documento")

    try:
        capital_f = float(str(capital).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        capital_f = 0.0

    if capital_f == 0 and confiab < 80:
        return h("V5.3", "Capital social", _B, _BN, False, Severidad.MEDIA,
                 f"Capital social $0 con confiabilidad {confiab}% — probable extracción fallida",
                 capital=capital, confiabilidad=confiab, fuente=fuente)

    if capital_f > 0:
        return h("V5.3", "Capital social", _B, _BN, True, Severidad.MEDIA,
                 f"Capital social: ${capital_f:,.2f} ({fuente}, confiabilidad {confiab}%)",
                 capital=capital_f, confiabilidad=confiab, fuente=fuente)

    return h("V5.3", "Capital social", _B, _BN, None, Severidad.MEDIA,
             f"Capital social: {capital} ({fuente}), requiere verificación",
             capital=capital, confiabilidad=confiab, fuente=fuente)


def _v5_4_clausula_extranjeros(exp: ExpedienteEmpresa) -> Hallazgo:
    """V5.4 — Cláusula de exclusión de extranjeros."""
    acta = obtener_datos(exp, "acta_constitutiva")
    if not acta:
        return h("V5.4", "Cláusula extranjeros", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No se encontró Acta Constitutiva en el expediente")

    clausula = get_valor_str(acta, "clausula_extranjeros")
    if not clausula:
        return h("V5.4", "Cláusula extranjeros", _B, _BN, None,
                 Severidad.INFORMATIVA,
                 "No se encontró cláusula de extranjeros en el Acta")

    clausula_norm = normalizar_texto(clausula)
    if "EXCLUSION" in clausula_norm and "EXTRANJERO" in clausula_norm:
        return h("V5.4", "Cláusula extranjeros", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"Cláusula de exclusión de extranjeros: {clausula}",
                 clausula=clausula)

    return h("V5.4", "Cláusula extranjeros", _B, _BN, True,
             Severidad.INFORMATIVA,
             f"Cláusula de extranjeros encontrada: {clausula}",
             clausula=clausula)
