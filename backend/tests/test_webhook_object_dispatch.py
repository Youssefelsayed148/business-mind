"""Coverage for the payload["object"] dispatcher branch in process_webhook_event()
(Phase 1 of the multi-platform expansion — see
docs/specs/2026-09-05-multi-platform-expansion-design.md).

Only `"object": "instagram"` should reach the existing Instagram parsers.
Anything else (missing, None, or some other platform's object type such as
"page" or "whatsapp_business_account") must be marked "skipped" without
calling any of the three Instagram parsers, mirroring the existing
"no events found" skip path.

process_webhook_event() is invoked directly (as a plain function) with the
test DB session injected via `_get_db`, same harness as
test_ai_continuation_dispatch.py — no Celery worker, Redis, or HTTP signature
machinery needed.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent
from tests.conftest import skip_if_no_db


def _run_webhook(db: Session, payload: dict | None):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type=payload.get("object") if payload else None,
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None  # task calls db.close() in its finally block
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "parse_instagram_comment_events"
        ) as mock_comment, patch.object(
            tasks, "parse_instagram_postback_events"
        ) as mock_postback, patch.object(
            tasks, "parse_instagram_message_events"
        ) as mock_message:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, (mock_comment, mock_postback, mock_message)


@skip_if_no_db
def test_missing_object_is_skipped_without_calling_ig_parsers(db_session: Session):
    event, parsers = _run_webhook(db_session, {"entry": []})

    assert event.processing_status == "skipped"
    for mock_parser in parsers:
        assert not mock_parser.called


@skip_if_no_db
def test_object_none_payload_is_skipped_without_calling_ig_parsers(db_session: Session):
    event, parsers = _run_webhook(db_session, None)

    assert event.processing_status == "skipped"
    for mock_parser in parsers:
        assert not mock_parser.called


@skip_if_no_db
def test_unrecognized_object_is_skipped_without_calling_ig_parsers(db_session: Session):
    event, parsers = _run_webhook(db_session, {"object": "page", "entry": []})

    assert event.processing_status == "skipped"
    for mock_parser in parsers:
        assert not mock_parser.called


@skip_if_no_db
def test_instagram_object_still_reaches_ig_parsers(db_session: Session):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="instagram",
        payload={"object": "instagram", "entry": []},
        processing_status="pending",
    )
    db_session.add(event)
    db_session.commit()

    orig_close = db_session.close
    db_session.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db_session), patch.object(
            tasks, "parse_instagram_comment_events", return_value=[]
        ) as mock_comment, patch.object(
            tasks, "parse_instagram_postback_events", return_value=[]
        ) as mock_postback, patch.object(
            tasks, "parse_instagram_message_events", return_value=[]
        ) as mock_message:
            tasks.process_webhook_event(str(event.id))
    finally:
        db_session.close = orig_close

    db_session.refresh(event)
    assert event.processing_status == "skipped"  # empty entry -> existing "no events" skip path
    mock_comment.assert_called_once()
    mock_postback.assert_called_once()
    mock_message.assert_called_once()
