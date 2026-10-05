"""Search CLI inspection script.

Usage:
    python -m scripts.search "What is linear regression?"
    python -m scripts.search "Your question here" --threshold 0.5
"""
import sys
import argparse
from typing import Optional

from app.core.config import settings
from app.services.rag_engine import get_rag_engine, RetrievalResult


def run_search(
    query: str,
    threshold: Optional[float] = None,
    top_k: Optional[int] = None,
    top_n: Optional[int] = None,
) -> RetrievalResult:
    """Run RAG retrieval and print formatted standalone results."""
    # Temporarily override threshold if provided
    active_threshold = threshold if threshold is not None else settings.RERANK_THRESHOLD

    engine = get_rag_engine()
    result = engine.retrieve(query=query)

    # Re-evaluate fallback decision if custom threshold was passed
    if threshold is not None:
        if not result.chunks or result.top_score is None or result.top_score < threshold:
            result.is_fallback = True
            result.fallback_message = settings.FALLBACK_MESSAGE
        else:
            result.is_fallback = False
            result.fallback_message = None

    print("\n" + "=" * 80)
    print(f"SEARCH QUERY: \"{query}\"")
    print("=" * 80)

    # Decision Banner
    if result.is_fallback:
        print("\n[!] LAYER 1 DECISION: FALLBACK TRIGGERED")
        if result.top_score is not None:
            print(f"    Reason: Top score {result.top_score:.4f} is BELOW threshold {active_threshold:.4f}")
        else:
            print("    Reason: No candidate chunks retrieved from knowledge base")
        print(f"    Canned Message: \"{result.fallback_message}\"")
    else:
        print("\n[+] LAYER 1 DECISION: PASSED")
        print(f"    Reason: Top score {result.top_score:.4f} satisfies threshold {active_threshold:.4f}")

    print("\n--- Telemetry & Latencies ---")
    print(f"  Retrieval Latency: {result.latency_ms_retrieval:.2f} ms")
    print(f"  Reranking Latency: {result.latency_ms_rerank:.2f} ms")
    print(f"  Total Latency:     {result.total_latency_ms:.2f} ms")
    if result.top_score is not None:
        print(f"  Best Score:        {result.top_score:.5f} (raw logit: {result.raw_top_score:.4f})")
    print(f"  Active Threshold:  {active_threshold:.4f}")

    print(f"\n--- Retrieved Chunks (Top {len(result.chunks)}) ---")
    if not result.chunks:
        print("  (No chunks found)")
    else:
        for i, chunk in enumerate(result.chunks, start=1):
            page_info = f"Page {chunk.page_number}" if chunk.page_number else "Page N/A"
            section_info = f"Section: {chunk.section_heading}" if chunk.section_heading else "Section: N/A"
            print(f"\n[{i}] Rerank Score: {chunk.rerank_score:.5f} | Raw Logit: {chunk.raw_rerank_score:+.4f} | RRF Score: {chunk.retrieval_score:.5f}")
            print(f"    Doc ID: {chunk.document_id} (v{chunk.version}, chunk #{chunk.chunk_index})")
            print(f"    Location: {page_info} | {section_info}")
            # Snippet of text
            snippet = chunk.content.replace("\n", " ").strip()
            if len(snippet) > 220:
                snippet = snippet[:220] + "..."
            print(f"    Content: \"{snippet}\"")

    print("\n" + "=" * 80 + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description="Standalone Knowledge Base Hybrid Search & Reranker CLI")
    parser.add_argument("question", type=str, nargs="?", help="Question or query string to search for")
    parser.add_argument("--query", "-q", type=str, help="Alternative query flag")
    parser.add_argument("--threshold", "-t", type=float, default=None, help="Custom RERANK_THRESHOLD override")
    parser.add_argument("--top-k", "-k", type=int, default=None, help="Hybrid retrieval candidate count")
    parser.add_argument("--top-n", "-n", type=int, default=None, help="Cross-encoder top chunks kept")

    args = parser.parse_args()
    query_text = args.question or args.query
    if not query_text:
        parser.print_help()
        sys.exit(1)

    run_search(
        query=query_text,
        threshold=args.threshold,
        top_k=args.top_k,
        top_n=args.top_n,
    )


if __name__ == "__main__":
    main()
