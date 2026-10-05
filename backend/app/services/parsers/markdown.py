"""Markdown Document parser preserving heading hierarchies."""
from typing import List, Dict, Any
import re
from app.core.logger import logger


def parse_markdown(file_path: str) -> List[Dict[str, Any]]:
    """Parse Markdown file, grouping text under nearest heading sections."""
    logger.info(f"Parsing Markdown: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        raise ValueError(f"Failed to read Markdown file '{file_path}': {exc}") from exc

    lines = content.splitlines()
    sections: List[Dict[str, Any]] = []
    current_section = None
    current_lines: List[str] = []

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            if current_lines:
                text_block = "\n".join(current_lines).strip()
                if text_block:
                    sections.append({
                        "text": text_block,
                        "page": None,
                        "section": current_section,
                    })
                current_lines = []
            current_section = match.group(2).strip()
        else:
            current_lines.append(line)

    if current_lines:
        text_block = "\n".join(current_lines).strip()
        if text_block:
            sections.append({
                "text": text_block,
                "page": None,
                "section": current_section,
            })

    return sections
