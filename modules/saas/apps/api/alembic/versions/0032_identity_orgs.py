"""Identity: organization mapping, locations, agencies (additive only).

Revision ID: 0032_identity_orgs
Revises: 0031_contact_erasure

Phase 3 design sections 4 and 8.1. Nothing existing is altered except new
nullable columns or columns with a constant default, so the legacy role
checks keep working unchanged.
"""

import sqlalchemy as sa

from alembic import op

revision = "0032_identity_orgs"
down_revision = "0031_contact_erasure"
branch_labels = None
depends_on = None

ORG_ROLES = "'owner','admin','manager','agent','viewer'"
LOCATION_TABLES = ("channel_connections", "contacts", "sources")


def upgrade() -> None:
    op.add_column("tenants", sa.Column("many_workspace_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_tenants_many_workspace_id", "tenants", ["many_workspace_id"])

    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_locations_status"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_locations_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_locations_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_locations_tenant_name"),
    )

    # org_role is the new role vocabulary; the legacy role column stays
    # authoritative while the identity flag is off (0034 backfills org_role).
    op.add_column("memberships", sa.Column("org_role", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_memberships_org_role", "memberships", f"org_role IS NULL OR org_role IN ({ORG_ROLES})"
    )
    op.add_column(
        "memberships",
        sa.Column("location_scope", sa.Text(), nullable=False, server_default=sa.text("'all'")),
    )
    op.create_check_constraint(
        "ck_memberships_location_scope", "memberships", "location_scope IN ('all','limited')"
    )

    op.create_table(
        "membership_locations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "location_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_membership_locations_member",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_membership_locations_location",
            ondelete="CASCADE",
        ),
    )

    for table in LOCATION_TABLES:
        op.add_column(table, sa.Column("location_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_location",
            table,
            "locations",
            ["tenant_id", "location_id"],
            ["tenant_id", "id"],
        )
        op.create_index(f"ix_{table}_location", table, ["tenant_id", "location_id"])

    op.create_table(
        "agencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','suspended')", name="ck_agencies_status"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_agencies_name"),
    )
    op.create_table(
        "agency_memberships",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'agency_member'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("agency_id", "user_id"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role IN ('agency_admin','agency_member')", name="ck_agency_memberships_role"
        ),
    )
    op.create_index("ix_agency_memberships_user", "agency_memberships", ["user_id"])
    op.create_table(
        "agency_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        # A cap is an ordinary role below Owner; never Owner (design 4.3).
        sa.Column("role_cap", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "role_cap IN ('admin','manager','agent','viewer')", name="ck_agency_grants_role_cap"
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_agency_grants_status"),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_agency_grants_revoked"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_agency_grants_id_tenant"),
    )
    op.create_index(
        "uq_agency_grants_active",
        "agency_grants",
        ["agency_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_agency_grants_tenant", "agency_grants", ["tenant_id"])
    op.create_table(
        "agency_grant_assignees",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("grant_id", "user_id"),
        sa.ForeignKeyConstraint(["grant_id"], ["agency_grants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agency_grant_assignees_user", "agency_grant_assignees", ["user_id"])
    op.create_table(
        "agency_grant_locations",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("grant_id", "location_id"),
        sa.ForeignKeyConstraint(
            ["grant_id", "tenant_id"],
            ["agency_grants.id", "agency_grants.tenant_id"],
            name="fk_agency_grant_locations_grant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_agency_grant_locations_location",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("agency_grant_locations")
    op.drop_table("agency_grant_assignees")
    op.drop_table("agency_grants")
    op.drop_table("agency_memberships")
    op.drop_table("agencies")
    for table in reversed(LOCATION_TABLES):
        op.drop_index(f"ix_{table}_location", table_name=table)
        op.drop_constraint(f"fk_{table}_location", table, type_="foreignkey")
        op.drop_column(table, "location_id")
    op.drop_table("membership_locations")
    op.drop_constraint("ck_memberships_location_scope", "memberships", type_="check")
    op.drop_column("memberships", "location_scope")
    op.drop_constraint("ck_memberships_org_role", "memberships", type_="check")
    op.drop_column("memberships", "org_role")
    op.drop_table("locations")
    op.drop_constraint("uq_tenants_many_workspace_id", "tenants", type_="unique")
    op.drop_column("tenants", "many_workspace_id")
