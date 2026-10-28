"""Typed grant proof and durable two-phase account erasure.

Revision ID: 0030_meta_account_erasure
Revises: 0029_hash_processed_event_keys
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0030_meta_account_erasure"
down_revision = "0029_hash_processed_event_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meta_authorizations", sa.Column("subject_namespace", sa.String(30), nullable=False, server_default="unresolved"))
    op.add_column("meta_authorizations", sa.Column("subject_encrypted", sa.Text(), nullable=True))
    op.add_column("meta_authorizations", sa.Column("provider_context_encrypted", sa.Text(), nullable=True))
    op.create_check_constraint("ck_meta_authorizations_subject_namespace", "meta_authorizations", "subject_namespace IN ('app_user', 'business_system_user', 'unresolved')")
    op.create_index("ix_meta_authorizations_app_namespace_digest", "meta_authorizations", ["app_id", "subject_namespace", "subject_digest"])
    op.create_table("account_erasure_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("channel_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("event_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("identity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("local_erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "platform", "channel_id", name="uq_account_erasure_scope"),
        sa.UniqueConstraint("request_id", name="uq_account_erasure_request"),
        sa.CheckConstraint("platform IN ('instagram', 'facebook', 'whatsapp')", name="ck_account_erasure_platform"),
        sa.CheckConstraint("state IN ('pending', 'waiting_remote_acceptance', 'local_erased', 'operator_action')", name="ck_account_erasure_state"),
        sa.CheckConstraint("error_code IS NULL OR error_code IN ('missing_signing_configuration', 'unknown_remote_scope', 'remote_not_accepted', 'channel_missing', 'audit_scope_unproven')", name="ck_account_erasure_error"),
        sa.CheckConstraint("identity_count >= 0 AND accepted_count >= 0 AND accepted_count <= identity_count", name="ck_account_erasure_counts"),
    )


def downgrade() -> None:
    # Accepted is not completed: even a locally erased job needs verified remote
    # cleanup before its durable ledger can be removed.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM account_erasure_jobs WHERE state != 'local_erased' OR remote_verified_at IS NULL)")).scalar():
        raise RuntimeError("Resolve and verify account erasure jobs before downgrade")
    op.drop_table("account_erasure_jobs")
    op.drop_index("ix_meta_authorizations_app_namespace_digest", table_name="meta_authorizations")
    op.drop_constraint("ck_meta_authorizations_subject_namespace", "meta_authorizations", type_="check")
    op.drop_column("meta_authorizations", "provider_context_encrypted")
    op.drop_column("meta_authorizations", "subject_encrypted")
    op.drop_column("meta_authorizations", "subject_namespace")
