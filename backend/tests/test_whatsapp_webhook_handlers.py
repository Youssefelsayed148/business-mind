from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.integrations.meta.whatsapp_webhooks import (
    parse_whatsapp_phone_quality_events,
    parse_whatsapp_status_events,
    parse_whatsapp_template_status_events,
)
from app.models.lead import Lead
from app.models.message import Message
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.workspace import Workspace
from app.services.whatsapp_webhook_service import (
    process_whatsapp_phone_quality_events,
    process_whatsapp_status_events,
    process_whatsapp_template_status_events,
)
from tests.conftest import skip_if_no_db


def _changes(field, value, *, entry_id="waba-1", entry_time=1700000300):
    return {"object": "whatsapp_business_account", "entry": [{
        "id": entry_id, "time": entry_time,
        "changes": [{"field": field, "value": value}],
    }]}


def _seed_outreach(db: Session, provider_id="wamid.status"):
    workspace = Workspace(name="W", slug=f"wh-{uuid4().hex[:12]}")
    user = User(email=f"{uuid4().hex}@example.test", password_hash="x", role="admin")
    db.add_all([workspace, user])
    db.flush()
    account = WhatsappAccount(
        workspace_id=workspace.id, phone_number_id=f"phone-{uuid4().hex}",
        whatsapp_business_account_id="waba-1", display_phone_number="+1 (631) 555-1234",
        quality_rating="GREEN",
    )
    db.add(account)
    db.flush()
    lead = Lead(
        workspace_id=workspace.id, platform="whatsapp", whatsapp_account_id=account.id,
        ig_user_id="16315551234", lead_source="cold_dm", status="new",
    )
    template = WhatsappTemplate(
        workspace_id=workspace.id, whatsapp_account_id=account.id,
        meta_template_id="tpl-1", name="welcome", language="en_US",
        category="marketing", status="pending",
    )
    db.add_all([lead, template])
    db.flush()
    contact = WhatsappContact(
        workspace_id=workspace.id, whatsapp_account_id=account.id,
        lead_id=lead.id, wa_id="16315551234",
    )
    db.add(contact)
    db.flush()
    campaign = WhatsappCampaign(
        workspace_id=workspace.id, whatsapp_account_id=account.id,
        template_id=template.id, name="Launch", status="running", created_by=user.id,
        total_recipients=1,
    )
    db.add(campaign)
    db.flush()
    message = Message(
        lead_id=lead.id, whatsapp_campaign_id=campaign.id,
        whatsapp_template_id=template.id, direction="outbound",
        message_type="whatsapp_template", status="queued",
        provider_message_id=provider_id,
    )
    db.add(message)
    db.flush()
    recipient = WhatsappCampaignRecipient(
        campaign_id=campaign.id, contact_id=contact.id,
        message_id=message.id, provider_message_id=provider_id,
    )
    db.add(recipient)
    db.commit()
    return account, template, campaign, message, recipient


@skip_if_no_db
def test_read_then_newer_delivered_does_not_regress_and_counters_are_once(db_session):
    _, _, campaign, message, recipient = _seed_outreach(db_session)
    payload = _changes("messages", {
        "metadata": {"phone_number_id": "phone-1"},
        "statuses": [
            {"id": "wamid.status", "status": "read", "timestamp": "300", "recipient_id": "16315551234"},
            {"id": "wamid.status", "status": "delivered", "timestamp": "400", "recipient_id": "16315551234"},
        ],
    })
    process_whatsapp_status_events(db_session, parse_whatsapp_status_events(payload))
    for row in (campaign, message, recipient):
        db_session.refresh(row)
    assert message.status == "read"
    assert message.read_at == datetime.fromtimestamp(300, tz=timezone.utc)
    assert recipient.status == "read"
    assert (campaign.sent_count, campaign.delivered_count, campaign.read_count) == (1, 1, 1)


@skip_if_no_db
def test_same_second_delivered_then_sent_does_not_regress(db_session):
    _, _, campaign, message, recipient = _seed_outreach(
        db_session, "wamid.same-second"
    )
    payload = _changes("messages", {
        "statuses": [
            {"id": "wamid.same-second", "status": "delivered", "timestamp": "200"},
            {"id": "wamid.same-second", "status": "sent", "timestamp": "200"},
        ],
    })
    process_whatsapp_status_events(db_session, parse_whatsapp_status_events(payload))
    for row in (campaign, message, recipient):
        db_session.refresh(row)
    assert message.status == "delivered"
    assert recipient.status == "delivered"
    assert message.delivered_at == datetime.fromtimestamp(200, tz=timezone.utc)
    assert (campaign.sent_count, campaign.delivered_count, campaign.read_count) == (1, 1, 0)


@skip_if_no_db
@pytest.mark.parametrize(
    ("meta_code", "retryable"),
    [
        (131026, False),
        (131049, False),
        (131048, True),
        (130429, True),
        (132000, False),
        (132012, False),
    ],
)
def test_failed_status_retains_numeric_meta_code_and_retryability(
    db_session, meta_code, retryable
):
    provider_id = f"wamid.failed.{meta_code}"
    _, _, campaign, message, recipient = _seed_outreach(db_session, provider_id)
    payload = _changes("messages", {"statuses": [{
        "id": provider_id, "status": "failed", "timestamp": "400",
        "errors": [{"code": meta_code, "title": "Meta send error", "error_data": {"details": "Delivery failed"}}],
    }]})
    process_whatsapp_status_events(db_session, parse_whatsapp_status_events(payload))
    for row in (campaign, message, recipient):
        db_session.refresh(row)
    assert message.status == "failed"
    assert message.error_code == str(meta_code)
    assert message.retryable is retryable
    assert recipient.error_code == str(meta_code)
    assert campaign.failed_count == 1


@skip_if_no_db
def test_template_status_updates_confirmed_state(db_session):
    account, template, _, _, _ = _seed_outreach(db_session)
    template_payload = _changes("message_template_status_update", {
        "event": "APPROVED", "message_template_id": "tpl-1",
        "message_template_name": "welcome", "message_template_language": "en_US",
    }, entry_time=1700000400)
    process_whatsapp_template_status_events(
        db_session, parse_whatsapp_template_status_events(template_payload)
    )
    db_session.refresh(template)
    assert template.status == "approved"
    assert template.last_synced_at == datetime.fromtimestamp(1700000400, tz=timezone.utc)


@skip_if_no_db
@pytest.mark.parametrize("health_event", ["FLAGGED", "DOWNGRADE"])
def test_phone_quality_risk_events_pause_outreach_without_health_poll_timestamp(
    db_session, health_event
):
    account, _, _, _, _ = _seed_outreach(db_session)
    quality_payload = _changes("phone_number_quality_update", {
        "display_phone_number": "+1 631 555 1234",
        "event": health_event,
        "current_limit": "TIER_1K",
    }, entry_time=1700000500)
    process_whatsapp_phone_quality_events(
        db_session, parse_whatsapp_phone_quality_events(quality_payload)
    )
    db_session.refresh(account)
    assert account.outreach_paused is True
    assert account.outreach_paused_reason == "phone_number_flagged"
    assert account.messaging_limit_tier == "TIER_1K"
    assert account.health_checked_at is None


@skip_if_no_db
def test_phone_quality_non_risk_event_does_not_unpause_outreach(db_session):
    account, _, _, _, _ = _seed_outreach(db_session)
    account.outreach_paused = True
    account.outreach_paused_reason = "phone_number_flagged"
    db_session.commit()
    payload = _changes("phone_number_quality_update", {
        "display_phone_number": "+1 631 555 1234",
        "event": "UNFLAGGED",
        "current_limit": "TIER_10K",
    })
    process_whatsapp_phone_quality_events(
        db_session, parse_whatsapp_phone_quality_events(payload)
    )
    db_session.refresh(account)
    assert account.outreach_paused is True
    assert account.outreach_paused_reason == "phone_number_flagged"
    assert account.health_checked_at is None
