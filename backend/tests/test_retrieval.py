"""Automated tests for hybrid retrieval, cross-encoder reranking, and Layer 1 fallback.

Covers:
- Strict is_active=False deactivation filtering (deactivated documents never appear).
- Hybrid search (dense and sparse RRF fusion).
- Cross-encoder reranking quality.
- Layer 1 threshold gating (triggering fallback when score < threshold).
- Telemetry and latency reporting.
"""
import uuid
import pytest
from qdrant_client import models as qmodels

from app.core.config import settings
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.services.rag_engine import (
    get_rag_engine,
    RAGEngine,
    RetrievedChunk,
    CrossEncoderSingleton,
)


@pytest.fixture
def rag_engine() -> RAGEngine:
    return get_rag_engine()


def test_deactivated_document_never_retrieved(rag_engine: RAGEngine):
    """Prove that chunks from a deactivated document (is_active=False) NEVER appear in results."""
    qc = get_qdrant_client()

    deactivated_doc_id = str(uuid.uuid4())
    active_doc_id = str(uuid.uuid4())
    deactivated_point_id = str(uuid.uuid4())
    active_point_id = str(uuid.uuid4())

    deactivated_text = "SECRET_DEACTIVATED_DATA: Quantum Hyperdrive Blueprint 998877"
    active_text = "PUBLIC_ACTIVE_DATA: Quantum Hyperdrive Blueprint 998877"

    # Embed dummy test points
    dense_deact = rag_engine.embedding_service.embed_query(deactivated_text)
    sparse_deact = rag_engine.embedding_service.embed_sparse_query(deactivated_text)

    dense_act = rag_engine.embedding_service.embed_query(active_text)
    sparse_act = rag_engine.embedding_service.embed_sparse_query(active_text)

    # Upsert deactivated point with is_active=False
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=deactivated_point_id,
                vector={
                    "dense": dense_deact,
                    "sparse": qmodels.SparseVector(
                        indices=sparse_deact.indices,
                        values=sparse_deact.values,
                    ),
                },
                payload={
                    "chunk_id": deactivated_point_id,
                    "document_id": deactivated_doc_id,
                    "version": 1,
                    "chunk_index": 0,
                    "content": deactivated_text,
                    "token_count": 12,
                    "page_number": 1,
                    "section_heading": "Confidential",
                    "is_active": False,  # MUST BE FILTERED OUT
                },
            ),
            qmodels.PointStruct(
                id=active_point_id,
                vector={
                    "dense": dense_act,
                    "sparse": qmodels.SparseVector(
                        indices=sparse_act.indices,
                        values=sparse_act.values,
                    ),
                },
                payload={
                    "chunk_id": active_point_id,
                    "document_id": active_doc_id,
                    "version": 1,
                    "chunk_index": 0,
                    "content": active_text,
                    "token_count": 12,
                    "page_number": 2,
                    "section_heading": "Public",
                    "is_active": True,
                },
            ),
        ],
    )

    try:
        # 1. Query for the exact unique string in deactivated document
        result = rag_engine.retrieve(query="Quantum Hyperdrive Blueprint 998877")

        retrieved_chunk_ids = [c.chunk_id for c in result.chunks]
        retrieved_contents = [c.content for c in result.chunks]

        # The deactivated chunk must NEVER appear in results
        assert deactivated_point_id not in retrieved_chunk_ids, (
            "SECURITY VIOLATION: Deactivated document chunk appeared in retrieval results!"
        )
        for content in retrieved_contents:
            assert "SECRET_DEACTIVATED_DATA" not in content, (
                "SECURITY VIOLATION: Deactivated content leaked into retrieval results!"
            )

        # 2. Also check hybrid_search candidates directly
        candidates, _ = rag_engine.hybrid_search(
            query="Quantum Hyperdrive Blueprint 998877",
            top_k=20,
        )
        candidate_ids = [c.chunk_id for c in candidates]
        assert deactivated_point_id not in candidate_ids, (
            "SECURITY VIOLATION: Deactivated chunk appeared in hybrid search candidates!"
        )

    finally:
        # Cleanup test points
        qc.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qmodels.PointIdsList(points=[deactivated_point_id, active_point_id]),
        )


def test_cross_encoder_reranking_accuracy(rag_engine: RAGEngine):
    """Verify cross-encoder orders relevant chunks above irrelevant ones."""
    query = "What is a Merkle tree and how is it used in blockchains?"
    candidates = [
        RetrievedChunk(
            chunk_id="chunk-irrelevant",
            document_id="doc-1",
            version=1,
            chunk_index=0,
            content="Today the weather is sunny with a mild breeze in Seattle.",
            token_count=10,
        ),
        RetrievedChunk(
            chunk_id="chunk-relevant",
            document_id="doc-2",
            version=1,
            chunk_index=1,
            content=(
                "A Merkle tree is a cryptographic binary tree of hashes used in blockchains "
                "to efficiently verify transactions and prove data integrity."
            ),
            token_count=20,
        ),
    ]

    reranked, latency = rag_engine.rerank(query=query, candidates=candidates, top_n=2)
    assert len(reranked) == 2
    assert latency >= 0.0

    # Relevant chunk must be ranked first
    assert reranked[0].chunk_id == "chunk-relevant"
    assert reranked[1].chunk_id == "chunk-irrelevant"

    # Relevant score must be significantly higher than irrelevant score
    assert reranked[0].rerank_score > reranked[1].rerank_score
    assert reranked[0].raw_rerank_score > reranked[1].raw_rerank_score


def test_layer_1_fallback_trigger_on_low_score(rag_engine: RAGEngine, monkeypatch):
    """Verify Layer 1 returns is_fallback=True when top rerank score < RERANK_THRESHOLD."""
    # Force high threshold to trigger fallback
    monkeypatch.setattr(settings, "RERANK_THRESHOLD", 0.999999)

    result = rag_engine.retrieve(query="What is a cryptographic hash function?")
    assert result.is_fallback is True
    assert result.fallback_message == settings.FALLBACK_MESSAGE


def test_layer_1_fallback_pass_on_high_score(rag_engine: RAGEngine, monkeypatch):
    """Verify Layer 1 returns is_fallback=False when top score >= RERANK_THRESHOLD."""
    # Set low threshold to guarantee pass for in-scope knowledge
    monkeypatch.setattr(settings, "RERANK_THRESHOLD", 0.10)

    result = rag_engine.retrieve(query="What is collision resistance in a cryptographic hash function?")
    assert result.is_fallback is False
    assert result.fallback_message is None
    assert result.top_score is not None
    assert result.top_score >= 0.10
    assert len(result.chunks) > 0


def test_retrieval_latencies_and_metadata(rag_engine: RAGEngine):
    """Verify latency telemetry and structured fields in RetrievalResult."""
    result = rag_engine.retrieve(query="cryptography review")

    assert result.latency_ms_retrieval > 0.0
    assert result.latency_ms_rerank >= 0.0
    assert result.total_latency_ms >= result.latency_ms_retrieval

    result_dict = result.to_dict()
    assert "query" in result_dict
    assert "chunks" in result_dict
    assert "top_score" in result_dict
    assert "is_fallback" in result_dict
    assert "latency_ms_retrieval" in result_dict
    assert "latency_ms_rerank" in result_dict
    assert "total_latency_ms" in result_dict
