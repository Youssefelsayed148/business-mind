"""Add Facebook Pages, tokens, campaigns, comments, and wire up Phase 1's
deferred facebook_page_id FKs

Phase 3 of the multi-platform expansion (see
docs/specs/2026-09-05-multi-platform-expansion-design.md, and
phase-3-facebook-prompt.md). Adds:

- `facebook_pages` table, modeled on `instagram_accounts`' full shape
  (unlike `whatsapp_accounts`, Facebook Pages have a real campaign concept,
  so `ai_cold_dm_enabled` and the rest of Instagram's AI fields carry over).
- `facebook_tokens` table (separate from `meta_tokens`, same reasoning as
  `whatsapp_tokens`: `meta_tokens.instagram_account_id` is NOT NULL and FK'd
  strictly to `instagram_accounts`).
- `facebook_campaigns` + `facebook_campaign_keywords` tables — `campaigns`/
  `campaign_keywords` aren't reusable: `campaigns.instagram_account_id` is
  NOT NULL and `campaign_matcher.find_matching_campaigns()` filters on it
  directly, with no platform-generic seam. No follow-prompt columns — per
  this phase's research spike, Facebook Pages have no documented equivalent
  of Instagram's is_user_follow_business consent field, so only
  delivery_mode='instant' is supported.
- `facebook_comments` table — `comments.instagram_account_id` is NOT NULL,
  zero platform awareness, same reasoning as campaigns.
- `facebook_user_cooldowns` table — `user_cooldowns.campaign_id` is FK'd
  strictly to `campaigns.id` and its `instagram_user_id` column is
  Instagram-named, same reasoning as `facebook_campaigns`.
- The FK constraints Phase 1 deferred: `leads.facebook_page_id` and
  `conversations.facebook_page_id` -> `facebook_pages.id`.
- A second uniqueness constraint on `leads`, `uq_lead_workspace_facebook_user`
  (workspace_id, facebook_page_id, ig_user_id) — same NULL-distinctness
  reasoning as Phase 2's `uq_lead_workspace_whatsapp_user`.
- `conversations.facebook_campaign_id` (nullable, FK to
  `facebook_campaigns.id`) plus `uq_conversation_lead_facebook_campaign` —
  `conversations.campaign_id` is FK'd strictly to `campaigns.id`, so a
  Facebook campaign-triggered conversation needs its own campaign reference,
  mirroring how `whatsapp_account_id` needed its own column rather than
  reusing `instagram_account_id`.
- `messages.facebook_campaign_id` and `messages.facebook_comment_id`
  (nullable, FKs to `facebook_campaigns.id`/`facebook_comments.id`) plus
  `uq_message_facebook_campaign_comment_type` — `messages.campaign_id`/
  `comment_id` are FK'd strictly to Instagram's tables. This new unique
  constraint is what actually enforces "one private reply per comment" for
  Facebook, the same role `uq_message_campaign_comment_type` plays for
  Instagram.
- `automation_logs.facebook_page_id` (nullable, FK to `facebook_pages.id`)
  — same reasoning as Phase 2's `whatsapp_account_id` addition there.

Does not touch `instagram_accounts`, `campaigns`, `comments`, `meta_tokens`,
`whatsapp_accounts`, or `whatsapp_tokens` in any way.

Revision ID: 0013_facebook_pages
Revises: 0012_whatsapp_accounts
Create Date: 2026-09-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_facebook_pages"
down_revision = "0012_whatsapp_accounts"
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


def upgrade() -> None:
    # facebook_pages ------------------------------------------------------
    if "facebook_pages" not in _table_names():
        op.create_table(
            "facebook_pages",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("page_id", sa.String(255), nullable=False, unique=True),
            sa.Column("page_name", sa.String(255), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="connected"),
            sa.Column("business_vertical", sa.String(50), nullable=False, server_default="general"),
            sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ai_cold_dm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        op.create_index("ix_facebook_pages_page_id", "facebook_pages", ["page_id"])

    # facebook_tokens -------------------------------------------------------
    if "facebook_tokens" not in _table_names():
        op.create_table(
            "facebook_tokens",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "facebook_page_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("facebook_pages.id"),
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

    # facebook_campaigns ----------------------------------------------------
    if "facebook_campaigns" not in _table_names():
        op.create_table(
            "facebook_campaigns",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column(
                "facebook_page_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("facebook_pages.id"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("post_id", sa.String(255), nullable=True),
            sa.Column("target_scope", sa.String(50), nullable=False, server_default="any_post"),
            sa.Column("target_post_id", sa.String(255), nullable=True),
            sa.Column("target_post_label", sa.String(255), nullable=True),
            sa.Column("match_type", sa.String(50), nullable=False, server_default="contains"),
            sa.Column("message_template", sa.Text(), nullable=False, server_default=""),
            sa.Column("link_url", sa.Text(), nullable=True),
            sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default="168"),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("delivery_mode", sa.String(50), nullable=False, server_default="instant"),
            sa.Column("comment_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("comment_reply_text", sa.Text(), nullable=True),
            sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ai_handoff_after_turns", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("total_triggers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("successful_sends", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_sends", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
        )

    # facebook_campaign_keywords ---------------------------------------------
    if "facebook_campaign_keywords" not in _table_names():
        op.create_table(
            "facebook_campaign_keywords",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("facebook_campaigns.id"),
                nullable=False,
            ),
            sa.Column("normalized_keyword", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "campaign_id", "normalized_keyword", name="uq_facebook_campaign_keyword"
            ),
        )

    # facebook_comments -----------------------------------------------------
    if "facebook_comments" not in _table_names():
        op.create_table(
            "facebook_comments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "facebook_page_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("facebook_pages.id"),
                nullable=False,
            ),
            sa.Column("comment_id", sa.String(255), nullable=False, unique=True),
            sa.Column("post_id", sa.String(255), nullable=True),
            sa.Column("from_id", sa.String(255), nullable=True),
            sa.Column("from_name", sa.String(255), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("normalized_text", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_facebook_comments_comment_id", "facebook_comments", ["comment_id"])

    # facebook_user_cooldowns -------------------------------------------------
    if "facebook_user_cooldowns" not in _table_names():
        op.create_table(
            "facebook_user_cooldowns",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("facebook_campaigns.id"),
                nullable=False,
            ),
            sa.Column("facebook_user_id", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "campaign_id", "facebook_user_id", name="uq_facebook_user_cooldown_campaign_user"
            ),
        )

    # leads / conversations: FK targets Phase 1 deferred ---------------------
    _create_fk_if_missing(
        "fk_leads_facebook_page_id", "leads", "facebook_pages", ["facebook_page_id"], ["id"]
    )
    _create_fk_if_missing(
        "fk_conversations_facebook_page_id",
        "conversations",
        "facebook_pages",
        ["facebook_page_id"],
        ["id"],
    )

    # leads: Facebook-scoped uniqueness (see module docstring) ---------------
    _create_unique_constraint_if_missing(
        "uq_lead_workspace_facebook_user", "leads", ["workspace_id", "facebook_page_id", "ig_user_id"]
    )

    # conversations.facebook_campaign_id --------------------------------------
    _add_column_if_missing(
        "conversations",
        sa.Column("facebook_campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _create_fk_if_missing(
        "fk_conversations_facebook_campaign_id",
        "conversations",
        "facebook_campaigns",
        ["facebook_campaign_id"],
        ["id"],
    )
    _create_unique_constraint_if_missing(
        "uq_conversation_lead_facebook_campaign", "conversations", ["lead_id", "facebook_campaign_id"]
    )

    # messages.facebook_campaign_id / facebook_comment_id ---------------------
    _add_column_if_missing(
        "messages",
        sa.Column("facebook_campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_column_if_missing(
        "messages",
        sa.Column("facebook_comment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _create_fk_if_missing(
        "fk_messages_facebook_campaign_id",
        "messages",
        "facebook_campaigns",
        ["facebook_campaign_id"],
        ["id"],
    )
    _create_fk_if_missing(
        "fk_messages_facebook_comment_id", "messages", "facebook_comments", ["facebook_comment_id"], ["id"]
    )
    _create_unique_constraint_if_missing(
        "uq_message_facebook_campaign_comment_type",
        "messages",
        ["facebook_campaign_id", "facebook_comment_id", "message_type"],
    )

    # automation_logs.facebook_page_id ----------------------------------------
    _add_column_if_missing(
        "automation_logs",
        sa.Column("facebook_page_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _create_fk_if_missing(
        "fk_automation_logs_facebook_page_id",
        "automation_logs",
        "facebook_pages",
        ["facebook_page_id"],
        ["id"],
    )


def downgrade() -> None:
    _drop_fk_if_present("fk_automation_logs_facebook_page_id", "automation_logs")
    _drop_column_if_present("automation_logs", "facebook_page_id")

    _drop_unique_constraint_if_present("uq_message_facebook_campaign_comment_type", "messages")
    _drop_fk_if_present("fk_messages_facebook_comment_id", "messages")
    _drop_fk_if_present("fk_messages_facebook_campaign_id", "messages")
    _drop_column_if_present("messages", "facebook_comment_id")
    _drop_column_if_present("messages", "facebook_campaign_id")

    _drop_unique_constraint_if_present("uq_conversation_lead_facebook_campaign", "conversations")
    _drop_fk_if_present("fk_conversations_facebook_campaign_id", "conversations")
    _drop_column_if_present("conversations", "facebook_campaign_id")

    _drop_unique_constraint_if_present("uq_lead_workspace_facebook_user", "leads")

    _drop_fk_if_present("fk_conversations_facebook_page_id", "conversations")
    _drop_fk_if_present("fk_leads_facebook_page_id", "leads")

    if "facebook_user_cooldowns" in _table_names():
        op.drop_table("facebook_user_cooldowns")

    if "facebook_comments" in _table_names():
        op.drop_index("ix_facebook_comments_comment_id", table_name="facebook_comments")
        op.drop_table("facebook_comments")

    if "facebook_campaign_keywords" in _table_names():
        op.drop_table("facebook_campaign_keywords")

    if "facebook_campaigns" in _table_names():
        op.drop_table("facebook_campaigns")

    if "facebook_tokens" in _table_names():
        op.drop_table("facebook_tokens")

    if "facebook_pages" in _table_names():
        op.drop_index("ix_facebook_pages_page_id", table_name="facebook_pages")
        op.drop_table("facebook_pages")
