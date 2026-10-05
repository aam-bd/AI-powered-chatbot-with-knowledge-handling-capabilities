"""DOCX Document parser using python-docx, extracting headings as section metadata."""
from typing import List, Dict, Any
import docx
from app.core.logger import logger


def parse_docx(file_path: str) -> List[Dict[str, Any]]:
    """Parse a DOCX file, associating text blocks with their closest heading."""
    logger.info(f"Parsing DOCX: {file_path}")
    try:
        doc = docx.Document(file_path)
    except Exception as exc:
        raise ValueError(f"Failed to open DOCX document '{file_path}': {exc}") from exc

    sections: List[Dict[str, Any]] = []
    current_section = None
    current_paragraphs: List[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = (para.style.name if para.style else "").lower()
        if "heading" in style_name or style_name.startswith("title"):
            if current_paragraphs:
                sections.append({
                    "text": "\n\n".join(current_paragraphs),
                    "page": None,
                    "section": current_section,
                })
                current_paragraphs = []
            current_section = text
        else:
            current_paragraphs.append(text)

    # Flush remaining text
    if current_paragraphs:
        sections.append({
            "text": "\n\n".join(current_paragraphs),
            "page": None,
            "section": current_section,
        })

    return sections
