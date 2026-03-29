# di.py
# Document Intelligence petitions
from os import getenv
import time
import requests
from dotenv import load_dotenv
from pydantic import FilePath
import logging

from ..model.DocFormat import DocFormat
from ..model.DocType import DocType
from .optimizer import (
    analyze_pdf_type,
    extract_text_local,
    should_try_local_extraction,
    get_cached_result,
    save_to_cache,
    PDFAnalysisResult,
    optimize_for_azure,
    cleanup_compressed_file
)
from .resilience import (
    get_circuit_breaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    retry_with_backoff,
    AzureDIRetryConfig
)

logger = logging.getLogger(__name__)

# Circuit breaker para Azure Document Intelligence
_azure_di_cb_config = CircuitBreakerConfig(
    failure_threshold=3,      # 3 fallos consecutivos
    success_threshold=2,      # 2 éxitos para recuperar
    timeout_seconds=120.0     # 2 minutos en estado OPEN
)
azure_di_circuit_breaker = get_circuit_breaker("azure_di", _azure_di_cb_config)

# Load environment variables - usar ruta absoluta basada en __file__
from pathlib import Path
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path)

AZURE_ENDPOINT  = getenv("DI_ENDPOINT")
AZURE_KEY       = getenv("DI_KEY")

# Using custom trained models
models = {
    DocType.ine:                "INE_Front",            # Custom INE front model
    DocType.estado_cuenta:      "prebuilt-layout",      # Layout model for bank statements
    DocType.ine_reverso:        "INE_Back",             # Custom INE back model
    DocType.acta_constitutiva:  "prebuilt-layout",      # Layout model for multi-page docs
    DocType.domicilio:          "prebuilt-layout",      # Layout model for proof of address
    DocType.csf:                "prebuilt-layout",      # Layout model for tax status certificate
    DocType.fiel:               "prebuilt-layout",      # Layout model for FIEL certificate
    DocType.poder_notarial:     "prebuilt-layout",      # Layout model for notarial power
    DocType.reforma_estatutos:  "prebuilt-layout"       # Layout model for reforma de estatutos
}


def analyze_document(file_path: FilePath, doctype: DocType, filetype: str, *, fast: bool = False, use_cache: bool = True) -> dict | None:
    """
    Sends a file to the Azure Document Intelligence Custom Extraction Model
    and returns the analysis results.

    Parameters:
        file_path (str): Path to the file to be analyzed.
        doctype (DocType): Type of document to analyze.
        filetype (DocFormat): Format of the document file.
        use_cache (bool): If True, check cache before calling Azure. Default True.

    Returns:
        dict: JSON response with the extracted data, or None if an error occurred.
    
    Raises:
        CircuitBreakerOpen: If Azure DI service is unavailable (too many failures).
    """
    import os
    filename = os.path.basename(file_path)
    
    # =========================================================================
    # CACHE CHECK - Avoid redundant Azure calls for already processed files
    # =========================================================================
    if use_cache:
        cached = get_cached_result(file_path, doctype)
        if cached is not None:
            logger.info(f"[CACHE HIT] Returning cached result for {filename} ({doctype.value})")
            return cached
    
    # Verificar circuit breaker antes de intentar
    if not azure_di_circuit_breaker.can_execute():
        logger.error(f"Azure DI circuit breaker OPEN - skipping request for {filename}")
        raise CircuitBreakerOpen("azure_di")
    
    logger.info(f"Analyzing document: {filename} | type={doctype.value} | format={filetype}")
    
    if doctype not in models:
        logger.error(f"Unsupported document type: {doctype}")
        return None
    if not AZURE_ENDPOINT or not AZURE_KEY or not models[doctype]:
        raise ValueError("Missing one or more environment variables.")
    
    # =========================================================================
    # PDF COMPRESSION OPTIMIZATION
    # =========================================================================
    optimized_path, compression_stats = optimize_for_azure(file_path)
    if compression_stats.get("compressed"):
        logger.info(f"[COMPRESS] Compression stats: {compression_stats}")
    
    logger.debug(f"Analyzing document: {optimized_path}")
    endpoint = AZURE_ENDPOINT.rstrip('/')
    url = f"{endpoint}/documentintelligence/documentModels/{models[doctype]}:analyze?_overload=analyzeDocument&api-version=2024-11-30"
    logger.debug(f"Request URL: {url}")

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": filetype
    }

    try:
        # Usar retry para la solicitud inicial
        def submit_document():
            with open(optimized_path, "rb") as file:
                response = requests.post(url, headers=headers, data=file, timeout=60)
            
            if response.status_code == 429:
                # Rate limited - es retryable
                raise requests.exceptions.HTTPError(f"Rate limited: {response.status_code}")
            
            if response.status_code != 202:
                logger.error(f"Error submitting document: {response.status_code} - {response.text}")
                raise requests.exceptions.HTTPError(f"Azure DI error: {response.status_code}")
            
            return response
        
        response = retry_with_backoff(
            submit_document,
            config=AzureDIRetryConfig(),
            circuit_breaker=azure_di_circuit_breaker,
            operation_name=f"Azure DI submit ({filename})"
        )

        operation_location = response.headers.get("operation-location")
        if not operation_location:
            logger.error("No operation-location found in response headers.")
            return None

        # Polling con retry
        if fast:
            result = poll_analysis_result_fast(operation_location)
        else:
            result = poll_analysis_result(operation_location)
        
        if result:
            azure_di_circuit_breaker.record_success()
            logger.info(f"Azure DI analysis successful for {filename}")
            # Save to cache for future requests
            if use_cache:
                save_to_cache(file_path, doctype, result)
        else:
            azure_di_circuit_breaker.record_failure(Exception("Analysis returned None"))
        
        return result
        
    except CircuitBreakerOpen:
        raise
    except Exception as e:
        azure_di_circuit_breaker.record_failure(e)
        logger.error(f"Azure DI analysis failed for {filename}: {type(e).__name__}: {e}")
        raise
    finally:
        # Clean up compressed file if it was created
        cleanup_compressed_file(optimized_path, file_path)


def poll_analysis_result(operation_url: str, max_retries:int = 20, interval:int = 3):
    """
    Polls the operation result URL until the analysis is complete.

    Parameters:
        operation_url (str): The URL to check the analysis result.
        max_retries (int): Maximum number of retries. Default 20 = 60 seconds max.
        interval (int): Seconds to wait between retries.

    Returns:
        dict: JSON response with the extracted results, or None if failed.
    """
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY}

    for attempt in range(max_retries):
        try:
            result = requests.get(operation_url, headers=headers, timeout=30)
            result_json = result.json()

            status = result_json.get("status")
            logger.debug(f"Poll attempt {attempt + 1}/{max_retries}: status={status}")
            
            if status is None:
                logger.error("No status found in the result.")
                return None
            if status == "succeeded":
                logger.info(f"Analysis succeeded after {attempt + 1} poll attempts")
                return result_json
            elif status == "failed":
                error_msg = result_json.get('error', {}).get('message', 'Unknown error')
                logger.error(f"Analysis failed: {error_msg}")
                return None

            time.sleep(interval)
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Poll attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(interval)
            else:
                raise

    logger.error(f"Max retries ({max_retries}) reached without success.")
    return None


def poll_analysis_result_fast(operation_url: str, max_retries:int = 6, interval:int = 2):
    """Faster polling for optional/back analyses. 6 retries × 2s = 12s max."""
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY}
    
    for attempt in range(max_retries):
        try:
            result = requests.get(operation_url, headers=headers, timeout=15)
            result_json = result.json()
            status = result_json.get("status")
            
            if status is None:
                logger.error("No status found in the result.")
                return None
            if status == "succeeded":
                logger.info(f"Fast analysis succeeded after {attempt + 1} poll attempts")
                return result_json
            elif status == "failed":
                error_msg = result_json.get('error', {}).get('message', 'Unknown error')
                logger.error(f"Fast analysis failed: {error_msg}")
                return None
            
            time.sleep(interval)
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Fast poll attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(interval)
    
    logger.warning("Max retries reached without success (fast mode).")
    return None


def extract_text_from_document(file_path: FilePath, doctype: DocType) -> str:
    """
    Extracts full text from a multi-page document.
    
    OPTIMIZED: First attempts local extraction for native PDFs (FREE).
    Falls back to Azure Document Intelligence for scanned documents.
    
    Parameters:
        file_path (FilePath): Path to the document file.
        doctype (DocType): Type of document to analyze.
    
    Returns:
        str: Extracted text with page markers in format [[[PÁGINA:N]]].
    """
    import os
    filename = os.path.basename(file_path)
    
    # Check if this document type supports local extraction optimization
    if should_try_local_extraction(doctype):
        # Analyze PDF to determine if it's native or scanned
        analysis = analyze_pdf_type(file_path)
        
        if analysis.is_native:
            # Native PDF - extract locally (FREE, no Azure cost)
            logger.info(f"[OPTIMIZATION] PDF NATIVO detectado - Usando extraccion LOCAL ($0)")
            logger.info(f"   Archivo: {filename}")
            logger.info(f"   Caracteres: {analysis.char_count} | Paginas: {analysis.page_count}")
            logger.info(f"[OPTIMIZATION] Using LOCAL extraction for {file_path} (saving Azure cost)")
            return extract_text_local(file_path)
        else:
            logger.info(f"[AZURE] PDF ESCANEADO detectado - Requiere Azure Document Intelligence ($)")
            logger.info(f"   Archivo: {filename}")
            logger.info(f"   Paginas: {analysis.page_count}")
            logger.info(f"[AZURE] Scanned PDF detected, using Azure DI for {file_path}")
    else:
        logger.info(f"[AZURE] Tipo de documento {doctype.value} requiere Azure DI")
        logger.info(f"[AZURE] Document type {doctype} requires Azure DI")
    
    # Fall back to Azure Document Intelligence
    return _extract_text_with_azure(file_path, doctype)


def _extract_text_with_azure(file_path: FilePath, doctype: DocType) -> str:
    """
    Internal function: Extracts text using Azure Document Intelligence.
    Called when local extraction is not possible (scanned documents).
    
    Parameters:
        file_path (FilePath): Path to the document file.
        doctype (DocType): Type of document to analyze.
    
    Returns:
        str: Extracted text with page markers in format [[[PÁGINA:N]]].
    """
    result = analyze_document(file_path, doctype, "application/pdf")
    if not result:
        raise ValueError("Failed to analyze document with Azure DI")
    
    # Extract text from pages with enhanced metadata
    pages = result.get('analyzeResult', {}).get('pages', [])
    full_text = ""
    
    for page in pages:
        page_num = page.get('pageNumber', 0)
        lines = page.get('lines', [])
        
        # Extract text with confidence scores (if available)
        page_lines = []
        for line in lines:
            content = line.get('content', '')
            # Note: Some Azure DI models provide confidence at word level
            # We include the content directly for text extraction
            page_lines.append(content)
        
        page_text = "\n".join(page_lines)
        full_text += f"\n\n[[[PÁGINA:{page_num}]]]\n\n{page_text}\n"
    
    return full_text.strip()


def extract_structured_data_from_document(file_path: FilePath, doctype: DocType) -> dict:
    """
    Extracts structured data with confidence scores and page references from a document.
    This function provides richer metadata than extract_text_from_document.
    
    Parameters:
        file_path (FilePath): Path to the document file.
        doctype (DocType): Type of document to analyze.
    
    Returns:
        dict: Structured data including key-value pairs, confidence scores, and page references.
    """
    result = analyze_document(file_path, doctype, "application/pdf")
    if not result:
        raise ValueError("Failed to analyze document with Azure DI")
    
    structured_data = {
        "pages": [],
        "key_value_pairs": [],
        "tables": [],
        "metadata": {
            "model_id": models.get(doctype),
            "api_version": "2024-11-30"
        }
    }
    
    analyze_result = result.get('analyzeResult', {})
    
    # Extract page information
    for page in analyze_result.get('pages', []):
        page_data = {
            "page_number": page.get('pageNumber'),
            "width": page.get('width'),
            "height": page.get('height'),
            "unit": page.get('unit'),
            "lines": [],
            "words": []
        }
        
        # Extract lines with confidence
        for line in page.get('lines', []):
            page_data["lines"].append({
                "content": line.get('content'),
                "bounding_box": line.get('polygon', []),
                "spans": line.get('spans', [])
            })
        
        # Extract words with confidence (if available)
        for word in page.get('words', []):
            page_data["words"].append({
                "content": word.get('content'),
                "confidence": word.get('confidence', 1.0),
                "bounding_box": word.get('polygon', [])
            })
        
        structured_data["pages"].append(page_data)
    
    # Extract key-value pairs (if available in document results)
    for doc in analyze_result.get('documents', []):
        for field_name, field_data in doc.get('fields', {}).items():
            if field_data:
                key_value_pair = {
                    "key": field_name,
                    "value": field_data.get('content') or field_data.get('valueString') or field_data.get('value'),
                    "confidence": field_data.get('confidence', 0.0),
                    "spans": field_data.get('spans', [])
                }
                structured_data["key_value_pairs"].append(key_value_pair)
    
    # Extract tables (if available)
    for table in analyze_result.get('tables', []):
        table_data = {
            "row_count": table.get('rowCount'),
            "column_count": table.get('columnCount'),
            "cells": []
        }
        for cell in table.get('cells', []):
            table_data["cells"].append({
                "row_index": cell.get('rowIndex'),
                "column_index": cell.get('columnIndex'),
                "content": cell.get('content'),
                "confidence": cell.get('confidence', 1.0)
            })
        structured_data["tables"].append(table_data)
    
    return structured_data


if __name__ == "__main__":
    FILE_PATH = FilePath("temp/PruebaEmiliano.jpeg")  # Replace with your file path
    result = analyze_document(FILE_PATH)
    if result:
        logger.info("[OK] Analysis Result:")
        logger.info(result)
