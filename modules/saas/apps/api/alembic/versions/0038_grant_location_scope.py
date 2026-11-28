"""Phase 6G: agency_grants.location_scope (docs/PHASE-3-REVIEW.md, open item 2).

Revision ID: 0038_grant_location_scope
Revises: 0037_erasure_cases

A grant's reach was "all locations" whenever it had no location rows, so deleting the last
location of a limited grant would have widened it. The scope is now stored (as on
memberships): ``limited`` with no rows means no access. Additive; existing grants that have
location rows become ``limited``, all others stay ``all``. The downgrade drops the column.
"""

import sqlalchemy as sa

from alembic import op

revision = "0038_grant_location_scope"
down_revision = "0037_erasure_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agency_grants",
        sa.Column("location_scope", sa.Text(), nullable=False, server_default=sa.text("'all'")),
    )
    op.create_check_constraint(
        "ck_agency_grants_location_scope", "agency_grants", "location_scope IN ('all','limited')"
    )
    op.execute(
        "UPDATE agency_grants SET location_scope = 'limited' "
        "WHERE id IN (SELECT grant_id FROM agency_grant_locations)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_agency_grants_location_scope", "agency_grants", type_="check")
    op.drop_column("agency_grants", "location_scope")
