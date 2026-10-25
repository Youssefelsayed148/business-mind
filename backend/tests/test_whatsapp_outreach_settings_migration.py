from __future__ import annotations

import os
from pathlib import Path
import subprocess
import uuid

import psycopg
from psycopg import errors
import pytest
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.models.whatsapp_account import WhatsappAccount


BACKEND_DIR = Path(__file__).resolve().parents[1]
NEW_COLUMNS = {
    "ctwa_counts_as_consent",
    "transactional_utility_attested",
    "opt_out_keywords",
    "opt_in_keywords",
    "outreach_daily_cap",
}
NEW_CONSTRAINTS = {
    "ck_whatsapp_accounts_opt_out_keywords_array",
    "ck_whatsapp_accounts_opt_in_keywords_array",
    "ck_whatsapp_accounts_outreach_daily_cap",
}


def _psycopg_dsn(url: str) -> str:
    parsed = make_url(url).set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "DATABASE_URL": database_url}
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        ["alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _strip_0019_shape(conn: psycopg.Connection) -> None:
    """Undo current-model create_all effects to reproduce a real 0018 database."""
    for constraint in NEW_CONSTRAINTS:
        conn.execute(
            f'ALTER TABLE whatsapp_accounts DROP CONSTRAINT IF EXISTS "{constraint}"'
        )
    for column in NEW_COLUMNS:
        conn.execute(
            f'ALTER TABLE whatsapp_accounts DROP COLUMN IF EXISTS "{column}"'
        )


@pytest.fixture(scope="module")
def migration_database():
    source_url = make_url(settings.DATABASE_URL)
    database_name = f"test_whatsapp_settings_{uuid.uuid4().hex[:12]}"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_dsn = _psycopg_dsn(admin_url.render_as_string(hide_password=False))
    target_dsn = _psycopg_dsn(target_url.render_as_string(hide_password=False))
    target_sa_url = target_url.render_as_string(hide_password=False)

    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database_name}"')

    try:
        _run_alembic(target_sa_url, "upgrade", "0018_whatsapp_outreach")
        with psycopg.connect(target_dsn, autocommit=True) as conn:
            _strip_0019_shape(conn)
            columns, constraints = _account_shape(conn)
            assert not (NEW_COLUMNS & columns)
            assert not (NEW_CONSTRAINTS & constraints)
        yield {"database_url": target_sa_url, "dsn": target_dsn}
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


def _account_shape(conn: psycopg.Connection) -> tuple[set[str], set[str]]:
    columns = {
        row[0]
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'whatsapp_accounts'
            """
        )
    }
    constraints = {
        row[0]
        for row in conn.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'whatsapp_accounts'::regclass
            """
        )
    }
    return columns, constraints


def test_whatsapp_outreach_settings_model_defaults():
    columns = WhatsappAccount.__table__.c
    assert columns.ctwa_counts_as_consent.default.arg is False
    assert columns.transactional_utility_attested.default.arg is False
    assert columns.opt_out_keywords.default is None
    assert columns.opt_in_keywords.default is None
    assert columns.outreach_daily_cap.default.arg == 250

    assert str(columns.ctwa_counts_as_consent.server_default.arg) == "false"
    assert str(columns.transactional_utility_attested.server_default.arg) == "false"
    assert str(columns.outreach_daily_cap.server_default.arg) == "250"
    assert columns.opt_out_keywords.server_default is None
    assert columns.opt_in_keywords.server_default is None


def test_0019_defaults_constraints_and_round_trip(migration_database):
    database_url = migration_database["database_url"]
    dsn = migration_database["dsn"]

    _run_alembic(database_url, "upgrade", "head")
    current = _run_alembic(database_url, "current")
    assert "0026_saas_channel_health" in current.stdout

    with psycopg.connect(dsn, autocommit=True) as conn:
        columns, constraints = _account_shape(conn)
        assert NEW_COLUMNS <= columns
        assert NEW_CONSTRAINTS <= constraints

        workspace_id = uuid.uuid4()
        account_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO workspaces (id, name, slug) VALUES (%s, %s, %s)",
            (workspace_id, "Outreach settings test", f"settings-{workspace_id}"),
        )
        conn.execute(
            """
            INSERT INTO whatsapp_accounts
                (id, workspace_id, phone_number_id, status, business_vertical,
                 ai_enabled, ai_daily_message_cap, ai_handoff_after_turns,
                 ai_messages_sent_today)
            VALUES (%s, %s, %s, 'connected', 'general', false, 100, 8, 0)
            """,
            (account_id, workspace_id, f"phone-{account_id}"),
        )
        defaults = conn.execute(
            """
            SELECT ctwa_counts_as_consent, transactional_utility_attested,
                   opt_out_keywords, opt_in_keywords, outreach_daily_cap
            FROM whatsapp_accounts WHERE id = %s
            """,
            (account_id,),
        ).fetchone()
        assert defaults == (False, False, None, None, 250)

        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "UPDATE whatsapp_accounts SET outreach_daily_cap = 0 WHERE id = %s",
                (account_id,),
            )
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "UPDATE whatsapp_accounts SET opt_out_keywords = '{}'::jsonb WHERE id = %s",
                (account_id,),
            )
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "UPDATE whatsapp_accounts SET opt_in_keywords = '\"START\"'::jsonb WHERE id = %s",
                (account_id,),
            )

    _run_alembic(database_url, "downgrade", "0018_whatsapp_outreach")
    current = _run_alembic(database_url, "current")
    assert "0018_whatsapp_outreach" in current.stdout
    with psycopg.connect(dsn) as conn:
        columns, constraints = _account_shape(conn)
        assert not (NEW_COLUMNS & columns)
        assert not (NEW_CONSTRAINTS & constraints)

    _run_alembic(database_url, "upgrade", "head")
    current = _run_alembic(database_url, "current")
    assert "0026_saas_channel_health" in current.stdout
    with psycopg.connect(dsn) as conn:
        columns, constraints = _account_shape(conn)
        assert NEW_COLUMNS <= columns
        assert NEW_CONSTRAINTS <= constraints
