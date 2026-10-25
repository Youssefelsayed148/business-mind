"""Add the SaaS outbound message idempotency table.

Revision ID: 0025_saas_outbound_messages
Revises: 0024_saas_forward_events
Create Date: 2026-10-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_saas_outbound_messages"
down_revision = "0024_saas_forward_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the schema with metadata.create_all, so on a fresh database
    # the table can already exist by the time this runs.
    if sa.inspect(op.get_bind()).has_table("saas_outbound_messages"):
        return
    op.create_table(
        "saas_outbound_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "message_pk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "message_id", name="uq_saas_outbound_connection_message"),
    )
    op.create_index("ix_saas_outbound_messages_message_pk", "saas_outbound_messages", ["message_pk"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("saas_outbound_messages"):
        op.drop_table("saas_outbound_messages")
