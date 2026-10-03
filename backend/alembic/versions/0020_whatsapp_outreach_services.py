"""Support atomic WhatsApp outreach reservations.

Revision ID: 0020_whatsapp_outreach_services
Revises: 0019_whatsapp_outreach_settings
Create Date: 2026-10-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_whatsapp_outreach_services"
down_revision = "0019_whatsapp_outreach_settings"
branch_labels = None
depends_on = None


_OLD_RECIPIENT_STATUSES = (
    "status IN ('queued', 'sent', 'delivered', 'read', 'failed', "
    "'skipped_no_consent', 'skipped_opted_out', 'skipped_not_eligible')"
)
_NEW_RECIPIENT_STATUSES = (
    "status IN ('queued', 'pending', 'sending', 'sent', 'delivered', 'read', 'failed', "
    "'skipped_no_consent', 'skipped_opted_out', 'skipped_not_eligible')"
)


def upgrade() -> None:
    op.alter_column("messages", "lead_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(
        "ck_whatsapp_campaign_recipients_status",
        "whatsapp_campaign_recipients",
        type_="check",
    )
    op.execute("UPDATE whatsapp_campaign_recipients SET status = 'pending' WHERE status = 'queued'")
    op.alter_column(
        "whatsapp_campaign_recipients",
        "status",
        existing_type=sa.String(length=30),
        server_default="pending",
    )
    op.create_check_constraint(
        "ck_whatsapp_campaign_recipients_status",
        "whatsapp_campaign_recipients",
        _NEW_RECIPIENT_STATUSES,
    )
    op.drop_constraint(
        "ck_whatsapp_consent_events_event_type",
        "whatsapp_consent_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_whatsapp_consent_events_event_type",
        "whatsapp_consent_events",
        "event_type IN ('opt_in', 'opt_out', 'import', 'revoke', 'resubscribe')",
    )
    op.drop_constraint(
        "ck_whatsapp_templates_status",
        "whatsapp_templates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_whatsapp_templates_status",
        "whatsapp_templates",
        "status IN ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled', 'deleted')",
    )


def downgrade() -> None:
    # This downgrade intentionally fails at the final ALTER when a Phase 3
    # outreach Message has lead_id=NULL. There is no truthful legacy Lead to
    # synthesize for an imported WhatsApp contact; operators must retain 0020
    # or remove/migrate those messages explicitly before downgrading.
    op.execute("UPDATE whatsapp_consent_events SET event_type = 'opt_in' WHERE event_type = 'resubscribe'")
    op.drop_constraint(
        "ck_whatsapp_consent_events_event_type",
        "whatsapp_consent_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_whatsapp_consent_events_event_type",
        "whatsapp_consent_events",
        "event_type IN ('opt_in', 'opt_out', 'import', 'revoke')",
    )
    op.execute("UPDATE whatsapp_templates SET status = 'disabled' WHERE status = 'deleted'")
    op.drop_constraint(
        "ck_whatsapp_templates_status",
        "whatsapp_templates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_whatsapp_templates_status",
        "whatsapp_templates",
        "status IN ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled')",
    )
    op.execute("UPDATE whatsapp_campaign_recipients SET status = 'queued' WHERE status IN ('pending', 'sending')")
    op.drop_constraint(
        "ck_whatsapp_campaign_recipients_status",
        "whatsapp_campaign_recipients",
        type_="check",
    )
    op.alter_column(
        "whatsapp_campaign_recipients",
        "status",
        existing_type=sa.String(length=30),
        server_default="queued",
    )
    op.create_check_constraint(
        "ck_whatsapp_campaign_recipients_status",
        "whatsapp_campaign_recipients",
        _OLD_RECIPIENT_STATUSES,
    )
    op.alter_column("messages", "lead_id", existing_type=sa.UUID(), nullable=False)
