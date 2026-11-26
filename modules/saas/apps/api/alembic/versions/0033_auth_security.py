"""Identity: auth security storage (columns and tables only, no behavior).

Revision ID: 0033_auth_security
Revises: 0032_identity_orgs

Phase 3 design sections 3.1, 6.3 to 6.5 and 8.1. The MFA, reset and session
logic arrives in a later change; this revision only adds storage.
"""

import sqlalchemy as sa

from alembic import op

revision = "0033_auth_security"
down_revision = "0032_identity_orgs"
branch_labels = None
depends_on = None

ORG_ROLES = "'owner','admin','manager','agent','viewer'"


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("locale", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("legacy_many_user_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_legacy_many_user_id", "users", ["legacy_many_user_id"])
    op.create_check_constraint("ck_users_failed_login_count", "users", "failed_login_count >= 0")

    op.add_column("sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("ip_hash", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("user_agent", sa.Text(), nullable=True))

    op.add_column("invitations", sa.Column("org_role", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_invitations_org_role", "invitations", f"org_role IS NULL OR org_role IN ({ORG_ROLES})"
    )
    op.add_column(
        "invitations",
        sa.Column("location_scope", sa.Text(), nullable=False, server_default=sa.text("'all'")),
    )
    op.create_check_constraint(
        "ck_invitations_location_scope", "invitations", "location_scope IN ('all','limited')"
    )
    op.add_column(
        "invitations",
        sa.Column("new_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "user_mfa",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        # Encrypted at rest with an environment key; never stored in clear.
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_key_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "user_recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_recovery_codes_user", "user_recovery_codes", ["user_id"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Only the SHA-256 of the one-time token is stored.
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_password_reset_tokens_user", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
    op.drop_table("user_recovery_codes")
    op.drop_table("user_mfa")
    op.drop_column("invitations", "new_account")
    op.drop_constraint("ck_invitations_location_scope", "invitations", type_="check")
    op.drop_column("invitations", "location_scope")
    op.drop_constraint("ck_invitations_org_role", "invitations", type_="check")
    op.drop_column("invitations", "org_role")
    op.drop_column("sessions", "user_agent")
    op.drop_column("sessions", "ip_hash")
    op.drop_column("sessions", "last_seen_at")
    op.drop_constraint("ck_users_failed_login_count", "users", type_="check")
    op.drop_constraint("uq_users_legacy_many_user_id", "users", type_="unique")
    for column in (
        "last_login_at",
        "legacy_many_user_id",
        "locked_until",
        "failed_login_count",
        "mfa_enrolled_at",
        "locale",
        "display_name",
    ):
        op.drop_column("users", column)
