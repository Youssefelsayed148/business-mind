"""Add per-account WhatsApp outreach settings.

Revision ID: 0019_whatsapp_outreach_settings
Revises: 0018_whatsapp_outreach
Create Date: 2026-10-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_whatsapp_outreach_settings"
down_revision = "0018_whatsapp_outreach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_accounts",
        sa.Column(
            "ctwa_counts_as_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "whatsapp_accounts",
        sa.Column(
            "transactional_utility_attested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "whatsapp_accounts",
        sa.Column("opt_out_keywords", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "whatsapp_accounts",
        sa.Column("opt_in_keywords", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "whatsapp_accounts",
        sa.Column(
            "outreach_daily_cap",
            sa.Integer(),
            nullable=False,
            server_default="250",
        ),
    )
    op.create_check_constraint(
        "ck_whatsapp_accounts_opt_out_keywords_array",
        "whatsapp_accounts",
        "opt_out_keywords IS NULL OR jsonb_typeof(opt_out_keywords) = 'array'",
    )
    op.create_check_constraint(
        "ck_whatsapp_accounts_opt_in_keywords_array",
        "whatsapp_accounts",
        "opt_in_keywords IS NULL OR jsonb_typeof(opt_in_keywords) = 'array'",
    )
    op.create_check_constraint(
        "ck_whatsapp_accounts_outreach_daily_cap",
        "whatsapp_accounts",
        "outreach_daily_cap > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_whatsapp_accounts_outreach_daily_cap",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_whatsapp_accounts_opt_in_keywords_array",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_whatsapp_accounts_opt_out_keywords_array",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_column("whatsapp_accounts", "outreach_daily_cap")
    op.drop_column("whatsapp_accounts", "opt_in_keywords")
    op.drop_column("whatsapp_accounts", "opt_out_keywords")
    op.drop_column("whatsapp_accounts", "transactional_utility_attested")
    op.drop_column("whatsapp_accounts", "ctwa_counts_as_consent")
