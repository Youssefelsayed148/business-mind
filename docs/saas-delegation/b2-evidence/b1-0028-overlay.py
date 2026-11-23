"""Durable Meta callback receipts and explicitly verified authorization ownership.

Revision ID: 0028_meta_compliance
Revises: 0027_saas_conn_id_lowercase
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028_meta_compliance"
down_revision = "0027_saas_conn_id_lowercase"
branch_labels = None
depends_on = None


def _present(table: str, expected: dict[str, tuple[str, int | None, bool]], unique_columns: set[tuple[str, ...]]) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    columns = {c["name"]: c for c in inspector.get_columns(table)}
    if set(columns) != set(expected):
        raise RuntimeError("Meta compliance table shape differs from migration")
    for name, (kind, length, nullable) in expected.items():
        column = columns[name]
        actual_kind = "uuid" if isinstance(column["type"], sa.Uuid) else (
            "string" if isinstance(column["type"], sa.String) else (
                "time" if isinstance(column["type"], sa.DateTime) and column["type"].timezone else "other"))
        if (actual_kind, getattr(column["type"], "length", None), column["nullable"]) != (kind, length, nullable):
            raise RuntimeError("Meta compliance column differs from migration")
    if inspector.get_pk_constraint(table).get("constrained_columns") != ["id"]:
        raise RuntimeError("Meta compliance primary key differs from migration")
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)}
    if not unique_columns <= uniques:
        raise RuntimeError("Meta compliance uniqueness differs from migration")
    if table == "meta_authorizations":
        # Runtime upserts address this constraint by name, not only by columns.
        if not any(item["name"] == "uq_meta_authorization_channel"
                   and item["column_names"] == ["platform", "channel_id"]
                   for item in inspector.get_unique_constraints(table)):
            raise RuntimeError("Meta authorization named upsert constraint differs from migration")
        foreign_keys = inspector.get_foreign_keys(table)
        if not any(fk["constrained_columns"] == ["workspace_id"] and fk["referred_table"] == "workspaces"
                   and fk["referred_columns"] == ["id"] and fk.get("options", {}).get("ondelete") == "CASCADE"
                   for fk in foreign_keys):
            raise RuntimeError("Meta authorization workspace foreign key differs from migration")
    return True


def upgrade() -> None:
    auth_shape = {
        "id": ("uuid", None, False), "app_id": ("string", 255, False),
        "subject_digest": ("string", 64, False), "workspace_id": ("uuid", None, False),
        "platform": ("string", 20, False), "channel_id": ("uuid", None, False),
        "verification_source": ("string", 80, False), "verified_at": ("time", None, False),
    }
    if not _present("meta_authorizations", auth_shape, {("platform", "channel_id")}):
        op.create_table("meta_authorizations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("app_id", sa.String(255), nullable=False),
            sa.Column("subject_digest", sa.String(64), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(20), nullable=False),
            sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("verification_source", sa.String(80), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("platform", "channel_id", name="uq_meta_authorization_channel"),
        )
    indexes = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes("meta_authorizations")}
    for name, column in (("ix_meta_authorizations_app_id", "app_id"),
                         ("ix_meta_authorizations_subject_digest", "subject_digest")):
        if name not in indexes:
            op.create_index(name, "meta_authorizations", [column])
        elif indexes[name]["column_names"] != [column] or indexes[name]["unique"]:
            raise RuntimeError("Meta authorization lookup index differs from migration")
    shape = {
        "id": ("uuid", None, False), "request_digest": ("string", 64, False),
        "app_id": ("string", 255, False), "subject_digest": ("string", 64, False),
        "kind": ("string", 20, False), "confirmation_code": ("string", 64, False),
        "status": ("string", 30, False), "created_at": ("time", None, False),
        "completed_at": ("time", None, True),
    }
    if not _present("data_deletion_requests", shape, {("request_digest",), ("confirmation_code",)}):
        op.create_table("data_deletion_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("request_digest", sa.String(64), nullable=False, unique=True),
            sa.Column("app_id", sa.String(255), nullable=False),
            sa.Column("subject_digest", sa.String(64), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("confirmation_code", sa.String(64), nullable=False, unique=True),
            sa.Column("status", sa.String(30), server_default="operator_action", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("data_deletion_requests")
    op.drop_index("ix_meta_authorizations_subject_digest", table_name="meta_authorizations")
    op.drop_index("ix_meta_authorizations_app_id", table_name="meta_authorizations")
    op.drop_table("meta_authorizations")
