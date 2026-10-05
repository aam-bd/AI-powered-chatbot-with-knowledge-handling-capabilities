"""Abstract base class and data structures for dense and sparse embeddings."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class SparseVector:
    """Sparse vector representation containing token indices and weights."""

    def __init__(self, indices: List[int], values: List[float]):
        self.indices = indices
        self.values = values

    def to_dict(self) -> Dict[str, Any]:
        return {"indices": self.indices, "values": self.values}


class EmbeddingService(ABC):
    """Abstract embedding interface supporting dual dense and sparse representations."""

    @abstractmethod
    def embed_dense(self, texts: List[str]) -> List[List[float]]:
        """Compute dense vector representations for a batch of texts."""
        pass

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Alias for embed_dense."""
        return self.embed_dense(texts)

    @abstractmethod
    def embed_sparse(self, texts: List[str]) -> List[SparseVector]:
        """Compute sparse BM25 vector representations for a batch of texts."""
        pass
