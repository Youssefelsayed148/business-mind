"""Phase 5C: erasure_cases and customer_links.external_id (docs/DATA-UNIFICATION.md section 6).

Revision ID: 0037_erasure_cases
Revises: 0036_customer_links

Additive. ``external_id`` is nullable and is scrubbed when an erasure completes. The downgrade drops
the new table and column only.
"""

import sqlalchemy as sa

from alembic import op

revision = "0037_erasure_cases"
down_revision = "0036_customer_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_links", sa.Column("external_id", sa.Text(), nullable=True))
    op.create_table(
        "erasure_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("many_channel_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("many_event_id", sa.Text(), nullable=True),
        sa.Column("many_remote_status", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_erasure_cases_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["link_id"], ["customer_links.id"], name="fk_erasure_cases_link", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name="fk_erasure_cases_user", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_erasure_cases_request"),
        sa.CheckConstraint(
            "state IN ('requested', 'saas_erased', 'complete', 'needs_action')",
            name="ck_erasure_cases_state",
        ),
        sa.CheckConstraint(
            "platform IN ('instagram', 'facebook', 'whatsapp')", name="ck_erasure_cases_platform"
        ),
    )
    op.create_index(
        "ix_erasure_cases_tenant_created", "erasure_cases", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("erasure_cases")
    op.drop_column("customer_links", "external_id")
