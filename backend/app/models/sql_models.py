"""SQLAlchemy 2 database models for users, documents, and query_logs.

Complies strictly with architecture.md section 4.1:
- users: id, email (unique), password_hash, role ('user' | 'admin'), is_active, created_at
- documents: id, name, source_type, source_uri, sha256, size_bytes, status, active_version,
             pending_version, last_error, heartbeat_at, created_by, created_at, updated_at
             with unique constraint on sha256 among non-deleted documents
- query_logs: id, user_id, session_id, intent, original_query, standalone_query, top_score,
              threshold, fallback_layer, cited_chunk_ids, latency per stage, created_at
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Text,
    BigInteger,
    Integer,
    Float,
    JSON,
    ForeignKey,
    Index,
    text,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class User(Base):
    """User accounts and role-based permissions."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default="user",
        nullable=False,
    )  # 'user' | 'admin'
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # Relationships
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="creator")
    query_logs: Mapped[List["QueryLog"]] = relationship("QueryLog", back_populates="user")
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Document(Base):
    """Knowledge base document metadata and lifecycle states."""
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )  # 'pdf' | 'docx' | 'md' | 'txt' | 'url'
    source_uri: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )  # 'pending' | 'processing' | 'active' | 'updating' | 'deleting' | 'failed'
    active_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    pending_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    creator: Mapped[Optional["User"]] = relationship("User", back_populates="documents")

    __table_args__ = (
        Index(
            "uq_documents_sha256_active",
            "sha256",
            unique=True,
            postgresql_where=text("status != 'deleting'"),
        ),
    )


class QueryLog(Base):
    """Telemetry, audit logs, and metrics for chat queries."""
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
    )
    intent: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # 'GREETING' | 'CLARIFY' | 'SEARCH'
    original_query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    standalone_query: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    top_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    threshold: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    fallback_layer: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )  # null | 1 | 2 | 3
    cited_chunk_ids: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
    )
    latency_ms_router: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    latency_ms_retrieval: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    latency_ms_rerank: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    latency_ms_generation: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="query_logs")


class ChatSession(Base):
    """Persistent chat conversation session."""
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="New Chat",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessageRecord"]] = relationship(
        "ChatMessageRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.created_at",
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_id_updated_at", "user_id", "updated_at"),
    )


class ChatMessageRecord(Base):
    """Individual conversation message stored in PostgreSQL."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # 'user' | 'assistant'
    kind: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
    )  # 'normal' | 'fallback' | 'clarification' | 'greeting' | 'error'
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    citations: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
    )
    fallback_layer: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )  # null | 1 | 2 | 3
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),
    )


class LLMProvider(Base):
    """Configured LLM providers and encrypted credentials (Prompt 7e)."""
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )
    provider_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # 'openai_compatible' | 'anthropic' | 'gemini' | 'openrouter' | 'ollama' | 'custom'
    base_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    models: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    default_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    last_test_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )  # 'success' | 'failed'
    last_test_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_preset: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    preset_key: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    docs_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    key_required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    discovery_kind: Mapped[str] = mapped_column(
        String(50),
        default="openai_models",
        nullable=False,
    )
    discovered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    discovered_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Relationships
    models_rel: Mapped[List["ProviderModel"]] = relationship(
        "ProviderModel",
        back_populates="provider",
        cascade="all, delete-orphan",
    )


class ProviderModel(Base):
    """Discovered or manually entered models for an LLM provider (Prompt 7e-2)."""
    __tablename__ = "provider_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    context_length: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    max_output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    price_prompt_per_1m: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    price_completion_per_1m: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        default="discovered",
        nullable=False,
    )  # 'discovered' | 'manual'
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider",
        back_populates="models_rel",
    )


class LLMUsage(Base):
    """Usage and token tracking per generation request (Prompt 7e-2)."""
    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )
    provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(
        String(150),
        index=True,
        nullable=False,
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    total_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    latency_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # 'success' | 'error' | 'retract' | 'fallback'
    error_class: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    estimated_cost: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )


class LLMSettings(Base):
    """Runtime LLM settings singleton row (Prompt 7e). Single row constrained to id=1."""
    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        default=1,
    )
    active_provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    active_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    fallback_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
    )
    fallback_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    temperature: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    max_tokens: Mapped[int] = mapped_column(
        Integer,
        default=1024,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    # Relationships
    active_provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider",
        foreign_keys=[active_provider_id],
    )
    fallback_provider: Mapped[Optional["LLMProvider"]] = relationship(
        "LLMProvider",
        foreign_keys=[fallback_provider_id],
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_llm_settings_single_row"),
    )


class SystemSettings(Base):
    """Runtime system settings singleton row (Prompt 7e-3). Single row constrained to id=1."""
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        default=1,
    )
    reranker_threshold: Mapped[float] = mapped_column(
        Float,
        default=0.5,
        nullable=False,
    )
    retrieval_top_k: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    rerank_top_n: Mapped[int] = mapped_column(
        Integer,
        default=4,
        nullable=False,
    )
    history_messages: Mapped[int] = mapped_column(
        Integer,
        default=6,
        nullable=False,
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )
    rate_limit_login_per_minute: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )
    sse_keepalive_interval: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    max_upload_size_bytes: Mapped[int] = mapped_column(
        Integer,
        default=20971520,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        BigInteger,
        default=1,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_system_settings_single_row"),
    )


class AuditLog(Base):
    """Structured administration audit trail entries (Prompt 7e-3)."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    target_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    target_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    details: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )

    user: Mapped[Optional["User"]] = relationship("User")


