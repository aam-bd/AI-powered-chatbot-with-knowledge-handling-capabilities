"""005_system_overview_and_settings

Revision ID: 005_system_overview_and_settings
Revises: 004_model_discovery_and_usage
Create Date: 2026-10-14 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_system_overview_and_settings"
down_revision: Union[str, None] = "004_model_discovery_and_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create system_settings table (singleton row id=1)
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("reranker_threshold", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False, server_default=sa.text("15")),
        sa.Column("rerank_top_n", sa.Integer(), nullable=False, server_default=sa.text("4")),
        sa.Column("history_messages", sa.Integer(), nullable=False, server_default=sa.text("6")),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("rate_limit_login_per_minute", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("sse_keepalive_interval", sa.Integer(), nullable=False, server_default=sa.text("15")),
        sa.Column("max_upload_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("20971520")),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 2. Seed initial singleton row
    op.execute(
        """
        INSERT INTO system_settings (
            id, reranker_threshold, retrieval_top_k, rerank_top_n, history_messages,
            rate_limit_per_minute, rate_limit_login_per_minute, sse_keepalive_interval,
            max_upload_size_bytes, version, updated_at
        ) VALUES (
            1, 0.5, 15, 4, 6, 60, 5, 15, 20971520, 1, now()
        ) ON CONFLICT (id) DO NOTHING;
        """
    )

    # 3. Create audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("system_settings")
