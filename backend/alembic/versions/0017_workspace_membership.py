"""Add user_workspace_memberships — workspace-scoped multi-tenancy (phase 1:
WhatsApp + Facebook only)

Adds a single new table, `user_workspace_memberships`, linking users to the
workspaces they belong to, with a per-membership role reusing the exact role
strings from app/roles.py (owner/admin/operator/viewer). Purely additive —
no existing table is modified in any way, and `users.role` keeps its current
meaning for every route that is not yet workspace-scoped (Instagram and the
other global-role routes keep gating off `users.role` exactly as today).

Data migration: every existing user gets one membership row pointing at the
workspace with slug='default', carrying that user's current `users.role`
value (normalized the same way app.roles.normalize_role does: lowercased,
unknown/NULL values fall back to 'viewer'). This keeps the deploy a strict
no-op behavior change — every current user keeps exactly the access they
have today.

Note: revision numbering follows the file name 0017_*; the previous head at
the time of writing is 0015_conv_cold_dm_uniq (no 0016 migration exists),
so down_revision points at 0015.

Revision ID: 0017_workspace_membership
Revises: 0015_conv_cold_dm_uniq
Create Date: 2026-09-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_workspace_membership"
down_revision = "0015_conv_cold_dm_uniq"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "user_workspace_memberships" not in _table_names():
        op.create_table(
            "user_workspace_memberships",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(50), nullable=False, server_default="operator"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "user_id", "workspace_id", name="uq_user_workspace_membership"
            ),
        )
        op.create_index(
            "ix_user_workspace_memberships_user_id",
            "user_workspace_memberships",
            ["user_id"],
        )

    # Data migration: one membership per existing user, pointing at the
    # 'default' workspace, role copied from users.role (normalized the same
    # way normalize_role() does). NOT EXISTS guard keeps the INSERT idempotent.
    op.execute(
        """
        INSERT INTO user_workspace_memberships
            (id, user_id, workspace_id, role, created_at, updated_at)
        SELECT gen_random_uuid(), u.id, w.id,
               CASE
                   WHEN lower(u.role) IN ('owner', 'admin', 'operator', 'viewer')
                       THEN lower(u.role)
                   ELSE 'viewer'
               END,
               now(), now()
        FROM users u
        JOIN workspaces w ON w.slug = 'default'
        WHERE NOT EXISTS (
            SELECT 1
            FROM user_workspace_memberships m
            WHERE m.user_id = u.id AND m.workspace_id = w.id
        )
        """
    )


def downgrade() -> None:
    if "user_workspace_memberships" in _table_names():
        op.drop_index(
            "ix_user_workspace_memberships_user_id", table_name="user_workspace_memberships"
        )
        op.drop_table("user_workspace_memberships")
