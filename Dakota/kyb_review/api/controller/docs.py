# controller/docs.py
# Logic for handling document-related requests
from pydantic import FilePath
import re
import os
import time
import logging

logger = logging.getLogger(__name__)

# ── Constantes MRZ/INE ────────────────────────────────────────────────────
_SIGLO_XX_THRESHOLD = 25        # AA > 25 → 19XX, AA ≤ 25 → 20XX
_DEFAULT_DATE_CONFIDENCE = 0.95
_DEFAULT_VIGENCIA_CONFIDENCE = 0.9

from ..model.DocType import DocType
from ..model.DocFormat import DocFormat

from .ocr.equivalencias import (
    agente_equivalencias,
    normalizar_texto_simple,
    normalizar
)
from ..service.di import analyze_document, extract_text_from_document
from ..service.document_identifier import identify_document_type
from ..service.openai import (
    init_openai_llm,
    extract_poder_fields,
    extract_acta_fields,
    extract_reforma_fields,
    extract_address_fields,
    extract_ine_reverso,
    extract_csf_fields,
    extract_fiel_fields,
    extract_estado_cuenta_fields,
    _find_page_and_paragraph,
    _buscar_valor_en_texto,
    _buscar_contexto_aproximado
)
from ..service.name_parser import parse_nombre_mexicano


def _add_ine_extraction_evidence(filtered_results: dict, text_ocr: str) -> dict:
    """
    Agrega evidencia de extracción (página y párrafo) a los campos de INE.
    Los campos de INE vienen de Azure DI con estructura {content, confidence}.
    """
    result = {}
    evidencia = {}
    confiabilidad_campos = {}
    
    for campo, valor_data in filtered_results.items():
        if isinstance(valor_data, dict) and "content" in valor_data:
            content = valor_data.get("content", "")
            confidence = valor_data.get("confidence", 0.0)
        else:
            content = str(valor_data) if valor_data else ""
            confidence = 0.0
        
        # Buscar ubicación en el texto
        if content and content not in ["", "N/A"]:
            pos = _buscar_valor_en_texto(content, text_ocr, campo)
            if pos >= 0:
                ubicacion = _find_page_and_paragraph(text_ocr, content, pos)
                evidencia[campo] = {
                    "encontrado": True,
                    "pagina": ubicacion["pagina"],
                    "parrafo": ubicacion["parrafo"]
                }
                confiabilidad_campos[campo] = confidence
            else:
                # Intentar encontrar contexto aproximado
                parrafo_aprox, pagina_aprox = _buscar_contexto_aproximado(campo, content, text_ocr)
                evidencia[campo] = {
                    "encontrado": False,
                    "pagina": pagina_aprox,
                    "parrafo": parrafo_aprox,
                    "nota": "Contexto aproximado" if parrafo_aprox else None
                }
                confiabilidad_campos[campo] = confidence * 0.8  # Reducir un poco si no se encuentra
        else:
            evidencia[campo] = {
                "encontrado": False,
                "pagina": None,
                "parrafo": None
            }
            confiabilidad_campos[campo] = 0.0
        
        # Copiar el campo original
        result[campo] = valor_data
    
    # Agregar metadata de evidencia
    result["_evidencia_extraccion"] = evidencia
    result["_confiabilidad_campos"] = confiabilidad_campos
    
    if confiabilidad_campos:
        result["_confiabilidad_promedio"] = round(
            sum(confiabilidad_campos.values()) / len(confiabilidad_campos), 2
        )
    
    return result


def _analyze_generic(
    file_path: FilePath,
    doc_type: DocType,
    doc_type_label: str,
    extract_fn,
    *,
    identification_key: str | None = None,
    normalize: bool = False,
) -> dict:
    """
    Flujo genérico de análisis de documentos basados en texto + LLM.

    1. Extrae texto con Azure DI.
    2. Identifica tipo de documento.
    3. Extrae campos estructurados con la función ``extract_fn(raw_txt, llm)``.
    4. Opcionalmente normaliza con equivalencias.
    5. Devuelve el dict de respuesta estándar.

    Args:
        file_path: Ruta al archivo.
        doc_type: DocType enum para Azure DI.
        doc_type_label: Etiqueta legible para logs.
        extract_fn: Callable(raw_txt, llm) → dict.
        identification_key: Clave que se pasa a ``identify_document_type``.
            Si es ``None`` usa ``doc_type.name``.
        normalize: Si ``True`` aplica equivalencias + normalización (acta/reforma).
    """
    logger.info("\n" + "=" * 80)
    logger.info(f"[INFO] Starting {doc_type_label} analysis...")
    logger.info("=" * 80)

    start_time = time.time()
    raw_txt = extract_text_from_document(file_path, doc_type)
    elapsed = time.time() - start_time
    logger.info(f"[INFO] Azure DI extraction completed in {elapsed:.2f} seconds")
    logger.info(f"[INFO] Extracted {len(raw_txt)} characters")

    id_key = identification_key or doc_type.name
    logger.info("[INFO] Verifying document type...")
    identification = identify_document_type(raw_txt, id_key)
    logger.info(
        f"[INFO] Document identification: is_correct={identification.is_correct}, "
        f"should_reject={identification.should_reject}"
    )

    logger.info("[INFO] Extracting structured fields with OpenAI...")
    llm = init_openai_llm()
    extracted_data = extract_fn(raw_txt, llm)
    logger.info(f"[INFO] Extracted {len(extracted_data)} fields")

    if normalize:
        extracted_data = agente_equivalencias(extracted_data)
        extracted_data = {
            k: normalizar(v) if isinstance(v, str) else v
            for k, v in extracted_data.items()
        }
        extracted_data = {
            k: normalizar_texto_simple(v) if isinstance(v, str) else v
            for k, v in extracted_data.items()
        }

    return {
        "archivo_procesado": os.path.basename(file_path),
        "datos_extraidos": extracted_data,
        "texto_ocr": raw_txt,
        "document_identification": identification.to_dict(),
    }


def get_doctype(path:FilePath) -> DocType:
    """
    Determines the document type based on the file path.
    
    Parameters:
        path (FilePath): The file path of the document.
    
    Returns:
        DocType: The determined document type.
    """
    path_lower = str(path).lower()
    if "ine_reverso" in path_lower or "ine_back" in path_lower:
        return DocType.ine_reverso
    elif "ine" in path_lower:
        return DocType.ine
    elif "estado_cuenta" in path_lower:
        return DocType.estado_cuenta
    elif "csf" in path_lower or "constancia_situacion" in path_lower:
        return DocType.csf
    elif "domicilio" in path_lower or "comprobante_domicilio" in path_lower:
        return DocType.domicilio
    elif "reforma" in path_lower or "reforma_estatutos" in path_lower:
        return DocType.reforma_estatutos
    elif "acta_constitutiva" in path_lower or "acta" in path_lower:
        return DocType.acta_constitutiva
    elif "poder" in path_lower or "poder_notarial" in path_lower:
        return DocType.poder_notarial
    elif "fiel" in path_lower:
        return DocType.fiel
    else:
        raise ValueError(f"Unsupported document type for path: {path}")

def get_docformat(path: FilePath) -> str:
    """
    Determines the document format based on the file path.
    
    Parameters:
        path (FilePath): The file path of the document.
    
    Returns:
        DocFormat: The determined document format.
    """
    str_to_search = str(path).lower()
    if ".pdf" in str_to_search:
        return DocFormat.pdf
    elif any(suffix in str_to_search for suffix in [".jpeg", ".jpg"]):
        return DocFormat.jpeg
    elif ".png" in str_to_search:
        return DocFormat.png
    else:
        raise ValueError("Unsupported document format")

def analyze_csf(file_path: FilePath) -> dict:
    """Analyzes a Constancia de Situación Fiscal document and returns extracted data."""
    return _analyze_generic(
        file_path, DocType.csf, "Constancia de Situación Fiscal",
        extract_csf_fields, identification_key="csf",
    )

def analyze_fiel(file_path: FilePath) -> dict:
    """Analyzes a FIEL (Firma Electrónica Avanzada) document and returns extracted data."""
    return _analyze_generic(
        file_path, DocType.fiel, "FIEL (Firma Electrónica Avanzada)",
        extract_fiel_fields, identification_key="fiel",
    )

def analyze_domicilio(file_path: FilePath) -> dict:
    """Analyzes a Comprobante de Domicilio document and returns extracted data."""
    return _analyze_generic(
        file_path, DocType.domicilio, "Comprobante de Domicilio",
        extract_address_fields, identification_key="comprobante_domicilio",
    )

def analyze_poder(file_path: FilePath) -> dict:
    """Analyzes a Poder Notarial document and returns extracted data."""
    return _analyze_generic(
        file_path, DocType.poder_notarial, "Poder Notarial",
        extract_poder_fields, identification_key="poder",
    )

def analyze_constitutiva(file_path: FilePath):
    """Analyzes an acta constitutiva document using Azure Document Intelligence."""
    return _analyze_generic(
        file_path, DocType.acta_constitutiva, "Acta Constitutiva",
        extract_acta_fields, identification_key="acta_constitutiva",
        normalize=True,
    )


def analyze_reforma(file_path: FilePath, acta_path: FilePath | None = None) -> dict:
    """
    Analyzes a Reforma de Estatutos document, using Acta Constitutiva as fallback context when provided.
    """
    logger.info("\n" + "="*80)
    logger.info("[INFO] Starting Reforma de Estatutos analysis...")
    logger.info("="*80)

    # Extract Reforma text
    raw_txt = extract_text_from_document(file_path, DocType.reforma_estatutos)
    logger.info(f"[INFO] Extracted {len(raw_txt)} characters from Reforma")
    
    # Step 1.5: Verify document type BEFORE calling LLM
    logger.info("[INFO] Verifying document type...")
    identification = identify_document_type(raw_txt, "reforma")
    logger.info(f"[INFO] Document identification: is_correct={identification.is_correct}, should_reject={identification.should_reject}")

    # Optional Acta context
    acta_text = ""
    if acta_path:
        try:
            acta_text = extract_text_from_document(acta_path, DocType.acta_constitutiva)
            logger.info(f"[INFO] Extracted {len(acta_text)} characters from Acta (fallback)")
        except Exception as e:
            logger.warning(f"[WARNING] Could not extract Acta fallback: {e}")

    llm = init_openai_llm()

    # Primary extraction using Reforma (with Acta as secondary context inside prompt)
    extracted_primary = extract_reforma_fields(raw_txt, llm, acta_text)

    # Secondary extraction directly on Acta if fields remain empty and Acta is available
    extracted_fallback = {}
    if acta_text:
        need_fallback = any(
            (not v) if isinstance(v, str) else (isinstance(v, list) and not v)
            for v in extracted_primary.values()
            if v is not None
        )
        if need_fallback:
            extracted_fallback = extract_reforma_fields(acta_text, llm)

    # Merge fallback values for missing fields
    merged = {}
    for k, v in extracted_primary.items():
        if isinstance(v, list):
            merged[k] = v if v else (extracted_fallback.get(k, []) if extracted_fallback else [])
        else:
            merged[k] = v if v else (extracted_fallback.get(k, "") if extracted_fallback else "")

    # Equivalences / normalization (skip lists)
    extraidos_eq = agente_equivalencias(merged)
    extraidos_norm = {
        k: normalizar(v) if isinstance(v, str) else v
        for k, v in extraidos_eq.items()
    }
    extraidos_norm_simple = {
        k: normalizar_texto_simple(v) if isinstance(v, str) else v
        for k, v in extraidos_norm.items()
    }

    # Return response
    return {
        "archivo_procesado": os.path.basename(file_path),
        "datos_extraidos": extraidos_norm,
        "texto_ocr": raw_txt,
        "document_identification": identification.to_dict()
    }

def analyze_ine(file_path: FilePath, format: DocFormat) -> dict:
    """
    Analyzes an INE document and returns the extracted data.
    
    Parameters:
        file_path (FilePath): The path to the INE document.
    
    Returns:
        dict: The extracted data.
    """
    logger.info("\n" + "="*80)
    logger.info("[INFO] Starting INE analysis with custom Azure DI model...")
    logger.info("="*80)
    
    # Step 1: Use custom Azure DI model for INE
    result = analyze_document(file_path, DocType.ine, format.value)
    if not result:
        raise ValueError("Failed to analyze INE document")
    
    fields = result['analyzeResult']['documents'][0]['fields']
    logger.info(f"[INFO] Azure DI extracted {len(fields)} fields")
    
    # Step 2: Clean field data
    filtered_results = {}
    for field_name, field_data in fields.items():
        if not field_data:
            continue
        
        content = None
        if "content" in field_data:
            content = field_data["content"]
        elif "valueString" in field_data:
            content = field_data["valueString"]
        elif "valueDate" in field_data:
            content = field_data["valueDate"]
        elif "value" in field_data:
            content = field_data["value"]
        
        if content is None or content == "":
            continue
        
        confidence = field_data.get("confidence", 0.0)
        filtered_results[field_name] = {
            "content": content,
            "confidence": confidence
        }
    
    # Step 2.5: Fix DateOfExpiration if it contains generic text like "INE"
    date_exp = filtered_results.get("DateOfExpiration", {})
    date_exp_content = date_exp.get("content", "") if isinstance(date_exp, dict) else str(date_exp)
    
    if date_exp_content.upper() in ["INE", "IFE", "INSTITUTO", "ELECTORAL"]:
        # Try to extract year from other fields or text
        import re
        # Look for year pattern in all extracted content
        all_content = " ".join(
            str(v.get("content", "") if isinstance(v, dict) else v) 
            for v in filtered_results.values()
        )
        # Search for vigencia year pattern (2020-2030, 2025, etc.)
        year_match = re.search(r'\b(202\d|203\d)\b', all_content)
        if year_match:
            filtered_results["DateOfExpiration"] = {
                "content": year_match.group(1),
                "confidence": 0.7  # Lower confidence since it's a fallback
            }
            logger.info(f"[INFO] Fixed DateOfExpiration: {year_match.group(1)} (extracted from content)")
    
    # Step 3: Extract full text using the DI pipeline
    logger.info("[INFO] Extracting full text (DI pages)...")
    try:
        raw_txt = extract_text_from_document(file_path, DocType.ine)
    except Exception as e:
        logger.warning(f"[WARNING] Could not extract text: {e}")
        raw_txt = str(filtered_results)  # Fallback to structured data
    
    # Step 3.1: Verify document type
    logger.info("[INFO] Verifying document type...")
    identification = identify_document_type(raw_txt, "ine")
    logger.info(f"[INFO] Document identification: is_correct={identification.is_correct}, should_reject={identification.should_reject}")
    
    # Step 3.5: Extract CURP from OCR if not detected by Azure DI
    if "curp" not in filtered_results or not filtered_results.get("curp", {}).get("content"):
        import re
        # CURP format: 18 characters (4 letters, 6 digits, 6 letters/digits, 2 digits)
        # Example: CUTO840628HCSRRS07
        curp_pattern = r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b'
        curp_match = re.search(curp_pattern, raw_txt.upper())
        if curp_match:
            curp_value = curp_match.group(0)
            filtered_results["curp"] = {
                "content": curp_value,
                "confidence": 0.9  # High confidence for regex match
            }
            logger.info(f"[INFO] CURP extracted from OCR: {curp_value}")
        else:
            logger.warning("[WARNING] CURP not found in OCR text")
    
    # Step 4: Add extraction evidence (page and paragraph) for INE fields
    filtered_results = _add_ine_extraction_evidence(filtered_results, raw_txt)
    
    # Step 5: Parse name into components (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido)
    first_name = filtered_results.get("FirstName", {})
    last_name = filtered_results.get("LastName", {})
    
    first_name_content = first_name.get("content", "") if isinstance(first_name, dict) else str(first_name)
    last_name_content = last_name.get("content", "") if isinstance(last_name, dict) else str(last_name)
    
    # Combinar nombre completo para parsing
    nombre_completo = f"{first_name_content} {last_name_content}".strip()
    
    if nombre_completo:
        parsed_name = parse_nombre_mexicano(nombre_completo)
        # Calcular confianza promedio de los campos de nombre originales
        first_name_conf = first_name.get("confidence", 0.0) if isinstance(first_name, dict) else 0.0
        last_name_conf = last_name.get("confidence", 0.0) if isinstance(last_name, dict) else 0.0
        base_confidence = (first_name_conf + last_name_conf) / 2 if (first_name_conf + last_name_conf) > 0 else 0.5
        
        # Agregar campos de nombre parseados
        filtered_results["primer_nombre"] = {
            "content": parsed_name.primer_nombre,
            "confidence": base_confidence * parsed_name.confianza
        }
        filtered_results["segundo_nombre"] = {
            "content": parsed_name.segundo_nombre or "",
            "confidence": base_confidence * parsed_name.confianza if parsed_name.segundo_nombre else 0.0
        }
        filtered_results["primer_apellido"] = {
            "content": parsed_name.primer_apellido,
            "confidence": base_confidence * parsed_name.confianza
        }
        filtered_results["segundo_apellido"] = {
            "content": parsed_name.segundo_apellido or "",
            "confidence": base_confidence * parsed_name.confianza if parsed_name.segundo_apellido else 0.0
        }
        filtered_results["nombre_completo"] = {
            "content": nombre_completo,
            "confidence": base_confidence
        }
        filtered_results["_nombre_parsing"] = {
            "confianza_parsing": parsed_name.confianza,
            "nombre_original": parsed_name.nombre_completo_original
        }
        logger.info(f"[INFO] Nombre parseado: {parsed_name.primer_nombre} | {parsed_name.segundo_nombre} | {parsed_name.primer_apellido} | {parsed_name.segundo_apellido}")
    
    # Return response
    return {
        "archivo_procesado": os.path.basename(file_path),
        "datos_extraidos": filtered_results,
        "texto_ocr": raw_txt,
        "document_identification": identification.to_dict()
    }

def analyze_ine_reverso(file_path: FilePath, format: DocFormat) -> dict:
    """
    Analyzes the back side of an INE document.
    
    Parameters:
        file_path (FilePath): The path to the INE back document.
        format (DocFormat): The format of the document.
    
    Returns:
        dict: The extracted data.
    """
    logger.info("\n" + "="*80)
    logger.info("[INFO] Starting INE Reverso analysis with custom Azure DI model...")
    logger.info("="*80)
    
    # Step 1: Use custom Azure DI model for INE back
    # NOTE: Don't use fast=True - INE reverso can take 20-35 seconds
    result = analyze_document(file_path, DocType.ine_reverso, format.value, fast=False)
    if not result:
        raise ValueError("Failed to analyze INE back document")
    
    fields = result['analyzeResult']['documents'][0]['fields']
    logger.info(f"[INFO] Azure DI extracted {len(fields)} fields from INE back")
    
    # Clean field data - handle both 'content' and 'valueString' from different field types
    filtered_results = {}
    for field_name, field_data in fields.items():
        # Skip empty fields
        if not field_data:
            continue
            
        # Extract content based on field type
        content = None
        if "content" in field_data:
            content = field_data["content"]
        elif "valueString" in field_data:
            content = field_data["valueString"]
        elif "valueDate" in field_data:
            content = field_data["valueDate"]
        elif "value" in field_data:
            content = field_data["value"]
        
        # Skip fields with no content
        if content is None or content == "":
            continue
            
        confidence = field_data.get("confidence", 0.0)
        filtered_results[field_name] = {
            "content": content,
            "confidence": confidence
        }
    
    # Step 2: Extract full text using the DI pipeline
    logger.info("[INFO] Extracting full text (DI pages)...")
    try:
        raw_txt = extract_text_from_document(file_path, DocType.ine_reverso)
    except Exception as e:
        logger.warning(f"[WARNING] Could not extract text: {e}")
        raw_txt = str(filtered_results)  # Fallback to structured data
    
    # Step 2.1: Verify document type
    logger.info("[INFO] Verifying document type...")
    identification = identify_document_type(raw_txt, "ine_reverso")
    logger.info(f"[INFO] Document identification: is_correct={identification.is_correct}, should_reject={identification.should_reject}")
    
    # Step 3: Parse MRZ data if IdMex field exists
    if "IdMex" in filtered_results:
        mrz_data = filtered_results["IdMex"]
        mrz_content = mrz_data.get("content", "") if isinstance(mrz_data, dict) else str(mrz_data)
        parsed_mrz = _parse_ine_mrz(mrz_content, raw_txt)
        
        # Add parsed fields with confidence from MRZ parsing
        for field_name, field_info in parsed_mrz.items():
            if field_name not in filtered_results:
                filtered_results[field_name] = field_info
        
        logger.info(f"[INFO] Parsed {len(parsed_mrz)} additional fields from MRZ")
    
    # Step 4: Add extraction evidence (page and paragraph) for INE reverso fields
    filtered_results = _add_ine_extraction_evidence(filtered_results, raw_txt)
    
    # Return response
    return {
        "archivo_procesado": os.path.basename(file_path),
        "datos_extraidos": filtered_results,
        "texto_ocr": raw_txt,
        "document_identification": identification.to_dict()
    }


def _parse_ine_mrz(mrz_string: str, texto_ocr: str = "") -> dict:
    """
    Parsea la cadena MRZ (Machine Readable Zone) de una INE mexicana.
    
    Formato típico MRZ INE (3 líneas):
    Línea 1: IDMEX + número de documento + << + CIC
    Línea 2: AAMMDD + dígito verificador + Sexo + vigencia + MEX + validadores
    Línea 3: APELLIDOS << NOMBRES
    
    Ejemplo: 8601160H3412318MEX
    - 860116 = Fecha nacimiento AAMMDD (16/01/1986)
    - 0 = Dígito verificador
    - H = Sexo (Hombre)
    - 341231 = Vigencia AAMMDD (31/12/2034)
    
    Args:
        mrz_string: Cadena MRZ completa
        texto_ocr: Texto OCR completo para búsqueda adicional
    
    Returns:
        dict: Campos parseados con confiabilidad
    """
    result = {}
    
    # Limpiar MRZ
    mrz_clean = mrz_string.replace('\n', ' ').replace(' ', '')
    
    # Buscar patrón de fecha nacimiento + sexo + vigencia
    # Formato: AAMMDD + dígito(0-9) + H/M + AAMMDD (vigencia)
    fecha_match = re.search(r'(\d{6})\d([HM])(\d{6})', mrz_clean)
    if fecha_match:
        fecha_nac_raw = fecha_match.group(1)  # AAMMDD nacimiento
        sexo = fecha_match.group(2)
        fecha_vig_raw = fecha_match.group(3)  # AAMMDD vigencia
        
        # Convertir fecha nacimiento AAMMDD a DD/MM/AAAA
        try:
            aa_nac = fecha_nac_raw[0:2]
            mm_nac = fecha_nac_raw[2:4]
            dd_nac = fecha_nac_raw[4:6]
            # Para nacimiento: siglo XX si año > 25, siglo XXI si <= 25
            siglo_nac = "19" if int(aa_nac) > _SIGLO_XX_THRESHOLD else "20"
            fecha_nacimiento = f"{dd_nac}/{mm_nac}/{siglo_nac}{aa_nac}"
            
            result["DateOfBirth"] = {
                "content": fecha_nacimiento,
                "confidence": _DEFAULT_DATE_CONFIDENCE
            }
        except (ValueError, IndexError) as e:
            logger.debug("Error parseando fecha nacimiento MRZ: %s", e)
        
        # Convertir vigencia AAMMDD a DD/MM/AAAA
        try:
            aa_vig = fecha_vig_raw[0:2]
            mm_vig = fecha_vig_raw[2:4]
            dd_vig = fecha_vig_raw[4:6]
            # Para vigencia: siempre siglo XXI (20XX) ya que son fechas futuras
            fecha_vigencia = f"{dd_vig}/{mm_vig}/20{aa_vig}"
            
            result["DateOfExpiration"] = {
                "content": fecha_vigencia,
                "confidence": _DEFAULT_VIGENCIA_CONFIDENCE
            }
        except (ValueError, IndexError) as e:
            logger.debug("Error parseando fecha vigencia MRZ: %s", e)
        
        # Sexo
        sexo_texto = "HOMBRE" if sexo == "H" else "MUJER"
        result["Sex"] = {
            "content": sexo_texto,
            "confidence": 0.98
        }
    
    # Buscar CURP en el texto OCR (18 caracteres con formato específico)
    curp_match = re.search(r'[A-Z]{4}\d{6}[HM][A-Z]{2}[A-Z0-9]{3}[A-Z0-9]{2}', texto_ocr.upper())
    if curp_match:
        result["DocumentNumber"] = {
            "content": curp_match.group(0),
            "confidence": 0.95
        }
    
    # Buscar nombre en el MRZ (APELLIDOS<APELLIDO2<<NOMBRE o APELLIDO<<NOMBRE)
    nombre_match = re.search(r'([A-Z]+)<([A-Z]+)\s*<<\s*([A-Z]+)', mrz_string.upper())
    if nombre_match:
        apellido1 = nombre_match.group(1).replace('<', ' ').strip()
        apellido2 = nombre_match.group(2).replace('<', ' ').strip()
        nombre = nombre_match.group(3).replace('<', ' ').strip()
        
        result["LastName"] = {
            "content": f"{apellido1} {apellido2}".title(),
            "confidence": 0.9
        }
        result["FirstName"] = {
            "content": nombre.title(),
            "confidence": 0.9
        }
    
    return result


def analyze_estado_cuenta(file_path: FilePath, format: DocFormat = None) -> dict:
    """Analyzes an Estado de Cuenta (bank statement) document and returns extracted data."""
    return _analyze_generic(
        file_path, DocType.estado_cuenta, "Estado de Cuenta",
        extract_estado_cuenta_fields, identification_key="estado_cuenta",
    )