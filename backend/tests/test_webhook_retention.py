from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import null

from app.models.webhook_event import WebhookEvent
from app.services.contact_erasure import purge_webhook_payloads
from app.workers import saas_retention_tasks
from app.workers.saas_beat_schedule import SAAS_BEAT_SCHEDULE


def test_raw_payload_purge_is_thirty_days_idempotent_and_preserves_dedupe(db_session):
    now = datetime.now(timezone.utc)
    events = []
    for age, payload in ((31, {"text": "old"}), (30, {"text": "boundary"}), (29, {"text": "recent"}), (31, None)):
        event = WebhookEvent(provider="meta", external_event_id=str(uuid4()), payload=payload, created_at=now-timedelta(days=age), processing_status="processed")
        db_session.add(event); events.append(event)
    db_session.commit()
    ids = [event.id for event in events]
    assert purge_webhook_payloads(db_session, now=now) == 2
    db_session.commit(); db_session.expire_all()
    assert db_session.query(WebhookEvent).count() == 4
    assert [db_session.get(WebhookEvent, key).payload for key in ids] == [None, None, {"text": "recent"}, None]
    assert all(db_session.get(WebhookEvent, key).processing_status == "processed" for key in ids)
    assert purge_webhook_payloads(db_session, now=now) == 0


def test_existing_daily_task_reports_only_counts_and_keeps_four_beat_tasks(db_session, monkeypatch, caplog):
    event = WebhookEvent(provider="meta", external_event_id=str(uuid4()), payload={"text": "PRIVATE-CONTENT"}, created_at=datetime.now(timezone.utc)-timedelta(days=31))
    db_session.add(event); db_session.commit()
    monkeypatch.setattr(saas_retention_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    result = saas_retention_tasks.purge_saas_data.run()
    assert result["webhook_payloads_cleared"] == 1
    assert "PRIVATE-CONTENT" not in caplog.text and "PRIVATE-CONTENT" not in str(result)
    assert len(SAAS_BEAT_SCHEDULE) == 4
    assert SAAS_BEAT_SCHEDULE["saas-retention-purge"]["task"] == saas_retention_tasks.purge_saas_data.name
