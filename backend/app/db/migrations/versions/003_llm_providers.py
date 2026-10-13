"""003_llm_providers

Revision ID: 003_llm_providers
Revises: 002_chat_history
Create Date: 2026-10-13 11:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_llm_providers"
down_revision: Union[str, None] = "002_chat_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. llm_providers table
    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("models", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("default_model", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_llm_providers_name", "llm_providers", ["name"], unique=True)

    # 2. llm_settings table (single-row singleton)
    op.create_table(
        "llm_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "active_provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_providers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("active_model", sa.String(length=100), nullable=False),
        sa.Column(
            "fallback_provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("fallback_model", sa.String(length=100), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default=sa.text("1024")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("id = 1", name="ck_llm_settings_single_row"),
    )


def downgrade() -> None:
    op.drop_table("llm_settings")
    op.drop_table("llm_providers")
