"""Add comment_reply_enabled and comment_reply_text to campaigns

Revision ID: 0008_campaign_comment_reply
Revises: 0007_add_expires_at_meta_token
Create Date: 2026-08-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_campaign_comment_reply"
down_revision = "0007_add_expires_at_meta_token"
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
        "campaigns",
        sa.Column("comment_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "campaigns",
        sa.Column("comment_reply_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_present("campaigns", "comment_reply_text")
    _drop_column_if_present("campaigns", "comment_reply_enabled")
