# optimizer.py
# PDF optimization module for cost reduction
# Detects native PDFs and extracts text locally to avoid unnecessary Azure calls
# Compresses scanned PDFs before sending to Azure to reduce bandwidth and cost

import fitz  # PyMuPDF
import hashlib
import json
import os
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from pydantic import FilePath

from ..model.DocType import DocType
from ..config import JSON_DIR

logger = logging.getLogger(__name__)

# Minimum characters to consider a PDF as "native" (has extractable text)
MIN_TEXT_THRESHOLD = 100

# Minimum characters per page to consider a PDF as truly native
# If a 13-page PDF has only 1300 chars, it's likely mostly scanned images
MIN_CHARS_PER_PAGE = 200

# Cache directory for processed documents
CACHE_DIR = Path(JSON_DIR) / "cache"

# Compression settings
MAX_IMAGE_DPI = 150          # 150 DPI is sufficient for OCR
JPEG_QUALITY = 85            # Good balance between quality and size
MAX_FILE_SIZE_MB = 4         # Azure DI limit is 500MB, but we optimize above 4MB
COMPRESSION_ENABLED = True   # Toggle to enable/disable compression


class PDFAnalysisResult:
    """Result of PDF analysis with optimization metadata."""
    
    def __init__(
        self,
        is_native: bool,
        text: str,
        page_count: int,
        char_count: int,
        image_count: int,
        file_hash: str
    ):
        self.is_native = is_native
        self.text = text
        self.page_count = page_count
        self.char_count = char_count
        self.image_count = image_count
        self.file_hash = file_hash
    
    def __repr__(self):
        pdf_type = "NATIVE" if self.is_native else "SCANNED"
        return f"PDFAnalysis({pdf_type}, pages={self.page_count}, chars={self.char_count})"


def get_file_hash(file_path: FilePath) -> str:
    """
    Calculate SHA256 hash of a file for caching purposes.
    
    Parameters:
        file_path: Path to the file.
    
    Returns:
        str: SHA256 hash of the file.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def analyze_pdf_type(file_path: FilePath) -> PDFAnalysisResult:
    """
    Analyze a PDF to determine if it's native (text-based) or scanned (image-based).
    
    A PDF is considered "native" if it contains extractable text (>100 characters).
    Native PDFs can be processed locally without Azure Document Intelligence.
    
    Parameters:
        file_path: Path to the PDF file.
    
    Returns:
        PDFAnalysisResult: Analysis result with PDF metadata.
    """
    file_hash = get_file_hash(file_path)
    
    try:
        doc = fitz.open(file_path)
        total_text = ""
        total_images = 0
        
        for page in doc:
            total_text += page.get_text()
            total_images += len(page.get_images())
        
        page_count = len(doc)
        doc.close()
        
        char_count = len(total_text.strip())
        
        # A PDF is native if:
        # 1. Has more than MIN_TEXT_THRESHOLD characters total AND
        # 2. Has at least MIN_CHARS_PER_PAGE average characters per page
        # This prevents false positives where a mostly-scanned PDF has a small text footer
        chars_per_page = char_count / page_count if page_count > 0 else 0
        is_native = char_count > MIN_TEXT_THRESHOLD and chars_per_page >= MIN_CHARS_PER_PAGE
        
        logger.info(
            f"PDF Analysis: {os.path.basename(file_path)} - "
            f"{'NATIVE' if is_native else 'SCANNED'} "
            f"({char_count} chars, {page_count} pages, {chars_per_page:.0f} chars/page, {total_images} images)"
        )
        
        return PDFAnalysisResult(
            is_native=is_native,
            text=total_text if is_native else "",
            page_count=page_count,
            char_count=char_count,
            image_count=total_images,
            file_hash=file_hash
        )
        
    except Exception as e:
        logger.error(f"Error analyzing PDF {file_path}: {e}")
        # If analysis fails, assume it needs Azure OCR
        return PDFAnalysisResult(
            is_native=False,
            text="",
            page_count=0,
            char_count=0,
            image_count=0,
            file_hash=file_hash
        )


def extract_text_local(file_path: FilePath) -> str:
    """
    Extract text from a native PDF using PyMuPDF (local, no cloud cost).
    Includes page markers in the same format as Azure DI for compatibility.
    
    Parameters:
        file_path: Path to the PDF file.
    
    Returns:
        str: Extracted text with page markers in format [[[PÁGINA:N]]].
    """
    try:
        doc = fitz.open(file_path)
        full_text = ""
        
        for i, page in enumerate(doc):
            page_num = i + 1
            page_text = page.get_text()
            full_text += f"\n\n[[[PÁGINA:{page_num}]]]\n\n{page_text}\n"
        
        doc.close()
        logger.info(f"Local extraction successful: {len(full_text)} characters")
        return full_text.strip()
        
    except Exception as e:
        logger.error(f"Error extracting text locally from {file_path}: {e}")
        raise ValueError(f"Failed to extract text locally: {e}")


def get_cached_result(file_path: FilePath, doctype: DocType) -> Optional[dict]:
    """
    Check if we have a cached result for this exact file.
    
    Parameters:
        file_path: Path to the file.
        doctype: Type of document.
    
    Returns:
        dict: Cached result if exists, None otherwise.
    """
    try:
        file_hash = get_file_hash(file_path)
        cache_file = CACHE_DIR / f"{file_hash}_{doctype.value}.json"
        
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                logger.info(f"Cache HIT for {os.path.basename(file_path)}")
                return cached
        
        return None
        
    except Exception as e:
        logger.warning(f"Error reading cache: {e}")
        return None


def save_to_cache(file_path: FilePath, doctype: DocType, result: dict) -> None:
    """
    Save a processing result to cache.
    
    Parameters:
        file_path: Path to the original file.
        doctype: Type of document.
        result: Result to cache.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        file_hash = get_file_hash(file_path)
        cache_file = CACHE_DIR / f"{file_hash}_{doctype.value}.json"
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Cached result for {os.path.basename(file_path)}")
        
    except Exception as e:
        logger.warning(f"Error saving to cache: {e}")


def smart_extract_text(
    file_path: FilePath,
    doctype: DocType,
    azure_fallback_fn
) -> Tuple[str, bool]:
    """
    Smart text extraction that uses local extraction for native PDFs
    and falls back to Azure for scanned documents.
    
    Parameters:
        file_path: Path to the PDF file.
        doctype: Type of document.
        azure_fallback_fn: Function to call Azure DI if needed.
    
    Returns:
        Tuple[str, bool]: (extracted_text, used_azure)
            - extracted_text: The full text from the document
            - used_azure: True if Azure was used, False if local extraction
    """
    # Analyze PDF type
    analysis = analyze_pdf_type(file_path)
    
    if analysis.is_native:
        # Native PDF - extract locally (FREE)
        logger.info(f"[LOCAL] Using LOCAL extraction for {os.path.basename(file_path)} (saving Azure cost)")
        text = extract_text_local(file_path)
        return text, False
    else:
        # Scanned PDF - must use Azure OCR
        logger.info(f"[AZURE] Using AZURE extraction for {os.path.basename(file_path)} (scanned document)")
        text = azure_fallback_fn(file_path, doctype)
        return text, True


def get_optimization_stats(file_paths: list[FilePath]) -> dict:
    """
    Analyze a batch of files and return optimization statistics.
    
    Parameters:
        file_paths: List of PDF file paths to analyze.
    
    Returns:
        dict: Statistics about potential cost savings.
    """
    native_count = 0
    scanned_count = 0
    native_pages = 0
    scanned_pages = 0
    
    for file_path in file_paths:
        if str(file_path).lower().endswith('.pdf'):
            analysis = analyze_pdf_type(file_path)
            if analysis.is_native:
                native_count += 1
                native_pages += analysis.page_count
            else:
                scanned_count += 1
                scanned_pages += analysis.page_count
    
    total_files = native_count + scanned_count
    savings_percentage = (native_count / total_files * 100) if total_files > 0 else 0
    
    # Estimated cost per page (Azure DI prebuilt-layout)
    COST_PER_PAGE = 0.01  # $0.01 USD per page (approximate)
    estimated_savings = native_pages * COST_PER_PAGE
    
    return {
        "total_files": total_files,
        "native_pdfs": native_count,
        "scanned_pdfs": scanned_count,
        "native_pages": native_pages,
        "scanned_pages": scanned_pages,
        "savings_percentage": round(savings_percentage, 1),
        "estimated_savings_usd": round(estimated_savings, 2)
    }


# Document types that support local extraction optimization
OPTIMIZABLE_DOCTYPES = {
    DocType.estado_cuenta,      # Bank statements often have native text
    DocType.csf,                # Some CSFs are native PDFs
    DocType.domicilio,          # Some utility bills are native
    DocType.acta_constitutiva,  # Some notarial docs are native
    DocType.poder_notarial,     # Some notarial docs are native
    DocType.reforma_estatutos,  # Some notarial docs are native
    DocType.fiel,               # FIEL certificates may be native
}

# Document types that ALWAYS need Azure (image-based)
AZURE_REQUIRED_DOCTYPES = {
    DocType.ine,                # INE is always a scanned ID
    DocType.ine_reverso,        # INE back is always scanned
}


def should_try_local_extraction(doctype: DocType) -> bool:
    """
    Determine if we should attempt local extraction for this document type.
    
    Parameters:
        doctype: Type of document.
    
    Returns:
        bool: True if local extraction should be attempted.
    """
    if doctype in AZURE_REQUIRED_DOCTYPES:
        return False
    return doctype in OPTIMIZABLE_DOCTYPES


# =============================================================================
# PDF COMPRESSION FOR AZURE UPLOAD OPTIMIZATION
# =============================================================================

def get_file_size_mb(file_path: FilePath) -> float:
    """Get file size in megabytes."""
    return os.path.getsize(file_path) / (1024 * 1024)


def compress_pdf_for_azure(file_path: FilePath) -> Tuple[FilePath, dict]:
    """
    Compress a PDF before sending to Azure Document Intelligence.
    
    This function:
    1. Reduces image resolution to 150 DPI (sufficient for OCR)
    2. Converts images to grayscale (reduces size ~40%)
    3. Compresses with JPEG quality 85
    
    Parameters:
        file_path: Path to the original PDF file.
    
    Returns:
        Tuple[FilePath, dict]: 
            - Path to compressed file (or original if compression not needed)
            - Stats dictionary with compression metrics
    """
    if not COMPRESSION_ENABLED:
        return file_path, {"compressed": False, "reason": "compression_disabled"}
    
    original_size_mb = get_file_size_mb(file_path)
    
    # Only compress if file is larger than threshold
    if original_size_mb <= MAX_FILE_SIZE_MB:
        logger.info(f"[OK] File {os.path.basename(file_path)} is {original_size_mb:.2f}MB - no compression needed")
        return file_path, {
            "compressed": False,
            "reason": "below_threshold",
            "original_size_mb": round(original_size_mb, 2)
        }
    
    logger.info(f"[COMPRESS] Compressing {os.path.basename(file_path)} ({original_size_mb:.2f}MB)...")
    
    try:
        # Open the PDF
        doc = fitz.open(file_path)
        
        # Create a new PDF for the compressed version
        new_doc = fitz.open()
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Render page to image at reduced DPI
            # 150 DPI is sufficient for OCR while reducing size significantly
            mat = fitz.Matrix(MAX_IMAGE_DPI / 72, MAX_IMAGE_DPI / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)  # Grayscale
            
            # Convert to JPEG bytes
            img_bytes = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
            
            # Create new page with same dimensions
            new_page = new_doc.new_page(
                width=page.rect.width,
                height=page.rect.height
            )
            
            # Insert compressed image
            new_page.insert_image(
                new_page.rect,
                stream=img_bytes
            )
        
        # Save compressed PDF to temp file
        temp_dir = Path(tempfile.gettempdir())
        compressed_path = temp_dir / f"compressed_{os.path.basename(file_path)}"
        new_doc.save(compressed_path, garbage=4, deflate=True)
        
        new_doc.close()
        doc.close()
        
        compressed_size_mb = get_file_size_mb(compressed_path)
        savings_percent = ((original_size_mb - compressed_size_mb) / original_size_mb) * 100
        
        stats = {
            "compressed": True,
            "original_size_mb": round(original_size_mb, 2),
            "compressed_size_mb": round(compressed_size_mb, 2),
            "savings_percent": round(savings_percent, 1),
            "savings_mb": round(original_size_mb - compressed_size_mb, 2)
        }
        
        logger.info(
            f"[OK] Compressed {os.path.basename(file_path)}: "
            f"{original_size_mb:.2f}MB → {compressed_size_mb:.2f}MB "
            f"({savings_percent:.1f}% reduction)"
        )
        
        return compressed_path, stats
        
    except Exception as e:
        logger.error(f"[ERROR] Compression failed for {file_path}: {e}")
        # Return original file if compression fails
        return file_path, {
            "compressed": False,
            "reason": f"error: {str(e)}",
            "original_size_mb": round(original_size_mb, 2)
        }


def compress_image_for_azure(file_path: FilePath) -> Tuple[FilePath, dict]:
    """
    Compress an image (JPEG/PNG) before sending to Azure.
    
    Parameters:
        file_path: Path to the original image file.
    
    Returns:
        Tuple[FilePath, dict]: Path to compressed file and stats.
    """
    if not COMPRESSION_ENABLED:
        return file_path, {"compressed": False, "reason": "compression_disabled"}
    
    original_size_mb = get_file_size_mb(file_path)
    
    # Only compress if larger than 1MB
    if original_size_mb <= 1.0:
        return file_path, {
            "compressed": False,
            "reason": "below_threshold",
            "original_size_mb": round(original_size_mb, 2)
        }
    
    try:
        # Open with PyMuPDF (works for images too)
        doc = fitz.open(file_path)
        page = doc[0]
        
        # Render at reduced resolution in grayscale
        mat = fitz.Matrix(MAX_IMAGE_DPI / 72, MAX_IMAGE_DPI / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        
        # Save compressed
        temp_dir = Path(tempfile.gettempdir())
        compressed_path = temp_dir / f"compressed_{os.path.basename(file_path)}"
        
        if str(file_path).lower().endswith('.png'):
            pix.save(compressed_path)
        else:
            # Save as JPEG
            compressed_path = compressed_path.with_suffix('.jpg')
            img_bytes = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
            with open(compressed_path, 'wb') as f:
                f.write(img_bytes)
        
        doc.close()
        
        compressed_size_mb = get_file_size_mb(compressed_path)
        savings_percent = ((original_size_mb - compressed_size_mb) / original_size_mb) * 100
        
        return compressed_path, {
            "compressed": True,
            "original_size_mb": round(original_size_mb, 2),
            "compressed_size_mb": round(compressed_size_mb, 2),
            "savings_percent": round(savings_percent, 1)
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Image compression failed: {e}")
        return file_path, {"compressed": False, "reason": f"error: {str(e)}"}


def optimize_for_azure(file_path: FilePath) -> Tuple[FilePath, dict]:
    """
    Main optimization function - decides whether to compress based on file type and size.
    
    Parameters:
        file_path: Path to the file to optimize.
    
    Returns:
        Tuple[FilePath, dict]: Optimized file path and compression stats.
    """
    file_ext = str(file_path).lower()
    
    if file_ext.endswith('.pdf'):
        return compress_pdf_for_azure(file_path)
    elif file_ext.endswith(('.jpg', '.jpeg', '.png')):
        return compress_image_for_azure(file_path)
    else:
        # Other file types - return as-is
        return file_path, {"compressed": False, "reason": "unsupported_format"}


def cleanup_compressed_file(compressed_path: FilePath, original_path: FilePath) -> None:
    """
    Clean up temporary compressed file after Azure processing.
    
    Parameters:
        compressed_path: Path to the compressed file.
        original_path: Path to the original file.
    """
    if compressed_path != original_path:
        try:
            if os.path.exists(compressed_path):
                os.remove(compressed_path)
                logger.debug(f"[CLEANUP] Cleaned up compressed file: {compressed_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup compressed file: {e}")
