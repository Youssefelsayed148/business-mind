"""Regression coverage for Facebook's two-ID-namespace problem.

Facebook gives us two different ids for the same human against the same Page:

- A Page-feed comment webhook's `value.from.id` is app-scoped (ASID).
- A Messenger webhook's `messaging[].sender.id`, and the Send API's
  `recipient.id`, are page-scoped (PSID).

Instagram unifies these (comment `from.id` == IGSID), so the Instagram-derived
code stored one value in `leads.ig_user_id` and used it for both comment
identity and messaging identity. Carried over to Facebook unchanged, that meant
a commenter who received a private reply and replied to it was compared
ASID-against-PSID, never matched their own lead, and was silently treated as a
brand new cold DM.

`leads.facebook_psid` holds the messaging identity separately, captured from
the private reply Send API response's `recipient_id`. These tests drive the
full round trip against Postgres: comment -> private reply -> reply in
Messenger, asserting exactly one lead exists and the reply continues that
lead's campaign conversation.

Note this is the *mechanism* test. It cannot prove Meta really returns a PSID
in `recipient_id` for a real Page -- that needs a live account (see the
`send_facebook_private_reply` mock below, which stands in for the real
response shape).
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.integrations.meta.messaging import MetaMessageResult
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
from app.models.facebook_comment import FacebookComment
from app.models.facebook_page import FacebookPage
from app.models.facebook_token import FacebookToken
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db

# Deliberately unlike each other: the whole bug was these two being compared.
COMMENTER_ASID = "asid_1000000000001"
COMMENTER_PSID = "psid_9000000000009"


def _fresh_page_id() -> str:
    return f"page_{uuid4().int % 10_000_000}"


def _seed(db: Session, page_id: str):
    ws = Workspace(id=uuid4(), name="Default", slug=f"psid-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=page_id,
        page_name="Test Page",
        ai_enabled=True,
        ai_cold_dm_enabled=False,
        ai_daily_message_cap=100,
    )
    db.add(page)
    db.commit()

    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo campaign",
        message_template="Hi {username}, here's your promo!",
        match_type="contains",
        status="active",
        cooldown_hours=0,
        ai_enabled=True,
    )
    db.add(campaign)
    db.add(FacebookCampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="promo"))
    db.commit()
    return ws, page, campaign


def _comment_payload(page_id: str, commenter_id: str, comment_id: str) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "post_id": f"{page_id}_post_1",
                            "comment_id": comment_id,
                            "from": {"id": commenter_id, "name": "Commenter Name"},
                            "message": "promo please",
                        },
                    }
                ],
            }
        ],
    }


def _dm_payload(page_id: str, sender_id: str, text: str, mid: str) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": 1700000000,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


def _run_webhook(db: Session, payload: dict, *, mock_name: str):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="page",
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, mock_name
        ) as mock_obj:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_obj


def _send_private_reply(db: Session, page, message_id, *, recipient_id: str | None = COMMENTER_PSID):
    """Run the real send task with only the HTTP client faked, so the
    PSID-capture branch actually executes."""
    from app.workers import tasks

    raw = {"message_id": "m_1"}
    if recipient_id is not None:
        raw["recipient_id"] = recipient_id

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks.facebook_token_service, "get_decrypted_token", return_value="tok"
        ), patch.object(tasks, "FacebookClient") as mock_client_cls:
            mock_client_cls.return_value.send_private_reply.return_value = MetaMessageResult(
                success=True, provider_message_id="m_1", raw_response=raw
            )
            tasks.send_facebook_private_reply(str(message_id))
    finally:
        db.close = orig_close


@skip_if_no_db
def test_commenter_reply_matches_original_lead_not_a_new_one(db_session: Session):
    """The end-to-end case the ASID/PSID mismatch broke."""
    page_id = _fresh_page_id()
    ws, page, campaign = _seed(db_session, page_id)
    db_session.add(
        FacebookToken(id=uuid4(), facebook_page_id=page.id, access_token="enc", status="active")
    )
    db_session.commit()

    # 1. They comment. Lead is created against the comment's ASID.
    _run_webhook(
        db_session,
        _comment_payload(page_id, COMMENTER_ASID, "c_psid_1"),
        mock_name="send_facebook_private_reply",
    )
    lead = db_session.query(Lead).filter(Lead.ig_user_id == COMMENTER_ASID).first()
    assert lead is not None
    assert lead.facebook_psid is None, "PSID is not knowable from the comment webhook"

    # 2. The private reply goes out; Meta's response discloses the PSID.
    message = (
        db_session.query(Message)
        .filter(Message.lead_id == lead.id, Message.message_type == "final_delivery")
        .first()
    )
    assert message is not None
    _send_private_reply(db_session, page, message.id)

    db_session.refresh(lead)
    assert lead.facebook_psid == COMMENTER_PSID

    # 3. They reply in Messenger, which uses the PSID. Before the fix this
    #    matched nothing and (cold DM being disabled) was dropped entirely.
    event, mock_turn = _run_webhook(
        db_session,
        _dm_payload(page_id, COMMENTER_PSID, "yes please", "mid.psid.1"),
        mock_name="process_facebook_ai_conversation_turn",
    )
    assert event.processing_status == "processed"
    assert mock_turn.delay.called, "reply was not dispatched as an AI turn"

    leads = db_session.query(Lead).filter(Lead.facebook_page_id == page.id).all()
    assert len(leads) == 1, f"expected one lead for one human, got {len(leads)}"
    assert leads[0].id == lead.id


@skip_if_no_db
def test_cold_dm_lead_gets_psid_at_creation(db_session: Session):
    """A cold-DM lead's originating event is a Messenger event, so its
    sender.id already is the PSID -- both columns should hold it."""
    page_id = _fresh_page_id()
    ws, page, _ = _seed(db_session, page_id)
    page.ai_cold_dm_enabled = True
    db_session.commit()

    _run_webhook(
        db_session,
        _dm_payload(page_id, COMMENTER_PSID, "hello", "mid.psid.2"),
        mock_name="process_facebook_ai_conversation_turn",
    )

    lead = db_session.query(Lead).filter(Lead.facebook_page_id == page.id).one()
    assert lead.lead_source == "cold_dm"
    assert lead.ig_user_id == COMMENTER_PSID
    assert lead.facebook_psid == COMMENTER_PSID


@skip_if_no_db
def test_legacy_cold_dm_lead_without_psid_is_backfilled(db_session: Session):
    """Rows created before facebook_psid existed match on ig_user_id and get
    the column populated on their next inbound message."""
    page_id = _fresh_page_id()
    ws, page, _ = _seed(db_session, page_id)

    legacy = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        ig_user_id=COMMENTER_PSID,
        facebook_psid=None,
        lead_source="cold_dm",
        status="new",
    )
    db_session.add(legacy)
    db_session.commit()
    page.ai_cold_dm_enabled = True
    db_session.commit()

    _run_webhook(
        db_session,
        _dm_payload(page_id, COMMENTER_PSID, "still here", "mid.psid.3"),
        mock_name="process_facebook_ai_conversation_turn",
    )

    db_session.refresh(legacy)
    assert legacy.facebook_psid == COMMENTER_PSID
    assert db_session.query(Lead).filter(Lead.facebook_page_id == page.id).count() == 1


@skip_if_no_db
def test_missing_recipient_id_does_not_break_a_delivered_message(db_session: Session):
    """If Meta returns no recipient_id, the message still counts as sent --
    recording the PSID is best-effort, never a reason to undo delivery."""
    page_id = _fresh_page_id()
    ws, page, campaign = _seed(db_session, page_id)
    db_session.add(
        FacebookToken(id=uuid4(), facebook_page_id=page.id, access_token="enc", status="active")
    )
    db_session.commit()

    _run_webhook(
        db_session,
        _comment_payload(page_id, COMMENTER_ASID, "c_psid_2"),
        mock_name="send_facebook_private_reply",
    )
    lead = db_session.query(Lead).filter(Lead.ig_user_id == COMMENTER_ASID).one()
    message = (
        db_session.query(Message)
        .filter(Message.lead_id == lead.id, Message.message_type == "final_delivery")
        .one()
    )

    _send_private_reply(db_session, page, message.id, recipient_id=None)

    db_session.refresh(message)
    db_session.refresh(lead)
    assert message.status == "sent"
    assert lead.facebook_psid is None


@skip_if_no_db
def test_psid_already_held_by_another_lead_is_left_alone(db_session: Session):
    """Same human as both a cold-DM lead and a campaign lead: don't point two
    lead rows at one messaging identity."""
    page_id = _fresh_page_id()
    ws, page, campaign = _seed(db_session, page_id)
    db_session.add(
        FacebookToken(id=uuid4(), facebook_page_id=page.id, access_token="enc", status="active")
    )
    existing = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        ig_user_id=COMMENTER_PSID,
        facebook_psid=COMMENTER_PSID,
        lead_source="cold_dm",
        status="new",
    )
    db_session.add(existing)
    db_session.commit()

    _run_webhook(
        db_session,
        _comment_payload(page_id, COMMENTER_ASID, "c_psid_3"),
        mock_name="send_facebook_private_reply",
    )
    campaign_lead = db_session.query(Lead).filter(Lead.ig_user_id == COMMENTER_ASID).one()
    message = (
        db_session.query(Message)
        .filter(Message.lead_id == campaign_lead.id, Message.message_type == "final_delivery")
        .one()
    )

    _send_private_reply(db_session, page, message.id)

    db_session.refresh(campaign_lead)
    db_session.refresh(existing)
    assert campaign_lead.facebook_psid is None, "must not claim a PSID another lead holds"
    assert existing.facebook_psid == COMMENTER_PSID
