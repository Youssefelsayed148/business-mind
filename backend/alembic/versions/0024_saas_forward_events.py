"""Add the SaaS forwarding outbox.

Revision ID: 0024_saas_forward_events
Revises: 0023_saas_delegation
Create Date: 2026-10-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_saas_forward_events"
down_revision = "0023_saas_delegation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the schema with metadata.create_all, so on a fresh database
    # the table can already exist by the time this runs.
    if sa.inspect(op.get_bind()).has_table("saas_forward_events"):
        return
    op.create_table(
        "saas_forward_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("ordering_key", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("seq"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_saas_forward_events_channel_id", "saas_forward_events", ["channel_id"])
    op.create_index(
        "ix_saas_forward_events_key_status_seq",
        "saas_forward_events",
        ["ordering_key", "status", "seq"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("saas_forward_events"):
        op.drop_table("saas_forward_events")
