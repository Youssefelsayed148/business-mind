from __future__ import annotations

import ast
import datetime
import os
from pathlib import Path
import subprocess
import uuid

import psycopg
from psycopg import errors
import pytest
from sqlalchemy.engine import make_url

from app.core.config import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_DIR / "alembic" / "versions" / "0018_whatsapp_outreach.py"
NEW_TABLES = {
    "whatsapp_contacts",
    "whatsapp_consent_events",
    "whatsapp_templates",
    "whatsapp_campaigns",
    "whatsapp_campaign_recipients",
}
ACCOUNT_COLUMNS = {
    "quality_rating",
    "messaging_limit_tier",
    "outreach_paused",
    "outreach_paused_reason",
    "health_checked_at",
}
SETTINGS_COLUMNS = {
    "ctwa_counts_as_consent",
    "transactional_utility_attested",
    "opt_out_keywords",
    "opt_in_keywords",
    "outreach_daily_cap",
}
SETTINGS_CONSTRAINTS = {
    "ck_whatsapp_accounts_opt_out_keywords_array",
    "ck_whatsapp_accounts_opt_in_keywords_array",
    "ck_whatsapp_accounts_outreach_daily_cap",
}
MESSAGE_COLUMNS = {
    "whatsapp_campaign_id",
    "whatsapp_template_id",
    "delivered_at",
    "read_at",
}


def _psycopg_dsn(url: str) -> str:
    parsed = make_url(url).set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "DATABASE_URL": database_url}
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        ["alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _migration_sql_constant(name: str) -> str:
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                value = ast.literal_eval(node.value)
                assert isinstance(value, str)
                return value
    raise AssertionError(f"Migration SQL constant {name} not found")


def _strip_0018_shape(conn: psycopg.Connection) -> None:
    """Undo live-model create_all effects to reproduce a real 0017 database."""
    conn.execute(
        "ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_messages_whatsapp_campaign_id"
    )
    conn.execute(
        "ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_messages_whatsapp_template_id"
    )
    for column in MESSAGE_COLUMNS:
        conn.execute(f'ALTER TABLE messages DROP COLUMN IF EXISTS "{column}"')

    conn.execute(
        "ALTER TABLE whatsapp_accounts "
        "DROP CONSTRAINT IF EXISTS ck_whatsapp_accounts_quality_rating"
    )
    for constraint in SETTINGS_CONSTRAINTS:
        conn.execute(
            f'ALTER TABLE whatsapp_accounts DROP CONSTRAINT IF EXISTS "{constraint}"'
        )
    for column in ACCOUNT_COLUMNS | SETTINGS_COLUMNS:
        conn.execute(f'ALTER TABLE whatsapp_accounts DROP COLUMN IF EXISTS "{column}"')

    for table in (
        "whatsapp_campaign_recipients",
        "whatsapp_campaigns",
        "whatsapp_templates",
        "whatsapp_consent_events",
        "whatsapp_contacts",
    ):
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')


def _seed_backfill_cases(conn: psycopg.Connection) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    workspace_id = uuid.uuid4()
    account_id = uuid.uuid4()
    first_valid_lead_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO workspaces (id, name, slug) VALUES (%s, %s, %s)",
        (workspace_id, "Outreach migration test", f"outreach-{workspace_id}"),
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

    values = (
        (first_valid_lead_id, "16315551234"),
        (uuid.uuid4(), "+1 (631) 555-1234"),
        (uuid.uuid4(), "1-631-555-1234"),
        (uuid.uuid4(), ""),
        (uuid.uuid4(), "123"),
        (uuid.uuid4(), "1234567890123456789012345"),
    )
    start = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    for index, (lead_id, ig_user_id) in enumerate(values):
        timestamp = start + datetime.timedelta(minutes=index)
        conn.execute(
            """
            INSERT INTO leads
                (id, workspace_id, platform, whatsapp_account_id, ig_user_id,
                 ig_username, lead_source, last_seen_at, status, created_at)
            VALUES (%s, %s, 'whatsapp', %s, %s, %s, 'cold_dm', %s, 'new', %s)
            """,
            (
                lead_id,
                workspace_id,
                account_id,
                ig_user_id,
                f"Fixture {index}",
                timestamp,
                timestamp,
            ),
        )
    return workspace_id, account_id, first_valid_lead_id


@pytest.fixture(scope="module")
def migration_database():
    source_url = make_url(settings.DATABASE_URL)
    database_name = f"test_whatsapp_outreach_{uuid.uuid4().hex[:12]}"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_dsn = _psycopg_dsn(admin_url.render_as_string(hide_password=False))
    target_dsn = _psycopg_dsn(target_url.render_as_string(hide_password=False))
    target_sa_url = target_url.render_as_string(hide_password=False)

    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database_name}"')

    try:
        _run_alembic(target_sa_url, "upgrade", "0017_workspace_membership")
        with psycopg.connect(target_dsn, autocommit=True) as conn:
            _strip_0018_shape(conn)
            workspace_id, account_id, first_valid_lead_id = _seed_backfill_cases(conn)
        yield {
            "database_url": target_sa_url,
            "dsn": target_dsn,
            "workspace_id": workspace_id,
            "account_id": account_id,
            "first_valid_lead_id": first_valid_lead_id,
        }
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


def test_0018_constraints_backfill_idempotency_and_round_trip(migration_database):
    database_url = migration_database["database_url"]
    dsn = migration_database["dsn"]
    account_id = migration_database["account_id"]
    workspace_id = migration_database["workspace_id"]
    first_valid_lead_id = migration_database["first_valid_lead_id"]

    upgrade = _run_alembic(database_url, "upgrade", "0018_whatsapp_outreach")
    migration_output = upgrade.stdout + upgrade.stderr
    assert "leads=6 eligible=3 inserted=1" in migration_output
    assert "invalid_skipped=3 duplicate_candidates=2 already_present=0" in migration_output
    assert "reason=empty count=1" in migration_output
    assert "reason=too_short count=1" in migration_output
    assert "reason=too_long count=1" in migration_output
    assert "masked_samples=[***123]" in migration_output
    assert "masked_samples=[***2345]" in migration_output
    assert "1234567890123456789012345" not in migration_output

    with psycopg.connect(dsn, autocommit=True) as conn:
        contacts = list(
            conn.execute(
                """
                SELECT wa_id, lead_id, marketing_consent, last_inbound_at
                FROM whatsapp_contacts
                ORDER BY wa_id
                """
            )
        )
        assert contacts == [
            (
                "16315551234",
                first_valid_lead_id,
                "unknown",
                datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc),
            )
        ]
        assert conn.execute(
            "SELECT count(*) FROM whatsapp_contacts WHERE marketing_consent = 'opted_in'"
        ).fetchone()[0] == 0

        constraint_names = {
            row[0]
            for row in conn.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid IN (
                    'whatsapp_contacts'::regclass,
                    'whatsapp_consent_events'::regclass,
                    'whatsapp_templates'::regclass,
                    'whatsapp_campaigns'::regclass,
                    'whatsapp_campaign_recipients'::regclass,
                    'whatsapp_accounts'::regclass,
                    'messages'::regclass
                )
                """
            )
        }
        assert {
            "uq_whatsapp_contacts_account_wa_id",
            "ck_whatsapp_contacts_marketing_consent",
            "ck_whatsapp_contacts_wa_id",
            "fk_messages_whatsapp_campaign_id",
            "fk_messages_whatsapp_template_id",
            "ck_whatsapp_accounts_quality_rating",
        } <= constraint_names

        index_names = {
            row[0]
            for row in conn.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename IN (
                      'whatsapp_contacts',
                      'whatsapp_consent_events',
                      'whatsapp_campaign_recipients'
                  )
                """
            )
        }
        assert {
            "ix_whatsapp_contacts_workspace_consent",
            "ix_whatsapp_consent_events_contact_created",
            "ix_whatsapp_campaign_recipients_campaign_status",
        } <= index_names

        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO whatsapp_contacts
                    (workspace_id, whatsapp_account_id, wa_id)
                VALUES (%s, %s, '16315551234')
                """,
                (workspace_id, account_id),
            )
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO whatsapp_contacts
                    (workspace_id, whatsapp_account_id, wa_id, marketing_consent)
                VALUES (%s, %s, '16315550000', 'implied')
                """,
                (workspace_id, account_id),
            )
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO whatsapp_contacts
                    (workspace_id, whatsapp_account_id, wa_id)
                VALUES (%s, %s, '+1 (631) 555-9999')
                """,
                (workspace_id, account_id),
            )

        backfill_sql = _migration_sql_constant("_BACKFILL_SQL")
        inserted_again = conn.execute(backfill_sql).fetchone()[0]
        assert inserted_again == 0
        assert conn.execute("SELECT count(*) FROM whatsapp_contacts").fetchone()[0] == 1

    downgrade = _run_alembic(database_url, "downgrade", "-1")
    assert downgrade.returncode == 0
    current = _run_alembic(database_url, "current")
    assert "0017_workspace_membership" in current.stdout

    with psycopg.connect(dsn) as conn:
        remaining_tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        assert not (remaining_tables & NEW_TABLES)

        account_columns = {
            row[0]
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'whatsapp_accounts'
                """
            )
        }
        message_columns = {
            row[0]
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'messages'
                """
            )
        }
        assert not (account_columns & ACCOUNT_COLUMNS)
        assert not (message_columns & MESSAGE_COLUMNS)

        leftover_names = {
            row[0]
            for row in conn.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conname LIKE '%whatsapp_contact%'
                   OR conname LIKE '%whatsapp_template%'
                   OR conname LIKE '%whatsapp_campaign%'
                UNION ALL
                SELECT indexname FROM pg_indexes
                WHERE indexname LIKE '%whatsapp_contact%'
                   OR indexname LIKE '%whatsapp_template%'
                   OR indexname LIKE '%whatsapp_campaign%'
                """
            )
        }
        assert not leftover_names

    second_upgrade = _run_alembic(
        database_url, "upgrade", "0018_whatsapp_outreach"
    )
    assert second_upgrade.returncode == 0
    current = _run_alembic(database_url, "current")
    assert "0018_whatsapp_outreach" in current.stdout
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM whatsapp_contacts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM whatsapp_contacts WHERE marketing_consent = 'opted_in'"
        ).fetchone()[0] == 0

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM leads WHERE id = %s", (first_valid_lead_id,))
        contact = conn.execute(
            "SELECT lead_id, wa_id FROM whatsapp_contacts WHERE whatsapp_account_id = %s",
            (account_id,),
        ).fetchone()
        assert contact == (None, "16315551234")
