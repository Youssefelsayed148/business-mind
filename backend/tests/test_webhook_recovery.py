from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.models.automation_log import AutomationLog
from app.models.webhook_event import WebhookEvent
from app.workers import tasks, webhook_recovery_tasks
from app.workers.celery_app import celery_app


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def sweep(db_session, monkeypatch):
    redis = _FakeRedis()
    enqueued = []
    monkeypatch.setattr(webhook_recovery_tasks, "_redis", lambda: redis)
    monkeypatch.setattr(webhook_recovery_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(tasks.process_webhook_event, "delay", lambda event_id: enqueued.append(event_id))
    db_session.query(WebhookEvent).delete()
    db_session.commit()
    return redis, enqueued


def _event(db, status, age_minutes):
    created = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    event = WebhookEvent(
        id=uuid4(),
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="instagram.comments",
        payload={},
        processing_status=status,
        created_at=created,
        updated_at=created,
    )
    db.add(event)
    db.commit()
    return event


def test_stale_pending_is_requeued_exactly_once(db_session, sweep):
    _, enqueued = sweep
    event = _event(db_session, "pending", 10)
    assert webhook_recovery_tasks.sweep_webhook_events.run()["requeued"] == 1
    assert webhook_recovery_tasks.sweep_webhook_events.run()["requeued"] == 0
    assert enqueued == [str(event.id)]


def test_fresh_pending_and_other_statuses_are_untouched(db_session, sweep):
    _, enqueued = sweep
    _event(db_session, "pending", 1)
    processed = _event(db_session, "processed", 60)
    skipped = _event(db_session, "skipped", 60)
    _event(db_session, "pending", 60 * 48)  # outside the age window
    webhook_recovery_tasks.sweep_webhook_events.run()
    assert enqueued == []
    db_session.refresh(processed)
    db_session.refresh(skipped)
    assert processed.processing_status == "processed"
    assert skipped.processing_status == "skipped"


def test_failed_event_is_logged_once_and_not_rerun(db_session, sweep):
    _, enqueued = sweep
    event = _event(db_session, "failed", 30)
    assert webhook_recovery_tasks.sweep_webhook_events.run()["failed_alerted"] == 1
    assert webhook_recovery_tasks.sweep_webhook_events.run()["failed_alerted"] == 0
    assert enqueued == []
    db_session.refresh(event)
    assert event.processing_status == "failed"
    logs = db_session.query(AutomationLog).filter(AutomationLog.action == "webhook_event_failed").all()
    assert [log.details["event_id"] for log in logs] == [str(event.id)]


def test_enqueue_failure_does_not_crash_and_is_retried_next_sweep(db_session, sweep, monkeypatch):
    _, enqueued = sweep
    bad = _event(db_session, "pending", 20)
    good = _event(db_session, "pending", 10)

    def flaky(event_id):
        if event_id == str(bad.id) and not enqueued:
            raise RuntimeError("broker down")
        enqueued.append(event_id)

    monkeypatch.setattr(tasks.process_webhook_event, "delay", flaky)
    result = webhook_recovery_tasks.sweep_webhook_events.run()
    assert result["enqueue_failed"] == 1 and result["requeued"] == 1
    assert enqueued == [str(good.id)]
    # The failed one is eligible again next time.
    assert webhook_recovery_tasks.sweep_webhook_events.run()["requeued"] == 1
    assert str(bad.id) in enqueued


def test_redis_down_skips_sweep(db_session, sweep, monkeypatch):
    _, enqueued = sweep
    _event(db_session, "pending", 10)

    class _Down(_FakeRedis):
        def ping(self):
            raise RedisError("down")

    monkeypatch.setattr(webhook_recovery_tasks, "_redis", lambda: _Down())
    assert webhook_recovery_tasks.sweep_webhook_events.run()["requeued"] == 0
    assert enqueued == []


def test_schedule_is_registered():
    entry = celery_app.conf.beat_schedule["webhook-recovery-sweep"]
    celery_app.loader.import_default_modules()
    assert entry["task"] in celery_app.tasks
