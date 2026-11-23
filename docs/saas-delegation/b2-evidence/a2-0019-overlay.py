"""Add per-account WhatsApp outreach settings.

Revision ID: 0019_whatsapp_outreach_settings
Revises: 0018_whatsapp_outreach
Create Date: 2026-10-02 00:00:00.000000
"""

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_whatsapp_outreach_settings"
down_revision = "0018_whatsapp_outreach"
branch_labels = None
depends_on = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("ctwa_counts_as_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transactional_utility_attested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("opt_out_keywords", postgresql.JSONB(), nullable=True),
        sa.Column("opt_in_keywords", postgresql.JSONB(), nullable=True),
        sa.Column("outreach_daily_cap", sa.Integer(), nullable=False, server_default="250"),
    ]


_CHECKS = {
    "ck_whatsapp_accounts_opt_out_keywords_array":
        "opt_out_keywords IS NULL OR jsonb_typeof(opt_out_keywords) = 'array'",
    "ck_whatsapp_accounts_opt_in_keywords_array":
        "opt_in_keywords IS NULL OR jsonb_typeof(opt_in_keywords) = 'array'",
    "ck_whatsapp_accounts_outreach_daily_cap": "outreach_daily_cap > 0",
}


def _normalise_expression(value: str) -> str:
    # PostgreSQL's deparser adds parentheses and a text cast to the array
    # literal. Ignore only those presentation differences, not operators.
    # Preserve SQL string literals byte-for-byte: 'ARRAY' and 'array' are
    # different values. Only fold keyword case/casts outside quoted literals.
    parts = re.split(r"('(?:''|[^'])*')", value)
    return "".join(
        part if index % 2 else "".join(part.lower().replace("::text", "").split()).replace("(", "").replace(")", "")
        for index, part in enumerate(parts)
    )


def _normalise_default(value: str | None) -> str | None:
    if value is None:
        return None
    # Only defaults for these boolean/integer columns are compared here.
    return value.strip().replace("(", "").replace(")", "").replace("::boolean", "").replace("::integer", "").strip("'")


def upgrade() -> None:
    # 0001 bootstraps from current metadata, so these objects can already
    # exist. Validate all existing objects before issuing any schema change.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"]: column for column in inspector.get_columns("whatsapp_accounts")}
    checks = {check["name"]: check for check in inspector.get_check_constraints("whatsapp_accounts")}
    columns = _columns()
    for column in columns:
        current = existing.get(column.name)
        if current is None:
            continue
        expected_default = str(column.server_default.arg) if column.server_default is not None else None
        if (
            current["type"].compile(dialect=bind.dialect) != column.type.compile(dialect=bind.dialect)
            or current["nullable"] != column.nullable
            or _normalise_default(current["default"]) != _normalise_default(expected_default)
        ):
            raise RuntimeError(f"0019 incompatible whatsapp_accounts column: {column.name}")
    for name, expression in _CHECKS.items():
        current = checks.get(name)
        if current is not None and _normalise_expression(current["sqltext"]) != _normalise_expression(expression):
            raise RuntimeError(f"0019 incompatible whatsapp_accounts constraint: {name}")
    for column in columns:
        if column.name not in existing:
            op.add_column("whatsapp_accounts", column)
    for name, expression in _CHECKS.items():
        if name not in checks:
            op.create_check_constraint(name, "whatsapp_accounts", expression)


def downgrade() -> None:
    op.drop_constraint(
        "ck_whatsapp_accounts_outreach_daily_cap",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_whatsapp_accounts_opt_in_keywords_array",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_whatsapp_accounts_opt_out_keywords_array",
        "whatsapp_accounts",
        type_="check",
    )
    op.drop_column("whatsapp_accounts", "outreach_daily_cap")
    op.drop_column("whatsapp_accounts", "opt_in_keywords")
    op.drop_column("whatsapp_accounts", "opt_out_keywords")
    op.drop_column("whatsapp_accounts", "transactional_utility_attested")
    op.drop_column("whatsapp_accounts", "ctwa_counts_as_consent")
