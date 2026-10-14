"""004_model_discovery_and_usage

Revision ID: 004_model_discovery_and_usage
Revises: 003_llm_providers
Create Date: 2026-10-13 16:00:00.000000

"""
from typing import Sequence, Union
import uuid
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_model_discovery_and_usage"
down_revision: Union[str, None] = "003_llm_providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Alter llm_providers: add preset, docs, discovery metadata
    op.add_column(
        "llm_providers",
        sa.Column("is_preset", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "llm_providers",
        sa.Column("preset_key", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "llm_providers",
        sa.Column("docs_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "llm_providers",
        sa.Column("key_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "llm_providers",
        sa.Column("discovery_kind", sa.String(length=50), nullable=False, server_default="openai_models"),
    )
    op.add_column(
        "llm_providers",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "llm_providers",
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_llm_providers_preset_key", "llm_providers", ["preset_key"], unique=False)

    # 2. Create provider_models table
    op.create_table(
        "provider_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_providers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("model_id", sa.String(length=150), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("price_prompt_per_1m", sa.Float(), nullable=True),
        sa.Column("price_completion_per_1m", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="discovered"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("provider_id", "model_id", name="uq_provider_models_provider_model"),
    )

    # 3. Create llm_usage table
    op.create_table(
        "llm_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("model_id", sa.String(length=150), nullable=False, index=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
    )

    # 4. Migrate existing JSON models into provider_models
    bind = op.get_bind()
    providers = bind.execute(sa.text("SELECT id, models, default_model FROM llm_providers")).fetchall()
    for row in providers:
        p_id = row[0]
        models_data = row[1]
        default_model = row[2]
        model_list = []
        if isinstance(models_data, list):
            model_list = models_data
        elif isinstance(models_data, str):
            try:
                model_list = json.loads(models_data)
            except Exception:
                model_list = []
        if default_model and default_model not in model_list:
            model_list.append(default_model)

        for m_id in model_list:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO provider_models (id, provider_id, model_id, display_name, source, is_available, is_enabled, discovered_at, created_at, updated_at)
                    VALUES (:id, :provider_id, :model_id, :display_name, 'manual', true, true, now(), now(), now())
                    ON CONFLICT (provider_id, model_id) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "provider_id": str(p_id),
                    "model_id": str(m_id),
                    "display_name": str(m_id),
                },
            )


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_table("provider_models")
    op.drop_index("ix_llm_providers_preset_key", table_name="llm_providers")
    op.drop_column("llm_providers", "discovered_count")
    op.drop_column("llm_providers", "discovered_at")
    op.drop_column("llm_providers", "discovery_kind")
    op.drop_column("llm_providers", "key_required")
    op.drop_column("llm_providers", "docs_url")
    op.drop_column("llm_providers", "preset_key")
    op.drop_column("llm_providers", "is_preset")
