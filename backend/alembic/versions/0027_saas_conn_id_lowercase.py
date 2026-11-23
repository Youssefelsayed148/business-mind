"""Normalise stored SaaS connection ids to canonical lowercase UUIDs.

Revision ID: 0027_saas_conn_id_lowercase
Revises: 0026_saas_channel_health
Create Date: 2026-10-30 00:00:00.000000
"""

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0027_saas_conn_id_lowercase"
down_revision = "0026_saas_channel_health"
branch_labels = None
depends_on = None


_TABLES = ("instagram_accounts", "whatsapp_accounts", "facebook_pages")


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        rows = bind.execute(
            sa.text(f"SELECT id, saas_connection_id FROM {table} WHERE saas_connection_id IS NOT NULL")
        ).fetchall()
        for row_id, value in rows:
            try:
                canonical = str(uuid.UUID(value.strip()))
            except ValueError:
                # Not a UUID: nothing to normalise to. Left as is so an
                # operator can see and correct it; the API now rejects it.
                continue
            if canonical != value:
                bind.execute(
                    sa.text(f"UPDATE {table} SET saas_connection_id = :v WHERE id = :id"),
                    {"v": canonical, "id": row_id},
                )


def downgrade() -> None:
    # Data-only normalisation; the original spelling is not recoverable and
    # the lowercase form is equally valid for the older schema.
    pass
