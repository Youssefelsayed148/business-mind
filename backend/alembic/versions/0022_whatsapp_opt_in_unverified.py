"""Add revocable opt-in links and unverified opt-in evidence.

Revision ID: 0022_whatsapp_opt_in
Revises: 0021_whatsapp_campaign_done
Create Date: 2026-10-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_whatsapp_opt_in"
down_revision = "0021_whatsapp_campaign_done"
branch_labels = None
depends_on = None


_OLD = "event_type IN ('opt_in', 'opt_out', 'import', 'revoke', 'resubscribe')"
_NEW = (
    "event_type IN ('opt_in', 'opt_out', 'import', 'revoke', 'resubscribe', "
    "'opt_in_unverified')"
)


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("whatsapp_accounts")
    }
    if "opt_in_link_salt" not in columns:
        op.add_column(
            "whatsapp_accounts",
            sa.Column(
                "opt_in_link_salt",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
        )
    if "outreach_paused_at" not in columns:
        op.add_column(
            "whatsapp_accounts",
            sa.Column("outreach_paused_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        "UPDATE whatsapp_accounts "
        "SET outreach_paused_at = COALESCE(health_checked_at, now()) "
        "WHERE outreach_paused = true AND outreach_paused_at IS NULL"
    )
    op.drop_constraint(
        "ck_whatsapp_consent_events_event_type", "whatsapp_consent_events", type_="check"
    )
    op.create_check_constraint(
        "ck_whatsapp_consent_events_event_type", "whatsapp_consent_events", _NEW
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM whatsapp_consent_events WHERE event_type = 'opt_in_unverified'"
    )
    op.drop_constraint(
        "ck_whatsapp_consent_events_event_type", "whatsapp_consent_events", type_="check"
    )
    op.create_check_constraint(
        "ck_whatsapp_consent_events_event_type", "whatsapp_consent_events", _OLD
    )
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("whatsapp_accounts")
    }
    if "opt_in_link_salt" in columns:
        op.drop_column("whatsapp_accounts", "opt_in_link_salt")
    if "outreach_paused_at" in columns:
        op.drop_column("whatsapp_accounts", "outreach_paused_at")
