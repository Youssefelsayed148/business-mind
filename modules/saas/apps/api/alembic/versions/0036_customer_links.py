"""Phase 5: customer_links and many_channel_claims (docs/DATA-UNIFICATION.md sections 3 and 4).

Revision ID: 0036_customer_links
Revises: 0035_invitation_locations

Additive and unused until DATA_UNIFICATION_ENABLED is on. The downgrade drops only these two
tables.
"""

import sqlalchemy as sa

from alembic import op

revision = "0036_customer_links"
down_revision = "0035_invitation_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("many_channel_id", sa.Text(), nullable=False),
        sa.Column("external_id_digest", sa.Text(), nullable=False),
        sa.Column("many_lead_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_customer_links_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name="fk_customer_links_contact", ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "platform",
            "many_channel_id",
            "external_id_digest",
            name="uq_customer_links_identity",
        ),
        sa.CheckConstraint(
            "platform IN ('instagram', 'facebook', 'whatsapp')", name="ck_customer_links_platform"
        ),
        sa.CheckConstraint(
            "state IN ('linked', 'many_only', 'saas_only', 'conflict', 'erased')",
            name="ck_customer_links_state",
        ),
        sa.CheckConstraint(
            "source IN ('delegated_event', 'many_lead')", name="ck_customer_links_source"
        ),
        sa.CheckConstraint("length(external_id_digest) = 64", name="ck_customer_links_digest"),
    )
    op.create_index(
        "ix_customer_links_tenant_contact", "customer_links", ["tenant_id", "contact_id"]
    )
    op.create_index("ix_customer_links_tenant_state", "customer_links", ["tenant_id", "state"])

    op.create_table(
        "many_channel_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("many_channel_id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_many_channel_claims_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_many_channel_claims_user", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("platform", "many_channel_id", name="uq_many_channel_claims_channel"),
        sa.CheckConstraint(
            "platform IN ('instagram', 'facebook', 'whatsapp')",
            name="ck_many_channel_claims_platform",
        ),
    )
    op.create_index("ix_many_channel_claims_tenant", "many_channel_claims", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("many_channel_claims")
    op.drop_table("customer_links")
