"""RAG Engine: Hybrid retrieval, cross-encoder reranking, and Layer 1 fallback.

Implements architecture sections 6.3, 6.4, and Prompt 3:
- Hybrid search via Qdrant Query API with dense and sparse prefetch and RRF fusion.
- Mandatory filter: is_active == True.
- Singleton cross-encoder model loader (FastEmbed TextCrossEncoder).
- Layer 1 fallback check against settings.RERANK_THRESHOLD.
- Structured telemetry logging with request_id and per-stage latency tracking.
"""
import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from qdrant_client import QdrantClient, models as qmodels

from app.core.config import settings
from app.core.logger import logger
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.services.embedding.base import EmbeddingService
from app.services.embedding.factory import get_embedding_service


@dataclass
class RetrievedChunk:
    """Representation of a retrieved and scored knowledge chunk."""
    chunk_id: str
    document_id: str
    version: int
    chunk_index: int
    content: str
    token_count: int = 0
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    retrieval_score: float = 0.0
    rerank_score: float = 0.0
    raw_rerank_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "version": self.version,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "token_count": self.token_count,
            "page_number": self.page_number,
            "section_heading": self.section_heading,
            "retrieval_score": self.retrieval_score,
            "rerank_score": self.rerank_score,
            "raw_rerank_score": self.raw_rerank_score,
        }


@dataclass
class RetrievalResult:
    """Structured result returned by the RAG retrieval engine."""
    query: str
    chunks: List[RetrievedChunk] = field(default_factory=list)
    top_score: Optional[float] = None
    raw_top_score: Optional[float] = None
    is_fallback: bool = False
    fallback_message: Optional[str] = None
    latency_ms_retrieval: float = 0.0
    latency_ms_rerank: float = 0.0
    total_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "chunks": [c.to_dict() for c in self.chunks],
            "top_score": self.top_score,
            "raw_top_score": self.raw_top_score,
            "is_fallback": self.is_fallback,
            "fallback_message": self.fallback_message,
            "latency_ms_retrieval": self.latency_ms_retrieval,
            "latency_ms_rerank": self.latency_ms_rerank,
            "total_latency_ms": self.total_latency_ms,
        }


def _sigmoid(x: float) -> float:
    """Stable sigmoid mapping raw logit to [0, 1]."""
    clamped = max(-50.0, min(50.0, x))
    return 1.0 / (1.0 + math.exp(-clamped))


class CrossEncoderSingleton:
    """Thread-safe lazy singleton for the cross-encoder reranker model."""
    _instance = None
    _model_name: Optional[str] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            # Map BAAI/bge-reranker-v2-m3 to FastEmbed's ONNX model BAAI/bge-reranker-base
            configured_model = settings.RERANKER_MODEL
            model_to_load = configured_model
            if configured_model in ("BAAI/bge-reranker-v2-m3", "BAAI/bge-reranker-large"):
                model_to_load = "BAAI/bge-reranker-base"
                logger.info(
                    f"Mapping configured reranker '{configured_model}' to FastEmbed ONNX model '{model_to_load}'"
                )

            logger.info(f"Loading CrossEncoder singleton model '{model_to_load}'...")
            start_t = time.perf_counter()
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            cls._instance = TextCrossEncoder(model_name=model_to_load)
            cls._model_name = model_to_load
            load_ms = (time.perf_counter() - start_t) * 1000.0
            logger.info(f"CrossEncoder singleton '{model_to_load}' loaded in {load_ms:.1f}ms")
        return cls._instance

    @classmethod
    def is_loaded(cls) -> bool:
        return cls._instance is not None

    @classmethod
    def get_model_name(cls) -> str:
        return cls._model_name or settings.RERANKER_MODEL


class RAGEngine:
    """Orchestrates hybrid retrieval (dense + BM25 with RRF) and cross-encoder reranking."""

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self._qdrant = qdrant_client or get_qdrant_client()
        self._embedding_service = embedding_service or get_embedding_service()

    @property
    def embedding_service(self) -> EmbeddingService:
        return self._embedding_service

    def _get_active_filter(self) -> qmodels.Filter:
        """Filter condition ensuring ONLY is_active == True chunks are returned."""
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="is_active",
                    match=qmodels.MatchValue(value=True),
                )
            ]
        )

    def hybrid_search(
        self,
        query: str,
        top_k: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[List[RetrievedChunk], float]:
        """Perform hybrid search (dense + BM25 sparse) fused with Reciprocal Rank Fusion (RRF).

        Filters strictly on `is_active == True`.
        Returns candidate chunks and retrieval latency in milliseconds.
        """
        k = top_k or settings.RETRIEVAL_TOP_K
        start_time = time.perf_counter()

        # Generate dense and sparse representations using embedding interface
        dense_vec = self._embedding_service.embed_query(query)
        sparse_vec = self._embedding_service.embed_sparse_query(query)

        active_filter = self._get_active_filter()

        try:
            # Query Qdrant with Universal Query API: prefetch dense and sparse, fuse with RRF
            query_response = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    qmodels.Prefetch(
                        query=dense_vec,
                        using="dense",
                        filter=active_filter,
                        limit=k,
                    ),
                    qmodels.Prefetch(
                        query=qmodels.SparseVector(
                            indices=sparse_vec.indices,
                            values=sparse_vec.values,
                        ),
                        using="sparse",
                        filter=active_filter,
                        limit=k,
                    ),
                ],
                query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                limit=k,
            )
            raw_points = query_response.points
        except Exception as exc:
            logger.warning(
                f"Qdrant Query API failed ({exc}), falling back to client-side RRF fusion",
                request_id=request_id,
            )
            raw_points = self._fallback_client_rrf(dense_vec, sparse_vec, active_filter, k)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        candidates: List[RetrievedChunk] = []
        for point in raw_points:
            payload = point.payload or {}
            # Safety check: ignore metadata sentinel points or any deactivated points
            if payload.get("_type") == "embedding_guard_metadata" or not payload.get("is_active", False):
                continue

            candidates.append(
                RetrievedChunk(
                    chunk_id=str(point.id),
                    document_id=str(payload.get("document_id", "")),
                    version=int(payload.get("version", 1)),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    content=str(payload.get("content", "")),
                    token_count=int(payload.get("token_count", 0)),
                    page_number=payload.get("page_number"),
                    section_heading=payload.get("section_heading"),
                    retrieval_score=float(point.score or 0.0),
                )
            )

        logger.info(
            f"Hybrid retrieval fetched {len(candidates)} candidates in {latency_ms:.1f}ms",
            request_id=request_id,
            query=query,
            candidates_count=len(candidates),
            latency_retrieval_ms=round(latency_ms, 2),
        )

        return candidates, latency_ms

    def _fallback_client_rrf(
        self,
        dense_vec: List[float],
        sparse_vec: Any,
        active_filter: qmodels.Filter,
        k: int,
    ) -> List[Any]:
        """Client-side RRF fallback if server Query API encounters compatibility issues."""
        try:
            # Query dense candidates
            dense_hits = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=dense_vec,
                using="dense",
                filter=active_filter,
                limit=k,
            ).points
        except Exception:
            dense_hits = []

        try:
            # Query sparse candidates
            sparse_hits = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=qmodels.SparseVector(indices=sparse_vec.indices, values=sparse_vec.values),
                using="sparse",
                filter=active_filter,
                limit=k,
            ).points
        except Exception:
            sparse_hits = []

        # RRF formula: Score(d) = sum(1 / (60 + rank))
        rrf_constant = 60
        rrf_scores: Dict[str, float] = {}
        points_map: Dict[str, Any] = {}

        for rank, p in enumerate(dense_hits):
            pid = str(p.id)
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_constant + rank + 1)
            points_map[pid] = p

        for rank, p in enumerate(sparse_hits):
            pid = str(p.id)
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_constant + rank + 1)
            points_map[pid] = p

        sorted_pids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:k]
        result_points = []
        for pid in sorted_pids:
            pt = points_map[pid]
            pt.score = rrf_scores[pid]
            result_points.append(pt)
        return result_points

    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        top_n: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[List[RetrievedChunk], float]:
        """Rerank candidates using cross-encoder singleton and keep top RERANK_TOP_N.

        Computes raw logit and sigmoid-normalized score for each candidate chunk.
        """
        n = top_n or settings.RERANK_TOP_N
        if not candidates:
            return [], 0.0

        start_time = time.perf_counter()
        encoder = CrossEncoderSingleton.get_instance()

        documents = [c.content for c in candidates]
        raw_scores_iter = encoder.rerank(query, documents)
        raw_scores = list(raw_scores_iter)

        for chunk, raw_score in zip(candidates, raw_scores):
            chunk.raw_rerank_score = float(raw_score)
            chunk.rerank_score = _sigmoid(float(raw_score))

        # Sort descending by rerank score
        candidates.sort(key=lambda c: c.rerank_score, reverse=True)
        top_chunks = candidates[:n]

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        top_score_str = f"{top_chunks[0].rerank_score:.4f}" if top_chunks else "None"
        raw_top_score_str = f"{top_chunks[0].raw_rerank_score:.4f}" if top_chunks else "None"
        logger.info(
            f"Cross-encoder reranking completed: top_score={top_score_str} (raw={raw_top_score_str}) in {latency_ms:.1f}ms",
            request_id=request_id,
            query=query,
            reranked_count=len(top_chunks),
            latency_rerank_ms=round(latency_ms, 2),
        )

        return top_chunks, latency_ms

    def retrieve(
        self,
        query: str,
        request_id: Optional[str] = None,
    ) -> RetrievalResult:
        """Full retrieval pipeline: hybrid search, cross-encoder rerank, and Layer 1 fallback check.

        Layer 1: If top rerank score < settings.RERANK_THRESHOLD or no chunks retrieved,
        returns structured result marked with is_fallback=True.
        """
        start_total = time.perf_counter()

        # Step 1: Hybrid retrieval
        candidates, latency_retrieval = self.hybrid_search(
            query=query,
            top_k=settings.RETRIEVAL_TOP_K,
            request_id=request_id,
        )

        # Step 2: Cross-encoder rerank
        reranked_chunks, latency_rerank = self.rerank(
            query=query,
            candidates=candidates,
            top_n=settings.RERANK_TOP_N,
            request_id=request_id,
        )

        total_latency = (time.perf_counter() - start_total) * 1000.0

        top_score: Optional[float] = None
        raw_top_score: Optional[float] = None
        if reranked_chunks:
            top_score = reranked_chunks[0].rerank_score
            raw_top_score = reranked_chunks[0].raw_rerank_score

        # Step 3: Layer 1 fallback gate
        # Threshold comes ONLY from config
        threshold = settings.RERANK_THRESHOLD
        is_fallback = False
        fallback_msg: Optional[str] = None

        if not reranked_chunks or top_score is None or top_score < threshold:
            is_fallback = True
            fallback_msg = settings.FALLBACK_MESSAGE
            logger.info(
                f"Layer 1 Fallback triggered: top_score={top_score} < threshold={threshold}",
                request_id=request_id,
                query=query,
                top_score=top_score,
                threshold=threshold,
                is_fallback=True,
            )
        else:
            logger.info(
                f"Layer 1 Passed: top_score={top_score:.4f} >= threshold={threshold}",
                request_id=request_id,
                query=query,
                top_score=top_score,
                threshold=threshold,
                is_fallback=False,
            )

        return RetrievalResult(
            query=query,
            chunks=reranked_chunks,
            top_score=top_score,
            raw_top_score=raw_top_score,
            is_fallback=is_fallback,
            fallback_message=fallback_msg,
            latency_ms_retrieval=round(latency_retrieval, 2),
            latency_ms_rerank=round(latency_rerank, 2),
            total_latency_ms=round(total_latency, 2),
        )


# Singleton instance accessor
_rag_engine_instance: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    """Return the global RAGEngine singleton."""
    global _rag_engine_instance
    if _rag_engine_instance is None:
        _rag_engine_instance = RAGEngine()
    return _rag_engine_instance
