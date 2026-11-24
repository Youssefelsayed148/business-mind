"""0031_sso_link: up, down, up on a private throwaway database (never many_test_r1 itself)."""
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def test_0031_up_down_up_keeps_legacy_data():
    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert os.environ["APP_ENV"] == "test" and source.database == "many_test_r1"
    name = "many_test_r1_sso_" + uuid4().hex[:8]
    admin = source.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    url = source.set(database=name).render_as_string(hide_password=False)
    dsn = source.set(drivername="postgresql", database=name).render_as_string(hide_password=False)

    def alembic(*args):
        result = subprocess.run(
            ["alembic", *args], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            env={**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": url, "DATABASE_URL": url},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    def columns(c, table):
        return {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))}

    print(f"Migration DB host={source.query.get('host')} database={name}")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        alembic("upgrade", "0030_meta_account_erasure")
        user, ws, m = uuid4(), uuid4(), uuid4()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("INSERT INTO users(id,email,password_hash,role,is_active) VALUES(%s,'syn@example.test','x','admin',true)", (user,))
            c.execute("INSERT INTO workspaces(id,name,slug) VALUES(%s,'Synthetic',%s)", (ws, str(ws)))
            c.execute("INSERT INTO user_workspace_memberships(id,user_id,workspace_id,role) VALUES(%s,%s,%s,'owner')", (m, user, ws))
        alembic("upgrade", "head")
        assert "No new upgrade operations detected" in alembic("check")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT auth_source,sso_subject FROM users WHERE id=%s", (user,)).fetchone() == ("local", None)
            assert c.execute("SELECT source FROM user_workspace_memberships WHERE id=%s", (m,)).fetchone() == ("local",)
            assert c.execute("SELECT saas_tenant_id FROM workspaces WHERE id=%s", (ws,)).fetchone() == (None,)
        alembic("downgrade", "0030_meta_account_erasure")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not {"sso_subject", "auth_source"} & columns(c, "users")
            assert "source" not in columns(c, "user_workspace_memberships")
            assert "saas_tenant_id" not in columns(c, "workspaces")
            assert c.execute("SELECT email,role FROM users WHERE id=%s", (user,)).fetchone() == ("syn@example.test", "admin")
            assert c.execute("SELECT role FROM user_workspace_memberships WHERE id=%s", (m,)).fetchone() == ("owner",)
        alembic("upgrade", "head")
        alembic("check")
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (name,))
            c.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
