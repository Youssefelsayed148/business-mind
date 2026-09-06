"""Coverage for process_whatsapp_ai_conversation_turn — the WhatsApp
equivalent of process_ai_conversation_turn. Verifies it reuses the shared
conversation_service budget/turn/handoff helpers (not a reimplementation)
and that ai_service.generate_reply is called with platform="whatsapp" so the
prompt text doesn't describe the bot as an Instagram assistant.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_token import WhatsappToken
from app.models.workspace import Workspace
from app.services import ai_service
from app.utils.crypto import encrypt_text
from tests.conftest import skip_if_no_db


def _seed(
    db: Session,
    *,
    ai_enabled: bool = True,
    turn_count: int = 0,
    ai_handoff_after_turns: int = 8,
    ai_daily_message_cap: int = 100,
    ai_messages_sent_today: int = 0,
):
    ws = Workspace(id=uuid4(), name="Default", slug=f"wa-turn-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=f"phone_{uuid4().int % 10_000_000}",
        display_phone_number="+1 650 555 1111",
        ai_enabled=ai_enabled,
        ai_handoff_after_turns=ai_handoff_after_turns,
        ai_daily_message_cap=ai_daily_message_cap,
        ai_messages_sent_today=ai_messages_sent_today,
        # Set so is_budget_exhausted()'s reset_daily_budget_if_needed() call
        # doesn't zero ai_messages_sent_today back out (it resets whenever
        # ai_budget_reset_at is None or dated before today).
        ai_budget_reset_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()

    db.add(WhatsappToken(id=uuid4(), whatsapp_account_id=account.id, access_token=encrypt_text("fake_token")))
    db.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        instagram_account_id=None,
        ig_user_id="16315551234",
        ig_username="Test User",
        lead_source="cold_dm",
        status="new",
    )
    db.add(lead)
    db.commit()

    conversation = Conversation(
        id=uuid4(),
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        instagram_account_id=None,
        status="bot_active",
        turn_count=turn_count,
    )
    db.add(conversation)
    db.commit()

    inbound = Message(
        id=uuid4(),
        campaign_id=None,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="inbound",
        content="do you deliver?",
        message_type="ai_conversation",
        status="received",
    )
    db.add(inbound)
    db.commit()

    return account, lead, conversation, inbound


def _run_turn(db: Session, conversation_id, inbound_message_id):
    from app.workers import tasks

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db):
            tasks.process_whatsapp_ai_conversation_turn(str(conversation_id), str(inbound_message_id))
    finally:
        db.close = orig_close


@skip_if_no_db
def test_happy_path_sends_reply_with_whatsapp_platform_prompt(db_session: Session):
    account, lead, conversation, inbound = _seed(db_session)

    with patch.object(
        ai_service, "generate_reply", return_value=ai_service.AIReplyResult(success=True, text="Yes, we deliver!")
    ) as mock_generate, patch("app.workers.tasks.WhatsappClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.send_text_message.return_value = MagicMock(
            success=True, provider_message_id="wamid.out1", error_code=None, error_message=None
        )
        MockClient.return_value = mock_client_instance

        _run_turn(db_session, conversation.id, inbound.id)

    # ai_service.generate_reply called with platform="whatsapp" — the whole
    # point of not hardcoding "Instagram" in the shared prompt builder.
    mock_generate.assert_called_once_with(db_session, account, None, conversation.id, platform="whatsapp")

    mock_client_instance.send_text_message.assert_called_once()
    send_kwargs = mock_client_instance.send_text_message.call_args.kwargs
    assert send_kwargs["phone_number_id"] == account.phone_number_id
    assert send_kwargs["recipient_wa_id"] == lead.ig_user_id
    assert send_kwargs["text"] == "Yes, we deliver!"

    db_session.refresh(conversation)
    assert conversation.turn_count == 1

    outbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "outbound")
        .first()
    )
    assert outbound is not None
    assert outbound.status == "sent"
    assert outbound.content == "Yes, we deliver!"

    db_session.refresh(account)
    assert account.ai_messages_sent_today == 1


@skip_if_no_db
def test_account_ai_disabled_hands_off_without_sending(db_session: Session):
    account, lead, conversation, inbound = _seed(db_session, ai_enabled=False)

    with patch("app.workers.tasks.WhatsappClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "ai_disabled"


@skip_if_no_db
def test_turn_limit_hands_off_without_sending(db_session: Session):
    account, lead, conversation, inbound = _seed(db_session, turn_count=8, ai_handoff_after_turns=8)

    with patch("app.workers.tasks.WhatsappClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "turn_limit"


@skip_if_no_db
def test_daily_budget_exhausted_hands_off_without_sending(db_session: Session):
    account, lead, conversation, inbound = _seed(
        db_session, ai_daily_message_cap=5, ai_messages_sent_today=5
    )

    with patch("app.workers.tasks.WhatsappClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "daily_cap_reached"


@skip_if_no_db
def test_ai_reply_send_failure_logged_without_incrementing_turn(db_session: Session):
    account, lead, conversation, inbound = _seed(db_session)

    with patch.object(
        ai_service, "generate_reply", return_value=ai_service.AIReplyResult(success=True, text="Hi!")
    ), patch("app.workers.tasks.WhatsappClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.send_text_message.return_value = MagicMock(
            success=False, provider_message_id=None, error_code="network_error", error_message="boom"
        )
        MockClient.return_value = mock_client_instance

        _run_turn(db_session, conversation.id, inbound.id)

    db_session.refresh(conversation)
    assert conversation.status == "bot_active"  # not handed off — fail closed, retry allowed
    assert conversation.turn_count == 0

    outbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "outbound")
        .first()
    )
    assert outbound is not None
    assert outbound.status == "failed"

    failed_log = (
        db_session.query(AutomationLog)
        .filter(AutomationLog.action == "ai_reply_send_failed", AutomationLog.whatsapp_account_id == account.id)
        .first()
    )
    assert failed_log is not None
