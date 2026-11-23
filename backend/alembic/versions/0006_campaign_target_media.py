"""Add campaign target media fields

Revision ID: 0006_campaign_target_media
Revises: 0005_processed_webhook_events
Create Date: 2026-05-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_campaign_target_media"
down_revision = "0005_processed_webhook_events"
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
    _add_column_if_missing("campaigns", sa.Column("target_scope", sa.String(50), nullable=False, server_default="any_media"))
    _add_column_if_missing("campaigns", sa.Column("target_media_url", sa.Text(), nullable=True))
    _add_column_if_missing("campaigns", sa.Column("target_media_shortcode", sa.String(255), nullable=True))
    _add_column_if_missing("campaigns", sa.Column("target_media_id", sa.String(255), nullable=True))
    _add_column_if_missing("campaigns", sa.Column("target_media_type", sa.String(50), nullable=False, server_default="unknown"))
    _add_column_if_missing("campaigns", sa.Column("target_media_label", sa.String(255), nullable=True))
    _add_column_if_missing("leads", sa.Column("source_media_id", sa.String(255), nullable=True))
    _add_column_if_missing("leads", sa.Column("source_media_type", sa.String(50), nullable=True))
    _add_column_if_missing("leads", sa.Column("source_media_label", sa.String(255), nullable=True))
    _add_column_if_missing("messages", sa.Column("source_media_id", sa.String(255), nullable=True))
    _add_column_if_missing("messages", sa.Column("source_media_type", sa.String(50), nullable=True))
    _add_column_if_missing("messages", sa.Column("source_media_label", sa.String(255), nullable=True))


def downgrade() -> None:
    for column in ("source_media_label", "source_media_type", "source_media_id"):
        _drop_column_if_present("messages", column)
        _drop_column_if_present("leads", column)
    for column in (
        "target_media_label",
        "target_media_type",
        "target_media_id",
        "target_media_shortcode",
        "target_media_url",
        "target_scope",
    ):
        _drop_column_if_present("campaigns", column)
