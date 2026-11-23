"""Track the last channel.status pushed to the SaaS.

Revision ID: 0026_saas_channel_health
Revises: 0025_saas_outbound_messages
Create Date: 2026-10-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_saas_channel_health"
down_revision = "0025_saas_outbound_messages"
branch_labels = None
depends_on = None


_TABLES = ("instagram_accounts", "whatsapp_accounts", "facebook_pages")


def _columns() -> list[sa.Column]:
    return [
        sa.Column("saas_last_health_status", sa.String(length=30), nullable=True),
        sa.Column("saas_last_health_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _existing(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # 0001 builds the schema with metadata.create_all, so on a fresh database
    # the columns can already exist by the time this runs.
    for table in _TABLES:
        present = _existing(table)
        for column in _columns():
            if column.name not in present:
                op.add_column(table, column)


def downgrade() -> None:
    for table in _TABLES:
        present = _existing(table)
        for column in reversed(_columns()):
            if column.name in present:
                op.drop_column(table, column.name)
