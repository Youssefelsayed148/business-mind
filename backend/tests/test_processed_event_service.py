"""Opaque dedupe markers retain replay protection without raw identifiers/text."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine, null, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models.processed_webhook_event import ProcessedWebhookEvent
from app.models.workspace import Workspace
from app.services.processed_event_service import build_event_key, check_and_mark_processed, storage_event_key

RAW = "ig_message:PRIVATE-CUSTOMER-ID:PRIVATE-FALLBACK-TEXT"


def _unguard(db):
    # Emulate the pre0029 schema only inside this rollback-only test transaction.
    for name in ("ck_processed_event_key_hashed", "ck_processed_event_metadata_empty", "ck_processed_event_type_safe"):
        db.execute(text(f'ALTER TABLE processed_webhook_events DROP CONSTRAINT IF EXISTS "{name}"'))


def test_storage_key_is_versioned_deterministic_and_not_double_hashed():
    value = storage_event_key(RAW)
    assert value.startswith("sha256:v1:") and len(value) == 74
    assert storage_event_key(value) == value == storage_event_key(RAW)
    assert "PRIVATE" not in value
    assert storage_event_key("sha256:v1:not-a-digest") != "sha256:v1:not-a-digest"


def test_new_markers_and_duplicate_logs_have_no_raw_metadata(db_session, caplog):
    import logging
    caplog.set_level(logging.DEBUG, logger="app.services.processed_event_service")
    assert check_and_mark_processed(db_session, RAW, "ig_message", {"sender_id": "PRIVATE-CUSTOMER-ID", "text": "PRIVATE-FALLBACK-TEXT"})
    assert not check_and_mark_processed(db_session, RAW, "ig_message", {"text": "PRIVATE-FALLBACK-TEXT"})
    db_session.flush()
    row = db_session.query(ProcessedWebhookEvent).one()
    assert row.event_key == storage_event_key(RAW) and row.metadata_ is None
    assert "PRIVATE-CUSTOMER-ID" not in caplog.text and "PRIVATE-FALLBACK-TEXT" not in caplog.text
    assert db_session.query(ProcessedWebhookEvent).filter(ProcessedWebhookEvent.metadata_.is_(None)).count() == 1


def test_legacy_duplicate_is_normalized_without_reprocessing(db_session):
    _unguard(db_session)
    row = ProcessedWebhookEvent(provider="meta", event_key=RAW, event_type="ig_message", metadata_={"text": "PRIVATE-FALLBACK-TEXT"})
    db_session.add(row); db_session.flush()
    assert not check_and_mark_processed(db_session, RAW)
    db_session.expire_all()
    assert db_session.query(ProcessedWebhookEvent).one().event_key == storage_event_key(RAW)
    assert db_session.query(ProcessedWebhookEvent).one().metadata_ is None


def test_raw_plus_hashed_collision_keeps_one_oldest_tombstone(db_session):
    _unguard(db_session)
    older = datetime.now(timezone.utc)-timedelta(days=5)
    db_session.add_all([
        ProcessedWebhookEvent(provider="meta", event_key=RAW, received_at=older, metadata_={"id": "PRIVATE-CUSTOMER-ID"}),
        ProcessedWebhookEvent(provider="meta", event_key=storage_event_key(RAW), metadata_={"text": "PRIVATE-FALLBACK-TEXT"}),
    ])
    db_session.flush()
    assert not check_and_mark_processed(db_session, RAW)
    db_session.expire_all()
    row = db_session.query(ProcessedWebhookEvent).one()
    assert row.event_key == storage_event_key(RAW) and row.metadata_ is None and row.received_at == older
    assert not check_and_mark_processed(db_session, RAW)


def test_platform_and_provider_namespaces_remain_distinct(db_session):
    ig = build_event_key(comment_id="same-id", platform="instagram")
    fb = build_event_key(comment_id="same-id", platform="facebook")
    assert check_and_mark_processed(db_session, ig)
    assert check_and_mark_processed(db_session, fb)
    db_session.add(ProcessedWebhookEvent(provider="other-provider", event_key=storage_event_key(RAW), metadata_=null()))
    db_session.flush()
    assert check_and_mark_processed(db_session, RAW)
    assert not check_and_mark_processed(db_session, RAW)
    assert db_session.query(ProcessedWebhookEvent).count() == 4


def test_duplicate_does_not_roll_back_unrelated_caller_changes(db_session):
    assert check_and_mark_processed(db_session, RAW)
    workspace = Workspace(name="retain", slug="retain-"+uuid4().hex)
    db_session.add(workspace); db_session.flush(); key = workspace.id
    assert not check_and_mark_processed(db_session, RAW)
    assert db_session.get(Workspace, key) is not None


def test_concurrent_duplicate_claims_process_at_most_once():
    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert os.environ["APP_ENV"] == "test"
    assert re.fullmatch(r"many_test(?:_[a-z0-9_]+)?", source.database or "")
    assert source.host in (None, "")
    assert str(source.query.get("host", "")).startswith(("/var/tmp/", "/tmp/"))
    engine = create_engine(source)
    raw = "ig_message:synthetic:"+uuid4().hex
    stored = storage_event_key(raw)
    barrier = Barrier(2)
    def claim():
        with Session(engine) as db:
            barrier.wait(timeout=5)
            result = check_and_mark_processed(db, raw, "ig_message", {"text": "not retained"})
            db.commit()
            return result
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim), pool.submit(claim)]
            assert sorted(future.result(timeout=10) for future in futures) == [False, True]
        with Session(engine) as db:
            rows = db.query(ProcessedWebhookEvent).filter_by(provider="meta", event_key=stored).all()
            assert len(rows) == 1 and rows[0].metadata_ is None
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM processed_webhook_events WHERE provider='meta' AND event_key=:key"), {"key": stored})
        engine.dispose()


def test_database_refuses_personal_event_type_even_with_an_opaque_key(db_session):
    import pytest
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError) as caught:
        with db_session.begin_nested():
            db_session.execute(insert(ProcessedWebhookEvent).values(
                id=uuid4(), provider="meta", event_key=storage_event_key("ig_message:synthetic:new-key"),
                event_type="PRIVATE-CUSTOMER-ID", metadata=null(),
            ))
    assert caught.value.orig.sqlstate == "23514"
    assert db_session.query(ProcessedWebhookEvent).count() == 0
