# service/validators.py
"""
Módulo de validación para campos extraídos de documentos.
Proporciona validaciones de formato, lógica de negocio y scoring de confianza.
"""

import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional


def format_evidence_report(data: dict) -> str:
    """
    Genera un reporte legible de la evidencia de extracción.
    """
    evidencia = data.get("_evidencia_extraccion", {})
    if not evidencia:
        return "Sin evidencia de extracción disponible."

    lines = ["═" * 60, "EVIDENCIA DE EXTRACCIÓN", "═" * 60]

    for campo, info in evidencia.items():
        encontrado = info.get("encontrado", False)
        estado = "[OK] ENCONTRADO" if encontrado else "[X] NO ENCONTRADO"
        lines.append(f"\n{campo}: {estado}")

        if encontrado and info.get("contexto"):
            lines.append(f"  Contexto: \"{info['contexto']}\"")
            lines.append(f"  Posición: {info.get('posicion', 'N/A')}")
        elif info.get("nota"):
            lines.append(f"  Nota: {info['nota']}")

    lines.append("\n" + "═" * 60)
    return "\n".join(lines)


class FieldValidator:
    """Validador de campos extraídos con scoring de confianza."""

    # Patrones de validación
    PATTERNS = {
        "fecha": r"^\d{2}/\d{2}/\d{4}$",
        "numero_escritura": r"^\d{1,7}$",
        "numero_notaria": r"^\d{1,4}$",
        # Folio mercantil: N-/M- con cualquier cantidad de dígitos, o número simple de 4-12 dígitos
        # Aceptamos hasta 12 dígitos para folios largos como 2019050847
        "folio_mercantil": r"^[NM]-\d{4,}$|^\d{4,12}$|^PENDIENTE",
        "rfc_moral": r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$",
        "rfc_fisica": r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$",
        # CURP mexicana: 18 caracteres
        # Formato: 4 letras + 6 dígitos (fecha) + H/M (sexo) + 2 letras (estado) + 3 consonantes + 2 dígitos
        # Variantes comunes en INE pueden tener dígitos en lugar de consonantes
        "curp": r"^[A-Z]{4}\d{6}[HM][A-Z]{2}[A-Z0-9]{3}[A-Z0-9]{2}$",
        "curp_ine": r"^[A-Z]{4}\d{6}[HM].{7}$",  # Más flexible para INE
        "clabe": r"^\d{18}$",
    }

    # Estados válidos de México
    ESTADOS_MEXICO = {
        "aguascalientes", "baja california", "baja california sur", "campeche",
        "chiapas", "chihuahua", "ciudad de mexico", "cdmx", "coahuila", "colima",
        "durango", "estado de mexico", "guanajuato", "guerrero", "hidalgo",
        "jalisco", "michoacan", "morelos", "nayarit", "nuevo leon", "oaxaca",
        "puebla", "queretaro", "quintana roo", "san luis potosi", "sinaloa",
        "sonora", "tabasco", "tamaulipas", "tlaxcala", "veracruz", "yucatan",
        "zacatecas", "distrito federal"
    }

    @classmethod
    def validate_fecha(cls, fecha: str, allow_future: bool = False) -> Tuple[bool, str, float]:
        """
        Valida una fecha en formato dd/mm/aaaa o dd-mm-aaaa.

        Args:
            fecha: Fecha a validar
            allow_future: Si True, permite fechas futuras (para vigencias)

        Returns:
            Tuple[bool, str, float]: (es_válido, mensaje, score_confianza)
        """
        if not fecha or fecha.lower() in ["n/a", "pendiente", ""]:
            return False, "Fecha vacía o pendiente", 0.0

        if "pendiente" in fecha.lower():
            # Estado válido para documentos pendientes - score más alto
            return True, "Pendiente de inscripción (estado válido)", 0.7

        # Normalizar separadores (aceptar / y -)
        fecha_norm = fecha.replace("-", "/")

        if not re.match(cls.PATTERNS["fecha"], fecha_norm):
            return False, f"Formato inválido: {fecha}", 0.2

        try:
            dia, mes, anio = fecha_norm.split("/")
            fecha_obj = datetime(int(anio), int(mes), int(dia))

            # Validar rango razonable (1900-2050 para permitir vigencias)
            if fecha_obj.year < 1900 or fecha_obj.year > 2050:
                return False, f"Año fuera de rango: {anio}", 0.3

            # Validar fecha futura solo si no se permite
            if not allow_future and fecha_obj > datetime.now(tz=timezone.utc).replace(tzinfo=None):
                return False, "Fecha en el futuro", 0.4

            return True, "Fecha válida", 1.0

        except ValueError as e:
            return False, f"Fecha inválida: {e}", 0.2

    @classmethod
    def validate_estado(cls, estado: str) -> Tuple[bool, str, float]:
        """Valida que sea un estado de México válido."""
        if not estado:
            return False, "Estado vacío", 0.0

        estado_lower = estado.lower().strip()
        estado_lower = estado_lower.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

        if estado_lower in cls.ESTADOS_MEXICO:
            return True, "Estado válido", 1.0

        # Buscar coincidencia parcial
        for est in cls.ESTADOS_MEXICO:
            if est in estado_lower or estado_lower in est:
                return True, f"Estado probable: {est}", 0.8

        return False, f"Estado no reconocido: {estado}", 0.3

    @classmethod
    def validate_numero(cls, numero: str, tipo: str = "escritura") -> Tuple[bool, str, float]:
        """Valida un número de escritura o notaría."""
        if not numero:
            return False, "Número vacío", 0.0

        # Limpiar el número
        numero_limpio = re.sub(r'[^\d]', '', str(numero))

        if not numero_limpio:
            return False, "No contiene dígitos", 0.0

        pattern_key = f"numero_{tipo}" if f"numero_{tipo}" in cls.PATTERNS else "numero_escritura"

        if re.match(cls.PATTERNS[pattern_key], numero_limpio):
            return True, f"Número de {tipo} válido", 1.0

        return False, f"Número de {tipo} fuera de rango esperado", 0.5

    @classmethod
    def validate_folio_mercantil(cls, folio: str) -> Tuple[bool, str, float]:
        """Valida un folio mercantil electrónico."""
        if not folio:
            return False, "Folio vacío", 0.0

        folio_upper = folio.upper().strip()

        if "PENDIENTE" in folio_upper:
            # Estado válido para empresas nuevas - score más alto
            return True, "Pendiente de inscripción (estado válido)", 0.7

        if re.match(cls.PATTERNS["folio_mercantil"], folio_upper):
            return True, "Folio mercantil válido", 1.0

        # Podría ser NCI si tiene más de 12 dígitos sin prefijo
        if re.match(r'^\d{13,}$', folio_upper):
            return False, "Parece ser NCI, no FME", 0.4

        return False, f"Formato de folio no reconocido: {folio}", 0.3

    @classmethod
    def validate_rfc(cls, rfc: str) -> Tuple[bool, str, float]:
        """
        Valida un RFC mexicano (persona física o moral).

        Args:
            rfc: RFC a validar

        Returns:
            Tuple[bool, str, float]: (es_válido, mensaje, score_confianza)
        """
        if not rfc:
            return False, "RFC vacío", 0.0

        rfc = rfc.strip().upper()

        # RFC de persona moral: 3 letras + 6 dígitos + 3 homoclave
        if re.match(cls.PATTERNS["rfc_moral"], rfc):
            return True, "RFC persona moral válido", 1.0

        # RFC de persona física: 4 letras + 6 dígitos + 3 homoclave
        if re.match(cls.PATTERNS["rfc_fisica"], rfc):
            return True, "RFC persona física válido", 1.0

        # Podría ser RFC sin homoclave (10 o 12 caracteres)
        if re.match(r"^[A-ZÑ&]{3,4}\d{6}$", rfc):
            return True, "RFC sin homoclave", 0.7

        return False, f"RFC con formato inválido: {rfc}", 0.0

    @classmethod
    def validate_nombre(cls, nombre: str) -> Tuple[bool, str, float]:
        """Valida que un nombre tenga formato razonable."""
        if not nombre:
            return False, "Nombre vacío", 0.0

        nombre = nombre.strip()

        # Debe tener al menos 2 palabras
        palabras = nombre.split()
        if len(palabras) < 2:
            return False, "Nombre incompleto (menos de 2 palabras)", 0.4

        # No debe tener solo mayúsculas (mala normalización)
        if nombre.isupper() and len(nombre) > 10:
            return True, "Nombre en mayúsculas (podría normalizarse)", 0.7

        # Verificar que no tenga caracteres extraños
        if re.search(r'[0-9@#$%^&*()=+\[\]{};:"|<>]', nombre):
            return False, "Nombre con caracteres inválidos", 0.3

        return True, "Nombre válido", 1.0


class ActaConstitutivaValidator:
    """Validador específico para Actas Constitutivas."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        """
        Valida todos los campos de un Acta Constitutiva.

        Returns:
            Dict con validaciones y score de confianza global.
        """
        validaciones = {}
        scores = []

        # Validar cada campo
        campos_validadores = {
            "fecha_constitucion": ("fecha", FieldValidator.validate_fecha),
            "fecha_expedicion": ("fecha", FieldValidator.validate_fecha),
            "estado_notaria": ("estado", FieldValidator.validate_estado),
            "numero_escritura_poliza": ("numero", lambda x: FieldValidator.validate_numero(x, "escritura")),
            "numero_notaria": ("numero", lambda x: FieldValidator.validate_numero(x, "notaria")),
            "folio_mercantil": ("folio", FieldValidator.validate_folio_mercantil),
            "nombre_notario": ("nombre", FieldValidator.validate_nombre),
        }

        for campo, (tipo, validador) in campos_validadores.items():
            valor = datos.get(campo, "")
            es_valido, mensaje, score = validador(valor)

            validaciones[campo] = {
                "valor": valor,
                "valido": es_valido,
                "mensaje": mensaje,
                "confianza": score
            }
            scores.append(score)

        # Validaciones de lógica de negocio
        logica_validations = cls._validate_business_logic(datos)
        validaciones["logica_negocio"] = logica_validations

        # Score global
        score_global = sum(scores) / len(scores) if scores else 0.0

        # Ajustar por validaciones de lógica
        for val in logica_validations:
            if not val["valido"]:
                score_global *= 0.9  # Penalizar por cada error de lógica

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": cls._get_confidence_level(score_global),
            "requiere_revision": score_global < 0.7
        }

    @classmethod
    def _validate_business_logic(cls, datos: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Valida reglas de negocio específicas."""
        validaciones = []

        # 1. Fecha constitución debe ser <= fecha expedición
        fecha_const = datos.get("fecha_constitucion", "")
        fecha_exp = datos.get("fecha_expedicion", "")

        if fecha_const and fecha_exp and "pendiente" not in fecha_exp.lower():
            try:
                fc = datetime.strptime(fecha_const, "%d/%m/%Y")
                fe = datetime.strptime(fecha_exp, "%d/%m/%Y")

                if fc > fe:
                    validaciones.append({
                        "regla": "fecha_constitucion <= fecha_expedicion",
                        "valido": False,
                        "mensaje": f"Fecha constitución ({fecha_const}) posterior a expedición ({fecha_exp})"
                    })
                else:
                    validaciones.append({
                        "regla": "fecha_constitucion <= fecha_expedicion",
                        "valido": True,
                        "mensaje": "Orden de fechas correcto"
                    })
            except (ValueError, TypeError):
                pass

        # 2. Si hay folio mercantil, debe haber fecha de expedición
        folio = datos.get("folio_mercantil", "")
        if folio and "pendiente" not in folio.lower():
            if not fecha_exp or "pendiente" in fecha_exp.lower():
                validaciones.append({
                    "regla": "folio_requiere_fecha_expedicion",
                    "valido": False,
                    "mensaje": "Tiene folio mercantil pero no fecha de expedición"
                })

        # 3. Campos_no_encontrados debe ser consistente con valores "Pendiente"
        campos_no_encontrados = datos.get("campos_no_encontrados", [])
        for campo in ["fecha_expedicion", "folio_mercantil"]:
            valor = datos.get(campo, "")
            if valor and "pendiente" in str(valor).lower():
                if campo not in campos_no_encontrados:
                    validaciones.append({
                        "regla": f"consistencia_{campo}",
                        "valido": False,
                        "mensaje": f"{campo} dice 'Pendiente' pero no está en campos_no_encontrados"
                    })

        return validaciones

    @classmethod
    def _get_confidence_level(cls, score: float) -> str:
        """Convierte score numérico a nivel de confianza."""
        if score >= 0.9:
            return "ALTA"
        elif score >= 0.7:
            return "MEDIA"
        elif score >= 0.5:
            return "BAJA"
        else:
            return "MUY_BAJA"


def validate_acta_extraction(datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
    """
    Función principal para validar extracción de Acta Constitutiva.

    Args:
        datos: Diccionario con los campos extraídos
        texto_ocr: Texto OCR original (opcional, para validaciones adicionales)

    Returns:
        Diccionario con validaciones, scores y recomendaciones
    """
    return ActaConstitutivaValidator.validate_all(datos, texto_ocr)


def print_validation_report(validacion: Dict[str, Any], doc_type: str = "ACTA CONSTITUTIVA") -> None:
    """Imprime un reporte de validación formateado."""
    logger.info("\n" + "=" * 70)
    logger.info(f"REPORTE DE VALIDACION - {doc_type}")
    logger.info("=" * 70)

    logger.info(f"\nScore Global: {validacion['score_global']:.0%}")
    logger.info(f"Nivel de Confianza: {validacion['nivel_confianza']}")
    logger.info(f"Requiere Revisión: {'Sí' if validacion['requiere_revision'] else 'No'}")

    logger.info("\n" + "-" * 70)
    logger.info("VALIDACIÓN POR CAMPO:")
    logger.info("-" * 70)

    for campo, info in validacion["campos"].items():
        if campo == "logica_negocio":
            continue

        estado = "[OK]" if info["valido"] else "[X]"
        confianza = f"{info['confianza']:.0%}"
        logger.info(f"  {estado} {campo}:")
        logger.info(f"      Valor: {info['valor'][:50]}..." if len(str(info['valor'])) > 50 else f"      Valor: {info['valor']}")
        logger.info(f"      Mensaje: {info['mensaje']}")
        logger.info(f"      Confianza: {confianza}")

    # Validaciones de lógica de negocio
    logica = validacion["campos"].get("logica_negocio", [])
    if logica:
        logger.info("\n" + "-" * 70)
        logger.info("VALIDACIÓN DE LÓGICA DE NEGOCIO:")
        logger.info("-" * 70)
        for val in logica:
            estado = "[OK]" if val["valido"] else "[!]"
            logger.info(f"  {estado} {val['regla']}: {val['mensaje']}")

    logger.info("\n" + "=" * 70)


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDADORES PARA OTROS TIPOS DE DOCUMENTOS
# ═══════════════════════════════════════════════════════════════════════════════

class CSFValidator:
    """Validador para Constancia de Situación Fiscal."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # RFC
        rfc = datos.get("rfc", "")
        if rfc:
            if re.match(FieldValidator.PATTERNS["rfc_moral"], rfc.upper()):
                validaciones["rfc"] = {"valor": rfc, "valido": True, "mensaje": "RFC moral válido", "confianza": 1.0}
            elif re.match(FieldValidator.PATTERNS["rfc_fisica"], rfc.upper()):
                validaciones["rfc"] = {"valor": rfc, "valido": True, "mensaje": "RFC físico válido", "confianza": 1.0}
            else:
                validaciones["rfc"] = {"valor": rfc, "valido": False, "mensaje": "Formato RFC inválido", "confianza": 0.3}
        else:
            validaciones["rfc"] = {"valor": "", "valido": False, "mensaje": "RFC vacío", "confianza": 0.0}
        scores.append(validaciones["rfc"]["confianza"])

        # Razón Social
        razon = datos.get("razon_social", "")
        if razon and len(razon) > 3:
            validaciones["razon_social"] = {"valor": razon, "valido": True, "mensaje": "Razón social presente", "confianza": 1.0}
        else:
            validaciones["razon_social"] = {"valor": razon, "valido": False, "mensaje": "Razón social vacía o muy corta", "confianza": 0.0}
        scores.append(validaciones["razon_social"]["confianza"])

        # Giro Mercantil
        giro = datos.get("giro_mercantil", "")
        if giro and len(giro) > 5:
            validaciones["giro_mercantil"] = {"valor": giro, "valido": True, "mensaje": "Giro mercantil presente", "confianza": 1.0}
        else:
            validaciones["giro_mercantil"] = {"valor": giro, "valido": False, "mensaje": "Giro mercantil vacío", "confianza": 0.0}
        scores.append(validaciones["giro_mercantil"]["confianza"])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class FIELValidator:
    """Validador para FIEL (Firma Electrónica)."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # RFC
        rfc = datos.get("rfc", "")
        if rfc and (re.match(FieldValidator.PATTERNS["rfc_moral"], rfc.upper()) or
                   re.match(FieldValidator.PATTERNS["rfc_fisica"], rfc.upper())):
            validaciones["rfc"] = {"valor": rfc, "valido": True, "mensaje": "RFC válido", "confianza": 1.0}
        else:
            validaciones["rfc"] = {"valor": rfc, "valido": False, "mensaje": "RFC inválido o vacío", "confianza": 0.0}
        scores.append(validaciones["rfc"]["confianza"])

        # Número de serie del certificado
        serie = datos.get("numero_serie_certificado", "")
        if serie and len(serie) >= 10:
            validaciones["numero_serie_certificado"] = {"valor": serie, "valido": True, "mensaje": "Número de serie presente", "confianza": 1.0}
        else:
            validaciones["numero_serie_certificado"] = {"valor": serie, "valido": False, "mensaje": "Número de serie vacío o incompleto", "confianza": 0.0}
        scores.append(validaciones["numero_serie_certificado"]["confianza"])

        # Vigencia
        vigencia_desde = datos.get("vigencia_desde", "")
        vigencia_hasta = datos.get("vigencia_hasta", "")

        _, _, score_desde = FieldValidator.validate_fecha(vigencia_desde)
        _, _, score_hasta = FieldValidator.validate_fecha(vigencia_hasta, allow_future=True)

        validaciones["vigencia_desde"] = {"valor": vigencia_desde, "valido": score_desde >= 0.5, "mensaje": "Vigencia inicio", "confianza": score_desde}
        validaciones["vigencia_hasta"] = {"valor": vigencia_hasta, "valido": score_hasta >= 0.5, "mensaje": "Vigencia fin", "confianza": score_hasta}
        scores.extend([score_desde, score_hasta])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class DomicilioValidator:
    """Validador para Comprobante de Domicilio."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # Campos obligatorios (afectan el score)
        campos_obligatorios = ["calle", "colonia", "codigo_postal", "entidad_federativa"]

        # Campos opcionales (se muestran pero no afectan el score si están vacíos)
        campos_opcionales = ["numero_exterior", "numero_interior", "ciudad", "estado", "alcaldia"]

        for campo in campos_obligatorios:
            valor = datos.get(campo, "")
            if valor and valor.upper() != "N/A" and len(valor) > 1:
                validaciones[campo] = {"valor": valor, "valido": True, "mensaje": f"{campo} presente", "confianza": 1.0}
                scores.append(1.0)
            else:
                validaciones[campo] = {"valor": valor, "valido": False, "mensaje": f"{campo} vacío o N/A", "confianza": 0.0}
                scores.append(0.0)

        # Validar campos opcionales (se incluyen en detalle pero no penalizan si faltan)
        for campo in campos_opcionales:
            valor = datos.get(campo, "")
            if valor and valor.upper() != "N/A" and len(str(valor)) > 0:
                validaciones[campo] = {"valor": valor, "valido": True, "mensaje": f"{campo} presente", "confianza": 1.0}
            else:
                validaciones[campo] = {"valor": valor if valor else "N/A", "valido": True, "mensaje": f"{campo} no especificado (opcional)", "confianza": None}

        # Código postal (5 dígitos)
        cp = datos.get("codigo_postal", "")
        if re.match(r"^\d{5}$", str(cp)):
            validaciones["codigo_postal"]["confianza"] = 1.0
            validaciones["codigo_postal"]["mensaje"] = "CP válido (5 dígitos)"
        elif cp and cp != "N/A":
            validaciones["codigo_postal"]["confianza"] = 0.5
            validaciones["codigo_postal"]["mensaje"] = "CP presente pero formato inusual"

        # Estado válido
        estado = datos.get("entidad_federativa", "")
        _, msg, score = FieldValidator.validate_estado(estado)
        validaciones["entidad_federativa"]["confianza"] = score
        validaciones["entidad_federativa"]["mensaje"] = msg

        # Validación adicional para número exterior
        num_ext = datos.get("numero_exterior", "")
        if num_ext and num_ext.upper() != "N/A":
            validaciones["numero_exterior"]["mensaje"] = "Número exterior identificado"

        # Validación adicional para ciudad
        ciudad = datos.get("ciudad", "")
        if ciudad and ciudad.upper() != "N/A":
            validaciones["ciudad"]["mensaje"] = "Ciudad identificada"

        # Validación adicional para estado abreviado
        estado_abrev = datos.get("estado", "")
        if estado_abrev and estado_abrev.upper() != "N/A":
            validaciones["estado"]["mensaje"] = "Estado (abreviado) identificado"

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class EstadoCuentaValidator:
    """Validador para Estado de Cuenta Bancario."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # Banco
        banco = datos.get("banco", "")
        if banco and len(banco) > 2:
            validaciones["banco"] = {"valor": banco, "valido": True, "mensaje": "Banco identificado", "confianza": 1.0}
        else:
            validaciones["banco"] = {"valor": banco, "valido": False, "mensaje": "Banco no identificado", "confianza": 0.0}
        scores.append(validaciones["banco"]["confianza"])

        # CLABE (18 dígitos)
        clabe = datos.get("clabe", "")
        clabe_limpia = re.sub(r'\D', '', str(clabe))
        if len(clabe_limpia) == 18:
            validaciones["clabe"] = {"valor": clabe, "valido": True, "mensaje": "CLABE válida (18 dígitos)", "confianza": 1.0}
        elif clabe_limpia:
            validaciones["clabe"] = {"valor": clabe, "valido": False, "mensaje": f"CLABE incompleta ({len(clabe_limpia)} dígitos)", "confianza": 0.3}
        else:
            validaciones["clabe"] = {"valor": "", "valido": False, "mensaje": "CLABE no encontrada", "confianza": 0.0}
        scores.append(validaciones["clabe"]["confianza"])

        # Titular
        titular = datos.get("titular", "")
        if titular and len(titular) > 3:
            validaciones["titular"] = {"valor": titular, "valido": True, "mensaje": "Titular identificado", "confianza": 1.0}
        else:
            validaciones["titular"] = {"valor": titular, "valido": False, "mensaje": "Titular no identificado", "confianza": 0.0}
        scores.append(validaciones["titular"]["confianza"])

        # Número de cuenta
        cuenta = datos.get("numero_cuenta", "")
        if cuenta and len(re.sub(r'\D', '', str(cuenta))) >= 6:
            validaciones["numero_cuenta"] = {"valor": cuenta, "valido": True, "mensaje": "Número de cuenta presente", "confianza": 1.0}
        else:
            validaciones["numero_cuenta"] = {"valor": cuenta, "valido": False, "mensaje": "Número de cuenta no encontrado", "confianza": 0.0}
        scores.append(validaciones["numero_cuenta"]["confianza"])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class PoderNotarialValidator:
    """Validador para Poder Notarial."""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # Número de escritura
        num_escritura = datos.get("numero_escritura", "")
        if isinstance(num_escritura, dict):
            num_escritura = num_escritura.get("valor", "")
        if num_escritura and str(num_escritura).strip():
            validaciones["numero_escritura"] = {"valor": num_escritura, "valido": True, "mensaje": "Número de escritura presente", "confianza": 1.0}
        else:
            validaciones["numero_escritura"] = {"valor": "", "valido": False, "mensaje": "Número de escritura no encontrado", "confianza": 0.0}
        scores.append(validaciones["numero_escritura"]["confianza"])

        # Nombre del apoderado
        nombre_apoderado = datos.get("nombre_apoderado", "")
        if isinstance(nombre_apoderado, dict):
            nombre_apoderado = nombre_apoderado.get("valor", "")
        if nombre_apoderado and len(str(nombre_apoderado).split()) >= 2:
            validaciones["nombre_apoderado"] = {"valor": nombre_apoderado, "valido": True, "mensaje": "Nombre completo presente", "confianza": 1.0}
        elif nombre_apoderado:
            validaciones["nombre_apoderado"] = {"valor": nombre_apoderado, "valido": True, "mensaje": "Nombre parcial", "confianza": 0.5}
        else:
            validaciones["nombre_apoderado"] = {"valor": "", "valido": False, "mensaje": "Nombre de apoderado no encontrado", "confianza": 0.0}
        scores.append(validaciones["nombre_apoderado"]["confianza"])

        # Nombre del poderdante
        nombre_poderdante = datos.get("nombre_poderdante", "")
        if isinstance(nombre_poderdante, dict):
            nombre_poderdante = nombre_poderdante.get("valor", "")
        if nombre_poderdante and len(str(nombre_poderdante)) > 3:
            validaciones["nombre_poderdante"] = {"valor": nombre_poderdante, "valido": True, "mensaje": "Poderdante identificado", "confianza": 1.0}
        else:
            validaciones["nombre_poderdante"] = {"valor": "", "valido": False, "mensaje": "Poderdante no encontrado", "confianza": 0.0}
        scores.append(validaciones["nombre_poderdante"]["confianza"])

        # Tipo de poder
        tipo_poder = datos.get("tipo_poder", "")
        if isinstance(tipo_poder, dict):
            tipo_poder = tipo_poder.get("valor", "")
        if tipo_poder and len(str(tipo_poder)) > 3:
            validaciones["tipo_poder"] = {"valor": tipo_poder, "valido": True, "mensaje": "Tipo de poder identificado", "confianza": 1.0}
        else:
            validaciones["tipo_poder"] = {"valor": "", "valido": False, "mensaje": "Tipo de poder no encontrado", "confianza": 0.0}
        scores.append(validaciones["tipo_poder"]["confianza"])

        # Fecha de otorgamiento
        fecha_otorg = datos.get("fecha_otorgamiento", "")
        if isinstance(fecha_otorg, dict):
            fecha_otorg = fecha_otorg.get("valor", "")
        _, msg, score = FieldValidator.validate_fecha(fecha_otorg)
        validaciones["fecha_otorgamiento"] = {"valor": fecha_otorg, "valido": score >= 0.5, "mensaje": msg, "confianza": score}
        scores.append(score)

        # Nombre del notario
        nombre_notario = datos.get("nombre_notario", "")
        if isinstance(nombre_notario, dict):
            nombre_notario = nombre_notario.get("valor", "")
        if nombre_notario and len(str(nombre_notario).split()) >= 2:
            validaciones["nombre_notario"] = {"valor": nombre_notario, "valido": True, "mensaje": "Nombre del notario presente", "confianza": 1.0}
        else:
            validaciones["nombre_notario"] = {"valor": "", "valido": False, "mensaje": "Nombre del notario no encontrado", "confianza": 0.0}
        scores.append(validaciones["nombre_notario"]["confianza"])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class ReformaValidator:
    """Validador para Reforma de Estatutos."""

    @classmethod
    def _get_valor(cls, datos: Dict, campo: str) -> Any:
        """Extrae el valor de un campo, manejando estructura anidada."""
        valor = datos.get(campo, "")
        if isinstance(valor, dict):
            return valor.get("valor", "") or valor.get("content", "") or ""
        return valor

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # Número de escritura
        num_escritura = cls._get_valor(datos, "numero_escritura")
        if num_escritura and str(num_escritura).strip():
            validaciones["numero_escritura"] = {"valor": num_escritura, "valido": True, "mensaje": "Número de escritura presente", "confianza": 1.0}
        else:
            validaciones["numero_escritura"] = {"valor": "", "valido": False, "mensaje": "Número de escritura no encontrado", "confianza": 0.0}
        scores.append(validaciones["numero_escritura"]["confianza"])

        # Razón social
        razon = cls._get_valor(datos, "razon_social")
        if razon and len(str(razon)) > 3:
            validaciones["razon_social"] = {"valor": razon, "valido": True, "mensaje": "Razón social presente", "confianza": 1.0}
        else:
            validaciones["razon_social"] = {"valor": razon, "valido": False, "mensaje": "Razón social no encontrada", "confianza": 0.0}
        scores.append(validaciones["razon_social"]["confianza"])

        # Fecha de otorgamiento
        fecha_otorg = cls._get_valor(datos, "fecha_otorgamiento")
        _, msg, score = FieldValidator.validate_fecha(fecha_otorg)
        validaciones["fecha_otorgamiento"] = {"valor": fecha_otorg, "valido": score >= 0.5, "mensaje": msg, "confianza": score}
        scores.append(score)

        # Nombre del notario
        nombre_notario = cls._get_valor(datos, "nombre_notario")
        if nombre_notario and len(str(nombre_notario).split()) >= 2:
            validaciones["nombre_notario"] = {"valor": nombre_notario, "valido": True, "mensaje": "Nombre del notario presente", "confianza": 1.0}
        else:
            validaciones["nombre_notario"] = {"valor": "", "valido": False, "mensaje": "Nombre del notario no encontrado", "confianza": 0.0}
        scores.append(validaciones["nombre_notario"]["confianza"])

        # Número de notaría
        num_notaria = cls._get_valor(datos, "numero_notaria")
        if num_notaria and str(num_notaria).strip():
            validaciones["numero_notaria"] = {"valor": num_notaria, "valido": True, "mensaje": "Número de notaría presente", "confianza": 1.0}
        else:
            validaciones["numero_notaria"] = {"valor": "", "valido": False, "mensaje": "Número de notaría no encontrado", "confianza": 0.0}
        scores.append(validaciones["numero_notaria"]["confianza"])

        # Folio mercantil
        folio = cls._get_valor(datos, "folio_mercantil")
        if folio and len(str(folio)) >= 4:
            validaciones["folio_mercantil"] = {"valor": folio, "valido": True, "mensaje": "Folio mercantil válido", "confianza": 1.0}
        else:
            validaciones["folio_mercantil"] = {"valor": folio, "valido": False, "mensaje": "Folio mercantil no encontrado", "confianza": 0.0}
        scores.append(validaciones["folio_mercantil"]["confianza"])

        # Estructura accionaria (lista)
        estructura = cls._get_valor(datos, "estructura_accionaria")
        if isinstance(estructura, list) and len(estructura) > 0:
            validaciones["estructura_accionaria"] = {"valor": f"{len(estructura)} accionistas", "valido": True, "mensaje": "Estructura accionaria presente", "confianza": 1.0}
        elif estructura and len(str(estructura)) > 10:
            validaciones["estructura_accionaria"] = {"valor": str(estructura)[:50] + "...", "valido": True, "mensaje": "Estructura accionaria presente", "confianza": 0.8}
        else:
            validaciones["estructura_accionaria"] = {"valor": "", "valido": False, "mensaje": "Estructura accionaria no encontrada", "confianza": 0.0}
        scores.append(validaciones["estructura_accionaria"]["confianza"])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class INEValidator:
    """Validador para INE."""

    @classmethod
    def _extract_value(cls, datos: Dict, field: str) -> str:
        """Extrae el valor de un campo, manejando estructura anidada de Azure DI."""
        value = datos.get(field, "")
        if isinstance(value, dict):
            return value.get("content", "") or value.get("valueString", "") or ""
        return value or ""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # CURP (en Azure DI se llama DocumentNumber)
        curp = cls._extract_value(datos, "DocumentNumber") or cls._extract_value(datos, "CURP") or cls._extract_value(datos, "curp")
        curp_upper = curp.upper().strip() if curp else ""

        # Validar CURP de 18 caracteres
        if curp_upper and len(curp_upper) == 18:
            # Verificar estructura básica: 4 letras + 6 dígitos + H/M + 7 caracteres
            if re.match(r"^[A-Z]{4}\d{6}[HM].{7}$", curp_upper):
                validaciones["curp"] = {"valor": curp, "valido": True, "mensaje": "CURP válida", "confianza": 1.0}
            else:
                validaciones["curp"] = {"valor": curp, "valido": True, "mensaje": "CURP presente (formato alternativo)", "confianza": 0.9}
        elif curp:
            validaciones["curp"] = {"valor": curp, "valido": False, "mensaje": f"CURP inválida ({len(curp_upper)} caracteres)", "confianza": 0.3}
        else:
            validaciones["curp"] = {"valor": "", "valido": False, "mensaje": "CURP no encontrada", "confianza": 0.0}
        scores.append(validaciones["curp"]["confianza"])

        # Nombre completo - Azure DI usa FirstName y LastName
        primer_nombre = cls._extract_value(datos, "FirstName") or cls._extract_value(datos, "Nombre")
        apellidos = cls._extract_value(datos, "LastName") or cls._extract_value(datos, "ApellidoPaterno")
        nombre = f"{primer_nombre} {apellidos}".strip()

        if len(nombre.split()) >= 2:
            validaciones["nombre"] = {"valor": nombre, "valido": True, "mensaje": "Nombre presente", "confianza": 1.0}
        else:
            validaciones["nombre"] = {"valor": nombre, "valido": False, "mensaje": "Nombre incompleto", "confianza": 0.0}
        scores.append(validaciones["nombre"]["confianza"])

        # Fecha de nacimiento (DateOfBirth en Azure DI)
        fecha_nac = cls._extract_value(datos, "DateOfBirth") or cls._extract_value(datos, "FechaNacimiento")
        _, msg, score = FieldValidator.validate_fecha(fecha_nac)
        validaciones["fecha_nacimiento"] = {"valor": fecha_nac, "valido": score >= 0.5, "mensaje": msg, "confianza": score}
        scores.append(score)

        # Vigencia (DateOfExpiration en Azure DI)
        vigencia = cls._extract_value(datos, "DateOfExpiration") or cls._extract_value(datos, "Vigencia")
        # Detectar si es una fecha válida o texto como "INE"
        if vigencia:
            # Verificar si es fecha (dd/mm/yyyy o yyyy)
            if re.match(r"^\d{2}/\d{2}/\d{4}$", vigencia):
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": "Vigencia válida", "confianza": 1.0}
            elif re.match(r"^\d{4}$", vigencia):
                # Solo año (ej: 2030)
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": f"Vigencia hasta {vigencia}", "confianza": 1.0}
            elif vigencia.upper() in ["INE", "IFE", "PERMANENTE", "VIGENTE"]:
                # Texto genérico - no es la vigencia real
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": "Vigencia no extraída correctamente (campo genérico)", "confianza": 0.5}
            else:
                # Otro valor - aceptar con confianza media
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": "Vigencia presente", "confianza": 0.8}
        else:
            validaciones["vigencia"] = {"valor": "", "valido": False, "mensaje": "Vigencia no encontrada", "confianza": 0.0}
        scores.append(validaciones["vigencia"]["confianza"])

        # Sexo
        sexo = cls._extract_value(datos, "Sex")
        if sexo and sexo.upper() in ["H", "M", "HOMBRE", "MUJER"]:
            validaciones["sexo"] = {"valor": sexo, "valido": True, "mensaje": "Sexo identificado", "confianza": 1.0}
        else:
            validaciones["sexo"] = {"valor": sexo, "valido": False, "mensaje": "Sexo no identificado", "confianza": 0.0}
        scores.append(validaciones["sexo"]["confianza"])

        # Dirección
        direccion = cls._extract_value(datos, "Address")
        if direccion and len(direccion) > 10:
            validaciones["direccion"] = {"valor": direccion[:50] + "..." if len(direccion) > 50 else direccion, "valido": True, "mensaje": "Dirección presente", "confianza": 1.0}
        else:
            validaciones["direccion"] = {"valor": direccion, "valido": False, "mensaje": "Dirección no encontrada", "confianza": 0.0}
        scores.append(validaciones["direccion"]["confianza"])

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


class INEReversoValidator:
    """Validador para INE Reverso - no penaliza por CURP y dirección (no presentes en reverso)."""

    @classmethod
    def _extract_value(cls, datos: Dict, field: str) -> str:
        """Extrae el valor de un campo, manejando estructura anidada de Azure DI."""
        value = datos.get(field, "")
        if isinstance(value, dict):
            return value.get("content", "") or value.get("valueString", "") or ""
        return value or ""

    @classmethod
    def validate_all(cls, datos: Dict[str, Any], texto_ocr: str = "") -> Dict[str, Any]:
        validaciones = {}
        scores = []

        # Nombre completo - Azure DI usa FirstName y LastName
        primer_nombre = cls._extract_value(datos, "FirstName") or cls._extract_value(datos, "Nombre")
        apellidos = cls._extract_value(datos, "LastName") or cls._extract_value(datos, "ApellidoPaterno")
        nombre = f"{primer_nombre} {apellidos}".strip()

        if len(nombre.split()) >= 2:
            validaciones["nombre"] = {"valor": nombre, "valido": True, "mensaje": "Nombre presente", "confianza": 1.0}
        elif nombre:
            validaciones["nombre"] = {"valor": nombre, "valido": True, "mensaje": "Nombre parcial", "confianza": 0.7}
        else:
            validaciones["nombre"] = {"valor": nombre, "valido": False, "mensaje": "Nombre no encontrado", "confianza": 0.0}
        scores.append(validaciones["nombre"]["confianza"])

        # Fecha de nacimiento (DateOfBirth)
        fecha_nac = cls._extract_value(datos, "DateOfBirth") or cls._extract_value(datos, "FechaNacimiento")
        _, msg, score = FieldValidator.validate_fecha(fecha_nac)
        validaciones["fecha_nacimiento"] = {"valor": fecha_nac, "valido": score >= 0.5, "mensaje": msg, "confianza": score}
        scores.append(score)

        # Vigencia (DateOfExpiration)
        vigencia = cls._extract_value(datos, "DateOfExpiration") or cls._extract_value(datos, "Vigencia")
        if vigencia:
            if re.match(r"^\d{2}/\d{2}/\d{4}$", vigencia):
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": "Vigencia válida", "confianza": 1.0}
            elif re.match(r"^\d{4}$", vigencia):
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": f"Vigencia hasta {vigencia}", "confianza": 1.0}
            else:
                validaciones["vigencia"] = {"valor": vigencia, "valido": True, "mensaje": "Vigencia presente", "confianza": 0.8}
        else:
            validaciones["vigencia"] = {"valor": "", "valido": False, "mensaje": "Vigencia no encontrada", "confianza": 0.0}
        scores.append(validaciones["vigencia"]["confianza"])

        # Sexo
        sexo = cls._extract_value(datos, "Sex")
        if sexo and sexo.upper() in ["H", "M", "HOMBRE", "MUJER"]:
            validaciones["sexo"] = {"valor": sexo, "valido": True, "mensaje": "Sexo identificado", "confianza": 1.0}
        else:
            validaciones["sexo"] = {"valor": sexo, "valido": False, "mensaje": "Sexo no identificado", "confianza": 0.0}
        scores.append(validaciones["sexo"]["confianza"])

        # CURP y Dirección son OPCIONALES en reverso (no penalizan)
        curp = cls._extract_value(datos, "DocumentNumber") or cls._extract_value(datos, "CURP")
        if curp:
            validaciones["curp"] = {"valor": curp, "valido": True, "mensaje": "CURP encontrada (bonus)", "confianza": 1.0}
            # No agregamos al score, es bonus
        else:
            validaciones["curp"] = {"valor": "", "valido": True, "mensaje": "CURP no aplica en reverso", "confianza": None}

        direccion = cls._extract_value(datos, "Address")
        if direccion:
            validaciones["direccion"] = {"valor": direccion, "valido": True, "mensaje": "Dirección encontrada (bonus)", "confianza": 1.0}
        else:
            validaciones["direccion"] = {"valor": "", "valido": True, "mensaje": "Dirección no aplica en reverso", "confianza": None}

        score_global = sum(scores) / len(scores) if scores else 0.0

        return {
            "campos": validaciones,
            "score_global": round(score_global, 2),
            "nivel_confianza": "ALTA" if score_global >= 0.9 else "MEDIA" if score_global >= 0.7 else "BAJA",
            "requiere_revision": score_global < 0.7
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE VALIDACIÓN UNIFICADAS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_extraction(datos: Dict[str, Any], doc_type: str, texto_ocr: str = "") -> Dict[str, Any]:
    """
    Función unificada para validar extracción de cualquier tipo de documento.

    Args:
        datos: Diccionario con los campos extraídos
        doc_type: Tipo de documento ("csf", "fiel", "domicilio", "estado_cuenta", "poder", "reforma", "ine", "acta")
        texto_ocr: Texto OCR original (opcional)

    Returns:
        Diccionario con validaciones, scores y recomendaciones
    """
    validators = {
        "acta": ActaConstitutivaValidator,
        "acta_constitutiva": ActaConstitutivaValidator,
        "csf": CSFValidator,
        "fiel": FIELValidator,
        "domicilio": DomicilioValidator,
        "domicilio_rl": DomicilioValidator,
        "domicilio_propietario_real": DomicilioValidator,
        "estado_cuenta": EstadoCuentaValidator,
        "poder": PoderNotarialValidator,
        "poder_notarial": PoderNotarialValidator,
        "reforma": ReformaValidator,
        "reforma_estatutos": ReformaValidator,
        "ine": INEValidator,
        "ine_reverso": INEReversoValidator,
        "ine_propietario_real": INEValidator,
    }

    validator = validators.get(doc_type.lower(), ActaConstitutivaValidator)
    return validator.validate_all(datos, texto_ocr)
