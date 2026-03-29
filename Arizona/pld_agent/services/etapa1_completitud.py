"""
Etapa 1 — Recepción y verificación de completitud documental.
Disposición 4ª de las DCG del artículo 115 de la Ley de Instituciones de Crédito.

Verifica que el expediente contenga:
1. Documentos soporte obligatorios
2. Datos obligatorios de la Persona Moral
3. Domicilio completo
4. Identificación de administradores / directores / apoderados
5. Poder para abrir cuentas bancarias
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..core.config import (
    CAMPOS_ALIAS,
    CAMPOS_DOMICILIO,
    CAMPOS_OBLIGATORIOS,
    DOCS_DOMICILIO_ALTERNATIVOS,
    DOCS_INE_ALTERNATIVOS,
    DOCS_OBLIGATORIOS_PLD,
)
from ..core.normalize import normalizar_nombre as _normalizar_nombre
from ..models.schemas import (
    ExpedientePLD,
    ItemCompletitud,
    PersonaIdentificada,
    ResultadoCompletitud,
    SeveridadPLD,
    VerificacionCompletitud,
)

logger = logging.getLogger("arizona.etapa1")


# ═══════════════════════════════════════════════════════════════════
#  Palabras clave para poder de cuentas bancarias
# ═══════════════════════════════════════════════════════════════════

_KEYWORDS_PODER_BANCARIO: list[str] = [
    "abrir cuentas",
    "apertura de cuentas",
    "cuentas bancarias",
    "cuentas de cheques",
    "contratos bancarios",
    "operaciones bancarias",
    "servicios bancarios",
    "contratos de crédito",
    "líneas de crédito",
    "instituciones de crédito",
    "instituciones bancarias",
    "abrir, cerrar y manejar cuentas",
    "operar cuentas",
    "firmar contratos bancarios",
    "actos de administración bancaria",
    # ── agregados: detectar facultades genéricas comunes ──
    "actos de administracion",
    "actos de administración",
    "poder general",
    "cambiario",
    "servicios financieros",
    "poder para actos de administracion",
    "poder para actos de administración",
    "actos de dominio",
]


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _obtener_datos(
    expediente: ExpedientePLD,
    doc_type: str,
) -> dict[str, Any]:
    """Obtiene datos_extraidos de un doc_type (dict vacío si no existe)."""
    return expediente.documentos.get(doc_type, {})


def _get_valor(datos: dict[str, Any], campo: str) -> Any:
    """Extrae el valor de un campo de datos_extraidos.

    Dakota almacena campos con formato enriched:
      {"campo": {"valor": X, "confiabilidad": Y}}
    Esta función desenvuelve automáticamente ese formato.
    
    También busca alias de campos definidos en CAMPOS_ALIAS.
    """
    if not datos:
        return None
    
    # Buscar campo principal y sus alias
    campos_a_buscar = [campo] + CAMPOS_ALIAS.get(campo, [])
    
    for c in campos_a_buscar:
        field = datos.get(c)
        if field is not None:
            if isinstance(field, dict) and "valor" in field:
                v = field.get("valor")
                if v is not None and v != "" and v != "N/A":
                    return v
            elif field not in (None, "", "N/A"):
                return field
    
    return None


def _get_valor_str(datos: dict[str, Any], campo: str) -> str:
    """Extrae el valor como string, devuelve '' si no existe."""
    v = _get_valor(datos, campo)
    if v is None:
        return ""
    return str(v).strip()


def _nombre_completo(nombre: str) -> bool:
    """True si el nombre tiene al menos 3 componentes (nombre + 2 apellidos)."""
    partes = _normalizar_nombre(nombre).split()
    return len(partes) >= 3


def _campo_presente(datos: dict[str, Any], campo: str) -> bool:
    """True si el campo existe y tiene contenido significativo."""
    valor = _get_valor(datos, campo)
    if valor is None:
        return False
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, list):
        return len(valor) > 0
    if isinstance(valor, dict):
        return len(valor) > 0
    return True


def _detectar_poder_bancario(expediente: ExpedientePLD) -> bool | None:
    """
    Detecta si el poder incluye facultad para abrir/operar cuentas bancarias.
    Retorna True/False/None.
    """
    # 1. Primero revisar si Colorado ya lo determinó
    if expediente.datos_clave:
        poder_bc = expediente.datos_clave.get("poder_cuenta_bancaria")
        if poder_bc is not None:
            return poder_bc

    # 2. Buscar en datos del poder directamente
    poder = _obtener_datos(expediente, "poder")
    if not poder:
        return None

    campos_texto = ["facultades", "tipo_poder", "alcance_poder", "objeto_poder"]
    for campo in campos_texto:
        valor = _get_valor_str(poder, campo)
        if valor:
            texto = valor.lower()
            for kw in _KEYWORDS_PODER_BANCARIO:
                if kw in texto:
                    return True

    return False


# ═══════════════════════════════════════════════════════════════════
#  Verificación de documentos obligatorios
# ═══════════════════════════════════════════════════════════════════

def _verificar_documentos(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    """Verifica que estén presentes todos los documentos obligatorios PLD."""
    items: list[ItemCompletitud] = []
    contador = 1

    for doc_type in DOCS_OBLIGATORIOS_PLD:
        # Caso especial: domicilio acepta alternativas
        if doc_type == "domicilio":
            tiene_domicilio = any(
                alt in expediente.doc_types_presentes
                for alt in DOCS_DOMICILIO_ALTERNATIVOS
            )
            fuente_dom = next(
                (alt for alt in DOCS_DOMICILIO_ALTERNATIVOS
                 if alt in expediente.doc_types_presentes),
                "",
            )
            items.append(ItemCompletitud(
                codigo=f"A1.{contador}",
                categoria="DOCUMENTO",
                elemento=f"Comprobante de domicilio ({doc_type})",
                presente=tiene_domicilio,
                fuente=fuente_dom if tiene_domicilio else "",
                detalle="Aceptado: domicilio o estado de cuenta" if tiene_domicilio else "Falta comprobante de domicilio o estado de cuenta",
                severidad=SeveridadPLD.CRITICA,
            ))
        # Caso especial: INE acepta alternativas (ine_propietario_real)
        elif doc_type == "ine":
            tiene_ine = any(
                alt in expediente.doc_types_presentes
                for alt in DOCS_INE_ALTERNATIVOS
            )
            fuente_ine = next(
                (alt for alt in DOCS_INE_ALTERNATIVOS
                 if alt in expediente.doc_types_presentes),
                "",
            )
            items.append(ItemCompletitud(
                codigo=f"A1.{contador}",
                categoria="DOCUMENTO",
                elemento=_nombre_documento(doc_type),
                presente=tiene_ine,
                fuente=fuente_ine if tiene_ine else "",
                detalle="" if tiene_ine else "Falta identificación oficial (INE)",
                severidad=SeveridadPLD.CRITICA,
            ))
        else:
            presente = doc_type in expediente.doc_types_presentes
            items.append(ItemCompletitud(
                codigo=f"A1.{contador}",
                categoria="DOCUMENTO",
                elemento=_nombre_documento(doc_type),
                presente=presente,
                fuente=doc_type if presente else "",
                detalle="" if presente else f"Documento '{doc_type}' no encontrado en el expediente",
                severidad=SeveridadPLD.CRITICA,
            ))
        contador += 1

    return items


def _nombre_documento(doc_type: str) -> str:
    """Nombre legible de un tipo de documento."""
    nombres = {
        "acta_constitutiva": "Testimonio de escritura constitutiva (inscrita en RPP)",
        "csf": "Cédula de Identificación Fiscal (CSF)",
        "domicilio": "Comprobante de domicilio",
        "poder": "Testimonio del instrumento con poderes del representante legal",
        "ine": "Identificación oficial vigente (INE) del representante legal",
        "fiel": "e.firma (FIEL)",
        "estado_cuenta": "Estado de cuenta bancario",
        "reforma_estatutos": "Reforma de estatutos",
    }
    return nombres.get(doc_type, doc_type)


# ═══════════════════════════════════════════════════════════════════
#  Verificación de datos obligatorios
# ═══════════════════════════════════════════════════════════════════

def _verificar_datos_obligatorios(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    """Verifica los datos obligatorios de la Persona Moral.
    
    Prioriza datos_clave de Colorado (ya validados) sobre documentos raw.
    """
    items: list[ItemCompletitud] = []
    base = 10  # A2.x
    
    # Intentar usar datos_clave de Colorado primero
    dc = expediente.datos_clave
    
    # ── Mapa de campos que pueden venir de datos_clave ──
    # (nombre_display, campo_datos_clave, doc_fallback, campo_fallback)
    campos_con_dc = [
        ("Denominación / razón social", "razon_social", "csf", "denominacion_razon_social"),
        ("RFC con homoclave", "rfc", "csf", "rfc"),
        ("e.firma (FIEL) — número de serie", "numero_serie_fiel", "fiel", "no_serie"),
        ("Objeto social / giro mercantil", "giro_mercantil", "csf", "actividad_economica"),
        ("Fecha de constitución", "fecha_constitucion", "acta_constitutiva", "fecha_constitucion"),
    ]
    
    for i, (nombre, campo_dc, doc_fallback, campo_fallback) in enumerate(campos_con_dc):
        valor = ""
        fuente = ""
        presente = False
        
        # Intentar datos_clave primero
        if dc and isinstance(dc, dict):
            val_dc = dc.get(campo_dc)
            if val_dc and str(val_dc).strip() and str(val_dc).strip() not in ("N/A", "None"):
                valor = str(val_dc).strip()
                fuente = "datos_clave"
                presente = True
        
        # Fallback a documentos raw
        if not presente:
            datos = _obtener_datos(expediente, doc_fallback)
            if _campo_presente(datos, campo_fallback):
                valor = _get_valor_str(datos, campo_fallback)
                fuente = doc_fallback
                presente = bool(valor)
        
        items.append(ItemCompletitud(
            codigo=f"A2.{i + 1}",
            categoria="DATO_OBLIGATORIO",
            elemento=nombre,
            presente=presente,
            fuente=fuente,
            detalle=valor[:120] if presente else f"Campo '{campo_fallback}' no encontrado",
            severidad=SeveridadPLD.CRITICA,
        ))

    # Actividad económica adicional (redundante con giro_mercantil, pero se mantiene para compatibilidad)
    csf = _obtener_datos(expediente, "csf")
    acta = _obtener_datos(expediente, "acta_constitutiva")
    
    # Primero verificar datos_clave
    giro_dc = dc.get("giro_mercantil") if dc and isinstance(dc, dict) else ""
    if giro_dc and str(giro_dc).strip():
        tiene_giro = True
        fuente_giro = "datos_clave"
        detalle_giro = str(giro_dc).strip()
    else:
        tiene_giro = _campo_presente(csf, "actividad_economica") or _campo_presente(acta, "objeto_social")
        fuente_giro = "csf" if _campo_presente(csf, "actividad_economica") else ("acta_constitutiva" if _campo_presente(acta, "objeto_social") else "")
        detalle_giro = (_get_valor_str(csf, "actividad_economica") or _get_valor_str(acta, "objeto_social")) if tiene_giro else ""
    
    items.append(ItemCompletitud(
        codigo=f"A2.{len(campos_con_dc) + 1}",
        categoria="DATO_OBLIGATORIO",
        elemento="Giro mercantil / actividad económica",
        presente=tiene_giro,
        fuente=fuente_giro,
        detalle=detalle_giro[:120] if tiene_giro else "No se encontró actividad económica ni objeto social",
        severidad=SeveridadPLD.ALTA,
    ))

    return items


# ═══════════════════════════════════════════════════════════════════
#  Verificación de domicilio completo
# ═══════════════════════════════════════════════════════════════════

def _verificar_domicilio(expediente: ExpedientePLD) -> list[ItemCompletitud]:
    """Verifica campos individuales del domicilio."""
    items: list[ItemCompletitud] = []
    base = 20  # A3.x

    # Buscar domicilio en CSF o en comprobante de domicilio
    csf_dom = _obtener_datos(expediente, "csf")
    comp_dom = _obtener_datos(expediente, "domicilio")

    # Intentar domicilio anidado en CSF
    domicilio_raw = _get_valor(csf_dom, "domicilio")
    if isinstance(domicilio_raw, dict):
        fuente_dom = domicilio_raw
        fuente_nombre = "csf"
    else:
        fuente_dom = csf_dom
        fuente_nombre = "csf"

    for i, (nombre_display, campo) in enumerate(CAMPOS_DOMICILIO):
        # Buscar en CSF → domicilio anidado → comprobante de domicilio
        presente = (
            _campo_presente(fuente_dom, campo)
            or _campo_presente(csf_dom, campo)
            or _campo_presente(comp_dom, campo)
        )
        if _campo_presente(fuente_dom, campo):
            src = fuente_nombre
            val = _get_valor_str(fuente_dom, campo)
        elif _campo_presente(csf_dom, campo):
            src = "csf"
            val = _get_valor_str(csf_dom, campo)
        elif _campo_presente(comp_dom, campo):
            src = "domicilio"
            val = _get_valor_str(comp_dom, campo)
        else:
            src = ""
            val = ""

        items.append(ItemCompletitud(
            codigo=f"A3.{i + 1}",
            categoria="DOMICILIO",
            elemento=f"Domicilio — {nombre_display}",
            presente=presente,
            fuente=src,
            detalle=str(val)[:80] if presente else f"Campo '{campo}' no encontrado",
            severidad=SeveridadPLD.ALTA,
        ))

    return items


# ═══════════════════════════════════════════════════════════════════
#  Identificación de personas (administradores, apoderados, etc.)
# ═══════════════════════════════════════════════════════════════════

def _identificar_personas(expediente: ExpedientePLD) -> tuple[list[ItemCompletitud], list[PersonaIdentificada]]:
    """
    Identifica personas relevantes del expediente.
    Retorna items de completitud + lista de personas para screening posterior.
    """
    items: list[ItemCompletitud] = []
    personas: list[PersonaIdentificada] = []
    base = 30  # A4.x

    # 1. Usar datos_clave de Colorado si están disponibles
    if expediente.datos_clave:
        dc = expediente.datos_clave

        # Apoderados
        apoderados = dc.get("apoderados", [])
        for ap in apoderados:
            if isinstance(ap, dict) and ap.get("nombre"):
                personas.append(PersonaIdentificada(
                    nombre=ap["nombre"],
                    rol="apoderado",
                    fuente=ap.get("fuente", "datos_clave"),
                    tipo_persona=ap.get("tipo_persona", "fisica"),
                    porcentaje=None,
                    requiere_screening=True,
                ))

        # Representante legal
        rep = dc.get("representante_legal")
        if isinstance(rep, dict) and rep.get("nombre"):
            personas.append(PersonaIdentificada(
                nombre=rep["nombre"],
                rol="representante_legal",
                fuente=rep.get("fuente", "datos_clave"),
                tipo_persona=rep.get("tipo_persona", "fisica"),
                requiere_screening=True,
            ))

        # Accionistas
        accionistas = dc.get("accionistas", [])
        for acc in accionistas:
            if isinstance(acc, dict) and acc.get("nombre"):
                personas.append(PersonaIdentificada(
                    nombre=acc["nombre"],
                    rol="accionista",
                    fuente=acc.get("fuente", "datos_clave"),
                    tipo_persona=acc.get("tipo_persona", "fisica"),
                    porcentaje=acc.get("porcentaje"),
                    requiere_screening=True,
                ))

        # Consejo de administración
        consejo = dc.get("consejo_administracion", [])
        for c in consejo:
            if isinstance(c, dict) and c.get("nombre"):
                personas.append(PersonaIdentificada(
                    nombre=c["nombre"],
                    rol="consejero",
                    fuente=c.get("fuente", "datos_clave"),
                    tipo_persona=c.get("tipo_persona", "fisica"),
                    requiere_screening=True,
                ))

    else:
        # 2. Fallback: extraer directamente de los documentos
        _extraer_personas_de_documentos(expediente, personas)

    # 2a. Siempre extraer apoderado del poder si no fue encontrado en datos_clave
    _extraer_apoderado_de_poder(expediente, personas)

    # 2b. Buscar referencia al Consejo de Administración en poder (BUG-04)
    _detectar_consejo_desde_poder(expediente, personas)

    # 3. Deduplicar personas por nombre normalizado (BUG-03 / BUG-06)
    personas = _deduplicar_personas(personas)

    # 4. Enriquecer con CURP del INE cuando esté disponible (BUG-07)
    _enriquecer_curp_desde_ine(expediente, personas)

    # Generar items de completitud
    tiene_apoderado = any(p.rol in ("apoderado", "representante_legal") for p in personas)
    tiene_accionistas = any(p.rol == "accionista" for p in personas)
    tiene_admin = any(p.rol in ("consejero", "administrador", "representante_legal") for p in personas)

    items.append(ItemCompletitud(
        codigo="A4.1",
        categoria="PERSONAS",
        elemento="Apoderado / representante legal identificado",
        presente=tiene_apoderado,
        fuente="datos_clave" if expediente.datos_clave else "documentos",
        detalle=f"{sum(1 for p in personas if p.rol in ('apoderado', 'representante_legal'))} persona(s)" if tiene_apoderado else "No se identificaron apoderados ni representante legal",
        severidad=SeveridadPLD.CRITICA,
    ))

    items.append(ItemCompletitud(
        codigo="A4.2",
        categoria="PERSONAS",
        elemento="Accionistas / socios identificados",
        presente=tiene_accionistas,
        fuente="datos_clave" if expediente.datos_clave else "documentos",
        detalle=f"{sum(1 for p in personas if p.rol == 'accionista')} accionista(s)" if tiene_accionistas else "No se identificaron accionistas",
        severidad=SeveridadPLD.ALTA,
    ))

    items.append(ItemCompletitud(
        codigo="A4.3",
        categoria="PERSONAS",
        elemento="Administradores / directores / consejeros identificados",
        presente=tiene_admin,
        fuente="datos_clave" if expediente.datos_clave else "documentos",
        detalle=f"{sum(1 for p in personas if p.rol in ('consejero', 'administrador', 'representante_legal'))} persona(s)" if tiene_admin else "No se identificaron administradores/consejeros",
        severidad=SeveridadPLD.ALTA,
    ))

    # ── A4.4–A4.6: Validar nombres completos (Nombre + Primer Apellido + Segundo Apellido) ──
    _roles_grupos = [
        ("A4.4", "apoderado", ("apoderado", "representante_legal"), "apoderados/representantes legales"),
        ("A4.5", "accionista", ("accionista",), "accionistas"),
        ("A4.6", "administrador", ("consejero", "administrador", "representante_legal"), "administradores/consejeros"),
    ]
    for codigo, _etiqueta, roles_set, roles_display in _roles_grupos:
        grupo = [p for p in personas if p.rol in roles_set and p.tipo_persona == "fisica"]
        incompletos = [p.nombre for p in grupo if not _nombre_completo(p.nombre)]
        todos_completos = len(grupo) == 0 or len(incompletos) == 0
        if incompletos:
            detalle_nc = "Nombre(s) incompleto(s): " + "; ".join(incompletos)
        elif grupo:
            detalle_nc = f"Todos los {roles_display} tienen nombre completo"
        else:
            detalle_nc = f"No se identificaron {roles_display} (persona física)"
        items.append(ItemCompletitud(
            codigo=codigo,
            categoria="PERSONAS",
            elemento=f"Nombre completo de {roles_display} (Nombre + 1er Apellido + 2do Apellido)",
            presente=todos_completos and len(grupo) > 0,
            fuente="datos_clave" if expediente.datos_clave else "documentos",
            detalle=detalle_nc[:200],
            severidad=SeveridadPLD.ALTA,
        ))

    return items, personas


def _deduplicar_personas(personas: list[PersonaIdentificada]) -> list[PersonaIdentificada]:
    """
    Deduplica personas por (nombre normalizado, rol) (BUG-03 / BUG-06).
    Una misma persona puede aparecer con roles distintos (ej. accionista + apoderado).
    Dentro del mismo rol, conserva la entrada con más información.
    """
    vistos: dict[tuple[str, str], PersonaIdentificada] = {}
    for p in personas:
        key = (_normalizar_nombre(p.nombre), p.rol)
        if key not in vistos:
            vistos[key] = p
        else:
            existente = vistos[key]
            if p.porcentaje is not None and existente.porcentaje is None:
                vistos[key] = p
    return list(vistos.values())


def _extraer_apoderado_de_poder(
    expediente: ExpedientePLD,
    personas: list[PersonaIdentificada],
) -> None:
    """Extrae el nombre del apoderado directamente del poder notarial si no existe ya."""
    poder = _obtener_datos(expediente, "poder")
    if not poder:
        return
    nombre_ap = _get_valor_str(poder, "nombre_apoderado")
    if not nombre_ap:
        return
    key = _normalizar_nombre(nombre_ap)
    ya_existe = any(
        _normalizar_nombre(p.nombre) == key and p.rol in ("apoderado", "representante_legal")
        for p in personas
    )
    if not ya_existe:
        personas.append(PersonaIdentificada(
            nombre=nombre_ap,
            rol="apoderado",
            fuente="poder_notarial",
            tipo_persona="fisica",
            requiere_screening=True,
        ))


def _detectar_consejo_desde_poder(
    expediente: ExpedientePLD,
    personas: list[PersonaIdentificada],
) -> None:
    """
    Detecta referencias al Consejo de Administración en el poder notarial (BUG-04).
    Si se menciona el Consejo pero ya hay personas con rol consejero, no agrega duplicados.
    """
    tiene_consejeros = any(p.rol in ("consejero", "administrador") for p in personas)
    if tiene_consejeros:
        return

    poder = _obtener_datos(expediente, "poder")
    if not poder:
        return

    # Buscar mención de "Consejo de Administración" en cualquier campo de texto
    campos_texto = ["nombre_apoderado", "tipo_poder", "facultades", "alcance_poder"]
    for campo in campos_texto:
        val = _get_valor(poder, campo)
        if isinstance(val, dict) and "parrafo" in val:
            texto = str(val.get("parrafo", "")).lower()
        elif isinstance(val, str):
            texto = val.lower()
        else:
            continue

        if "consejo de administraci" in texto:
            # Extraer el nombre del apoderado como delegado del consejo
            nombre_ap = _get_valor_str(poder, "nombre_apoderado")
            if nombre_ap:
                # Verificar si ya existe como representante/apoderado
                key = _normalizar_nombre(nombre_ap)
                ya_existe = any(_normalizar_nombre(p.nombre) == key for p in personas)
                if not ya_existe:
                    personas.append(PersonaIdentificada(
                        nombre=nombre_ap,
                        rol="consejero",
                        fuente="poder_notarial",
                        tipo_persona="fisica",
                        requiere_screening=True,
                    ))
                else:
                    # Marcar como delegado del consejo — agregar referencia
                    personas.append(PersonaIdentificada(
                        nombre=f"Consejo de Administración (ref. poder escritura)",
                        rol="consejero",
                        fuente="poder_notarial",
                        tipo_persona="fisica",
                        requiere_screening=False,
                    ))
            break


def _enriquecer_curp_desde_ine(
    expediente: ExpedientePLD,
    personas: list[PersonaIdentificada],
) -> None:
    """
    Enriquece personas con CURP del INE cuando está disponible (BUG-07).
    Match por nombre normalizado: ine.nombre_completo == persona.nombre.
    """
    ine = _obtener_datos(expediente, "ine")
    if not ine:
        return

    curp_ine = _get_valor_str(ine, "curp")
    if not curp_ine:
        return

    # Construir nombre completo del INE
    nombre_ine = _get_valor_str(ine, "nombre_completo")
    if not nombre_ine:
        # Intentar componer de campos individuales
        nombre_p = _get_valor_str(ine, "nombre") or _get_valor_str(ine, "nombres")
        ap_pat = _get_valor_str(ine, "apellido_paterno") or _get_valor_str(ine, "primer_apellido")
        ap_mat = _get_valor_str(ine, "apellido_materno") or _get_valor_str(ine, "segundo_apellido")
        partes = [p for p in [nombre_p, ap_pat, ap_mat] if p]
        nombre_ine = " ".join(partes) if partes else ""

    if not nombre_ine:
        return

    key_ine = _normalizar_nombre(nombre_ine)

    # Intentar matchear con personas identificadas
    for p in personas:
        key_p = _normalizar_nombre(p.nombre)
        # Match exacto o contenido
        if key_p == key_ine or key_ine in key_p or key_p in key_ine:
            # Agregar CURP como atributo si no tiene ya datos de identificación
            if not hasattr(p, '_curp_ine'):
                p._curp_ine = curp_ine  # type: ignore[attr-defined]


def _extraer_personas_de_documentos(
    expediente: ExpedientePLD,
    personas: list[PersonaIdentificada],
) -> None:
    """Extrae personas directamente de los documentos cuando no hay datos_clave."""

    # Poder → apoderado
    poder = _obtener_datos(expediente, "poder")
    if poder:
        nombre_ap = _get_valor_str(poder, "nombre_apoderado")
        if nombre_ap:
            personas.append(PersonaIdentificada(
                nombre=nombre_ap,
                rol="apoderado",
                fuente="poder",
                requiere_screening=True,
            ))

    # Acta constitutiva → representante legal, accionistas
    acta = _obtener_datos(expediente, "acta_constitutiva")
    if acta:
        rep_raw = _get_valor(acta, "representante_legal")
        if isinstance(rep_raw, str) and rep_raw:
            personas.append(PersonaIdentificada(
                nombre=rep_raw,
                rol="representante_legal",
                fuente="acta_constitutiva",
                requiere_screening=True,
            ))
        elif isinstance(rep_raw, dict):
            nombre_rep = rep_raw.get("nombre", "")
            # El nombre interno también puede estar enriched
            if isinstance(nombre_rep, dict) and "valor" in nombre_rep:
                nombre_rep = str(nombre_rep.get("valor", ""))
            if nombre_rep:
                personas.append(PersonaIdentificada(
                    nombre=str(nombre_rep),
                    rol="representante_legal",
                    fuente="acta_constitutiva",
                    requiere_screening=True,
                ))

        estructura = _get_valor(acta, "estructura_accionaria")
        if isinstance(estructura, list):
            for acc in estructura:
                if isinstance(acc, dict):
                    nombre_acc = acc.get("nombre", "")
                    if isinstance(nombre_acc, dict) and "valor" in nombre_acc:
                        nombre_acc = str(nombre_acc.get("valor", ""))
                    if nombre_acc:
                        pct = acc.get("porcentaje")
                        if isinstance(pct, dict) and "valor" in pct:
                            pct = pct.get("valor")
                        try:
                            pct = float(pct) if pct else None
                        except (ValueError, TypeError):
                            pct = None
                        tipo_p = acc.get("tipo_persona", "fisica")
                        if isinstance(tipo_p, dict) and "valor" in tipo_p:
                            tipo_p = str(tipo_p.get("valor", "fisica"))
                        personas.append(PersonaIdentificada(
                            nombre=str(nombre_acc),
                            rol="accionista",
                            fuente="acta_constitutiva",
                            tipo_persona=str(tipo_p) if tipo_p else "fisica",
                            porcentaje=pct,
                            requiere_screening=True,
                        ))

    # Reforma → consejo de administración
    reforma = _obtener_datos(expediente, "reforma_estatutos") or _obtener_datos(expediente, "reforma")
    if reforma:
        consejo = _get_valor(reforma, "consejo_administracion")
        if isinstance(consejo, list):
            for c in consejo:
                if isinstance(c, str) and c:
                    personas.append(PersonaIdentificada(
                        nombre=c,
                        rol="consejero",
                        fuente="reforma_estatutos",
                        requiere_screening=True,
                    ))
                elif isinstance(c, dict):
                    nombre_c = c.get("nombre", "")
                    if isinstance(nombre_c, dict) and "valor" in nombre_c:
                        nombre_c = str(nombre_c.get("valor", ""))
                    if nombre_c:
                        personas.append(PersonaIdentificada(
                            nombre=str(nombre_c),
                            rol="consejero",
                            fuente="reforma_estatutos",
                            requiere_screening=True,
                        ))


# ═══════════════════════════════════════════════════════════════════
#  Verificación del poder para cuentas bancarias
# ═══════════════════════════════════════════════════════════════════

def _verificar_poder_bancario(expediente: ExpedientePLD) -> tuple[ItemCompletitud, bool | None]:
    """Verifica si existe poder para abrir cuentas bancarias."""
    poder_bc = _detectar_poder_bancario(expediente)

    if poder_bc is True:
        detalle = "Se detectó poder para abrir/operar cuentas bancarias"
        severidad = SeveridadPLD.INFORMATIVA
    elif poder_bc is False:
        detalle = "No se detectó facultad expresa para abrir/operar cuentas bancarias"
        severidad = SeveridadPLD.ALTA
    else:
        detalle = "No se pudo determinar (documento de poder no disponible)"
        severidad = SeveridadPLD.CRITICA

    item = ItemCompletitud(
        codigo="A5.1",
        categoria="PODER_BANCARIO",
        elemento="Poder para abrir/operar cuentas bancarias",
        presente=poder_bc is True,
        fuente="poder" if poder_bc is not None else "",
        detalle=detalle,
        severidad=severidad,
    )
    return item, poder_bc


# ═══════════════════════════════════════════════════════════════════
#  Verificación de validación cruzada (Colorado — tabla validaciones_cruzadas)
# ═══════════════════════════════════════════════════════════════════

_BLOQUES_PLD: list[tuple[str, str, SeveridadPLD]] = [
    ("1", "Identidad corporativa", SeveridadPLD.CRITICA),
    ("2", "Domicilio", SeveridadPLD.ALTA),
    ("3", "Vigencia de documentos", SeveridadPLD.CRITICA),
    ("4", "Apoderado legal", SeveridadPLD.CRITICA),
    ("5", "Estructura societaria", SeveridadPLD.ALTA),
    ("6", "Datos bancarios", SeveridadPLD.ALTA),
    ("7", "Consistencia notarial", SeveridadPLD.MEDIA),
    ("8", "Calidad de extracción", SeveridadPLD.INFORMATIVA),
    ("9", "Completitud del expediente", SeveridadPLD.ALTA),
    ("10", "Portales gubernamentales", SeveridadPLD.MEDIA),
]


def _verificar_validacion_cruzada(
    expediente: ExpedientePLD,
) -> tuple[list[ItemCompletitud], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """
    Verifica resultados de la validación cruzada de Colorado.
    Lee de expediente.validacion_cruzada (cargado de la tabla validaciones_cruzadas).

    Returns:
        (items, hallazgos_criticos_fallidos, hallazgos_todos, resumen_colorado)
    """
    items: list[ItemCompletitud] = []
    hallazgos_criticos: list[dict[str, Any]] = []
    hallazgos_todos: list[dict[str, Any]] = []
    resumen: dict[str, Any] = {}

    vc = expediente.validacion_cruzada

    # PLD1.50: Validación cruzada ejecutada
    vc_disponible = vc is not None
    items.append(ItemCompletitud(
        codigo="A6.1",
        categoria="VALIDACION_CRUZADA",
        elemento="Validación cruzada (Colorado) ejecutada",
        presente=vc_disponible,
        fuente="validaciones_cruzadas" if vc_disponible else "",
        detalle=f"Dictamen: {vc.get('dictamen', 'N/D')}" if vc_disponible else "No se encontró validación cruzada en la BD",
        severidad=SeveridadPLD.ALTA,
    ))

    if not vc:
        return items, hallazgos_criticos, hallazgos_todos, resumen

    # Datos de Colorado
    dictamen = vc.get("dictamen", "")
    hallazgos = vc.get("hallazgos", [])
    resumen_bloques = vc.get("resumen_bloques", {})

    # Construir resumen (excluyendo datos_clave)
    for k, v in resumen_bloques.items():
        if k != "datos_clave" and isinstance(v, dict):
            resumen[k] = v

    # PLD1.51: Dictamen no rechazado
    dictamen_ok = dictamen != "RECHAZADO"
    items.append(ItemCompletitud(
        codigo="A6.2",
        categoria="VALIDACION_CRUZADA",
        elemento="Dictamen Colorado no rechazado",
        presente=dictamen_ok,
        fuente="validaciones_cruzadas",
        detalle=f"Dictamen: {dictamen}" if dictamen else "Sin dictamen",
        severidad=SeveridadPLD.CRITICA if not dictamen_ok else SeveridadPLD.INFORMATIVA,
    ))

    # Todos los hallazgos de Colorado
    hallazgos_todos = [h for h in hallazgos if isinstance(h, dict)]

    # Recopilar hallazgos críticos fallidos
    for h in hallazgos_todos:
        if h.get("severidad") == "CRITICA" and h.get("pasa") is False:
            hallazgos_criticos.append(h)

    # PLD1.52–PLD1.61: Un item por cada bloque de Colorado
    for bloque_num, nombre_bloque, severidad_default in _BLOQUES_PLD:
        bloque_info = resumen.get(bloque_num, {})

        if bloque_info:
            criticos_fallan = bloque_info.get("criticos", 0)
            total = bloque_info.get("total", 0)
            pasan = bloque_info.get("pasan", 0)

            bloque_ok = criticos_fallan == 0
            detalle = f"{pasan}/{total} validaciones pasan"
            if not bloque_ok:
                detalle += f" | {criticos_fallan} hallazgo(s) crítico(s) fallido(s)"
                severidad = severidad_default
            else:
                severidad = SeveridadPLD.INFORMATIVA
        else:
            bloque_ok = True
            detalle = "Bloque no evaluado por Colorado"
            severidad = SeveridadPLD.INFORMATIVA

        items.append(ItemCompletitud(
            codigo=f"A6.{2 + int(bloque_num)}",
            categoria="VALIDACION_CRUZADA",
            elemento=f"Colorado — {nombre_bloque}",
            presente=bloque_ok,
            fuente="validaciones_cruzadas",
            detalle=detalle,
            severidad=severidad,
        ))

    return items, hallazgos_criticos, hallazgos_todos, resumen


# ═══════════════════════════════════════════════════════════════════
#  Generación de recomendaciones Etapa 1
# ═══════════════════════════════════════════════════════════════════

def _generar_recomendaciones_etapa1(
    items: list[ItemCompletitud],
    personas: list[PersonaIdentificada],
    poder_bc: bool | None,
    dictamen_colorado: str = "",
    hallazgos_colorado_criticos: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Genera recomendaciones basadas en los hallazgos de completitud."""
    recs: list[str] = []

    # Documentos faltantes
    docs_faltantes = [it for it in items if it.categoria == "DOCUMENTO" and not it.presente]
    if docs_faltantes:
        nombres_docs = ", ".join(it.elemento for it in docs_faltantes)
        recs.append(f"SOLICITAR documentos faltantes: {nombres_docs}")

    # Datos obligatorios faltantes
    datos_faltantes = [it for it in items if it.categoria == "DATO_OBLIGATORIO" and not it.presente]
    if datos_faltantes:
        nombres_datos = ", ".join(it.elemento for it in datos_faltantes)
        recs.append(f"VERIFICAR datos obligatorios faltantes: {nombres_datos}")

    # Domicilio incompleto
    dom_faltantes = [it for it in items if it.categoria == "DOMICILIO" and not it.presente]
    if dom_faltantes:
        campos_dom = ", ".join(it.elemento.replace("Domicilio — ", "") for it in dom_faltantes)
        recs.append(f"COMPLETAR domicilio: campos faltantes — {campos_dom}")

    # Personas
    if not any(p.rol in ("apoderado", "representante_legal") for p in personas):
        recs.append("IDENTIFICAR apoderado o representante legal del poder notarial")
    if not any(p.rol == "accionista" for p in personas):
        recs.append("OBTENER estructura accionaria del acta constitutiva o reforma")

    # Nombres incompletos
    nombres_incompletos = [
        p for p in personas
        if p.tipo_persona == "fisica" and not _nombre_completo(p.nombre)
    ]
    if nombres_incompletos:
        listado = "; ".join(f"{p.nombre} ({p.rol})" for p in nombres_incompletos)
        recs.append(
            f"COMPLETAR nombre(s) — se requiere Nombre + Primer Apellido + Segundo Apellido: {listado}"
        )

    # Poder bancario
    if poder_bc is None:
        recs.append("SOLICITAR poder notarial para verificar facultades bancarias")
    elif poder_bc is False:
        recs.append("ALERTA: El poder no incluye facultad expresa para abrir cuentas bancarias. Solicitar poder específico o ampliación.")

    # Personas para screening
    total_screening = sum(1 for p in personas if p.requiere_screening)
    if total_screening > 0:
        recs.append(f"ETAPA 2: {total_screening} persona(s) identificada(s) pendiente(s) de screening contra listas (LPB, OFAC, PEP, 69-B)")

    # Colorado / validación cruzada
    if dictamen_colorado == "RECHAZADO":
        recs.insert(0, "URGENTE: Colorado rechazó el expediente — resolver hallazgos críticos antes de continuar proceso PLD")
    elif dictamen_colorado == "APROBADO_CON_OBSERVACIONES":
        recs.append("REVISAR observaciones de la validación cruzada (Colorado) antes de emitir dictamen final")

    if hallazgos_colorado_criticos:
        codigos = ", ".join(h.get("codigo", "?") for h in hallazgos_colorado_criticos)
        recs.append(f"ATENDER {len(hallazgos_colorado_criticos)} hallazgo(s) crítico(s) de Colorado: {codigos}")

    return recs


# ═══════════════════════════════════════════════════════════════════
#  Función principal — ejecutar_etapa1
# ═══════════════════════════════════════════════════════════════════

def ejecutar_etapa1(expediente: ExpedientePLD) -> VerificacionCompletitud:
    """
    Ejecuta la Etapa 1 del proceso PLD:
    Verificación de completitud documental conforme a DCG Art.115 LIC.

    Args:
        expediente: Datos completos de la empresa cargados de la BD.

    Returns:
        VerificacionCompletitud con todos los items verificados,
        personas identificadas y recomendaciones.
    """
    ahora = datetime.now(timezone.utc)

    # 1. Verificar documentos obligatorios
    items_docs = _verificar_documentos(expediente)

    # 2. Verificar datos obligatorios
    items_datos = _verificar_datos_obligatorios(expediente)

    # 3. Verificar domicilio completo
    items_domicilio = _verificar_domicilio(expediente)

    # 4. Identificar personas
    items_personas, personas = _identificar_personas(expediente)

    # 5. Verificar poder bancario
    item_poder, poder_bc = _verificar_poder_bancario(expediente)

    # 6. Verificar validación cruzada (Colorado — desde tabla validaciones_cruzadas)
    items_colorado, hallazgos_criticos, hallazgos_colorado_todos, resumen_colorado = _verificar_validacion_cruzada(expediente)

    # Consolidar items
    todos_items = items_docs + items_datos + items_domicilio + items_personas + [item_poder] + items_colorado

    # Contadores
    total = len(todos_items)
    presentes = sum(1 for it in todos_items if it.presente)
    faltantes = total - presentes
    criticos_faltantes = sum(
        1 for it in todos_items
        if not it.presente and it.severidad == SeveridadPLD.CRITICA
    )

    # Documentos faltantes (de la lista obligatoria)
    docs_presentes_pld = [
        dt for dt in DOCS_OBLIGATORIOS_PLD
        if dt in expediente.doc_types_presentes
        or (dt == "domicilio" and any(
            alt in expediente.doc_types_presentes for alt in DOCS_DOMICILIO_ALTERNATIVOS
        ))
        or (dt == "ine" and any(
            alt in expediente.doc_types_presentes for alt in DOCS_INE_ALTERNATIVOS
        ))
    ]
    docs_faltantes_pld = [
        dt for dt in DOCS_OBLIGATORIOS_PLD
        if dt not in docs_presentes_pld
    ]

    # Determinar resultado
    if criticos_faltantes == 0 and faltantes == 0:
        resultado = ResultadoCompletitud.COMPLETO
    elif criticos_faltantes == 0:
        resultado = ResultadoCompletitud.PARCIAL
    else:
        resultado = ResultadoCompletitud.INCOMPLETO

    # Colorado info
    dictamen_colorado = ""
    vc_disponible = False
    if expediente.validacion_cruzada:
        dictamen_colorado = expediente.validacion_cruzada.get("dictamen", "")
        vc_disponible = True

    # Recomendaciones
    recomendaciones = _generar_recomendaciones_etapa1(
        todos_items, personas, poder_bc,
        dictamen_colorado=dictamen_colorado,
        hallazgos_colorado_criticos=hallazgos_criticos,
    )

    logger.info(
        "Etapa 1 completada: %s (%s) → %s | items=%d/%d | criticos_faltantes=%d | personas=%d",
        expediente.rfc,
        expediente.razon_social,
        resultado.value,
        presentes,
        total,
        criticos_faltantes,
        len(personas),
    )

    return VerificacionCompletitud(
        empresa_id=expediente.empresa_id,
        rfc=expediente.rfc,
        razon_social=expediente.razon_social,
        fecha_analisis=ahora,
        resultado=resultado,
        items=todos_items,
        personas_identificadas=personas,
        documentos_presentes=expediente.doc_types_presentes,
        documentos_faltantes=docs_faltantes_pld,
        total_items=total,
        items_presentes=presentes,
        items_faltantes=faltantes,
        items_criticos_faltantes=criticos_faltantes,
        dictamen_colorado=dictamen_colorado,
        validacion_cruzada_disponible=vc_disponible,
        hallazgos_colorado_criticos=hallazgos_criticos,
        hallazgos_colorado=hallazgos_colorado_todos,
        resumen_colorado=resumen_colorado,
        recomendaciones=recomendaciones,
        poder_cuenta_bancaria=poder_bc,
    )
