"""Initial migration

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.base import Base
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import UUID
    # This historical migration bootstraps current metadata. Preserve the
    # pre-0030 authorization shape so 0028's fail-closed schema validation and
    # the actual 0030 transition run on empty databases too.
    bootstrap = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in {"account_erasure_jobs", "meta_authorizations"}:
            table.to_metadata(bootstrap)
    sa.Table("meta_authorizations", bootstrap,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("app_id", sa.String(255), nullable=False, index=True),
        sa.Column("subject_digest", sa.String(64), nullable=False, index=True),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), nullable=False),
        sa.Column("verification_source", sa.String(80), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform", "channel_id", name="uq_meta_authorization_channel"),
    )
    bootstrap.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db.base import Base
    Base.metadata.drop_all(bind=op.get_bind())
