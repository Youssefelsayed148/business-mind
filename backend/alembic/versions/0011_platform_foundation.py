"""Add multi-platform foundation columns to leads and conversations

Phase 1 of the multi-platform expansion (see
docs/specs/2026-09-05-multi-platform-expansion-design.md). Adds, on both
`leads` and `conversations`:

- `platform` ('instagram' | 'whatsapp' | 'facebook'), not null, default
  'instagram', backfilled for all existing rows. Plain String(50), not a
  native Postgres ENUM — matches the existing convention used by
  `leads.lead_source` / `instagram_accounts.status` / `.business_vertical`,
  and keeps adding a new platform a plain data migration instead of an
  `ALTER TYPE ... ADD VALUE`.
- `whatsapp_account_id`, `facebook_page_id` (nullable UUID, no FK yet — the
  `whatsapp_accounts` / `facebook_pages` tables don't exist until Phase 2/3,
  which will add the FK constraint via op.create_foreign_key at that point).
- A CHECK constraint requiring exactly one of `instagram_account_id` /
  `whatsapp_account_id` / `facebook_page_id` to be set, consistent with
  `platform`.

Important: `leads.instagram_account_id` and `conversations.instagram_account_id`
stay NOT NULL in this migration (untouched, per the hard constraint that
Instagram-related columns are not modified in Phase 1). That means the CHECK
constraint below is only satisfiable today by `platform = 'instagram'` rows —
which is correct, since no whatsapp/facebook accounts exist yet. Inserting a
real 'whatsapp' or 'facebook' row will only become possible once a **Phase 2
migration relaxes `instagram_account_id` to nullable on `leads`/`conversations`**.
That relaxation is intentionally NOT done here — flagging it now so it isn't
rediscovered mid-Phase-2.

This migration does not touch `instagram_accounts`, `campaigns`, or `comments`
in any way.

Revision ID: 0011_platform_foundation
Revises: 0010_cold_dm_ai
Create Date: 2026-09-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_platform_foundation"
down_revision = "0010_cold_dm_ai"
branch_labels = None
depends_on = None

_TABLES = ("leads", "conversations")

_CHECK_SQL = (
    "(platform = 'instagram' AND instagram_account_id IS NOT NULL"
    " AND whatsapp_account_id IS NULL AND facebook_page_id IS NULL)"
    " OR (platform = 'whatsapp' AND whatsapp_account_id IS NOT NULL"
    " AND instagram_account_id IS NULL AND facebook_page_id IS NULL)"
    " OR (platform = 'facebook' AND facebook_page_id IS NOT NULL"
    " AND instagram_account_id IS NULL AND whatsapp_account_id IS NULL)"
)


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    if column_name in _columns(table):
        op.drop_column(table, column_name)


def _check_constraint_name(table: str) -> str:
    return f"ck_{table}_platform_account_fk"


def _check_constraint_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {ck["name"] for ck in sa.inspect(bind).get_check_constraints(table)}


def _create_check_constraint_if_missing(name: str, table: str, condition: str) -> None:
    # 0001_initial.py creates tables via Base.metadata.create_all() against the
    # *current* model definitions, so on a freshly-created DB this constraint
    # (declared in Lead/Conversation.__table_args__) already exists by the time
    # this migration runs. On a DB that was incrementally migrated up through
    # 0010 (i.e. every real deployment), it won't exist yet and this adds it.
    if name not in _check_constraint_names(table):
        op.create_check_constraint(name, table, condition)


def _drop_check_constraint_if_present(name: str, table: str) -> None:
    if name in _check_constraint_names(table):
        op.drop_constraint(name, table, type_="check")


def upgrade() -> None:
    for table in _TABLES:
        # platform ------------------------------------------------------
        _add_column_if_missing(
            table,
            sa.Column(
                "platform",
                sa.String(50),
                nullable=False,
                server_default="instagram",
            ),
        )
        op.execute(f"UPDATE {table} SET platform = 'instagram' WHERE platform IS NULL")

        # whatsapp_account_id / facebook_page_id (FK added in Phase 2/3) -
        _add_column_if_missing(
            table,
            sa.Column("whatsapp_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        _add_column_if_missing(
            table,
            sa.Column("facebook_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

        # exactly one platform account FK set, consistent with `platform` -
        _create_check_constraint_if_missing(_check_constraint_name(table), table, _CHECK_SQL)


def downgrade() -> None:
    for table in _TABLES:
        _drop_check_constraint_if_present(_check_constraint_name(table), table)
        _drop_column_if_present(table, "facebook_page_id")
        _drop_column_if_present(table, "whatsapp_account_id")
        _drop_column_if_present(table, "platform")
