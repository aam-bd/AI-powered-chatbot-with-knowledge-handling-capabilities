"""Citation resolution and Layer 3 verification service.

Implements Architecture §6.6 and Prompt 4:
- Extracts [Cn] tags from generated answer using regex.
- Drops hallucinated tags whose numbers were not in the injected context.
- Layer 3 check: If NO valid tag remains, triggers retraction with FALLBACK_MESSAGE.
- Otherwise resolves valid tags to {tag, document, page, section, chunk_id}.
"""
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from app.core.logger import logger
from app.models.schemas import CitationItem
from app.services.rag_engine import RetrievedChunk


@dataclass
class CitationResolutionResult:
    """Outcome of Layer 3 citation verification."""
    citations: List[CitationItem] = field(default_factory=list)
    valid_tags: List[int] = field(default_factory=list)
    hallucinated_tags: List[int] = field(default_factory=list)
    is_retracted: bool = False

    @property
    def cited_chunk_ids(self) -> List[str]:
        return [c.chunk_id for c in self.citations]


class CitationService:
    """Service to extract, filter, and resolve citation tags."""

    TAG_PATTERN = re.compile(r"\[C(\d+)\]")

    def extract_tags(self, text: str) -> List[int]:
        """Extract ordered, distinct integer citation tags from text."""
        if not text:
            return []
        matches = self.TAG_PATTERN.findall(text)
        tags: List[int] = []
        seen = set()
        for m in matches:
            tag_num = int(m)
            if tag_num not in seen:
                seen.add(tag_num)
                tags.append(tag_num)
        return tags

    def resolve_citations(
        self,
        text: str,
        context_chunks: List[RetrievedChunk],
        doc_name_lookup: Optional[Dict[str, str]] = None,
    ) -> CitationResolutionResult:
        """Resolve citation tags from answer text against injected context chunks.

        Rules (Architecture §6.6):
        1. Extract tags with \\[C(\\d+)\\].
        2. Discard any tag whose number was not in the injected context.
        3. If NO valid tag remains, send a retract event (Layer 3 fallback).
        4. Otherwise resolve each valid tag to {tag, document, page, section, chunk_id}.
        """
        doc_names = doc_name_lookup or {}
        extracted = self.extract_tags(text)
        max_context = len(context_chunks)

        valid_tags: List[int] = []
        hallucinated_tags: List[int] = []

        for tag_num in extracted:
            if 1 <= tag_num <= max_context:
                valid_tags.append(tag_num)
            else:
                hallucinated_tags.append(tag_num)

        if hallucinated_tags:
            logger.warning(
                f"Layer 3: Pruned hallucinated citation tags: {hallucinated_tags} "
                f"(context size={max_context})"
            )

        # Layer 3 trigger: no valid citations exist in the generated text
        if not valid_tags:
            logger.info("Layer 3: No valid citations found in answer text. Triggering retraction.")
            return CitationResolutionResult(
                citations=[],
                valid_tags=[],
                hallucinated_tags=hallucinated_tags,
                is_retracted=True,
            )

        citations: List[CitationItem] = []
        for tag_num in valid_tags:
            chunk = context_chunks[tag_num - 1]
            doc_name = (
                doc_names.get(chunk.document_id)
                or getattr(chunk, "document_name", None)
                or f"Document {chunk.document_id[:8]}"
            )
            citations.append(
                CitationItem(
                    tag=f"C{tag_num}",
                    document=doc_name,
                    page=chunk.page_number,
                    section=chunk.section_heading,
                    chunk_id=chunk.chunk_id,
                )
            )

        return CitationResolutionResult(
            citations=citations,
            valid_tags=valid_tags,
            hallucinated_tags=hallucinated_tags,
            is_retracted=False,
        )


_citation_service_instance: Optional[CitationService] = None


def get_citation_service() -> CitationService:
    """Singleton getter for CitationService."""
    global _citation_service_instance
    if _citation_service_instance is None:
        _citation_service_instance = CitationService()
    return _citation_service_instance
