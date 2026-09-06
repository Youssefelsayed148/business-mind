"""Coverage for process_facebook_ai_conversation_turn — the Facebook
equivalent of process_ai_conversation_turn. Verifies it reuses the shared
conversation_service budget/turn/handoff helpers, that ai_service.generate_reply
is called with platform="facebook", and — unlike WhatsApp's always-cold-DM
task — that the campaign-aware branch (handoff_after_turns from the
facebook_campaigns row, not the page) works via conversation.facebook_campaign_id.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_page import FacebookPage
from app.models.facebook_token import FacebookToken
from app.models.lead import Lead
from app.models.message import Message
from app.models.workspace import Workspace
from app.services import ai_service
from app.utils.crypto import encrypt_text
from tests.conftest import skip_if_no_db


def _seed(
    db: Session,
    *,
    ai_enabled: bool = True,
    ai_cold_dm_enabled: bool = True,
    turn_count: int = 0,
    ai_handoff_after_turns: int = 8,
    ai_daily_message_cap: int = 100,
    ai_messages_sent_today: int = 0,
    campaign_ai_enabled: bool | None = None,
    campaign_handoff_after_turns: int | None = None,
):
    ws = Workspace(id=uuid4(), name="Default", slug=f"fb-turn-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        page_name="Test Page",
        ai_enabled=ai_enabled,
        ai_cold_dm_enabled=ai_cold_dm_enabled,
        ai_handoff_after_turns=ai_handoff_after_turns,
        ai_daily_message_cap=ai_daily_message_cap,
        ai_messages_sent_today=ai_messages_sent_today,
        ai_budget_reset_at=datetime.now(timezone.utc),
    )
    db.add(page)
    db.commit()

    db.add(FacebookToken(id=uuid4(), facebook_page_id=page.id, access_token=encrypt_text("fake_token")))
    db.commit()

    campaign = None
    if campaign_ai_enabled is not None:
        campaign = FacebookCampaign(
            id=uuid4(),
            workspace_id=ws.id,
            facebook_page_id=page.id,
            name="Promo",
            message_template="hi",
            status="active",
            ai_enabled=campaign_ai_enabled,
            ai_handoff_after_turns=campaign_handoff_after_turns or 8,
        )
        db.add(campaign)
        db.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        instagram_account_id=None,
        ig_user_id="fb_user_1",
        # The messaging identity. Every real Facebook lead has one by the time
        # it can have a conversation: a cold-DM lead gets it at creation (its
        # originating event is a Messenger event) and a campaign lead gets it
        # from the private reply's Send API response. Without it the turn is
        # correctly aborted, since ig_user_id is not a valid recipient.
        facebook_psid="fb_psid_1",
        ig_username="Test User",
        lead_source="campaign" if campaign else "cold_dm",
        status="new",
    )
    db.add(lead)
    db.commit()

    conversation = Conversation(
        id=uuid4(),
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        facebook_campaign_id=campaign.id if campaign else None,
        platform="facebook",
        facebook_page_id=page.id,
        instagram_account_id=None,
        status="bot_active",
        turn_count=turn_count,
    )
    db.add(conversation)
    db.commit()

    inbound = Message(
        id=uuid4(),
        campaign_id=None,
        comment_id=None,
        facebook_campaign_id=campaign.id if campaign else None,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="inbound",
        content="do you deliver?",
        message_type="ai_conversation",
        status="received",
    )
    db.add(inbound)
    db.commit()

    return page, lead, conversation, inbound, campaign


def _run_turn(db: Session, conversation_id, inbound_message_id):
    from app.workers import tasks

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db):
            tasks.process_facebook_ai_conversation_turn(str(conversation_id), str(inbound_message_id))
    finally:
        db.close = orig_close


@skip_if_no_db
def test_happy_path_cold_dm_sends_reply_with_facebook_platform_prompt(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(db_session)

    with patch.object(
        ai_service, "generate_reply", return_value=ai_service.AIReplyResult(success=True, text="Yes, we deliver!")
    ) as mock_generate, patch("app.workers.tasks.FacebookClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.send_direct_message.return_value = MagicMock(
            success=True, provider_message_id="fbmid.out1", error_code=None, error_message=None
        )
        MockClient.return_value = mock_client_instance

        _run_turn(db_session, conversation.id, inbound.id)

    mock_generate.assert_called_once_with(db_session, page, None, conversation.id, platform="facebook")

    mock_client_instance.send_direct_message.assert_called_once()
    send_kwargs = mock_client_instance.send_direct_message.call_args.kwargs
    assert send_kwargs["page_id"] == page.page_id
    # The PSID, not ig_user_id: the latter holds the comment's app-scoped id
    # for a campaign lead and is not a valid Send API recipient. This
    # assertion previously encoded the pre-facebook_psid behaviour.
    assert send_kwargs["recipient_id"] == lead.facebook_psid
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

    db_session.refresh(page)
    assert page.ai_messages_sent_today == 1


@skip_if_no_db
def test_campaign_continuation_uses_campaign_handoff_after_turns(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(
        db_session,
        turn_count=3,
        ai_handoff_after_turns=8,  # page-level cap — should NOT apply here
        campaign_ai_enabled=True,
        campaign_handoff_after_turns=3,  # campaign-level cap — turn_count already at this
    )

    with patch("app.workers.tasks.FacebookClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "turn_limit"


@skip_if_no_db
def test_campaign_ai_disabled_hands_off_without_sending(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(db_session, campaign_ai_enabled=False)

    with patch("app.workers.tasks.FacebookClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "campaign_inactive"


@skip_if_no_db
def test_account_ai_disabled_hands_off_without_sending(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(db_session, ai_enabled=False)

    with patch("app.workers.tasks.FacebookClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "ai_disabled"


@skip_if_no_db
def test_daily_budget_exhausted_hands_off_without_sending(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(
        db_session, ai_daily_message_cap=5, ai_messages_sent_today=5
    )

    with patch("app.workers.tasks.FacebookClient") as MockClient:
        _run_turn(db_session, conversation.id, inbound.id)
        MockClient.assert_not_called()

    db_session.refresh(conversation)
    assert conversation.status == "handed_off"
    assert conversation.handoff_reason == "daily_cap_reached"


@skip_if_no_db
def test_ai_reply_send_failure_logged_without_incrementing_turn(db_session: Session):
    page, lead, conversation, inbound, campaign = _seed(db_session)

    with patch.object(
        ai_service, "generate_reply", return_value=ai_service.AIReplyResult(success=True, text="Hi!")
    ), patch("app.workers.tasks.FacebookClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.send_direct_message.return_value = MagicMock(
            success=False, provider_message_id=None, error_code="network_error", error_message="boom"
        )
        MockClient.return_value = mock_client_instance

        _run_turn(db_session, conversation.id, inbound.id)

    db_session.refresh(conversation)
    assert conversation.status == "bot_active"
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
        .filter(AutomationLog.action == "ai_reply_send_failed", AutomationLog.facebook_page_id == page.id)
        .first()
    )
    assert failed_log is not None
