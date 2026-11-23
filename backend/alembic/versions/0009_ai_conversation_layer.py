"""Add AI conversation continuation layer

Adds:
- conversations table (per lead+campaign AI thread tracking)
- messages.direction, messages.conversation_id
- campaigns.ai_enabled, campaigns.ai_handoff_after_turns
- instagram_accounts AI scope/budget fields (business_vertical,
  ai_enabled, ai_business_profile, ai_tone_instructions,
  ai_daily_message_cap, ai_messages_sent_today, ai_budget_reset_at)

Revision ID: 0009_ai_conversation_layer
Revises: 0008_campaign_comment_reply
Create Date: 2026-08-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_ai_conversation_layer"
down_revision = "0008_campaign_comment_reply"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column_name in columns:
        op.drop_column(table, column_name)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()

    if "conversations" not in existing_tables:
        op.create_table(
            "conversations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column(
                "lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False
            ),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id"),
                nullable=False,
            ),
            sa.Column(
                "instagram_account_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("instagram_accounts.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(50), nullable=False, server_default="bot_active"),
            sa.Column("handoff_reason", sa.String(50), nullable=True),
            sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.UniqueConstraint("lead_id", "campaign_id", name="uq_conversation_lead_campaign"),
        )
        op.create_index("ix_conversations_status", "conversations", ["status"])
        op.create_index(
            "ix_conversations_instagram_account_id", "conversations", ["instagram_account_id"]
        )

    # messages: direction + conversation_id
    _add_column_if_missing(
        "messages",
        sa.Column("direction", sa.String(20), nullable=False, server_default="outbound"),
    )
    _add_column_if_missing(
        "messages",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=True,
        ),
    )

    # campaigns: AI opt-in + handoff limit
    _add_column_if_missing(
        "campaigns",
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "campaigns",
        sa.Column("ai_handoff_after_turns", sa.Integer(), nullable=False, server_default="8"),
    )

    # instagram_accounts: AI scope + shared budget
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column("business_vertical", sa.String(50), nullable=False, server_default="general"),
    )
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "instagram_accounts", sa.Column("ai_business_profile", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "instagram_accounts", sa.Column("ai_tone_instructions", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column("ai_daily_message_cap", sa.Integer(), nullable=False, server_default="100"),
    )
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column("ai_messages_sent_today", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column("ai_budget_reset_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_present("instagram_accounts", "ai_budget_reset_at")
    _drop_column_if_present("instagram_accounts", "ai_messages_sent_today")
    _drop_column_if_present("instagram_accounts", "ai_daily_message_cap")
    _drop_column_if_present("instagram_accounts", "ai_tone_instructions")
    _drop_column_if_present("instagram_accounts", "ai_business_profile")
    _drop_column_if_present("instagram_accounts", "ai_enabled")
    _drop_column_if_present("instagram_accounts", "business_vertical")

    _drop_column_if_present("campaigns", "ai_handoff_after_turns")
    _drop_column_if_present("campaigns", "ai_enabled")

    _drop_column_if_present("messages", "conversation_id")
    _drop_column_if_present("messages", "direction")

    bind = op.get_bind()
    if "conversations" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_conversations_instagram_account_id", table_name="conversations")
        op.drop_index("ix_conversations_status", table_name="conversations")
        op.drop_table("conversations")
