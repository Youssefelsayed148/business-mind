"""Add processed_webhook_events table for per-change deduplication

Revision ID: 0005_processed_webhook_events
Revises: 0004_roles_and_audit_logs
Create Date: 2026-05-22 00:00:00.000000

Rows in this table act as a fast, race-safe guard against Meta resending the
same webhook change (comment) more than once.  Old rows (> 30-90 days) can be
pruned with a cron job or a future migration without affecting correctness.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_processed_webhook_events"
down_revision = "0004_roles_and_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "processed_webhook_events" not in inspector.get_table_names():
        op.create_table(
            "processed_webhook_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("provider", sa.String(50), nullable=False, server_default="meta"),
            sa.Column("event_key", sa.String(500), nullable=False),
            sa.Column("event_type", sa.String(100), nullable=True),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.UniqueConstraint("provider", "event_key", name="uq_processed_webhook_provider_key"),
        )
        op.create_index(
            "ix_processed_webhook_events_received_at",
            "processed_webhook_events",
            ["received_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "processed_webhook_events" in inspector.get_table_names():
        indexes = {idx["name"] for idx in inspector.get_indexes("processed_webhook_events")}
        if "ix_processed_webhook_events_received_at" in indexes:
            op.drop_index(
                "ix_processed_webhook_events_received_at",
                table_name="processed_webhook_events",
            )
        op.drop_table("processed_webhook_events")
