"""Acceptance evaluation script for Prompt 3.

Runs 5 in-scope and 5 out-of-scope questions against sample_kb using RAGEngine.
Collects top scores (both sigmoid-normalized and raw logit), latencies, and fallback status.
"""
from app.services.rag_engine import get_rag_engine
from app.core.config import settings

IN_SCOPE_QUESTIONS = [
    "What is collision resistance in a cryptographic hash function?",
    "What is a Merkle tree and how does it verify transactions?",
    "What is the Byzantine Generals Problem in distributed consensus?",
    "What is puzzle friendliness and how is it used in Bitcoin proof of work?",
    "What is the difference between symmetric and asymmetric encryption?",
]

OUT_OF_SCOPE_QUESTIONS = [
    "How do you cook a traditional French beef bourguignon?",
    "What are the official rules and player positions in professional basketball?",
    "How does the Python Global Interpreter Lock (GIL) impact multithreading?",
    "What is quantum entanglement and how does Bell's theorem test it?",
    "How do central banks use interest rate adjustments to fight macroeconomic inflation?",
]


def main():
    engine = get_rag_engine()
    results_in = []
    results_out = []

    print("\n" + "=" * 90)
    print("PROMPT 3 ACCEPTANCE EVALUATION: 5 IN-SCOPE & 5 OUT-OF-SCOPE QUESTIONS")
    print(f"Current Configured RERANK_THRESHOLD: {settings.RERANK_THRESHOLD}")
    print("=" * 90 + "\n")

    print(">>> RUNNING IN-SCOPE QUESTIONS:")
    for q in IN_SCOPE_QUESTIONS:
        res = engine.retrieve(query=q)
        results_in.append(res)
        status = "PASSED" if not res.is_fallback else "FALLBACK"
        top_s = f"{res.top_score:.5f}" if res.top_score is not None else "N/A"
        raw_s = f"{res.raw_top_score:+.4f}" if res.raw_top_score is not None else "N/A"
        print(f"  [IN-SCOPE] \"{q}\"")
        print(f"      Top Score: {top_s} (Raw Logit: {raw_s}) | Decision: {status} | Latency: {res.total_latency_ms:.1f}ms")
        if res.chunks:
            top_chunk = res.chunks[0]
            print(f"      Top Chunk: [p.{top_chunk.page_number}] {top_chunk.content[:100]}...")

    print("\n>>> RUNNING OUT-OF-SCOPE QUESTIONS:")
    for q in OUT_OF_SCOPE_QUESTIONS:
        res = engine.retrieve(query=q)
        results_out.append(res)
        status = "PASSED" if not res.is_fallback else "FALLBACK"
        top_s = f"{res.top_score:.5f}" if res.top_score is not None else "N/A"
        raw_s = f"{res.raw_top_score:+.4f}" if res.raw_top_score is not None else "N/A"
        print(f"  [OUT-OF-SCOPE] \"{q}\"")
        print(f"      Top Score: {top_s} (Raw Logit: {raw_s}) | Decision: {status} | Latency: {res.total_latency_ms:.1f}ms")
        if res.chunks:
            top_chunk = res.chunks[0]
            print(f"      Top Chunk: [p.{top_chunk.page_number}] {top_chunk.content[:100]}...")

    print("\n" + "=" * 90)
    print("EVALUATION SUMMARY & EMPIRICAL SCORE SEPARATION")
    print("=" * 90)
    print(f"{'Category':<14} | {'Top Score (Sigmoid)':<20} | {'Raw Logit':<14} | {'Query'}")
    print("-" * 90)
    for res in results_in:
        top_s = f"{res.top_score:.5f}" if res.top_score is not None else "N/A"
        raw_s = f"{res.raw_top_score:+.4f}" if res.raw_top_score is not None else "N/A"
        print(f"{'In-Scope':<14} | {top_s:<20} | {raw_s:<14} | {res.query[:45]}...")

    print("-" * 90)
    for res in results_out:
        top_s = f"{res.top_score:.5f}" if res.top_score is not None else "N/A"
        raw_s = f"{res.raw_top_score:+.4f}" if res.raw_top_score is not None else "N/A"
        print(f"{'Out-of-Scope':<14} | {top_s:<20} | {raw_s:<14} | {res.query[:45]}...")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
