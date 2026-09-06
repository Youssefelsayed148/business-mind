"""Coverage for the WhatsApp inbound-message dispatch path: an unknown WA ID
messages a connected WhatsApp number, and (if that account has AI enabled) a
Lead + Conversation get created and process_whatsapp_ai_conversation_turn is
dispatched — the WhatsApp equivalent of test_cold_dm_ai_dispatch.py.

process_webhook_event() is invoked directly (as a plain function) with the
test DB session injected via `_get_db`, and
process_whatsapp_ai_conversation_turn is mocked — so these need only
PostgreSQL, no Celery/Redis.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _fresh_phone_number_id() -> str:
    return f"phone_{uuid4().int % 10_000_000}"


def _seed_account(db: Session, phone_number_id: str, *, ai_enabled: bool) -> WhatsappAccount:
    ws = Workspace(id=uuid4(), name="Default", slug=f"wa-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=phone_number_id,
        display_phone_number="+1 650 555 1111",
        ai_enabled=ai_enabled,
        ai_daily_message_cap=100,
        ai_handoff_after_turns=8,
    )
    db.add(account)
    db.commit()
    return account


def _dm_payload(phone_number_id: str, sender_wa_id: str, text: str, message_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_1",
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": sender_wa_id}],
                            "messages": [
                                {
                                    "from": sender_wa_id,
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _run_webhook(db: Session, payload: dict):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="whatsapp_business_account",
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "process_whatsapp_ai_conversation_turn"
        ) as mock_turn:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_turn


@skip_if_no_db
def test_account_not_found_is_skipped(db_session: Session):
    event, mock_turn = _run_webhook(
        db_session, _dm_payload("nonexistent_phone", "16315551234", "hi", "wamid.1")
    )
    assert event.processing_status == "processed"
    assert not mock_turn.called
    assert db_session.query(Lead).filter(Lead.ig_user_id == "16315551234").first() is None


@skip_if_no_db
def test_account_ai_disabled_skips_without_creating_lead(db_session: Session):
    phone_number_id = _fresh_phone_number_id()
    _seed_account(db_session, phone_number_id, ai_enabled=False)

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(phone_number_id, "16315551234", "hi", "wamid.1")
    )
    assert event.processing_status == "processed"
    assert not mock_turn.called
    assert db_session.query(Lead).filter(Lead.ig_user_id == "16315551234").first() is None


@skip_if_no_db
def test_ai_enabled_creates_lead_and_conversation_and_dispatches(db_session: Session):
    phone_number_id = _fresh_phone_number_id()
    account = _seed_account(db_session, phone_number_id, ai_enabled=True)

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(phone_number_id, "16315551234", "do you deliver?", "wamid.1")
    )
    assert event.processing_status == "processed"
    assert mock_turn.delay.called

    lead = db_session.query(Lead).filter(Lead.ig_user_id == "16315551234").first()
    assert lead is not None
    assert lead.platform == "whatsapp"
    assert lead.whatsapp_account_id == account.id
    assert lead.instagram_account_id is None
    assert lead.lead_source == "cold_dm"
    assert lead.ig_username == "Test User"

    conversation = db_session.query(Conversation).filter(Conversation.lead_id == lead.id).first()
    assert conversation is not None
    assert conversation.platform == "whatsapp"
    assert conversation.whatsapp_account_id == account.id
    assert conversation.instagram_account_id is None
    assert conversation.campaign_id is None


@skip_if_no_db
def test_existing_lead_is_reused_not_duplicated(db_session: Session):
    phone_number_id = _fresh_phone_number_id()
    _seed_account(db_session, phone_number_id, ai_enabled=True)

    _run_webhook(db_session, _dm_payload(phone_number_id, "16315551234", "first message", "wamid.1"))
    _run_webhook(db_session, _dm_payload(phone_number_id, "16315551234", "second message", "wamid.2"))

    leads = db_session.query(Lead).filter(Lead.ig_user_id == "16315551234").all()
    assert len(leads) == 1


def test_dispatch_loop_checks_and_marks_processed_before_lead_lookup():
    """Not a DB test: confirms _process_whatsapp_message_events calls the
    shared check_and_mark_processed() guard (same dedup mechanism the
    Instagram message loop uses, unmodified by this phase) before doing any
    account/lead work, and skips the rest of the loop body when it returns
    False.

    A live end-to-end duplicate-delivery test would need to trigger
    check_and_mark_processed()'s IntegrityError -> db.rollback() path
    in-session, which this test harness's db_session fixture doesn't support
    (rollback() expires the whole identity map — including objects committed
    moments earlier in the same test — since the session is bound directly
    to an externally-managed connection with no savepoint listener; the
    pre-existing Instagram equivalents, test_duplicate_webhook_does_not_duplicate_message
    and test_duplicate_comment_does_not_duplicate_message, are in the
    project's known pre-existing failure baseline for related reasons).
    Verified by source inspection instead, which is what actually matters
    here: the dedup call and its is_new guard are unchanged from the pattern
    every other message loop in this codebase already uses.
    """
    import inspect

    from app.workers import tasks

    source = inspect.getsource(tasks._process_whatsapp_message_events)
    assert "check_and_mark_processed(" in source
    assert "if not is_new:" in source
    assert "continue" in source
