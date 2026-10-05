"""Plain text parser with encoding detection."""
from typing import List, Dict, Any
from app.core.logger import logger


def parse_text(file_path: str) -> List[Dict[str, Any]]:
    """Parse plain text file."""
    logger.info(f"Parsing Text file: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="latin-1") as f:
            content = f.read()
    except Exception as exc:
        raise ValueError(f"Failed to read text file '{file_path}': {exc}") from exc

    text = content.strip()
    if not text:
        return []

    return [{
        "text": text,
        "page": None,
        "section": None,
    }]
