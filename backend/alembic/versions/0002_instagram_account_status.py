"""Add Instagram account status

Revision ID: 0002_instagram_account_status
Revises: 0001_initial
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0002_instagram_account_status"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("instagram_accounts")}
    if "status" in columns:
        return

    op.add_column(
        "instagram_accounts",
        sa.Column("status", sa.String(length=50), nullable=False, server_default="connected"),
    )
    op.alter_column("instagram_accounts", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("instagram_accounts", "status")
