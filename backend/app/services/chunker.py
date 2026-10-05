"""Token chunking module with structural metadata preservation and deterministic IDs."""
import re
import uuid
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import tiktoken

from app.core.config import settings
from app.core.logger import logger


@dataclass
class TextChunk:
    """Representation of an ingested text chunk."""
    chunk_id: str
    document_id: str
    version: int
    chunk_index: int
    content: str
    token_count: int
    page_number: Optional[int] = None
    section_heading: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        """Convert chunk metadata to Qdrant payload dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "version": self.version,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "token_count": self.token_count,
            "page_number": self.page_number,
            "section_heading": self.section_heading,
        }


def get_tokenizer():
    """Get tiktoken cl100k_base encoding."""
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        logger.warning(f"Could not load tiktoken cl100k_base: {exc}, using cl100k_base fallback")
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, tokenizer=None) -> int:
    """Count tokens for a text string."""
    if not text:
        return 0
    if tokenizer is None:
        tokenizer = get_tokenizer()
    return len(tokenizer.encode(text, disallowed_special=()))


def generate_chunk_id(document_id: str, version: int, chunk_index: int) -> str:
    """Generate deterministic RFC 4122 UUID from document_id, version, and chunk_index."""
    seed = f"{document_id}:{version}:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def split_text_into_units(text: str) -> List[str]:
    """Split text into sentences/paragraphs while keeping structure."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    units: List[str] = []

    for para in paragraphs:
        # If paragraph is very short, keep it together
        if len(para) < 200:
            units.append(para)
            continue

        # Split on sentence boundaries (. ! ?) followed by whitespace
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for s in sentences:
            s_clean = s.strip()
            if s_clean:
                units.append(s_clean)

    return units if units else [text.strip()]


def chunk_document(
    parsed_blocks: List[Dict[str, Any]],
    document_id: str,
    version: int,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[TextChunk]:
    """Chunk parsed document blocks into token-capped chunks with overlap.

    Args:
        parsed_blocks: List of dicts with 'text', 'page', and 'section'.
        document_id: UUID string of the document.
        version: Version number of this ingestion.
        chunk_size: Target token size per chunk (default from settings: 650).
        chunk_overlap: Overlap tokens between consecutive chunks (default from settings: 80).

    Returns:
        List of TextChunk instances with deterministic chunk_ids.
    """
    target_size = chunk_size or settings.CHUNK_SIZE_TOKENS
    overlap_size = chunk_overlap or settings.CHUNK_OVERLAP_TOKENS
    tokenizer = get_tokenizer()

    chunks: List[TextChunk] = []
    chunk_index = 0

    current_units: List[str] = []
    current_tokens = 0
    current_page: Optional[int] = None
    current_section: Optional[str] = None

    def flush_chunk():
        nonlocal chunk_index, current_units, current_tokens, current_page, current_section
        if not current_units:
            return

        chunk_text = " ".join(current_units).strip()
        if not chunk_text:
            current_units = []
            current_tokens = 0
            return

        token_cnt = count_tokens(chunk_text, tokenizer)
        c_id = generate_chunk_id(document_id, version, chunk_index)

        chunks.append(
            TextChunk(
                chunk_id=c_id,
                document_id=document_id,
                version=version,
                chunk_index=chunk_index,
                content=chunk_text,
                token_count=token_cnt,
                page_number=current_page,
                section_heading=current_section,
            )
        )
        chunk_index += 1

        # Retain tail units for overlap
        if overlap_size > 0 and len(current_units) > 1:
            overlap_units: List[str] = []
            overlap_tok = 0
            for u in reversed(current_units):
                u_tok = count_tokens(u, tokenizer)
                if overlap_tok + u_tok <= overlap_size:
                    overlap_units.insert(0, u)
                    overlap_tok += u_tok
                else:
                    break
            current_units = overlap_units
            current_tokens = overlap_tok
        else:
            current_units = []
            current_tokens = 0

    for block in parsed_blocks:
        block_text = block.get("text", "").strip()
        if not block_text:
            continue

        page = block.get("page")
        section = block.get("section")

        if current_page is None and page is not None:
            current_page = page
        if current_section is None and section is not None:
            current_section = section

        units = split_text_into_units(block_text)

        for unit in units:
            unit_tokens = count_tokens(unit, tokenizer)

            # If a single unit exceeds target_size, split by tokens
            if unit_tokens > target_size:
                # Flush existing buffer first
                if current_units:
                    flush_chunk()

                # Slice oversized unit by tokens
                raw_tokens = tokenizer.encode(unit, disallowed_special=())
                step = max(1, target_size - overlap_size)
                for start_idx in range(0, len(raw_tokens), step):
                    sub_tokens = raw_tokens[start_idx : start_idx + target_size]
                    sub_text = tokenizer.decode(sub_tokens).strip()
                    if sub_text:
                        c_id = generate_chunk_id(document_id, version, chunk_index)
                        chunks.append(
                            TextChunk(
                                chunk_id=c_id,
                                document_id=document_id,
                                version=version,
                                chunk_index=chunk_index,
                                content=sub_text,
                                token_count=len(sub_tokens),
                                page_number=page or current_page,
                                section_heading=section or current_section,
                            )
                        )
                        chunk_index += 1
                current_units = []
                current_tokens = 0
                current_page = page
                current_section = section
                continue

            # If adding unit exceeds target_size, flush chunk
            if current_tokens + unit_tokens > target_size and current_units:
                flush_chunk()
                current_page = page
                current_section = section

            current_units.append(unit)
            current_tokens += unit_tokens
            if page is not None:
                current_page = page
            if section is not None:
                current_section = section

    # Flush any remaining units
    if current_units:
        flush_chunk()

    return chunks
