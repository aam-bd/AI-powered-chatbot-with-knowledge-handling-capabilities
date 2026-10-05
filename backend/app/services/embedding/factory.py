"""Factory for constructing configured embedding service instance."""
from app.services.embedding.base import EmbeddingService
from app.services.embedding.local import LocalEmbeddingService
from app.services.embedding.openai_compat import OpenAICompatEmbeddingService
from app.core.config import settings

_embedding_instance: EmbeddingService = None


def get_embedding_service() -> EmbeddingService:
    """Return singleton instance of configured embedding service."""
    global _embedding_instance
    if _embedding_instance is None:
        provider = settings.EMBEDDING_PROVIDER.lower().strip()
        if provider == "local":
            _embedding_instance = LocalEmbeddingService()
        elif provider == "openai_compatible":
            _embedding_instance = OpenAICompatEmbeddingService()
        else:
            raise ValueError(f"Unsupported EMBEDDING_PROVIDER '{provider}'. Must be 'local' or 'openai_compatible'.")
    return _embedding_instance
