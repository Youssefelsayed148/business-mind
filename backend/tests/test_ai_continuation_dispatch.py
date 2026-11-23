"""Coverage for the inbound-DM -> AI-continuation dispatch path in
process_webhook_event().

Regression target: a real inbound DM reply was being marked "processed" but
never dispatched process_ai_conversation_turn, with zero log trace, because the
campaign-level ai_enabled gate (tasks.py, in the `for msg_evt in message_events`
loop) returned via `continue` without emitting any logger or log_action call.
The production scenario was account 17841454454076321 / lead 1371598884833863 on
campaign "burger post" (account AI on, campaign AI off).

These tests pin both halves of the fix:
  * the happy path still creates a Conversation + inbound Message and dispatches
    the AI turn, and
  * the gated paths (campaign.ai_enabled / account.ai_enabled == False) are now
    observable: they write an `ai_continuation_skipped` AutomationLog with a
    machine-readable reason.

process_webhook_event() is invoked directly (as a plain function) with the test
DB session injected via `_get_db`, so the test needs only PostgreSQL — no
Celery worker, Redis, or HTTP signature machinery.
"""

from uuid import uuid4
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _fresh_ids() -> tuple[str, str]:
    """Unique (account_ig_id, lead_ig_id) per test — the conftest session does
    not roll back committed writes, and InstagramAccount.ig_user_id is UNIQUE."""
    tag = uuid4().int % 10_000_000
    return f"178414{tag:010d}", f"137159{tag:010d}"


def _seed(
    db: Session,
    account_ig: str,
    lead_ig: str,
    *,
    account_ai_enabled: bool,
    campaign_ai_enabled: bool,
):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ai-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    acc = InstagramAccount(
        id=uuid4(),
        workspace_id=ws.id,
        ig_user_id=account_ig,
        ig_username="popeye_restaurant_",
        business_vertical="general",
        ai_enabled=account_ai_enabled,
        ai_daily_message_cap=100,
    )
    db.add(acc)
    db.commit()

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="burger post",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
        ai_enabled=campaign_ai_enabled,
        ai_handoff_after_turns=8,
    )
    db.add(campaign)
    db.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id=lead_ig,
        ig_username="hungry_lead",
        source_campaign_id=campaign.id,
        status="new",
    )
    db.add(lead)
    db.commit()

    return ws, acc, campaign, lead


def _dm_payload(account_ig: str, lead_ig: str, text: str, mid: str) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_ig,
                "time": 1788012570939,
                "messaging": [
                    {
                        "sender": {"id": lead_ig},
                        "recipient": {"id": account_ig},
                        "timestamp": 1788012570939,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


def _run_webhook(db: Session, payload: dict):
    """Run process_webhook_event() synchronously against the test session with
    process_ai_conversation_turn mocked. Returns (event, mock_turn)."""
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="instagram",
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None  # task calls db.close() in its finally block
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "process_ai_conversation_turn"
        ) as mock_turn:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_turn


@skip_if_no_db
def test_campaign_ai_enabled_creates_conversation_and_dispatches(db_session: Session):
    account_ig, lead_ig = _fresh_ids()
    _, acc, campaign, lead = _seed(
        db_session, account_ig, lead_ig, account_ai_enabled=True, campaign_ai_enabled=True
    )

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, lead_ig, "what is your delivery hours", "mid.happy1")
    )
    assert event.processing_status == "processed"

    conversation = (
        db_session.query(Conversation)
        .filter(Conversation.lead_id == lead.id, Conversation.campaign_id == campaign.id)
        .first()
    )
    assert conversation is not None
    assert conversation.status == "bot_active"

    inbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "inbound")
        .all()
    )
    assert len(inbound) == 1
    assert inbound[0].content == "what is your delivery hours"
    assert inbound[0].message_type == "ai_conversation"

    mock_turn.delay.assert_called_once_with(str(conversation.id), str(inbound[0].id))

    dispatched = (
        db_session.query(AutomationLog)
        .filter(
            AutomationLog.action == "ai_continuation_dispatched",
            AutomationLog.lead_id == lead.id,
        )
        .all()
    )
    assert len(dispatched) == 1
    assert dispatched[0].details["conversation_id"] == str(conversation.id)


@skip_if_no_db
def test_campaign_ai_disabled_skips_but_is_logged(db_session: Session):
    """The exact production bug: account AI on, campaign AI off. No AI turn is
    dispatched (fail-closed, unchanged), but the skip is now diagnosable."""
    account_ig, lead_ig = _fresh_ids()
    _, acc, campaign, lead = _seed(
        db_session, account_ig, lead_ig, account_ai_enabled=True, campaign_ai_enabled=False
    )

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, lead_ig, "how much time for the delivery", "mid.gated1")
    )
    assert event.processing_status == "processed"

    # Fail-closed behaviour preserved: nothing dispatched, no conversation.
    mock_turn.delay.assert_not_called()
    assert (
        db_session.query(Conversation).filter(Conversation.lead_id == lead.id).first()
        is None
    )

    # ...but the skip is no longer silent.
    skipped = (
        db_session.query(AutomationLog)
        .filter(
            AutomationLog.action == "ai_continuation_skipped",
            AutomationLog.lead_id == lead.id,
        )
        .all()
    )
    assert len(skipped) == 1
    assert skipped[0].details["reason"] == "campaign_ai_disabled"
    assert skipped[0].details["campaign_id"] == str(campaign.id)
    assert skipped[0].campaign_id == campaign.id
    assert skipped[0].lead_id == lead.id


@skip_if_no_db
def test_account_ai_disabled_skips_but_is_logged(db_session: Session):
    account_ig, lead_ig = _fresh_ids()
    _, acc, campaign, lead = _seed(
        db_session, account_ig, lead_ig, account_ai_enabled=False, campaign_ai_enabled=True
    )

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, lead_ig, "hello there", "mid.acct1")
    )
    assert event.processing_status == "processed"
    mock_turn.delay.assert_not_called()

    skipped = (
        db_session.query(AutomationLog)
        .filter(
            AutomationLog.action == "ai_continuation_skipped",
            AutomationLog.instagram_account_id == acc.id,
        )
        .all()
    )
    assert len(skipped) == 1
    assert skipped[0].details["reason"] == "account_ai_disabled"
    assert skipped[0].instagram_account_id == acc.id
