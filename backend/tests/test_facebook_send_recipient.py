"""What Facebook actually receives as `recipient.id` on an outbound AI reply.

These tests execute `process_facebook_ai_conversation_turn` for real (only the
HTTP client is faked) and assert on the recipient id handed to the Send API.
The rest of the Facebook suite stops at `mock_turn.delay.called`, which means
the recipient line is never reached -- reverting it to the original
`recipient_id=lead.ig_user_id` bug produced zero failures across the whole
suite. That gap is what this file closes.

Why it matters: `ig_user_id` holds the *comment's* app-scoped id for a campaign
lead, which is not a valid messaging recipient. Only `facebook_psid` -- learned
from the private reply's Send API response -- is.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.integrations.meta.messaging import MetaMessageResult
from app.models.automation_log import AutomationLog
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_page import FacebookPage
from app.models.lead import Lead
from app.models.message import Message
from app.models.workspace import Workspace
from app.services import conversation_service
from tests.conftest import skip_if_no_db

COMMENT_ASID = "asid_1000000000001"
MESSAGING_PSID = "psid_9000000000009"


def _seed(db: Session, *, facebook_psid: str | None, lead_source: str = "campaign"):
    ws = Workspace(id=uuid4(), name="Default", slug=f"send-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        status="connected",
        ai_enabled=True,
        ai_cold_dm_enabled=True,
        ai_daily_message_cap=100,
        ai_handoff_after_turns=8,
    )
    db.add(page)
    db.commit()

    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo",
        message_template="hi",
        status="active",
        ai_enabled=True,
        ai_handoff_after_turns=8,
    )
    db.add(campaign)
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        # The comment's app-scoped id -- deliberately NOT a valid recipient.
        ig_user_id=COMMENT_ASID,
        facebook_psid=facebook_psid,
        lead_source=lead_source,
        status="new",
    )
    db.add(lead)
    db.commit()

    conversation = conversation_service.get_or_create_conversation(
        db,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="facebook",
        facebook_page_id=page.id,
        facebook_campaign_id=campaign.id,
    )
    return ws, page, campaign, lead, conversation


def _run_turn(db: Session, conversation):
    """Run the real task; fake only the HTTP client and the model call."""
    from app.workers import tasks

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks.facebook_token_service, "get_decrypted_token", return_value="tok"
        ), patch.object(
            tasks.ai_service,
            "generate_reply",
            return_value=tasks.ai_service.AIReplyResult(success=True, text="hello from the bot"),
        ), patch.object(
            tasks, "FacebookClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.send_direct_message.return_value = MetaMessageResult(
                success=True, provider_message_id="m_out_1", raw_response={}
            )
            tasks.process_facebook_ai_conversation_turn(str(conversation.id), str(uuid4()))
            return mock_client_cls.return_value.send_direct_message
    finally:
        db.close = orig_close


@skip_if_no_db
def test_send_uses_facebook_psid_not_ig_user_id(db_session: Session):
    """The whole point of Fix 1: the outbound reply must go to the PSID."""
    ws, page, campaign, lead, conversation = _seed(db_session, facebook_psid=MESSAGING_PSID)

    send = _run_turn(db_session, conversation)

    assert send.called, "the AI reply was never sent"
    kwargs = send.call_args.kwargs
    assert kwargs["recipient_id"] == MESSAGING_PSID, (
        f"sent to {kwargs['recipient_id']!r}; must be the PSID, not the comment ASID"
    )
    assert kwargs["recipient_id"] != lead.ig_user_id
    assert kwargs["page_id"] == page.page_id

    # And the turn completed normally.
    db_session.refresh(conversation)
    assert conversation.turn_count == 1
    outbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "outbound")
        .one()
    )
    assert outbound.status == "sent"


@skip_if_no_db
def test_no_psid_skips_the_send_entirely(db_session: Session):
    """A campaign lead whose private reply never succeeded has no verified
    messaging identity. Sending to its ig_user_id (an ASID) would be a
    guaranteed Meta rejection logged as a failed message, which misattributes
    the cause -- so the send is skipped with an explicit reason instead."""
    ws, page, campaign, lead, conversation = _seed(db_session, facebook_psid=None)

    send = _run_turn(db_session, conversation)

    assert not send.called, "must not attempt a send with no verified messaging identity"

    # No phantom outbound message row.
    assert (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "outbound")
        .count()
        == 0
    )

    # Not a handoff: an identity problem, not a conversation problem. The
    # thread must stay recoverable once a private reply discloses the PSID.
    db_session.refresh(conversation)
    assert conversation.status == "bot_active"
    assert conversation.handoff_reason is None
    assert conversation.turn_count == 0

    # And the skip is diagnosable from the audit log alone.
    log = (
        db_session.query(AutomationLog)
        .filter(AutomationLog.action == "ai_reply_skipped", AutomationLog.lead_id == lead.id)
        .one()
    )
    assert log.details["reason"] == "no_messaging_identity"


@skip_if_no_db
def test_cold_dm_lead_sends_to_its_own_psid(db_session: Session):
    """A cold-DM lead's ig_user_id and facebook_psid hold the same value, so
    this must keep working -- guards against an over-strict fix."""
    ws = Workspace(id=uuid4(), name="Default", slug=f"send-c-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        status="connected",
        ai_enabled=True,
        ai_cold_dm_enabled=True,
        ai_daily_message_cap=100,
    )
    db_session.add(page)
    db_session.commit()
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        ig_user_id=MESSAGING_PSID,
        facebook_psid=MESSAGING_PSID,
        lead_source="cold_dm",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()
    conversation = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="facebook",
        facebook_page_id=page.id,
    )

    send = _run_turn(db_session, conversation)

    assert send.called
    assert send.call_args.kwargs["recipient_id"] == MESSAGING_PSID
