"""Add the WhatsApp campaign completion timestamp.

Revision ID: 0021_whatsapp_campaign_done
Revises: 0020_whatsapp_outreach_services
Create Date: 2026-10-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_whatsapp_campaign_done"
down_revision = "0020_whatsapp_outreach_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("whatsapp_campaigns")
    }
    if "completed_at" not in columns:
        op.add_column(
            "whatsapp_campaigns",
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("whatsapp_campaigns")
    }
    if "completed_at" in columns:
        op.drop_column("whatsapp_campaigns", "completed_at")
