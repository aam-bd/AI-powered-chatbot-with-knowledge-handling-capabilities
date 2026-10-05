"""PDF Document parser using PyMuPDF (fitz), preserving page numbers and table text."""
from typing import List, Dict, Any, Optional
import fitz
from app.core.logger import logger
from app.core.config import settings


def parse_pdf(file_path: str) -> List[Dict[str, Any]]:
    """Parse a PDF file, extracting text per page and retaining page metadata."""
    logger.info(f"Parsing PDF: {file_path}")
    pages: List[Dict[str, Any]] = []

    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise ValueError(f"Failed to open PDF document '{file_path}': {exc}") from exc

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_text = page.get_text("text").strip()

            # Optional OCR fallback if page text is empty and ENABLE_OCR is enabled
            if not page_text and settings.ENABLE_OCR:
                try:
                    import pytesseract
                    from PIL import Image
                    import io

                    pix = page.get_pixmap()
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    page_text = pytesseract.image_to_string(img).strip()
                except Exception as ocr_err:
                    logger.warning(f"OCR failed for PDF page {page_idx + 1}: {ocr_err}")

            if page_text:
                pages.append({
                    "text": page_text,
                    "page": page_idx + 1,
                    "section": None,
                })
    finally:
        doc.close()

    return pages
