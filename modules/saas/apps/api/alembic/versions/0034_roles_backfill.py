"""Identity: backfill memberships.org_role from the legacy role (data only).

Revision ID: 0034_roles_backfill
Revises: 0033_auth_security

Mapping (design 5.3, no silent escalation): viewer -> viewer, editor -> agent,
admin -> admin. Nobody becomes owner or manager here; Owner promotion is an
explicit staff action (D10). The legacy ``role`` column is never modified, so
the downgrade only clears what this revision filled.
"""

from alembic import op

revision = "0034_roles_backfill"
down_revision = "0033_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE memberships SET org_role = CASE role
            WHEN 'viewer' THEN 'viewer'
            WHEN 'editor' THEN 'agent'
            WHEN 'admin' THEN 'admin'
        END
        WHERE org_role IS NULL
        """
    )
    op.execute(
        """
        UPDATE invitations SET org_role = CASE role
            WHEN 'viewer' THEN 'viewer'
            WHEN 'editor' THEN 'agent'
            WHEN 'admin' THEN 'admin'
        END
        WHERE org_role IS NULL
        """
    )


def downgrade() -> None:
    # Only rows whose org_role is exactly the backfilled mapping are cleared;
    # a role assigned later (owner, manager, or a changed value) is kept.
    for table in ("memberships", "invitations"):
        op.execute(
            f"""
            UPDATE {table} SET org_role = NULL
            WHERE (role, org_role) IN (('viewer','viewer'),('editor','agent'),('admin','admin'))
            """
        )
