"""Application configuration using pydantic-settings.

All settings defined in architecture.md section 12 are represented here.
Secrets are handled as SecretStr to prevent accidental leakage in logs.
"""
from typing import List, Optional
import json
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System-wide configuration settings with validation and defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --------------------------------------------------------------------------
    # Application & Environment Settings
    # --------------------------------------------------------------------------
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    JWT_SECRET_KEY: SecretStr = SecretStr("default-insecure-secret-key-change-in-production")
    ACCESS_TOKEN_MINUTES: int = 30
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --------------------------------------------------------------------------
    # Database, Redis & Vector Database Settings
    # --------------------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/chatbot"
    REDIS_URL: str = "redis://redis:6379/0"
    QDRANT_URL: str = "http://qdrant:6333"

    # Optional initial admin user seed
    ADMIN_EMAIL: Optional[str] = None
    ADMIN_PASSWORD: Optional[SecretStr] = None

    # --------------------------------------------------------------------------
    # Shared LLM Provider Settings (Architecture §12)
    # --------------------------------------------------------------------------
    LLM_PROVIDER: str = "openai_compatible"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: Optional[SecretStr] = None
    FAST_MODEL: Optional[str] = None
    ANSWER_MODEL: Optional[str] = None

    # Role-specific LLM overrides
    FAST_LLM_PROVIDER: Optional[str] = None
    FAST_LLM_BASE_URL: Optional[str] = None
    FAST_LLM_API_KEY: Optional[SecretStr] = None

    ANSWER_LLM_PROVIDER: Optional[str] = None
    ANSWER_LLM_BASE_URL: Optional[str] = None
    ANSWER_LLM_API_KEY: Optional[SecretStr] = None

    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 2

    # --------------------------------------------------------------------------
    # Embeddings & Reranker Settings
    # --------------------------------------------------------------------------
    EMBEDDING_PROVIDER: str = "local"  # 'local' or 'openai_compatible'
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[SecretStr] = None
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # --------------------------------------------------------------------------
    # Ingestion, Chunking & Retrieval Parameters
    # --------------------------------------------------------------------------
    CHUNK_SIZE_TOKENS: int = 650
    CHUNK_OVERLAP_TOKENS: int = 80
    RETRIEVAL_TOP_K: int = 15
    RERANK_TOP_N: int = 4
    RERANK_THRESHOLD: float = 0.5
    MAX_UPLOAD_MB: int = 20
    ALLOWED_URL_DOMAINS: List[str] = Field(default_factory=list)
    ENABLE_OCR: bool = False
    RECONCILE_STALE_MINUTES: int = 15

    # --------------------------------------------------------------------------
    # Conversation Memory & Messaging
    # --------------------------------------------------------------------------
    HISTORY_MESSAGES: int = 6
    SESSION_TTL_HOURS: int = 24
    FALLBACK_MESSAGE: str = (
        "I'm sorry, I couldn't find information about that in my knowledge base."
    )
    GREETING_MESSAGE: str = (
        "Hi! I can answer questions about the knowledge base. What would you like to know?"
    )

    # --------------------------------------------------------------------------
    # Validators
    # --------------------------------------------------------------------------
    @field_validator("CORS_ORIGINS", "ALLOWED_URL_DOMAINS", mode="before")
    @classmethod
    def parse_json_or_comma_list(cls, v):
        """Parse JSON list string or comma-separated string into a list of strings."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("CHUNK_SIZE_TOKENS")
    @classmethod
    def validate_chunk_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("CHUNK_SIZE_TOKENS must be greater than 0")
        return v

    @field_validator("CHUNK_OVERLAP_TOKENS")
    @classmethod
    def validate_overlap(cls, v: int) -> int:
        if v < 0:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be non-negative")
        return v

    @field_validator("MAX_UPLOAD_MB", "RETRIEVAL_TOP_K", "RERANK_TOP_N")
    @classmethod
    def validate_positive_ints(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Value must be greater than 0")
        return v

    @field_validator("EMBEDDING_PROVIDER")
    @classmethod
    def validate_embedding_provider(cls, v: str) -> str:
        allowed = {"local", "openai_compatible"}
        if v.lower() not in allowed:
            raise ValueError(f"EMBEDDING_PROVIDER must be one of {allowed}")
        return v.lower()

    @field_validator("LLM_PROVIDER")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"openai_compatible", "anthropic"}
        if v.lower() not in allowed:
            raise ValueError(f"LLM_PROVIDER must be one of {allowed}")
        return v.lower()

    @model_validator(mode="after")
    def validate_relationships(self) -> "Settings":
        """Verify cross-field constraints."""
        if self.CHUNK_OVERLAP_TOKENS >= self.CHUNK_SIZE_TOKENS:
            raise ValueError(
                f"CHUNK_OVERLAP_TOKENS ({self.CHUNK_OVERLAP_TOKENS}) must be less than "
                f"CHUNK_SIZE_TOKENS ({self.CHUNK_SIZE_TOKENS})"
            )
        if self.RERANK_TOP_N > self.RETRIEVAL_TOP_K:
            raise ValueError(
                f"RERANK_TOP_N ({self.RERANK_TOP_N}) cannot exceed "
                f"RETRIEVAL_TOP_K ({self.RETRIEVAL_TOP_K})"
            )
        return self

    # --------------------------------------------------------------------------
    # Helper Inspection Methods
    # --------------------------------------------------------------------------
    def is_llm_configured(self) -> bool:
        """Check whether LLM credentials and models are set without making external calls."""
        fast_key = self.FAST_LLM_API_KEY or self.LLM_API_KEY
        answer_key = self.ANSWER_LLM_API_KEY or self.LLM_API_KEY
        has_fast = bool(fast_key and fast_key.get_secret_value() and self.FAST_MODEL)
        has_answer = bool(answer_key and answer_key.get_secret_value() and self.ANSWER_MODEL)
        return has_fast and has_answer

    def require_llm_configured(self, role: str = "general") -> None:
        """Validate LLM configuration when the LLM layer is invoked.
        
        Args:
            role: 'fast', 'answer', or 'general'
        """
        if role == "fast":
            key = self.FAST_LLM_API_KEY or self.LLM_API_KEY
            if not key or not key.get_secret_value():
                raise ValueError("FAST_LLM_API_KEY or LLM_API_KEY is required to use the fast LLM role")
            if not self.FAST_MODEL:
                raise ValueError("FAST_MODEL must be configured to use the fast LLM role")
        elif role == "answer":
            key = self.ANSWER_LLM_API_KEY or self.LLM_API_KEY
            if not key or not key.get_secret_value():
                raise ValueError("ANSWER_LLM_API_KEY or LLM_API_KEY is required to use the answer LLM role")
            if not self.ANSWER_MODEL:
                raise ValueError("ANSWER_MODEL must be configured to use the answer LLM role")
        else:
            if not self.is_llm_configured():
                raise ValueError(
                    "LLM configuration incomplete. LLM_API_KEY, FAST_MODEL, and ANSWER_MODEL are required."
                )


# Global settings singleton
settings = Settings()
