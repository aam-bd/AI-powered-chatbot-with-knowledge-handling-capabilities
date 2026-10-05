"""OpenAI-compatible embedding backend with FastEmbed BM25 sparse vectors."""
from typing import List
import httpx
from fastembed import SparseTextEmbedding
from app.services.embedding.base import EmbeddingService, SparseVector
from app.core.config import settings
from app.core.logger import logger


class OpenAICompatEmbeddingService(EmbeddingService):
    """Embedding backend using remote /embeddings endpoint for dense vectors and FastEmbed for BM25."""

    def __init__(self):
        self.base_url = (settings.EMBEDDING_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self.api_key = settings.EMBEDDING_API_KEY.get_secret_value() if settings.EMBEDDING_API_KEY else None
        self.model = settings.EMBEDDING_MODEL
        self._sparse_model = None

    @property
    def sparse_model(self) -> SparseTextEmbedding:
        if self._sparse_model is None:
            self._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        return self._sparse_model

    def embed_dense(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/embeddings"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json={"input": texts, "model": self.model})
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAICompat embedding call failed with status {resp.status_code}: {resp.text}")
            data = resp.json()
            # Extract embeddings sorted by index
            sorted_items = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_items]

    def embed_sparse(self, texts: List[str]) -> List[SparseVector]:
        if not texts:
            return []
        embeddings = list(self.sparse_model.embed(texts))
        result = []
        for emb in embeddings:
            indices = emb.indices.tolist() if hasattr(emb.indices, "tolist") else list(emb.indices)
            values = emb.values.tolist() if hasattr(emb.values, "tolist") else list(emb.values)
            result.append(SparseVector(indices=indices, values=[float(v) for v in values]))
        return result
