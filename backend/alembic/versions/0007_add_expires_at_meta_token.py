"""Add expires_at to meta_tokens

Revision ID: 0007_add_expires_at_meta_token
Revises: 0006_campaign_target_media
Create Date: 2026-06-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_add_expires_at_meta_token"
down_revision = "0006_campaign_target_media"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column_name in columns:
        op.drop_column(table, column_name)


def upgrade() -> None:
    _add_column_if_missing(
        "meta_tokens",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_present("meta_tokens", "expires_at")
