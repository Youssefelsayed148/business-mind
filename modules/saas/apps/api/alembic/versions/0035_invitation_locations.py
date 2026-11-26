"""Identity: the locations an invitation grants when its scope is ``limited`` (design 4.2).

Revision ID: 0035_invitation_locations
Revises: 0034_roles_backfill

Additive and unused until IDENTITY_V2_ENABLED is on and a limited invitation is created.
The downgrade drops only this table.
"""

import sqlalchemy as sa

from alembic import op

revision = "0035_invitation_locations"
down_revision = "0034_roles_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitation_locations",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("invitation_id", "location_id"),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["invitations.id"],
            name="fk_invitation_locations_invitation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_invitation_locations_location",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("invitation_locations")
