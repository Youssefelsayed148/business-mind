"""Offline unittest suite; DB cases require explicit disposable many_test.

No backend conftest import. DB fixtures create/drop only two synthetic tables,
and refuse to start if either table already exists.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

import canary_preflight as preflight


ACCOUNT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = "abcdefab-1234-4234-8234-123456789abc"


class SourceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("backend/alembic/versions", "backend/app/workers", "nginx"):
            target = self.root / name
            target.mkdir(parents=True)
            source = preflight.ROOT / name
            paths = source.glob("*.py") if name != "nginx" else [source / "default.conf"]
            for path in paths:
                shutil.copyfile(path, target / path.name)

    def replace(self, name, before, after):
        path = self.root / name
        source = path.read_text()
        self.assertIn(before, source)
        path.write_text(source.replace(before, after))

    def test_real_source_passes_but_static_only_is_not_ready(self):
        self.assertEqual(preflight.migration_head(self.root), preflight.REQUIRED_REVISIONS[-1])
        preflight.check_beat(self.root)
        preflight.check_nginx(self.root / "nginx/default.conf")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(preflight.main(["--root", str(self.root), "--static-only"]), 2)
        self.assertIn("UNVERIFIED", output.getvalue())

    def test_multiple_migration_heads_fail(self):
        (self.root / "backend/alembic/versions/extra.py").write_text(
            "revision='extra'\ndown_revision='0022_whatsapp_opt_in'\n"
        )
        with self.assertRaises(preflight.CheckFailed):
            preflight.migration_head(self.root)

    def test_missing_migration_fails(self):
        (self.root / "backend/alembic/versions/0024_saas_forward_events.py").unlink()
        with self.assertRaises(preflight.CheckFailed):
            preflight.migration_head(self.root)

    def test_missing_saas_task_fails(self):
        self.replace("backend/app/workers/saas_beat_schedule.py", "sweep_saas_forwards", "different_task")
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_beat(self.root)

    def test_duplicate_task_under_another_entry_fails(self):
        self.replace("backend/app/workers/saas_beat_schedule.py",
                     "app.workers.saas_send_tasks.sweep_saas_sends",
                     "app.workers.saas_forward_tasks.sweep_saas_forwards")
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_beat(self.root)

    def test_second_beat_assignment_fails(self):
        path = self.root / "backend/app/workers/celery_app.py"
        path.write_text(path.read_text() + "\ncelery_app.conf.beat_schedule = {}\n")
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_beat(self.root)

    def test_commented_gzip_does_not_count(self):
        self.replace("nginx/default.conf", "        gzip off;", "        # gzip off;")
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_nginx(self.root / "nginx/default.conf")

    def test_gzip_alias_must_also_be_off(self):
        self.replace("nginx/default.conf", "location /saas/ {", "location /different/ {")
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_nginx(self.root / "nginx/default.conf")

    def test_canonical_uuid_rejects_uppercase_and_other_spellings(self):
        self.assertTrue(preflight.canonical_uuid(CONNECTION))
        for value in (None, "", CONNECTION.upper(), " " + CONNECTION, "{" + CONNECTION + "}", "bad"):
            with self.subTest(value=value):
                self.assertFalse(preflight.canonical_uuid(value))

    def test_database_url_fallback_is_refused(self):
        with redirect_stdout(io.StringIO()) as output:
            status = preflight.main(["--database-url-env", "DATABASE_URL"])
        self.assertEqual(status, 1)
        self.assertNotIn("Traceback", output.getvalue())


class DisposableDatabaseChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.engine import make_url

        raw_url = os.environ.get("TEST_DATABASE_URL")
        if os.environ.get("APP_ENV") != "test" or not raw_url:
            raise RuntimeError("Explicit APP_ENV=test and TEST_DATABASE_URL are required")
        url = make_url(raw_url)
        if url.database != "many_test" or url.host is not None or not url.query.get("host", "").startswith("/"):
            raise RuntimeError("Only disposable local-socket many_test is permitted")
        cls.url = raw_url
        cls.engine = create_engine(url)
        cls.text = staticmethod(text)
        with cls.engine.begin() as conn:
            if conn.execute(text("SELECT current_database()")).scalar_one() != "many_test":
                raise RuntimeError("Wrong test database")
            if {"alembic_version", "whatsapp_accounts"} & set(inspect(conn).get_table_names()):
                raise RuntimeError("Synthetic fixture tables already exist; refusing to overwrite")
            conn.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE whatsapp_accounts (id uuid PRIMARY KEY, saas_connection_id varchar(64))"))
            conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": preflight.REQUIRED_REVISIONS[-1]})
            conn.execute(text("INSERT INTO whatsapp_accounts VALUES (:id, :cid)"), {"id": ACCOUNT, "cid": CONNECTION})

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as conn:
            conn.execute(cls.text("DROP TABLE whatsapp_accounts"))
            conn.execute(cls.text("DROP TABLE alembic_version"))
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as conn:
            conn.execute(self.text("UPDATE alembic_version SET version_num=:v"), {"v": preflight.REQUIRED_REVISIONS[-1]})
            conn.execute(self.text("UPDATE whatsapp_accounts SET saas_connection_id=:v"), {"v": CONNECTION})

    def test_database_head_and_lowercase_uuid_pass(self):
        preflight.check_database(self.url, ACCOUNT, preflight.REQUIRED_REVISIONS[-1])

    def test_old_database_revision_fails(self):
        with self.engine.begin() as conn:
            conn.execute(self.text("UPDATE alembic_version SET version_num='0022_whatsapp_opt_in'"))
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_database(self.url, ACCOUNT, preflight.REQUIRED_REVISIONS[-1])

    def test_uppercase_stored_uuid_fails(self):
        with self.engine.begin() as conn:
            conn.execute(self.text("UPDATE whatsapp_accounts SET saas_connection_id=:v"), {"v": CONNECTION.upper()})
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_database(self.url, ACCOUNT, preflight.REQUIRED_REVISIONS[-1])

    def test_missing_account_fails(self):
        with self.assertRaises(preflight.CheckFailed):
            preflight.check_database(self.url, UUID(int=0), preflight.REQUIRED_REVISIONS[-1])

    def test_tcp_is_refused_and_not_printed(self):
        marker = "synthetic-private-marker"
        with patch.dict(os.environ, {"CANARY_DATABASE_URL": f"postgresql+psycopg://user:{marker}@example.invalid/many_test"}):
            with redirect_stdout(io.StringIO()) as output:
                status = preflight.main(["--account-id", str(ACCOUNT)])
        self.assertEqual(status, 1)
        self.assertNotIn(marker, output.getvalue())
        self.assertIn("TCP is refused", output.getvalue())

    def test_complete_cli_passes_without_outputting_uuid(self):
        with redirect_stdout(io.StringIO()) as output:
            status = preflight.main(["--database-url-env", "TEST_DATABASE_URL", "--account-id", str(ACCOUNT)])
        self.assertEqual(status, 0, output.getvalue())
        self.assertNotIn(CONNECTION, output.getvalue())
        self.assertNotIn(str(ACCOUNT), output.getvalue())


if __name__ == "__main__":
    unittest.main()
