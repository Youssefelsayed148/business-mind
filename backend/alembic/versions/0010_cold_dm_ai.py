"""Add cold-DM AI support

Adds:
- leads.lead_source ('campaign' | 'cold_dm'), not null, default 'campaign';
  existing rows backfilled to 'campaign' (every pre-existing lead came through
  the comment -> DM campaign pipeline).
- instagram_accounts.ai_cold_dm_enabled, not null, default false — a separate
  opt-in from ai_enabled for answering unsolicited DMs.
- instagram_accounts.ai_handoff_after_turns, not null, default 8 — account-level
  turn cap used by the cold-DM path (the campaign path keeps using
  campaigns.ai_handoff_after_turns, unchanged).

Also relaxes NOT NULL so a cold-DM conversation (which has no originating
campaign) can be represented:
- leads.source_campaign_id -> nullable (usually already nullable; enforced here)
- conversations.campaign_id -> nullable
- messages.campaign_id -> nullable

Revision ID: 0010_cold_dm_ai
Revises: 0009_ai_conversation_layer
Create Date: 2026-08-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_cold_dm_ai"
down_revision = "0009_ai_conversation_layer"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    if column_name in _columns(table):
        op.drop_column(table, column_name)


def _is_nullable(table: str, column_name: str) -> bool:
    bind = op.get_bind()
    for col in sa.inspect(bind).get_columns(table):
        if col["name"] == column_name:
            return bool(col["nullable"])
    return True


def upgrade() -> None:
    # leads.lead_source -----------------------------------------------------
    _add_column_if_missing(
        "leads",
        sa.Column(
            "lead_source",
            sa.String(50),
            nullable=False,
            server_default="campaign",
        ),
    )
    # Explicit backfill (defensive — server_default already covers existing rows).
    op.execute("UPDATE leads SET lead_source = 'campaign' WHERE lead_source IS NULL")

    # instagram_accounts.ai_cold_dm_enabled -------------------------------
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column(
            "ai_cold_dm_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # instagram_accounts.ai_handoff_after_turns --------------------------
    _add_column_if_missing(
        "instagram_accounts",
        sa.Column(
            "ai_handoff_after_turns",
            sa.Integer(),
            nullable=False,
            server_default="8",
        ),
    )

    # Relax NOT NULL for the campaign-less cold-DM path ------------------
    if not _is_nullable("leads", "source_campaign_id"):
        op.alter_column("leads", "source_campaign_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    if not _is_nullable("conversations", "campaign_id"):
        op.alter_column("conversations", "campaign_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    if not _is_nullable("messages", "campaign_id"):
        op.alter_column("messages", "campaign_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)


def downgrade() -> None:
    # Re-imposing NOT NULL is unsafe if cold-DM rows exist; leave the columns
    # nullable on downgrade and only drop the additive columns.
    _drop_column_if_present("instagram_accounts", "ai_handoff_after_turns")
    _drop_column_if_present("instagram_accounts", "ai_cold_dm_enabled")
    _drop_column_if_present("leads", "lead_source")
