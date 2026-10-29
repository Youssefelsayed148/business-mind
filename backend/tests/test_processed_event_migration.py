"""Real0028?0029 transition, repeated rollback/upgrade, and guarded old writers."""
import os
import re
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import errors, sql
from sqlalchemy.engine import make_url

from app.services.processed_event_service import storage_event_key


def _dsn(url):
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _alembic(url, *arguments):
    parsed = make_url(url)
    print(f"Alembic host={parsed.query.get('host')} db={parsed.database}")
    result = subprocess.run(["alembic", *arguments], cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": url, "DATABASE_URL": url},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout+result.stderr


def test_migration_hashes_existing_keys_merges_collision_and_never_restores_raw_data():
    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert os.environ["APP_ENV"] == "test"
    assert re.fullmatch(r"many_test(?:_[a-z0-9_]+)?", source.database or "")
    assert source.host in (None, "")
    assert str(source.query.get("host", "")).startswith(("/var/tmp/", "/tmp/"))
    name = "many_test_b2_hash_"+uuid4().hex[:12]
    target = source.set(database=name).render_as_string(hide_password=False)
    admin = _dsn(source.set(database="postgres"))
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    raw_a = "ig_message:PRIVATE-ID-A:PRIVATE-TEXT-A"
    raw_b = "facebook_message:PRIVATE-ID-B:PRIVATE-TEXT-B"
    malformed = "sha256:v1:PRIVATE-INVALID-MARKER"
    try:
        _alembic(target, "upgrade", "0028_meta_compliance")
        with psycopg.connect(_dsn(target), autocommit=True) as connection:
            #0001 uses current metadata: remove new guards to emulate actual0028.
            for guard in ("ck_processed_event_key_hashed", "ck_processed_event_metadata_empty", "ck_processed_event_type_safe"):
                connection.execute(sql.SQL("ALTER TABLE processed_webhook_events DROP CONSTRAINT IF EXISTS {}").format(sql.Identifier(guard)))
            for provider, key in (("meta", raw_a), ("meta", storage_event_key(raw_a)), ("meta", raw_b), ("other", raw_a), ("meta", malformed)):
                connection.execute("INSERT INTO processed_webhook_events(id,provider,event_key,event_type,metadata) VALUES(%s,%s,%s,%s,%s::jsonb)",
                                   (uuid4(), provider, key, "PRIVATE-TYPE", '{"text":"PRIVATE-TEXT"}'))
        _alembic(target, "upgrade", "head")
        with psycopg.connect(_dsn(target), autocommit=True) as connection:
            rows = connection.execute("SELECT provider,event_key,event_type,metadata FROM processed_webhook_events ORDER BY provider,event_key").fetchall()
            assert len(rows) == 4
            assert {(row[0],row[1]) for row in rows} == {("meta", storage_event_key(raw_a)), ("meta", storage_event_key(raw_b)), ("other", storage_event_key(raw_a)), ("meta", storage_event_key(malformed))}
            assert all(row[2] is None and row[3] is None for row in rows)
            import pytest
            with pytest.raises(errors.CheckViolation):
                connection.execute("INSERT INTO processed_webhook_events(id,provider,event_key) VALUES(%s,'meta',%s)", (uuid4(), "ig_message:PRIVATE-ID:PRIVATE-TEXT"))
        for _ in range(2):
            _alembic(target, "downgrade", "0028_meta_compliance")
            with psycopg.connect(_dsn(target)) as connection:
                assert connection.execute("SELECT provider,event_key,event_type,metadata FROM processed_webhook_events ORDER BY provider,event_key").fetchall() == rows
            _alembic(target, "upgrade", "head")
            with psycopg.connect(_dsn(target)) as connection:
                assert connection.execute("SELECT provider,event_key,event_type,metadata FROM processed_webhook_events ORDER BY provider,event_key").fetchall() == rows
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (name,))
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
