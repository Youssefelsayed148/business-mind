"""Standalone 0028 operations rehearsal; not a claim of a full-chain upgrade."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

raw = os.environ["TEST_DATABASE_URL"]
url = make_url(raw)
assert os.environ["APP_ENV"] == "test" and url.database == "many_test_b1_b4" and url.host is None
assert url.query["host"] == "/var/tmp/many-b1-b4-20261028/socket"
engine = create_engine(url)
with engine.begin() as connection:
    assert not inspect(connection).get_table_names()
    connection.execute(text("CREATE TABLE workspaces (id uuid PRIMARY KEY)"))
    spec = importlib.util.spec_from_file_location("compliance_migration", Path.cwd()/"backend/alembic/versions/0028_meta_compliance.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    assert {"meta_authorizations", "data_deletion_requests"} <= set(inspect(connection).get_table_names())
    migration.upgrade()
    print("PASS: standalone 0028 creates tables; repeated upgrade validates correct existing schema")
    transaction = connection.begin_nested()
    connection.execute(text("ALTER TABLE data_deletion_requests ALTER COLUMN app_id TYPE varchar(128)"))
    try:
        migration.upgrade()
    except RuntimeError:
        print("PASS: incompatible existing column type/length fails closed")
    else:
        raise AssertionError("schema drift accepted")
    finally:
        transaction.rollback()
    transaction = connection.begin_nested()
    connection.execute(text("ALTER TABLE meta_authorizations RENAME CONSTRAINT uq_meta_authorization_channel TO wrong_upsert_constraint"))
    try:
        migration.upgrade()
    except RuntimeError:
        print("PASS: wrong named upsert constraint fails closed")
    else:
        raise AssertionError("named constraint drift accepted")
    finally:
        transaction.rollback()
    connection.execute(text("DROP INDEX ix_meta_authorizations_app_id"))
    migration.upgrade()
    assert any(index["name"] == "ix_meta_authorizations_app_id"
               for index in inspect(connection).get_indexes("meta_authorizations"))
    print("PASS: existing table missing lookup index is repaired before downgrade")
    migration.downgrade()
    assert inspect(connection).get_table_names() == ["workspaces"]
    migration.upgrade()
    migration.downgrade()
    connection.execute(text("DROP TABLE workspaces"))
    print("PASS: standalone 0028 downgrade and upgrade/downgrade round trip")
engine.dispose()
