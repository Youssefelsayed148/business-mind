"""Private-cluster real Alembic transitions; never app metadata shortcuts."""
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url


@pytest.mark.parametrize("start", [None, "0022_whatsapp_opt_in"])
def test_r1_upgrade_downgrade_drift_and_pending_guard(start):
    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert os.environ["APP_ENV"] == "test" and source.database == "many_test_r1"
    assert not source.host and str(source.query.get("host", "")).startswith("/var/tmp/many-r1-")
    name = "many_test_r1_migration_" + uuid4().hex[:8]
    admin = source.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    url = source.set(database=name).render_as_string(hide_password=False)
    dsn = source.set(drivername="postgresql", database=name).render_as_string(hide_password=False)
    def alembic(*args, success=True):
        result = subprocess.run(["alembic", *args], cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": url, "DATABASE_URL": url}, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout + result.stderr
    print(f"Migration DB host={source.query['host']} database={name}")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        if start:
            alembic("upgrade", start)
        alembic("upgrade", "0029_hash_processed_event_keys")
        workspace, channel, mapping = uuid4(), uuid4(), uuid4()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("INSERT INTO workspaces(id,name,slug) VALUES(%s,'Synthetic',%s)", (workspace, str(workspace)))
            c.execute("INSERT INTO meta_authorizations(id,app_id,subject_digest,workspace_id,platform,channel_id,verification_source) VALUES(%s,'app','digest',%s,'facebook',%s,'legacy')", (mapping, workspace, channel))
        alembic("upgrade", "head")
        assert "No new upgrade operations detected" in alembic("check")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT subject_namespace,subject_encrypted,provider_context_encrypted FROM meta_authorizations WHERE id=%s", (mapping,)).fetchone() == ("unresolved", None, None)
        alembic("downgrade", "0029_hash_processed_event_keys")
        alembic("upgrade", "head")
        job = uuid4()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("INSERT INTO account_erasure_jobs(id,workspace_id,platform,channel_id,request_id,event_ids) VALUES(%s,%s,'facebook',%s,%s,'{}')", (job, workspace, channel, uuid4()))
        assert "Resolve and verify account erasure jobs" in alembic("downgrade", "0029_hash_processed_event_keys", success=False)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT state FROM account_erasure_jobs WHERE id=%s", (job,)).fetchone() == ("pending",)
            c.execute("UPDATE account_erasure_jobs SET state='local_erased',remote_verified_at=now() WHERE id=%s", (job,))
        alembic("downgrade", "0029_hash_processed_event_keys")
        alembic("upgrade", "head")
        alembic("check")
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (name,))
            c.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
