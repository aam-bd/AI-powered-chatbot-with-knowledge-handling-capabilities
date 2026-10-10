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

