"""Add compliant WhatsApp outreach schema and backfill contacts.

Revision ID: 0018_whatsapp_outreach
Revises: 0017_workspace_membership
Create Date: 2026-10-02 00:00:00.000000
"""

from __future__ import annotations

import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_whatsapp_outreach"
down_revision = "0017_workspace_membership"
branch_labels = None
depends_on = None

_LOG = logging.getLogger("alembic.runtime.migration")

_NEW_TABLES = (
    "whatsapp_contacts",
    "whatsapp_consent_events",
    "whatsapp_templates",
    "whatsapp_campaigns",
    "whatsapp_campaign_recipients",
)

_BACKFILL_SQL = """
WITH candidates AS (
    SELECT l.id AS lead_id,
           l.workspace_id,
           l.whatsapp_account_id,
           l.ig_username AS display_name,
           l.last_seen_at,
           regexp_replace(coalesce(l.ig_user_id, ''), '\\D', '', 'g') AS normalized_wa_id,
           l.created_at
    FROM leads l
    WHERE l.platform = 'whatsapp'
),
ranked AS (
    SELECT c.*,
           row_number() OVER (
               PARTITION BY c.whatsapp_account_id, c.normalized_wa_id
               ORDER BY c.created_at, c.lead_id
           ) AS duplicate_rank
    FROM candidates c
    WHERE c.normalized_wa_id ~ '^[0-9]{6,20}$'
),
inserted AS (
    INSERT INTO whatsapp_contacts
        (id, workspace_id, whatsapp_account_id, wa_id, display_name, lead_id,
         marketing_consent, last_inbound_at, created_at, updated_at)
    SELECT gen_random_uuid(), r.workspace_id, r.whatsapp_account_id,
           r.normalized_wa_id, r.display_name, r.lead_id,
           'unknown', r.last_seen_at, now(), now()
    FROM ranked r
    WHERE r.duplicate_rank = 1
      AND NOT EXISTS (
          SELECT 1
          FROM whatsapp_contacts wc
          WHERE wc.whatsapp_account_id = r.whatsapp_account_id
            AND wc.wa_id = r.normalized_wa_id
      )
    ON CONFLICT DO NOTHING
    RETURNING 1
)
SELECT count(*)::integer FROM inserted
"""

_BACKFILL_STATS_SQL = """
WITH candidates AS (
    SELECT whatsapp_account_id,
           regexp_replace(coalesce(ig_user_id, ''), '\\D', '', 'g') AS normalized_wa_id
    FROM leads
    WHERE platform = 'whatsapp'
)
SELECT count(*)::integer AS total,
       count(*) FILTER (WHERE normalized_wa_id = '')::integer AS empty_count,
       count(*) FILTER (
           WHERE normalized_wa_id <> '' AND length(normalized_wa_id) < 6
       )::integer AS too_short_count,
       count(*) FILTER (
           WHERE length(normalized_wa_id) > 20
       )::integer AS too_long_count,
       count(*) FILTER (
           WHERE normalized_wa_id ~ '^[0-9]{6,20}$'
       )::integer AS eligible_count,
       count(DISTINCT (whatsapp_account_id, normalized_wa_id)) FILTER (
           WHERE normalized_wa_id ~ '^[0-9]{6,20}$'
       )::integer AS distinct_eligible_count
FROM candidates
"""

_BACKFILL_INVALID_SAMPLES_SQL = """
WITH invalid AS (
    SELECT CASE
               WHEN normalized_wa_id = '' THEN 'empty'
               WHEN length(normalized_wa_id) < 6 THEN 'too_short'
               ELSE 'too_long'
           END AS reason,
           CASE
               WHEN normalized_wa_id = '' THEN '<empty>'
               ELSE '***' || right(normalized_wa_id, 4)
           END AS masked_wa_id
    FROM (
        SELECT regexp_replace(coalesce(ig_user_id, ''), '\\D', '', 'g') AS normalized_wa_id
        FROM leads
        WHERE platform = 'whatsapp'
    ) candidates
    WHERE normalized_wa_id !~ '^[0-9]{6,20}$'
)
SELECT reason,
       count(*)::integer AS row_count,
       array_to_string((array_agg(masked_wa_id ORDER BY masked_wa_id))[1:5], ', ') AS samples
FROM invalid
GROUP BY reason
ORDER BY reason
"""


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_names() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table)}


def _constraint_names(table: str, kind: str) -> set[str]:
    inspector = _inspector()
    if kind == "primary":
        name = inspector.get_pk_constraint(table).get("name")
        return {name} if name else set()
    if kind == "foreignkey":
        return {item["name"] for item in inspector.get_foreign_keys(table) if item["name"]}
    if kind == "unique":
        return {
            item["name"]
            for item in inspector.get_unique_constraints(table)
            if item["name"]
        }
    if kind == "check":
        return {
            item["name"]
            for item in inspector.get_check_constraints(table)
            if item["name"]
        }
    raise ValueError(kind)


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_indexes(table) if item["name"]}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    if column_name in _columns(table):
        op.drop_column(table, column_name)


def _add_fk(
    name: str,
    table: str,
    referent: str,
    local_columns: list[str],
    remote_columns: list[str],
    *,
    ondelete: str | None = None,
) -> None:
    if name not in _constraint_names(table, "foreignkey"):
        op.create_foreign_key(
            name,
            table,
            referent,
            local_columns,
            remote_columns,
            ondelete=ondelete,
        )


def _add_unique(name: str, table: str, columns: list[str]) -> None:
    if name not in _constraint_names(table, "unique"):
        op.create_unique_constraint(name, table, columns)


def _add_check(name: str, table: str, condition: str) -> None:
    if name not in _constraint_names(table, "check"):
        op.create_check_constraint(name, table, condition)


def _add_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns)


def _drop_constraint_if_present(name: str, table: str, kind: str) -> None:
    if name in _constraint_names(table, kind):
        alembic_kind = "foreignkey" if kind == "foreignkey" else kind
        op.drop_constraint(name, table, type_=alembic_kind)


def _create_tables() -> None:
    tables = _table_names()
    if "whatsapp_contacts" not in tables:
        op.create_table(
            "whatsapp_contacts",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "whatsapp_account_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("wa_id", sa.String(32), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=True),
            sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "marketing_consent",
                sa.String(20),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("consent_source", sa.String(40), nullable=True),
            sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "free_entry_point_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_whatsapp_contacts"),
        )

    tables = _table_names()
    if "whatsapp_consent_events" not in tables:
        op.create_table(
            "whatsapp_consent_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_type", sa.String(20), nullable=False),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column(
                "evidence",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_whatsapp_consent_events"),
        )

    tables = _table_names()
    if "whatsapp_templates" not in tables:
        op.create_table(
            "whatsapp_templates",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "whatsapp_account_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("meta_template_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("language", sa.String(16), nullable=False),
            sa.Column("category", sa.String(20), nullable=False),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="draft"
            ),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column(
                "components",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("quality_score", sa.String(20), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_whatsapp_templates"),
        )

    tables = _table_names()
    if "whatsapp_campaigns" not in tables:
        op.create_table(
            "whatsapp_campaigns",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "whatsapp_account_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="draft"
            ),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "throttle_per_minute",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column(
                "variable_mapping",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "total_recipients", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "delivered_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_whatsapp_campaigns"),
        )

    tables = _table_names()
    if "whatsapp_campaign_recipients" not in tables:
        op.create_table(
            "whatsapp_campaign_recipients",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "status", sa.String(30), nullable=False, server_default="queued"
            ),
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("provider_message_id", sa.String(255), nullable=True),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint(
                "id", name="pk_whatsapp_campaign_recipients"
            ),
        )


def _add_columns() -> None:
    _add_column_if_missing(
        "whatsapp_accounts",
        sa.Column("quality_rating", sa.String(20), nullable=True),
    )
    _add_column_if_missing(
        "whatsapp_accounts",
        sa.Column("messaging_limit_tier", sa.String(30), nullable=True),
    )
    _add_column_if_missing(
        "whatsapp_accounts",
        sa.Column(
            "outreach_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column_if_missing(
        "whatsapp_accounts",
        sa.Column("outreach_paused_reason", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "whatsapp_accounts",
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
    )

    _add_column_if_missing(
        "messages",
        sa.Column("whatsapp_campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_column_if_missing(
        "messages",
        sa.Column("whatsapp_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_column_if_missing(
        "messages",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "messages",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def _run_backfill() -> int:
    bind = op.get_bind()
    stats = bind.execute(sa.text(_BACKFILL_STATS_SQL)).mappings().one()
    inserted = bind.execute(sa.text(_BACKFILL_SQL)).scalar_one()
    duplicate_candidates = stats["eligible_count"] - stats["distinct_eligible_count"]
    already_present = stats["distinct_eligible_count"] - inserted
    invalid_count = (
        stats["empty_count"] + stats["too_short_count"] + stats["too_long_count"]
    )

    _LOG.info(
        "WhatsApp contact backfill: leads=%d eligible=%d inserted=%d "
        "invalid_skipped=%d duplicate_candidates=%d already_present=%d; "
        "marketing_consent=unknown for every inserted contact",
        stats["total"],
        stats["eligible_count"],
        inserted,
        invalid_count,
        duplicate_candidates,
        already_present,
    )
    for row in bind.execute(sa.text(_BACKFILL_INVALID_SAMPLES_SQL)).mappings():
        _LOG.warning(
            "WhatsApp contact backfill skipped reason=%s count=%d masked_samples=[%s]",
            row["reason"],
            row["row_count"],
            row["samples"],
        )
    return inserted


def _add_constraints_and_indexes() -> None:
    _add_fk(
        "fk_whatsapp_contacts_workspace_id",
        "whatsapp_contacts",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_contacts_whatsapp_account_id",
        "whatsapp_contacts",
        "whatsapp_accounts",
        ["whatsapp_account_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_contacts_lead_id",
        "whatsapp_contacts",
        "leads",
        ["lead_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _add_unique(
        "uq_whatsapp_contacts_account_wa_id",
        "whatsapp_contacts",
        ["whatsapp_account_id", "wa_id"],
    )
    _add_check(
        "ck_whatsapp_contacts_marketing_consent",
        "whatsapp_contacts",
        "marketing_consent IN ('unknown', 'opted_in', 'opted_out')",
    )
    _add_check(
        "ck_whatsapp_contacts_consent_source",
        "whatsapp_contacts",
        "consent_source IS NULL OR consent_source IN "
        "('web_form', 'click_to_whatsapp', 'inbound_keyword', 'in_store', "
        "'imported_attested', 'manual')",
    )
    _add_check(
        "ck_whatsapp_contacts_wa_id",
        "whatsapp_contacts",
        "wa_id ~ '^[0-9]{6,20}$'",
    )
    _add_index(
        "ix_whatsapp_contacts_workspace_consent",
        "whatsapp_contacts",
        ["workspace_id", "marketing_consent"],
    )

    _add_fk(
        "fk_whatsapp_consent_events_contact_id",
        "whatsapp_consent_events",
        "whatsapp_contacts",
        ["contact_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_consent_events_workspace_id",
        "whatsapp_consent_events",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_consent_events_actor_user_id",
        "whatsapp_consent_events",
        "users",
        ["actor_user_id"],
        ["id"],
    )
    _add_check(
        "ck_whatsapp_consent_events_event_type",
        "whatsapp_consent_events",
        "event_type IN ('opt_in', 'opt_out', 'import', 'revoke')",
    )
    _add_index(
        "ix_whatsapp_consent_events_contact_created",
        "whatsapp_consent_events",
        ["contact_id", "created_at"],
    )

    _add_fk(
        "fk_whatsapp_templates_workspace_id",
        "whatsapp_templates",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_templates_whatsapp_account_id",
        "whatsapp_templates",
        "whatsapp_accounts",
        ["whatsapp_account_id"],
        ["id"],
    )
    _add_unique(
        "uq_whatsapp_templates_account_name_language",
        "whatsapp_templates",
        ["whatsapp_account_id", "name", "language"],
    )
    _add_check(
        "ck_whatsapp_templates_category",
        "whatsapp_templates",
        "category IN ('marketing', 'utility', 'authentication')",
    )
    _add_check(
        "ck_whatsapp_templates_status",
        "whatsapp_templates",
        "status IN ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled')",
    )

    _add_fk(
        "fk_whatsapp_campaigns_workspace_id",
        "whatsapp_campaigns",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_campaigns_whatsapp_account_id",
        "whatsapp_campaigns",
        "whatsapp_accounts",
        ["whatsapp_account_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_campaigns_template_id",
        "whatsapp_campaigns",
        "whatsapp_templates",
        ["template_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_campaigns_created_by",
        "whatsapp_campaigns",
        "users",
        ["created_by"],
        ["id"],
    )
    _add_check(
        "ck_whatsapp_campaigns_status",
        "whatsapp_campaigns",
        "status IN ('draft', 'scheduled', 'running', 'paused', 'completed', "
        "'cancelled', 'failed')",
    )

    _add_fk(
        "fk_whatsapp_campaign_recipients_campaign_id",
        "whatsapp_campaign_recipients",
        "whatsapp_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )
    _add_fk(
        "fk_whatsapp_campaign_recipients_contact_id",
        "whatsapp_campaign_recipients",
        "whatsapp_contacts",
        ["contact_id"],
        ["id"],
    )
    _add_fk(
        "fk_whatsapp_campaign_recipients_message_id",
        "whatsapp_campaign_recipients",
        "messages",
        ["message_id"],
        ["id"],
    )
    _add_unique(
        "uq_whatsapp_campaign_recipients_campaign_contact",
        "whatsapp_campaign_recipients",
        ["campaign_id", "contact_id"],
    )
    _add_check(
        "ck_whatsapp_campaign_recipients_status",
        "whatsapp_campaign_recipients",
        "status IN ('queued', 'sent', 'delivered', 'read', 'failed', "
        "'skipped_no_consent', 'skipped_opted_out', 'skipped_not_eligible')",
    )
    _add_index(
        "ix_whatsapp_campaign_recipients_campaign_status",
        "whatsapp_campaign_recipients",
        ["campaign_id", "status"],
    )

    _add_check(
        "ck_whatsapp_accounts_quality_rating",
        "whatsapp_accounts",
        "quality_rating IS NULL OR quality_rating IN ('GREEN', 'YELLOW', 'RED')",
    )
    _add_fk(
        "fk_messages_whatsapp_campaign_id",
        "messages",
        "whatsapp_campaigns",
        ["whatsapp_campaign_id"],
        ["id"],
    )
    _add_fk(
        "fk_messages_whatsapp_template_id",
        "messages",
        "whatsapp_templates",
        ["whatsapp_template_id"],
        ["id"],
    )


def upgrade() -> None:
    _create_tables()
    _add_columns()
    _run_backfill()
    _add_constraints_and_indexes()


def downgrade() -> None:
    _drop_constraint_if_present(
        "fk_messages_whatsapp_campaign_id", "messages", "foreignkey"
    )
    _drop_constraint_if_present(
        "fk_messages_whatsapp_template_id", "messages", "foreignkey"
    )
    for column_name in (
        "read_at",
        "delivered_at",
        "whatsapp_template_id",
        "whatsapp_campaign_id",
    ):
        _drop_column_if_present("messages", column_name)

    _drop_constraint_if_present(
        "ck_whatsapp_accounts_quality_rating", "whatsapp_accounts", "check"
    )
    for column_name in (
        "health_checked_at",
        "outreach_paused_reason",
        "outreach_paused",
        "messaging_limit_tier",
        "quality_rating",
    ):
        _drop_column_if_present("whatsapp_accounts", column_name)

    tables = _table_names()
    for table_name in (
        "whatsapp_campaign_recipients",
        "whatsapp_campaigns",
        "whatsapp_templates",
        "whatsapp_consent_events",
        "whatsapp_contacts",
    ):
        if table_name in tables:
            op.drop_table(table_name)
            tables.remove(table_name)
