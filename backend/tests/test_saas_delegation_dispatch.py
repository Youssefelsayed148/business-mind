"""M-02: delegated-mode inbound branches for WhatsApp and Facebook, and proof
that with delegation off the existing dispatch is untouched."""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.facebook_page import FacebookPage
from app.models.workspace import Workspace
from app.services import saas_delegation_service as delegation
from tests.conftest import skip_if_no_db
from tests.test_facebook_message_dispatch import _dm_payload as fb_payload
from tests.test_whatsapp_message_dispatch import _dm_payload as wa_payload

SECRET = "k" * 40


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import crypto

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    yield
    monkeypatch.setattr(crypto, "_fernet", None)


def _delegate(channel, on=True):
    if on:
        delegation.apply_config(
            channel,
            {
                "saas_connection_id": "11111111-1111-4111-8111-111111111111",
                "saas_base_url": "https://saas.example.com",
                "secret": SECRET,
                "saas_delegation_enabled": True,
            },
        )


def _wa_account(db, *, delegated, ai_enabled=False, status="connected"):
    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    db.add(ws)
    db.flush()
    acc = WhatsappAccount(
        id=uuid4(), workspace_id=ws.id, phone_number_id=f"p{uuid4().hex}", ai_enabled=ai_enabled, status=status
    )
    _delegate(acc, delegated)
    db.add(acc)
    db.commit()
    return acc


def _fb_page(db, *, delegated, ai_enabled=False):
    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    db.add(ws)
    db.flush()
    page = FacebookPage(id=uuid4(), workspace_id=ws.id, page_id=f"pg{uuid4().int % 10**9}", ai_enabled=ai_enabled)
    _delegate(page, delegated)
    db.add(page)
    db.commit()
    return page


def _run(db, payload, event_type):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta", external_event_id=uuid4().hex, event_type=event_type,
        payload=payload, processing_status="pending",
    )
    db.add(event)
    db.commit()
    close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "process_whatsapp_ai_conversation_turn"
        ) as wa_turn, patch.object(tasks, "process_facebook_ai_conversation_turn") as fb_turn, patch.object(
            tasks.ai_service, "generate_reply"
        ) as generate, patch("app.services.saas_inbound._kick") as kick:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = close
    return SimpleResult(wa_turn, fb_turn, generate, kick)


class SimpleResult:
    def __init__(self, wa_turn, fb_turn, generate, kick):
        self.wa_turn, self.fb_turn, self.generate, self.kick = wa_turn, fb_turn, generate, kick

    @property
    def ai_touched(self):
        return self.wa_turn.delay.called or self.fb_turn.delay.called or self.generate.called


def _events(db, channel):
    return db.query(SaasForwardEvent).filter_by(channel_id=channel.id).order_by(SaasForwardEvent.seq).all()


# --- WhatsApp -------------------------------------------------------------


@skip_if_no_db
def test_whatsapp_delegated_forwards_even_with_ai_disabled_and_never_calls_ai(db_session):
    acc = _wa_account(db_session, delegated=True, ai_enabled=False)
    result = _run(db_session, wa_payload(acc, "16315551234", "hello there", "wamid.1"), "whatsapp_business_account")
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    p = event.payload
    conv = db_session.query(Conversation).filter_by(whatsapp_account_id=acc.id).one()
    assert event.event_id == "in:whatsapp:wamid.1" and event.ordering_key == str(conv.id)
    assert p["event_type"] == "message.received" and p["version"] == 1 and p["connection_id"] == "11111111-1111-4111-8111-111111111111"
    assert p["channel"] == "whatsapp" and p["external_contact_id"] == "16315551234"
    assert p["external_conversation_id"] == str(conv.id) and p["external_message_id"] == "wamid.1"
    assert p["type"] == "text" and p["text"] == "hello there"
    assert p["contact"] == {"name": "Test User", "phone": "+16315551234"}
    assert p["received_at"] == "2023-11-14T22:13:20Z" and p["window_expires_at"] == "2023-11-15T22:13:20Z"
    assert "origin" not in p
    result.kick.assert_called_once_with(str(conv.id))
    inbound = db_session.query(Message).filter_by(conversation_id=conv.id).one()
    assert inbound.direction == "inbound" and inbound.content == "hello there"


@skip_if_no_db
def test_whatsapp_delegated_forwards_unsupported_types_but_not_reactions(db_session):
    acc = _wa_account(db_session, delegated=True)
    image = wa_payload(acc, "16315551234", "x", "wamid.img")
    msg = image["entry"][0]["changes"][0]["value"]["messages"][0]
    msg.pop("text")
    msg["type"] = "image"
    _run(db_session, image, "whatsapp_business_account")
    reaction = wa_payload(acc, "16315551234", "x", "wamid.react")
    msg = reaction["entry"][0]["changes"][0]["value"]["messages"][0]
    msg.pop("text")
    msg["type"] = "reaction"
    _run(db_session, reaction, "whatsapp_business_account")
    [event] = _events(db_session, acc)
    assert event.payload["type"] == "unsupported" and "text" not in event.payload


@skip_if_no_db
def test_whatsapp_delegated_does_not_forward_consent_commands(db_session):
    acc = _wa_account(db_session, delegated=True)
    result = _run(db_session, wa_payload(acc, "16315551234", "STOP", "wamid.stop"), "whatsapp_business_account")
    assert _events(db_session, acc) == [] and not result.ai_touched and not result.kick.called


@skip_if_no_db
def test_whatsapp_delegated_disconnected_account_is_still_forwarded(db_session):
    # F-05: the SaaS stores the message and flags a human; replies fail with
    # channel_disconnected. Nothing is dropped silently.
    acc = _wa_account(db_session, delegated=True, status="disconnected")
    result = _run(db_session, wa_payload(acc, "16315551234", "hi", "wamid.d"), "whatsapp_business_account")
    [event] = _events(db_session, acc)
    assert event.event_id == "in:whatsapp:wamid.d" and event.payload["text"] == "hi"
    assert not result.ai_touched


@skip_if_no_db
def test_same_message_id_queued_twice_forwards_once(db_session):
    # Webhook-level dedupe (check_and_mark_processed) is the first line; the
    # outbox's unique event_id is the second. Exercise the second directly.
    from app.models.lead import Lead
    from app.services.saas_inbound import delegate_inbound

    acc = _wa_account(db_session, delegated=True)
    lead = Lead(id=uuid4(), workspace_id=acc.workspace_id, whatsapp_account_id=acc.id,
                platform="whatsapp", ig_user_id="16315551234", lead_source="cold_dm", status="new")
    db_session.add(lead)
    db_session.commit()
    for _ in range(2):
        delegate_inbound(
            db_session, platform="whatsapp", channel=acc, lead=lead, external_contact_id="16315551234",
            contact={}, text="hi", message_type="text", external_message_id="wamid.dup",
            timestamp="1700000000", received_at=datetime.now(timezone.utc), kick=False,
        )
    assert len(_events(db_session, acc)) == 1


@skip_if_no_db
def test_whatsapp_delegation_off_behaves_as_before(db_session):
    acc = _wa_account(db_session, delegated=False, ai_enabled=True)
    result = _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.off"), "whatsapp_business_account")
    assert result.wa_turn.delay.called
    assert _events(db_session, acc) == [] and not result.kick.called


@skip_if_no_db
def test_whatsapp_delegation_off_with_ai_disabled_still_skips(db_session):
    acc = _wa_account(db_session, delegated=False, ai_enabled=False)
    result = _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.off2"), "whatsapp_business_account")
    assert not result.ai_touched and _events(db_session, acc) == []


# --- Facebook -------------------------------------------------------------


@skip_if_no_db
def test_facebook_delegated_forwards_with_ai_and_cold_dm_off(db_session):
    page = _fb_page(db_session, delegated=True, ai_enabled=False)
    result = _run(db_session, fb_payload(page.page_id, "psid-1", "hi page", "mid.1"), "page")
    assert not result.ai_touched
    [event] = _events(db_session, page)
    p = event.payload
    conv = db_session.query(Conversation).filter_by(facebook_page_id=page.id).one()
    assert event.event_id == "in:facebook:mid.1"
    assert p["channel"] == "messenger" and p["external_contact_id"] == "psid-1"
    assert p["external_message_id"] == "mid.1" and p["text"] == "hi page" and p["type"] == "text"
    assert p["external_conversation_id"] == str(conv.id) and p["contact"] == {}
    result.kick.assert_called_once_with(str(conv.id))


@skip_if_no_db
def test_facebook_second_message_reuses_conversation_and_keeps_order(db_session):
    page = _fb_page(db_session, delegated=True)
    _run(db_session, fb_payload(page.page_id, "psid-1", "one", "mid.a"), "page")
    _run(db_session, fb_payload(page.page_id, "psid-1", "two", "mid.b"), "page")
    events = _events(db_session, page)
    assert [e.payload["text"] for e in events] == ["one", "two"]
    assert events[0].ordering_key == events[1].ordering_key
    assert db_session.query(Conversation).filter_by(facebook_page_id=page.id).count() == 1


@skip_if_no_db
def test_facebook_delegation_off_with_ai_disabled_skips_as_before(db_session):
    page = _fb_page(db_session, delegated=False, ai_enabled=False)
    result = _run(db_session, fb_payload(page.page_id, "psid-1", "hi", "mid.off"), "page")
    assert not result.ai_touched and _events(db_session, page) == []
    assert db_session.query(Conversation).filter_by(facebook_page_id=page.id).count() == 0


@skip_if_no_db
def test_facebook_delegated_disconnected_page_is_not_forwarded(db_session):
    page = _fb_page(db_session, delegated=True)
    page.status = "disconnected"
    db_session.commit()
    _run(db_session, fb_payload(page.page_id, "psid-1", "hi", "mid.x"), "page")
    assert _events(db_session, page) == []


# --- Instagram -------------------------------------------------------------

from app.models.instagram_account import InstagramAccount  # noqa: E402
from tests.test_cold_dm_ai_dispatch import _dm_payload as ig_payload  # noqa: E402


def _ig_account(db, *, delegated, ai_enabled=False, cold=False, status="connected"):
    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    db.add(ws)
    db.flush()
    acc = InstagramAccount(
        id=uuid4(), workspace_id=ws.id, ig_user_id=f"178414{uuid4().int % 10**10:010d}",
        ai_enabled=ai_enabled, ai_cold_dm_enabled=cold, status=status,
    )
    _delegate(acc, delegated)
    db.add(acc)
    db.commit()
    return acc


@skip_if_no_db
def test_instagram_delegated_forwards_with_ai_and_cold_dm_off(db_session):
    from app.workers import tasks

    acc = _ig_account(db_session, delegated=True, ai_enabled=False, cold=False)
    with patch.object(tasks, "process_ai_conversation_turn") as ig_turn:
        result = _run(db_session, ig_payload(acc.ig_user_id, "9000011", "price?", "mid.ig1"), "instagram")
        assert not ig_turn.delay.called
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    p = event.payload
    conv = db_session.query(Conversation).filter_by(instagram_account_id=acc.id).one()
    assert event.event_id == "in:instagram:mid.ig1" and event.ordering_key == str(conv.id)
    assert p["channel"] == "instagram" and p["external_contact_id"] == "9000011"
    assert p["text"] == "price?" and p["external_conversation_id"] == str(conv.id)
    assert p["received_at"].startswith("2026-")  # epoch-ms timestamp parsed as milliseconds
    result.kick.assert_called_once_with(str(conv.id))


@skip_if_no_db
def test_instagram_delegated_reuses_existing_campaign_conversation(db_session):
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from app.services import conversation_service

    acc = _ig_account(db_session, delegated=True)
    campaign = Campaign(id=uuid4(), workspace_id=acc.workspace_id, instagram_account_id=acc.id,
                        name="Summer promo", status="active")
    db_session.add(campaign)
    lead = Lead(id=uuid4(), workspace_id=acc.workspace_id, instagram_account_id=acc.id,
                ig_user_id="9000012", lead_source="campaign", source_campaign_id=campaign.id, status="new")
    db_session.add(lead)
    db_session.commit()
    existing = conversation_service.get_or_create_conversation(
        db_session, workspace_id=acc.workspace_id, lead_id=lead.id,
        campaign_id=campaign.id, instagram_account_id=acc.id,
    )
    db_session.add(Message(campaign_id=campaign.id, lead_id=lead.id, direction="outbound",
                           message_type="final_delivery", rendered_body="Here is your promo code",
                           status="sent"))
    db_session.commit()

    # T1-P3: queued/failed campaign messages must never supply the origin.
    for status, body in (("queued", "queued text"), ("failed", "failed text")):
        db_session.add(Message(campaign_id=campaign.id, lead_id=lead.id, direction="outbound",
                               message_type="final_delivery", rendered_body=body, status=status))
    db_session.commit()

    _run(db_session, ig_payload(acc.ig_user_id, "9000012", "thanks, how do I use it?", "mid.ig2"), "instagram")
    [event] = _events(db_session, acc)
    assert event.ordering_key == str(existing.id)
    assert db_session.query(Conversation).filter_by(instagram_account_id=acc.id).count() == 1
    assert event.payload["origin"] == {
        "type": "campaign", "campaign_name": "Summer promo",
        "opening_message_text": "Here is your promo code", "campaign_ref": str(campaign.id),
    }


@skip_if_no_db
def test_instagram_delegation_off_behaves_as_before(db_session):
    from app.workers import tasks

    acc = _ig_account(db_session, delegated=False, ai_enabled=True, cold=True)
    with patch.object(tasks, "process_ai_conversation_turn") as ig_turn:
        result = _run(db_session, ig_payload(acc.ig_user_id, "9000013", "hello", "mid.ig3"), "instagram")
        # _run patches the WA/FB turns only; the IG turn is patched here.
        assert ig_turn.delay.called
    assert _events(db_session, acc) == [] and not result.kick.called


@skip_if_no_db
def test_instagram_delegation_off_with_ai_disabled_still_skips(db_session):
    acc = _ig_account(db_session, delegated=False, ai_enabled=False)
    result = _run(db_session, ig_payload(acc.ig_user_id, "9000014", "hello", "mid.ig4"), "instagram")
    assert _events(db_session, acc) == [] and not result.ai_touched
    assert db_session.query(Conversation).filter_by(instagram_account_id=acc.id).count() == 0


@skip_if_no_db
def test_instagram_delegated_disconnected_account_is_not_forwarded(db_session):
    acc = _ig_account(db_session, delegated=True, status="disconnected")
    _run(db_session, ig_payload(acc.ig_user_id, "9000015", "hi", "mid.ig5"), "instagram")
    assert _events(db_session, acc) == []
