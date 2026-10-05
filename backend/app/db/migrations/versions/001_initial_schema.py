"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-05 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. documents table
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("active_version", sa.Integer(), nullable=True),
        sa.Column("pending_version", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)
    # Partial unique index for sha256 among non-deleted documents per §4.1
    op.create_index(
        "uq_documents_sha256_active",
        "documents",
        ["sha256"],
        unique=True,
        postgresql_where=sa.text("status != 'deleting'"),
    )

    # 3. query_logs table
    op.create_table(
        "query_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("standalone_query", sa.Text(), nullable=True),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("fallback_layer", sa.Integer(), nullable=True),
        sa.Column("cited_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("latency_ms_router", sa.Float(), nullable=True),
        sa.Column("latency_ms_retrieval", sa.Float(), nullable=True),
        sa.Column("latency_ms_rerank", sa.Float(), nullable=True),
        sa.Column("latency_ms_generation", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_query_logs_session_id", "query_logs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_query_logs_session_id", table_name="query_logs")
    op.drop_table("query_logs")

    op.drop_index("uq_documents_sha256_active", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
