"""Add role defaults and audit logs

Revision ID: 0004_roles_and_audit_logs
Revises: 0003_follow_prompt_flow
Create Date: 2026-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_roles_and_audit_logs"
down_revision = "0003_follow_prompt_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "audit_logs" not in inspector.get_table_names():
        op.create_table(
            "audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("actor_email", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("entity_type", sa.String(length=100), nullable=True),
            sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("entity_name", sa.String(length=255), nullable=True),
            sa.Column("severity", sa.String(length=50), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" in user_columns:
        op.execute("UPDATE users SET role = lower(role) WHERE role IS NOT NULL")
        op.execute("UPDATE users SET role = 'viewer' WHERE role IS NULL OR role = 'user'")
        op.alter_column("users", "role", server_default="admin")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "audit_logs" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
        if "ix_audit_logs_action" in indexes:
            op.drop_index("ix_audit_logs_action", table_name="audit_logs")
        op.drop_table("audit_logs")
    if "role" in {column["name"] for column in inspector.get_columns("users")}:
        op.alter_column("users", "role", server_default="user")
