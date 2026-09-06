"""Disconnecting a WhatsApp number or a Facebook Page must actually stop the bot.

Both platforms use a *soft* disconnect (`status = "disconnected"`) rather than
Instagram's destructive delete, so that reconnecting restores the account with
its leads, conversations and campaign history intact. That design is only
correct if every dispatch path honours `status` -- otherwise a "disconnected"
account keeps sending real AI replies using its retained token, which is what
these tests pin down.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
from app.models.facebook_page import FacebookPage
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _run_webhook(db: Session, payload: dict, *, mock_name: str):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type=payload["object"],
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


# --- WhatsApp ---------------------------------------------------------------


def _wa_payload(phone_number_id: str, sender: str, mid: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"wa_id": sender, "profile": {"name": "Someone"}}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": mid,
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _seed_whatsapp(db: Session, *, status: str) -> WhatsappAccount:
    ws = Workspace(id=uuid4(), name="Default", slug=f"disc-wa-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()
    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=f"pn_{uuid4().int % 10_000_000}",
        status=status,
        ai_enabled=True,
        ai_daily_message_cap=100,
    )
    db.add(account)
    db.commit()
    return account


@skip_if_no_db
def test_disconnected_whatsapp_account_does_not_dispatch(db_session: Session):
    account = _seed_whatsapp(db_session, status="disconnected")

    event, mock_turn = _run_webhook(
        db_session,
        _wa_payload(account.phone_number_id, "20100000001", "wamid.disc.1"),
        mock_name="process_whatsapp_ai_conversation_turn",
    )

    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
    assert db_session.query(Lead).filter(Lead.whatsapp_account_id == account.id).count() == 0


@skip_if_no_db
def test_connected_whatsapp_account_still_dispatches(db_session: Session):
    """Guard against the status gate being too broad."""
    account = _seed_whatsapp(db_session, status="connected")

    event, mock_turn = _run_webhook(
        db_session,
        _wa_payload(account.phone_number_id, "20100000002", "wamid.disc.2"),
        mock_name="process_whatsapp_ai_conversation_turn",
    )

    assert event.processing_status == "processed"
    assert mock_turn.delay.called


@skip_if_no_db
def test_whatsapp_ai_turn_aborts_if_disconnected_after_queueing(db_session: Session):
    """A turn queued while connected must not send once disconnected."""
    from app.services import conversation_service
    from app.workers import tasks

    account = _seed_whatsapp(db_session, status="connected")
    lead = Lead(
        id=uuid4(),
        workspace_id=account.workspace_id,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        ig_user_id="20100000003",
        lead_source="cold_dm",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()
    conversation = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=account.workspace_id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
    )

    account.status = "disconnected"
    db_session.commit()

    orig_close = db_session.close
    db_session.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db_session), patch.object(
            tasks, "WhatsappClient"
        ) as mock_client:
            tasks.process_whatsapp_ai_conversation_turn(str(conversation.id), str(uuid4()))
    finally:
        db_session.close = orig_close

    assert not mock_client.called
    db_session.refresh(conversation)
    assert conversation.status == "handed_off"


# --- Facebook ---------------------------------------------------------------


def _seed_facebook(db: Session, *, status: str, keyword: str = "promo"):
    ws = Workspace(id=uuid4(), name="Default", slug=f"disc-fb-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        status=status,
        ai_enabled=True,
        ai_cold_dm_enabled=True,
        ai_daily_message_cap=100,
    )
    db.add(page)
    db.commit()
    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo",
        message_template="hi",
        match_type="contains",
        status="active",
        cooldown_hours=0,
    )
    db.add(campaign)
    db.add(FacebookCampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword=keyword))
    db.commit()
    return page, campaign


def _fb_dm_payload(page_id: str, sender: str, mid: str) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": sender},
                        "recipient": {"id": page_id},
                        "timestamp": 1700000000,
                        "message": {"mid": mid, "text": "hello"},
                    }
                ],
            }
        ],
    }


def _fb_comment_payload(page_id: str, commenter: str, comment_id: str) -> dict:
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
                            "from": {"id": commenter, "name": "Someone"},
                            "message": "promo please",
                        },
                    }
                ],
            }
        ],
    }


@skip_if_no_db
def test_disconnected_page_does_not_dispatch_messages(db_session: Session):
    page, _ = _seed_facebook(db_session, status="disconnected")

    event, mock_turn = _run_webhook(
        db_session,
        _fb_dm_payload(page.page_id, "psid_disc_1", "mid.disc.1"),
        mock_name="process_facebook_ai_conversation_turn",
    )

    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
    assert db_session.query(Lead).filter(Lead.facebook_page_id == page.id).count() == 0


@skip_if_no_db
def test_disconnected_page_does_not_trigger_campaigns(db_session: Session):
    """The comment path is a separate entry point from the message path."""
    page, _ = _seed_facebook(db_session, status="disconnected")

    event, mock_send = _run_webhook(
        db_session,
        _fb_comment_payload(page.page_id, "asid_disc_1", "c.disc.1"),
        mock_name="send_facebook_private_reply",
    )

    assert event.processing_status == "processed"
    assert not mock_send.delay.called
    assert db_session.query(Message).filter(Message.lead_id.isnot(None)).count() == 0


@skip_if_no_db
def test_connected_page_still_triggers_campaigns(db_session: Session):
    page, _ = _seed_facebook(db_session, status="connected")

    event, mock_send = _run_webhook(
        db_session,
        _fb_comment_payload(page.page_id, "asid_disc_2", "c.disc.2"),
        mock_name="send_facebook_private_reply",
    )

    assert event.processing_status == "processed"
    assert mock_send.delay.called


@skip_if_no_db
def test_queued_facebook_message_is_skipped_if_page_disconnected(db_session: Session):
    """Disconnected between queueing and sending."""
    from app.workers import tasks

    page, campaign = _seed_facebook(db_session, status="connected")
    event, _ = _run_webhook(
        db_session,
        _fb_comment_payload(page.page_id, "asid_disc_3", "c.disc.3"),
        mock_name="send_facebook_private_reply",
    )
    message = db_session.query(Message).filter(Message.facebook_campaign_id == campaign.id).one()

    page.status = "disconnected"
    db_session.commit()

    orig_close = db_session.close
    db_session.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db_session), patch.object(
            tasks, "FacebookClient"
        ) as mock_client:
            tasks.send_facebook_private_reply(str(message.id))
    finally:
        db_session.close = orig_close

    assert not mock_client.called
    db_session.refresh(message)
    assert message.status != "sent"
