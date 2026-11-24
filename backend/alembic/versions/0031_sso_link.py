"""Additive SSO link columns (identity design 8.1).

Revision ID: 0031_sso_link
Revises: 0030_meta_account_erasure

Adds nullable/defaulted columns only; no existing column changes, no table is
rewritten, no Instagram table is touched. downgrade() drops exactly what this
revision added. channel_location_map from the design is deferred: nothing in
the first SSO release reads it.

0001_initial bootstraps tables from the *current* models, so on an empty
database these columns already exist when this revision runs; every step is
therefore guarded (same pattern as 0011 and 0014).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0031_sso_link"
down_revision = "0030_meta_account_erasure"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _unique_names(table: str) -> set[str]:
    return {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _add_unique(name: str, table: str, column: str) -> None:
    if name not in _unique_names(table):
        op.create_unique_constraint(name, table, [column])


def _drop_unique(name: str, table: str) -> None:
    if name in _unique_names(table):
        op.drop_constraint(name, table, type_="unique")


def _drop_column(table: str, column: str) -> None:
    if column in _columns(table):
        op.drop_column(table, column)


def upgrade() -> None:
    _add_column("users", sa.Column("sso_subject", pg.UUID(as_uuid=True), nullable=True))
    _add_column("users", sa.Column("auth_source", sa.String(20), nullable=False, server_default="local"))
    _add_unique("uq_users_sso_subject", "users", "sso_subject")
    _add_column("user_workspace_memberships", sa.Column("source", sa.String(20), nullable=False, server_default="local"))
    _add_column("workspaces", sa.Column("saas_tenant_id", pg.UUID(as_uuid=True), nullable=True))
    _add_unique("uq_workspaces_saas_tenant_id", "workspaces", "saas_tenant_id")


def downgrade() -> None:
    _drop_unique("uq_workspaces_saas_tenant_id", "workspaces")
    _drop_column("workspaces", "saas_tenant_id")
    _drop_column("user_workspace_memberships", "source")
    _drop_unique("uq_users_sso_subject", "users")
    _drop_column("users", "auth_source")
    _drop_column("users", "sso_subject")
