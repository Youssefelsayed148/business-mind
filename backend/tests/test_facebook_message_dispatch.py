"""Coverage for the Facebook Messenger inbound-message dispatch path: both
the cold-DM entry point (unknown sender messages a Page directly) and the
campaign-continuation path (a lead who came from a matched comment replies
in Messenger) — the Facebook equivalent of the Instagram
`for msg_evt in message_events:` loop, since Facebook has the same
campaign-vs-cold_dm branch Instagram does (unlike WhatsApp).
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_page import FacebookPage
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _fresh_page_id() -> str:
    return f"page_{uuid4().int % 10_000_000}"


def _seed_page(db: Session, page_id: str, *, ai_enabled: bool, ai_cold_dm_enabled: bool = False) -> tuple[Workspace, FacebookPage]:
    ws = Workspace(id=uuid4(), name="Default", slug=f"fbmsg-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=page_id,
        ai_enabled=ai_enabled,
        ai_cold_dm_enabled=ai_cold_dm_enabled,
        ai_daily_message_cap=100,
    )
    db.add(page)
    db.commit()
    return ws, page


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


def _run_webhook(db: Session, payload: dict):
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
            tasks, "process_facebook_ai_conversation_turn"
        ) as mock_turn:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_turn


@skip_if_no_db
def test_cold_dm_creates_lead_and_dispatches_when_enabled(db_session: Session):
    page_id = _fresh_page_id()
    ws, page = _seed_page(db_session, page_id, ai_enabled=True, ai_cold_dm_enabled=True)

    event, mock_turn = _run_webhook(db_session, _dm_payload(page_id, "sender_1", "hi there", "mid.1"))
    assert event.processing_status == "processed"
    assert mock_turn.delay.called

    lead = db_session.query(Lead).filter(Lead.ig_user_id == "sender_1").first()
    assert lead is not None
    assert lead.platform == "facebook"
    assert lead.facebook_page_id == page.id
    assert lead.lead_source == "cold_dm"


@skip_if_no_db
def test_cold_dm_disabled_skips_without_creating_lead(db_session: Session):
    page_id = _fresh_page_id()
    _seed_page(db_session, page_id, ai_enabled=True, ai_cold_dm_enabled=False)

    event, mock_turn = _run_webhook(db_session, _dm_payload(page_id, "sender_2", "hi", "mid.2"))
    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
    assert db_session.query(Lead).filter(Lead.ig_user_id == "sender_2").first() is None


@skip_if_no_db
def test_account_ai_disabled_skips_entirely(db_session: Session):
    page_id = _fresh_page_id()
    _seed_page(db_session, page_id, ai_enabled=False)

    event, mock_turn = _run_webhook(db_session, _dm_payload(page_id, "sender_3", "hi", "mid.3"))
    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
    assert db_session.query(Lead).filter(Lead.ig_user_id == "sender_3").first() is None


@skip_if_no_db
def test_campaign_lead_continues_via_most_recent_facebook_campaign(db_session: Session):
    page_id = _fresh_page_id()
    ws, page = _seed_page(db_session, page_id, ai_enabled=True)

    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo",
        message_template="hi",
        status="active",
        ai_enabled=True,
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        instagram_account_id=None,
        ig_user_id="sender_4",
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    # The Message row created when the comment matched is what records which
    # facebook_campaigns row this lead came from (Lead.source_campaign_id is
    # FK'd to Instagram's campaigns and can't represent this).
    db_session.add(
        Message(
            id=uuid4(),
            campaign_id=None,
            comment_id=None,
            facebook_campaign_id=campaign.id,
            facebook_comment_id=None,
            lead_id=lead.id,
            rendered_body="original delivery",
            message_type="final_delivery",
            status="sent",
        )
    )
    db_session.commit()

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(page_id, "sender_4", "what are your hours?", "mid.4")
    )
    assert event.processing_status == "processed"
    assert mock_turn.delay.called


@skip_if_no_db
def test_campaign_lead_with_no_ai_enabled_campaign_skips(db_session: Session):
    page_id = _fresh_page_id()
    ws, page = _seed_page(db_session, page_id, ai_enabled=True)

    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo",
        message_template="hi",
        status="active",
        ai_enabled=False,
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        instagram_account_id=None,
        ig_user_id="sender_5",
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    db_session.add(
        Message(
            id=uuid4(),
            campaign_id=None,
            comment_id=None,
            facebook_campaign_id=campaign.id,
            facebook_comment_id=None,
            lead_id=lead.id,
            rendered_body="original delivery",
            message_type="final_delivery",
            status="sent",
        )
    )
    db_session.commit()

    event, mock_turn = _run_webhook(db_session, _dm_payload(page_id, "sender_5", "hi again", "mid.5"))
    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
