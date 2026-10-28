"""Real Alembic upgrades in fresh disposable databases, without stamps."""
import os
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url

from tests.test_whatsapp_outreach_settings_migration import _psycopg_dsn, _run_alembic


@contextmanager
def _database():
    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert os.environ["APP_ENV"] == "test"
    assert source.database.startswith("many_test")
    name = "many_test_a2_a4_" + uuid4().hex[:12]
    admin_dsn = _psycopg_dsn(source.set(database="postgres").render_as_string(hide_password=False))
    target = source.set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield target, _psycopg_dsn(target)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (name,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_empty_to_head_then_0022_to_head_round_trip():
    with _database() as (url, dsn):
        _run_alembic(url, "upgrade", "head")
        expected_head = _run_alembic(url, "heads").stdout.split()[0]
        assert expected_head in _run_alembic(url, "current").stdout
        _run_alembic(url, "downgrade", "0022_whatsapp_opt_in")
        with psycopg.connect(dsn) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0022_whatsapp_opt_in"
            assert connection.execute("SELECT to_regclass('saas_forward_events')").fetchone()[0] is None
        _run_alembic(url, "upgrade", "head")
        assert expected_head in _run_alembic(url, "current").stdout
        _run_alembic(url, "downgrade", "0018_whatsapp_outreach")
        _run_alembic(url, "upgrade", "head")
        assert expected_head in _run_alembic(url, "current").stdout


def _shape(connection):
    columns = connection.execute("SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_name='whatsapp_accounts' ORDER BY ordinal_position").fetchall()
    checks = connection.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='whatsapp_accounts'::regclass ORDER BY conname").fetchall()
    return columns, checks


def test_0019_accepts_correct_existing_shape_without_changing_it():
    with _database() as (url, dsn):
        _run_alembic(url, "upgrade", "0018_whatsapp_outreach")
        with psycopg.connect(dsn) as connection:
            before = _shape(connection)
        _run_alembic(url, "upgrade", "0019_whatsapp_outreach_settings")
        with psycopg.connect(dsn) as connection:
            assert _shape(connection) == before


@pytest.mark.parametrize("alteration, object_name", [
    ("ALTER TABLE whatsapp_accounts ALTER COLUMN outreach_daily_cap TYPE bigint", "outreach_daily_cap"),
    ("ALTER TABLE whatsapp_accounts ALTER COLUMN ctwa_counts_as_consent SET DEFAULT true", "ctwa_counts_as_consent"),
    ("ALTER TABLE whatsapp_accounts ALTER COLUMN outreach_daily_cap DROP NOT NULL", "outreach_daily_cap"),
    ("ALTER TABLE whatsapp_accounts DROP CONSTRAINT ck_whatsapp_accounts_outreach_daily_cap; ALTER TABLE whatsapp_accounts ADD CONSTRAINT ck_whatsapp_accounts_outreach_daily_cap CHECK (outreach_daily_cap >= 0)", "ck_whatsapp_accounts_outreach_daily_cap"),
    pytest.param(
        "ALTER TABLE whatsapp_accounts DROP CONSTRAINT ck_whatsapp_accounts_opt_out_keywords_array; ALTER TABLE whatsapp_accounts ADD CONSTRAINT ck_whatsapp_accounts_opt_out_keywords_array CHECK (opt_out_keywords IS NULL OR jsonb_typeof(opt_out_keywords) = 'ARRAY')",
        "ck_whatsapp_accounts_opt_out_keywords_array",
        id="wrong-case-json-type",
    ),
])
def test_0019_refuses_incompatible_existing_shape(alteration, object_name):
    with _database() as (url, dsn):
        _run_alembic(url, "upgrade", "0018_whatsapp_outreach")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(alteration)
            before = _shape(connection)
        with pytest.raises(AssertionError, match="0019 incompatible.*" + object_name):
            _run_alembic(url, "upgrade", "0019_whatsapp_outreach_settings")
        with psycopg.connect(dsn) as connection:
            assert _shape(connection) == before
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0018_whatsapp_outreach"
