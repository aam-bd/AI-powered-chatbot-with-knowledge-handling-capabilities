"""Local embedding service using FastEmbed for dense (BGE-m3) and sparse (BM25) vectors."""
from typing import List
from fastembed import TextEmbedding, SparseTextEmbedding
from app.services.embedding.base import EmbeddingService, SparseVector
from app.core.config import settings
from app.core.logger import logger


class LocalEmbeddingService(EmbeddingService):
    """Local embedding backend leveraging FastEmbed ONNX runtime."""

    def __init__(self, dense_model_name: str = None, sparse_model_name: str = "Qdrant/bm25"):
        self.dense_model_name = dense_model_name or settings.EMBEDDING_MODEL
        self.sparse_model_name = sparse_model_name

        # FastEmbed ONNX registry maps 1024-dim BAAI embeddings to BAAI/bge-large-en-v1.5
        self._fastembed_dense_name = self.dense_model_name
        if self.dense_model_name == "BAAI/bge-m3":
            self._fastembed_dense_name = "BAAI/bge-large-en-v1.5"

        logger.info(f"Initializing LocalEmbeddingService with dense='{self.dense_model_name}' (FastEmbed='{self._fastembed_dense_name}'), sparse='{self.sparse_model_name}'")
        self._dense_model = None
        self._sparse_model = None

    @property
    def dense_model(self) -> TextEmbedding:
        if self._dense_model is None:
            self._dense_model = TextEmbedding(model_name=self._fastembed_dense_name)
        return self._dense_model

    @property
    def sparse_model(self) -> SparseTextEmbedding:
        if self._sparse_model is None:
            self._sparse_model = SparseTextEmbedding(model_name=self.sparse_model_name)
        return self._sparse_model

    def embed_dense(self, texts: List[str]) -> List[List[float]]:
        """Compute dense vectors using BGE-m3."""
        if not texts:
            return []
        embeddings = list(self.dense_model.embed(texts))
        return [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in embeddings]

    def embed_sparse(self, texts: List[str]) -> List[SparseVector]:
        """Compute BM25 sparse vectors."""
        if not texts:
            return []
        embeddings = list(self.sparse_model.embed(texts))
        result = []
        for emb in embeddings:
            indices = emb.indices.tolist() if hasattr(emb.indices, "tolist") else list(emb.indices)
            values = emb.values.tolist() if hasattr(emb.values, "tolist") else list(emb.values)
            result.append(SparseVector(indices=indices, values=[float(v) for v in values]))
        return result
