"""Add WhatsApp Cloud API accounts, tokens, and wire up Phase 1's deferred FKs

Phase 2 of the multi-platform expansion (see
docs/specs/2026-09-05-multi-platform-expansion-design.md, and
phase-2-whatsapp-prompt.md). Adds:

- `whatsapp_accounts` table (modeled on `instagram_accounts`' shape, minus
  campaign-related fields and `ai_cold_dm_enabled` — every WhatsApp
  conversation is cold-DM-shaped by nature in this reactive-only phase).
- `whatsapp_tokens` table (separate from `meta_tokens`, which is NOT NULL /
  FK'd strictly to `instagram_accounts` and cannot represent a WhatsApp
  token without touching Instagram's token storage).
- The FK constraints Phase 1 deferred: `leads.whatsapp_account_id` and
  `conversations.whatsapp_account_id` -> `whatsapp_accounts.id`.
- Relaxes `leads.instagram_account_id` and `conversations.instagram_account_id`
  to nullable — required for a `platform='whatsapp'` row to ever be
  insertable, since Phase 1's CHECK constraint already requires
  `instagram_account_id IS NULL` for such rows but the column itself was
  still NOT NULL. Existing Instagram rows are untouched (their values stay
  populated); this only affects future inserts.
- A second uniqueness constraint on `leads`,
  `uq_lead_workspace_whatsapp_user` (workspace_id, whatsapp_account_id,
  ig_user_id). Postgres treats NULL as distinct from every other NULL in a
  unique constraint, so the existing `uq_lead_workspace_instagram_user`
  constraint provides zero duplicate protection for WhatsApp leads (every
  WhatsApp row has instagram_account_id IS NULL). This new constraint only
  actually constrains rows where whatsapp_account_id is set, leaving
  Instagram rows untouched by it in turn.
- `automation_logs.whatsapp_account_id` (nullable, FK to
  `whatsapp_accounts.id`) — `automation_logs.instagram_account_id` is FK'd
  strictly to `instagram_accounts`, so a WhatsApp account's UUID cannot be
  stored there without a foreign-key violation. This preserves per-account
  AI observability for WhatsApp the same way it exists for Instagram.

Does not touch `instagram_accounts`, `campaigns`, `comments`, or `meta_tokens`
in any way.

Revision ID: 0012_whatsapp_accounts
Revises: 0011_platform_foundation
Create Date: 2026-09-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_whatsapp_accounts"
down_revision = "0011_platform_foundation"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    if column_name in _columns(table):
        op.drop_column(table, column_name)


def _constraint_names(table: str, kind: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if kind == "unique":
        return {c["name"] for c in inspector.get_unique_constraints(table)}
    if kind == "foreignkey":
        return {c["name"] for c in inspector.get_foreign_keys(table) if c["name"]}
    raise ValueError(kind)


def _create_unique_constraint_if_missing(name: str, table: str, columns: list[str]) -> None:
    if name not in _constraint_names(table, "unique"):
        op.create_unique_constraint(name, table, columns)


def _drop_unique_constraint_if_present(name: str, table: str) -> None:
    if name in _constraint_names(table, "unique"):
        op.drop_constraint(name, table, type_="unique")


def _create_fk_if_missing(
    name: str, source_table: str, referent_table: str, local_cols: list[str], remote_cols: list[str]
) -> None:
    if name not in _constraint_names(source_table, "foreignkey"):
        op.create_foreign_key(name, source_table, referent_table, local_cols, remote_cols)


def _drop_fk_if_present(name: str, table: str) -> None:
    if name in _constraint_names(table, "foreignkey"):
        op.drop_constraint(name, table, type_="foreignkey")


def _is_nullable(table: str, column_name: str) -> bool:
    bind = op.get_bind()
    for col in sa.inspect(bind).get_columns(table):
        if col["name"] == column_name:
            return bool(col["nullable"])
    return True


def upgrade() -> None:
    # whatsapp_accounts -------------------------------------------------
    if "whatsapp_accounts" not in _table_names():
        op.create_table(
            "whatsapp_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("phone_number_id", sa.String(255), nullable=False, unique=True),
            sa.Column("display_phone_number", sa.String(50), nullable=True),
            sa.Column("whatsapp_business_account_id", sa.String(255), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="connected"),
            sa.Column("business_vertical", sa.String(50), nullable=False, server_default="general"),
            sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ai_business_profile", sa.Text(), nullable=True),
            sa.Column("ai_tone_instructions", sa.Text(), nullable=True),
            sa.Column("ai_daily_message_cap", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("ai_handoff_after_turns", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("ai_messages_sent_today", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_budget_reset_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_whatsapp_accounts_phone_number_id", "whatsapp_accounts", ["phone_number_id"]
        )

    # whatsapp_tokens -----------------------------------------------------
    if "whatsapp_tokens" not in _table_names():
        op.create_table(
            "whatsapp_tokens",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "whatsapp_account_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("whatsapp_accounts.id"),
                nullable=False,
            ),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("token_type", sa.String(50), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="active"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
        )

    # leads / conversations: FK targets Phase 1 deferred -----------------
    _create_fk_if_missing(
        "fk_leads_whatsapp_account_id", "leads", "whatsapp_accounts", ["whatsapp_account_id"], ["id"]
    )
    _create_fk_if_missing(
        "fk_conversations_whatsapp_account_id",
        "conversations",
        "whatsapp_accounts",
        ["whatsapp_account_id"],
        ["id"],
    )

    # leads / conversations: relax instagram_account_id to nullable ------
    if not _is_nullable("leads", "instagram_account_id"):
        op.alter_column(
            "leads", "instagram_account_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
        )
    if not _is_nullable("conversations", "instagram_account_id"):
        op.alter_column(
            "conversations",
            "instagram_account_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )

    # leads: WhatsApp-scoped uniqueness (see module docstring) ------------
    _create_unique_constraint_if_missing(
        "uq_lead_workspace_whatsapp_user", "leads", ["workspace_id", "whatsapp_account_id", "ig_user_id"]
    )

    # automation_logs.whatsapp_account_id ---------------------------------
    _add_column_if_missing(
        "automation_logs",
        sa.Column("whatsapp_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _create_fk_if_missing(
        "fk_automation_logs_whatsapp_account_id",
        "automation_logs",
        "whatsapp_accounts",
        ["whatsapp_account_id"],
        ["id"],
    )


def downgrade() -> None:
    _drop_fk_if_present("fk_automation_logs_whatsapp_account_id", "automation_logs")
    _drop_column_if_present("automation_logs", "whatsapp_account_id")

    _drop_unique_constraint_if_present("uq_lead_workspace_whatsapp_user", "leads")

    # Re-imposing NOT NULL on instagram_account_id is unsafe if WhatsApp rows
    # exist by now; leave both columns nullable on downgrade (matches the
    # existing pattern in 0010_cold_dm_ai.py for the same situation).
    _drop_fk_if_present("fk_conversations_whatsapp_account_id", "conversations")
    _drop_fk_if_present("fk_leads_whatsapp_account_id", "leads")

    if "whatsapp_tokens" in _table_names():
        op.drop_table("whatsapp_tokens")

    if "whatsapp_accounts" in _table_names():
        op.drop_index("ix_whatsapp_accounts_phone_number_id", table_name="whatsapp_accounts")
        op.drop_table("whatsapp_accounts")
