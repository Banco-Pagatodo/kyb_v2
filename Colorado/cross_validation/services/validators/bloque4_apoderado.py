"""
BLOQUE 4: APODERADO LEGAL (Identidad y facultades)
V4.1 — Nombre del apoderado consistente entre INE y Poder
V4.2 — Apoderado aparece en estructura accionaria o consejo
V4.3 — Poder notarial otorgado por la empresa correcta
V4.4 — Facultades del apoderado suficientes
V4.5 — INE anverso vs reverso consistente
V4.6 — Poderes del representante legal verificados
"""
from __future__ import annotations

from ...models.schemas import Hallazgo, Severidad, ExpedienteEmpresa
from ..text_utils import (
    get_valor_str, get_valor, comparar_nombres,
    comparar_razones_sociales, normalizar_texto,
)
from .base import h, obtener_datos, obtener_reforma

_KEYWORDS_PODERES = [
    "ADMINISTRACION", "PLEITOS", "COBRANZAS", "DOMINIO",
    "CAMBIARIO", "ACTOS DE ADMINISTRACION", "GENERAL",
]

# ── Keywords específicas para apertura/operación bancaria (LGSM Art. 10) ──
_KEYWORDS_BANCARIAS = [
    "ABRIR CUENTAS",
    "APERTURA DE CUENTAS",
    "OPERACION DE CUENTAS",
    "OPERACIONES BANCARIAS",
    "CUENTAS BANCARIAS",
    "INSTITUCIONES DE CREDITO",
    "INSTITUCIONES BANCARIAS",
    "CONTRATAR SERVICIOS BANCARIOS",
    "SERVICIOS FINANCIEROS",
    "CAMBIARIO",
]

_B = 4
_BN = "APODERADO LEGAL"


def validar(exp: ExpedienteEmpresa) -> list[Hallazgo]:
    resultado = []
    resultado.append(_v4_1_nombre_apoderado(exp))
    resultado.append(_v4_2_apoderado_en_estructura(exp))
    resultado.append(_v4_3_poder_empresa_correcta(exp))
    resultado.append(_v4_4_facultades_suficientes(exp))
    resultado.append(_v4_5_ine_anverso_reverso(exp))
    resultado.append(_v4_6_poderes_verificados(exp))
    return resultado


def _extraer_nombre_ine(datos: dict) -> str:
    """Extrae el nombre completo de una INE."""
    # Intentar nombre_completo primero
    nombre = get_valor_str(datos, "nombre_completo")
    if nombre:
        return nombre

    # Construir desde FirstName + LastName
    first = get_valor_str(datos, "FirstName")
    last = get_valor_str(datos, "LastName")
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if last:
        return last

    # Intentar campos en español
    nombre_s = get_valor_str(datos, "nombre")
    apellidos = get_valor_str(datos, "apellidos")
    if nombre_s and apellidos:
        return f"{nombre_s} {apellidos}"

    return nombre_s or apellidos or ""


def _v4_1_nombre_apoderado(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.1 — Nombre del apoderado consistente entre INE y Poder."""
    ine = obtener_datos(exp, "ine")
    poder = obtener_datos(exp, "poder")

    if not ine:
        return h("V4.1", "Apoderado INE vs Poder", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró INE en el expediente")
    if not poder:
        return h("V4.1", "Apoderado INE vs Poder", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró Poder Notarial en el expediente")

    nombre_ine = _extraer_nombre_ine(ine)
    nombre_poder = get_valor_str(poder, "nombre_apoderado")

    if not nombre_ine:
        return h("V4.1", "Apoderado INE vs Poder", _B, _BN, None, Severidad.CRITICA,
                 "No se pudo extraer nombre del apoderado de la INE")
    if not nombre_poder:
        return h("V4.1", "Apoderado INE vs Poder", _B, _BN, None, Severidad.CRITICA,
                 "No se pudo extraer nombre del apoderado del Poder Notarial")

    coincide, sim = comparar_nombres(nombre_ine, nombre_poder)

    if coincide:
        return h("V4.1", "Apoderado INE vs Poder", _B, _BN, True, Severidad.CRITICA,
                 f"Nombre del apoderado coincide ({sim:.0%})",
                 ine=nombre_ine, poder=nombre_poder, similitud=sim)

    return h("V4.1", "Apoderado INE vs Poder", _B, _BN, False, Severidad.CRITICA,
             f"DISCREPANCIA: INE '{nombre_ine}' vs Poder '{nombre_poder}' ({sim:.0%})",
             ine=nombre_ine, poder=nombre_poder, similitud=sim)


def _v4_2_apoderado_en_estructura(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.2 — Apoderado aparece en estructura accionaria o consejo."""
    ine = obtener_datos(exp, "ine")
    if not ine:
        return h("V4.2", "Apoderado en estructura", _B, _BN, None,
                 Severidad.MEDIA,
                 "No se encontró INE para verificar")

    nombre_apoderado = _extraer_nombre_ine(ine)
    if not nombre_apoderado:
        return h("V4.2", "Apoderado en estructura", _B, _BN, None,
                 Severidad.MEDIA,
                 "No se pudo extraer nombre del apoderado")

    encontrado_en: list[str] = []
    norm_apoderado = normalizar_texto(nombre_apoderado)

    # Buscar en acta constitutiva → estructura_accionaria
    acta = obtener_datos(exp, "acta_constitutiva")
    if acta:
        estructura = get_valor(acta, "estructura_accionaria")
        if isinstance(estructura, list):
            for socio in estructura:
                nombre_socio = socio.get("nombre", "") if isinstance(socio, dict) else str(socio)
                coincide, _ = comparar_nombres(nombre_apoderado, nombre_socio, 0.80)
                if coincide:
                    encontrado_en.append(f"acta (accionista: {nombre_socio})")
                    break

    # Buscar en reforma → estructura_accionaria y consejo
    reforma = obtener_reforma(exp)
    if reforma:
        estructura = get_valor(reforma, "estructura_accionaria")
        if isinstance(estructura, list):
            for socio in estructura:
                nombre_socio = socio.get("nombre", "") if isinstance(socio, dict) else str(socio)
                coincide, _ = comparar_nombres(nombre_apoderado, nombre_socio, 0.80)
                if coincide:
                    encontrado_en.append(f"reforma (accionista: {nombre_socio})")
                    break

        consejo = get_valor(reforma, "consejo_administracion")
        if isinstance(consejo, list):
            for miembro in consejo:
                nombre_m = miembro.get("nombre", "") if isinstance(miembro, dict) else str(miembro)
                coincide, _ = comparar_nombres(nombre_apoderado, nombre_m, 0.80)
                if coincide:
                    encontrado_en.append(f"reforma (consejero: {nombre_m})")
                    break

    if encontrado_en:
        return h("V4.2", "Apoderado en estructura", _B, _BN, True,
                 Severidad.INFORMATIVA,
                 f"Apoderado '{nombre_apoderado}' encontrado en: {', '.join(encontrado_en)}",
                 apoderado=nombre_apoderado, encontrado_en=encontrado_en)

    # El apoderado/RL NO necesariamente es accionista ni consejero;
    # su ausencia en la estructura societaria es normal y no implica fallo.
    return h("V4.2", "Apoderado en estructura", _B, _BN, None,
             Severidad.INFORMATIVA,
             f"Apoderado '{nombre_apoderado}' no aparece como accionista ni consejero "
             "en la estructura societaria. Esto es normal — el apoderado/RL no está "
             "obligado a ser socio o consejero.",
             apoderado=nombre_apoderado)


def _v4_3_poder_empresa_correcta(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.3 — Poder notarial otorgado por la empresa correcta."""
    poder = obtener_datos(exp, "poder")
    if not poder:
        return h("V4.3", "Poder otorgado por empresa", _B, _BN, None,
                 Severidad.CRITICA, "No se encontró Poder Notarial en el expediente")

    poderdante = get_valor_str(poder, "nombre_poderdante")
    if not poderdante:
        return h("V4.3", "Poder otorgado por empresa", _B, _BN, None,
                 Severidad.CRITICA, "No se pudo extraer el nombre del poderdante")

    # Comparar con razón social de CSF o acta
    csf = obtener_datos(exp, "csf")
    razon_ref = ""
    if csf:
        razon_ref = get_valor_str(csf, "razon_social")
    if not razon_ref:
        acta = obtener_datos(exp, "acta_constitutiva")
        if acta:
            razon_ref = get_valor_str(acta, "denominacion_social")
    if not razon_ref:
        razon_ref = exp.razon_social

    coincide, sim, desc = comparar_razones_sociales(poderdante, razon_ref)

    if coincide:
        return h("V4.3", "Poder otorgado por empresa", _B, _BN, True,
                 Severidad.CRITICA,
                 f"El poderdante coincide con la empresa ({desc})",
                 poderdante=poderdante, empresa=razon_ref, similitud=sim)

    return h("V4.3", "Poder otorgado por empresa", _B, _BN, False,
             Severidad.CRITICA,
             f"DISCREPANCIA: Poderdante '{poderdante}' vs empresa '{razon_ref}' — {desc}",
             poderdante=poderdante, empresa=razon_ref, similitud=sim)


def _v4_4_facultades_suficientes(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.4 — Facultades del apoderado suficientes.

    LGSM Art. 10: el representante debe acreditar facultades para
    actos de administración **y** apertura / operación de cuentas
    bancarias.  Se incluyen los datos notariales del instrumento
    que contiene los poderes.  Severidad: CRITICA.
    """
    poder = obtener_datos(exp, "poder")
    if not poder:
        return h("V4.4", "Facultades suficientes", _B, _BN, None, Severidad.CRITICA,
                 "No se encontró Poder Notarial en el expediente")

    tipo_poder = get_valor_str(poder, "tipo_poder")
    facultades = get_valor_str(poder, "facultades")

    if not tipo_poder and not facultades:
        return h("V4.4", "Facultades suficientes", _B, _BN, None, Severidad.CRITICA,
                 "No se pudieron extraer tipo de poder ni facultades",
                 **_datos_notariales_poder(poder))

    # ── Textos normalizados para búsqueda ──
    tipo_norm = normalizar_texto(tipo_poder) if tipo_poder else ""
    fac_norm = normalizar_texto(facultades) if facultades else ""
    texto_completo = f"{tipo_norm} {fac_norm}"

    # 1) Verificar facultades de administración
    tiene_admin = any(kw in texto_completo for kw in [
        "ADMINISTRACION", "GENERAL", "AMPLIO", "PLEITOS Y COBRANZAS",
        "ACTOS DE ADMINISTRACION", "DOMINIO", "ADMINISTRAR",
    ])

    # 2) Verificar texto expreso de apertura / operación bancaria
    tiene_bancaria = any(kw in texto_completo for kw in _KEYWORDS_BANCARIAS)

    # 3) Keywords encontradas (para detalle)
    kw_admin_encontradas = [kw for kw in [
        "ADMINISTRACION", "GENERAL", "AMPLIO", "PLEITOS Y COBRANZAS",
        "ACTOS DE ADMINISTRACION", "DOMINIO", "ADMINISTRAR",
    ] if kw in texto_completo]
    kw_bancarias_encontradas = [kw for kw in _KEYWORDS_BANCARIAS if kw in texto_completo]

    # ── Datos notariales para incluir en el hallazgo ──
    detalles_notariales = _datos_notariales_poder(poder)

    # ── Bloque de detalle común ──
    detalle_campos = []
    if tipo_poder:
        detalle_campos.append(f"Tipo de poder: {tipo_poder}")
    if facultades:
        detalle_campos.append(f"Facultades: {facultades}")
    detalle_base = ". ".join(detalle_campos)

    if tiene_admin and tiene_bancaria:
        kw_txt = ", ".join(kw_bancarias_encontradas)
        return h("V4.4", "Facultades suficientes", _B, _BN, True, Severidad.CRITICA,
                 f"Poder con actos de administración y facultades bancarias expresas. "
                 f"{detalle_base}. "
                 f"Keywords bancarias detectadas: {kw_txt}",
                 tipo_poder=tipo_poder, facultades=facultades,
                 tiene_admin=True, tiene_bancaria=True,
                 keywords_admin=kw_admin_encontradas,
                 keywords_bancarias=kw_bancarias_encontradas,
                 **detalles_notariales)

    if tiene_admin and not tiene_bancaria:
        kw_buscadas = ", ".join(_KEYWORDS_BANCARIAS)
        return h("V4.4", "Facultades suficientes", _B, _BN, False, Severidad.CRITICA,
                 f"Poder con facultades de administración PERO sin mención expresa "
                 f"de apertura/operación de cuentas bancarias. "
                 f"{detalle_base}. "
                 f"Keywords admin detectadas: {', '.join(kw_admin_encontradas)}. "
                 f"Keywords bancarias buscadas (ninguna encontrada): {kw_buscadas}. "
                 f"Se requiere texto expreso conforme a LGSM Art. 10.",
                 tipo_poder=tipo_poder, facultades=facultades,
                 tiene_admin=True, tiene_bancaria=False,
                 keywords_admin=kw_admin_encontradas,
                 keywords_bancarias=[],
                 **detalles_notariales)

    return h("V4.4", "Facultades suficientes", _B, _BN, False, Severidad.CRITICA,
             f"Facultades insuficientes. {detalle_base}. "
             f"Se requieren actos de administración y apertura/operación de "
             f"cuentas bancarias (LGSM Art. 10). "
             f"Keywords admin buscadas: ADMINISTRACION, GENERAL, DOMINIO, etc. "
             f"Keywords bancarias buscadas: {', '.join(_KEYWORDS_BANCARIAS)}.",
             tipo_poder=tipo_poder, facultades=facultades,
             tiene_admin=tiene_admin, tiene_bancaria=tiene_bancaria,
             keywords_admin=kw_admin_encontradas,
             keywords_bancarias=[],
             **detalles_notariales)


def _datos_notariales_poder(poder: dict) -> dict:
    """Extrae datos notariales del instrumento que contiene los poderes."""
    datos: dict[str, str] = {}
    for campo, clave in [
        ("numero_escritura_poliza", "escritura"),
        ("nombre_notario", "notario"),
        ("numero_notaria", "notaria"),
        ("estado_notaria", "estado_notaria"),
        ("fecha_otorgamiento", "fecha"),
        ("fecha_escritura", "fecha"),
        ("lugar_otorgamiento", "lugar"),
    ]:
        val = get_valor_str(poder, campo)
        if val and clave not in datos:
            datos[clave] = val
    return {"datos_notariales": datos} if datos else {}


# Campos que sólo aparecen en el reverso de la INE mexicana.
# Si el documento INE (anverso) contiene alguno de estos campos,
# significa que ambas caras fueron escaneadas juntas.
_CAMPOS_REVERSO_INE = {
    "MachineReadableZone", "machinereadablezone",
    "CIC", "cic",
    "codigo_ocr", "numero_vertical",
    "barcode", "codigo_barras",
    "numero_seguridad",
}


def _ine_contiene_reverso(ine: dict) -> bool:
    """Detecta si el documento INE (anverso) contiene también el reverso.

    Cubre dos escenarios:
      1. **Multi-página**: el archivo tiene ≥2 páginas (Azure extrae campos
         con ``pagina >= 2``).
      2. **Misma página**: ambas caras escaneadas en una sola imagen. Se
         detecta por la presencia de campos exclusivos del reverso
         (MachineReadableZone, CIC, código de barras, etc.).
    """
    for campo, valor in ine.items():
        if isinstance(valor, dict):
            # Escenario 1: campo en página ≥ 2
            pagina = valor.get("pagina")
            if pagina is not None:
                try:
                    if int(pagina) >= 2:
                        return True
                except (ValueError, TypeError):
                    pass

        # Escenario 2: campo exclusivo del reverso presente (cualquier página)
        if campo in _CAMPOS_REVERSO_INE:
            return True

    return False


def _v4_5_ine_anverso_reverso(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.5 — INE anverso vs reverso consistente."""
    ine = obtener_datos(exp, "ine")
    ine_rev = obtener_datos(exp, "ine_reverso")

    # ── Caso: INE anverso contiene ambas caras en un solo documento ──
    if ine and not ine_rev and _ine_contiene_reverso(ine):
        return h("V4.5", "INE anverso vs reverso", _B, _BN, True, Severidad.CRITICA,
                 "El documento INE (anverso) contiene ambas caras (anverso y reverso) "
                 "en un solo archivo. Se considera identificación completa.",
                 ine_doble_cara=True)

    if not ine or not ine_rev:
        faltantes = []
        if not ine:
            faltantes.append("INE anverso")
        if not ine_rev:
            faltantes.append("INE reverso")
        return h("V4.5", "INE anverso vs reverso", _B, _BN, False, Severidad.CRITICA,
                 f"Identificación INCOMPLETA: falta(n) {', '.join(faltantes)}. "
                 "Se requieren ambas caras de la INE para validar la identidad del apoderado.",
                 faltantes=faltantes)

    # Comparar campos comunes
    discrepancias: list[str] = []

    for campo_frente, campo_reverso in [
        ("FirstName", "FirstName"),
        ("LastName", "LastName"),
        ("DateOfBirth", "DateOfBirth"),
        ("nombre", "nombre"),
        ("apellidos", "apellidos"),
    ]:
        val_frente = get_valor_str(ine, campo_frente)
        val_reverso = get_valor_str(ine_rev, campo_reverso)

        if val_frente and val_reverso:
            if normalizar_texto(val_frente) != normalizar_texto(val_reverso):
                discrepancias.append(
                    f"{campo_frente}: frente='{val_frente}' vs reverso='{val_reverso}'"
                )

    if not discrepancias:
        return h("V4.5", "INE anverso vs reverso", _B, _BN, True, Severidad.CRITICA,
                 "Datos de INE anverso y reverso son consistentes")

    return h("V4.5", "INE anverso vs reverso", _B, _BN, False, Severidad.CRITICA,
             "DISCREPANCIA entre INE anverso y reverso:\n  " +
             "\n  ".join(discrepancias),
             discrepancias=discrepancias)


def _v4_6_poderes_verificados(exp: ExpedienteEmpresa) -> Hallazgo:
    """V4.6 — Verificar que existan poderes del representante legal.

    El Acta Constitutiva generalmente integra poderes otorgados a los
    administradores. Si no, debe existir un Poder Notarial independiente.
    """
    poder = obtener_datos(exp, "poder")

    # ── Poder Notarial independiente existe ──
    if poder:
        tipo = get_valor_str(poder, "tipo_poder")
        apoderado = get_valor_str(poder, "nombre_apoderado")
        partes = ["Poderes verificados mediante Poder Notarial independiente"]
        if apoderado:
            partes.append(f"Apoderado: {apoderado}")
        if tipo:
            partes.append(f"Facultades: {tipo[:120]}")
        return h("V4.6", "Poderes del representante", _B, _BN, True, Severidad.MEDIA,
                 ". ".join(partes), fuente="poder_notarial")

    # ── No hay poder independiente → buscar indicios en acta / reforma ──
    acta = obtener_datos(exp, "acta_constitutiva")
    reforma = obtener_reforma(exp)

    # Reforma con consejo de administración implica poderes conferidos
    if reforma:
        consejo = get_valor(reforma, "consejo_administracion")
        if isinstance(consejo, list) and len(consejo) > 0:
            miembros = ", ".join(
                m.get("nombre", "?") if isinstance(m, dict) else str(m)
                for m in consejo[:5]
            )
            return h("V4.6", "Poderes del representante", _B, _BN, True, Severidad.MEDIA,
                     f"No hay Poder Notarial independiente, pero la reforma de estatutos "
                     f"establece consejo de administración ({len(consejo)} miembros: {miembros}). "
                     "Los poderes pueden estar integrados en el acta constitutiva.",
                     fuente="reforma_consejo")

    # Acta existe pero no hay poder ni consejo
    if acta:
        return h("V4.6", "Poderes del representante", _B, _BN, False, Severidad.MEDIA,
                 "No se encontró Poder Notarial independiente ni consejo de administración "
                 "en la reforma. Verificar que los poderes estén integrados en el "
                 "Acta Constitutiva.",
                 fuente="no_poder_encontrado")

    # Ni acta ni poder
    return h("V4.6", "Poderes del representante", _B, _BN, False, Severidad.MEDIA,
             "No se encontraron poderes del representante legal. "
             "No hay Poder Notarial ni Acta Constitutiva en el expediente.",
             fuente="sin_documentos")
