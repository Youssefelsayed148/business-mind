"""Add per-channel SaaS delegation settings.

Revision ID: 0023_saas_delegation
Revises: 0022_whatsapp_opt_in
Create Date: 2026-10-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_saas_delegation"
down_revision = "0022_whatsapp_opt_in"
branch_labels = None
depends_on = None


_TABLES = ("instagram_accounts", "whatsapp_accounts", "facebook_pages")


def _columns() -> list[sa.Column]:
    return [
        sa.Column(
            "saas_delegation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("saas_connection_id", sa.String(length=64), nullable=True),
        sa.Column("saas_base_url", sa.String(length=512), nullable=True),
        sa.Column("saas_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("saas_previous_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "saas_previous_secret_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("saas_last_forward_status", sa.String(length=50), nullable=True),
        sa.Column("saas_last_forward_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "saas_degraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
