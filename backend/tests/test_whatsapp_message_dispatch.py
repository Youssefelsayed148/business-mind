"""Database coverage for Phase 1's inbound WhatsApp pipeline."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _fresh_phone_number_id() -> str:
    return f"phone_{uuid4().hex}"


def _seed_account(db: Session, *, ai_enabled=False, **settings) -> WhatsappAccount:
    workspace = Workspace(name="Default", slug=f"wa-{uuid4().hex[:12]}")
    db.add(workspace)
    db.flush()
    account = WhatsappAccount(
        workspace_id=workspace.id,
        phone_number_id=_fresh_phone_number_id(),
        display_phone_number="+1 650 555 1111",
        ai_enabled=ai_enabled,
        ai_daily_message_cap=100,
        ai_handoff_after_turns=8,
        **settings,
    )
    db.add(account)
    db.commit()
    return account


def _dm_payload(account, sender, text, message_id, *, timestamp="1700000000", referral=None):
    message = {
        "from": sender, "id": message_id, "timestamp": timestamp,
        "text": {"body": text}, "type": "text",
    }
    if referral is not None:
        message["referral"] = referral
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{
        "field": "messages", "value": {
            "metadata": {"phone_number_id": account.phone_number_id},
            "contacts": [{"profile": {"name": "Test User"}, "wa_id": sender}],
            "messages": [message],
        },
    }]}]}


def _run_webhook(db: Session, payload: dict):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta", external_event_id=uuid4().hex,
        event_type="whatsapp_business_account", payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()
    original_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "process_whatsapp_ai_conversation_turn"
        ) as mock_turn:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = original_close
    db.refresh(event)
    return event, mock_turn


@skip_if_no_db
def test_identity_is_upserted_before_ai_disabled_exit_and_plain_text_never_infers_consent(db_session):
    account = _seed_account(db_session, ai_enabled=False)
    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account, "+1 (631) 555-1234", "hello", "wamid.plain")
    )
    assert event.processing_status == "processed"
    assert not mock_turn.delay.called
    lead = db_session.query(Lead).filter(Lead.whatsapp_account_id == account.id).one()
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    assert lead.ig_user_id == "16315551234"
    assert contact.wa_id == "16315551234"
    assert contact.last_inbound_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert contact.marketing_consent == "unknown"
    assert db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).count() == 0


@skip_if_no_db
def test_non_text_inbound_still_upserts_contact_without_ai_dispatch(db_session):
    account = _seed_account(db_session, ai_enabled=True)
    payload = _dm_payload(account, "16315551234", "placeholder", "wamid.image")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = "image"
    message["image"] = {"id": "media-1"}
    _, mock_turn = _run_webhook(db_session, payload)
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    assert contact.last_inbound_at is not None
    assert contact.marketing_consent == "unknown"
    assert not mock_turn.delay.called


@skip_if_no_db
def test_formatted_existing_lead_is_found_without_rewriting(db_session):
    account = _seed_account(db_session)
    existing = Lead(
        workspace_id=account.workspace_id, platform="whatsapp",
        whatsapp_account_id=account.id, instagram_account_id=None,
        ig_user_id="+1 (631) 555-1234", lead_source="cold_dm", status="new",
    )
    db_session.add(existing)
    db_session.commit()
    original_id = existing.id
    _run_webhook(db_session, _dm_payload(account, "16315551234", "hello", "wamid.existing"))
    leads = db_session.query(Lead).filter_by(whatsapp_account_id=account.id).all()
    assert [(lead.id, lead.ig_user_id) for lead in leads] == [(original_id, "+1 (631) 555-1234")]
    assert db_session.query(WhatsappContact).filter_by(lead_id=original_id, wa_id="16315551234").one()


@skip_if_no_db
def test_opt_out_is_honoured_with_ai_disabled_and_writes_consent_event(db_session):
    account = _seed_account(db_session, ai_enabled=False)
    _, mock_turn = _run_webhook(
        db_session, _dm_payload(account, "16315551234", "  STOP  ", "wamid.stop")
    )
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    consent = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "opted_out"
    assert contact.consent_source == "inbound_keyword"
    assert consent.event_type == "opt_out"
    assert consent.evidence["keyword"] == "stop"
    assert not mock_turn.delay.called


@skip_if_no_db
def test_cancel_is_not_default_opt_out_and_is_passed_to_ai(db_session):
    account = _seed_account(db_session, ai_enabled=True)
    _, mock_turn = _run_webhook(
        db_session, _dm_payload(account, "16315551234", "cancel", "wamid.cancel")
    )
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    assert contact.marketing_consent == "unknown"
    assert db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).count() == 0
    assert mock_turn.delay.called


@skip_if_no_db
def test_account_keyword_override_is_exact(db_session):
    account = _seed_account(db_session, opt_out_keywords=["HALT"])
    _run_webhook(db_session, _dm_payload(account, "16315551234", "STOP", "wamid.default-disabled"))
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    assert contact.marketing_consent == "unknown"
    _run_webhook(db_session, _dm_payload(account, "16315551234", "halt now", "wamid.not-exact"))
    assert contact.marketing_consent == "unknown"
    _run_webhook(db_session, _dm_payload(account, "16315551234", " HALT ", "wamid.override"))
    db_session.refresh(contact)
    assert contact.marketing_consent == "opted_out"


@skip_if_no_db
def test_default_opt_in_keyword_does_not_grant_consent_from_unknown(db_session):
    account = _seed_account(db_session, ai_enabled=False)
    _run_webhook(db_session, _dm_payload(account, "16315551234", "start", "wamid.start"))
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    assert contact.marketing_consent == "unknown"
    assert db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).count() == 0


@skip_if_no_db
def test_default_opt_in_keyword_resubscribes_opted_out_contact(db_session):
    account = _seed_account(db_session, ai_enabled=False)
    _run_webhook(db_session, _dm_payload(account, "16315551234", "stop", "wamid.stop-first"))
    later_opt_in = _dm_payload(account, "16315551234", "start", "wamid.start-after-stop")
    later_opt_in["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = "1700000001"
    _run_webhook(db_session, later_opt_in)
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    events = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).all()
    assert contact.marketing_consent == "opted_in"
    assert sorted(event.event_type for event in events) == ["opt_in", "opt_out"]


@skip_if_no_db
def test_configured_opt_in_keyword_grants_consent_from_unknown(db_session):
    account = _seed_account(db_session, ai_enabled=False, opt_in_keywords=["JOIN"])
    _run_webhook(db_session, _dm_payload(account, "16315551234", " join ", "wamid.join"))
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    consent = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "opted_in"
    assert consent.event_type == "opt_in"


@skip_if_no_db
def test_ctwa_sets_72_hour_window_and_records_evidence_but_not_consent_by_default(db_session):
    account = _seed_account(db_session, ctwa_counts_as_consent=False)
    _run_webhook(db_session, _dm_payload(
        account, "16315551234", "hello", "wamid.ctwa",
        referral={"source_url": "https://example.test/ad", "source_id": "ad-1", "source_type": "ad"},
    ))
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert contact.free_entry_point_expires_at == expected + timedelta(hours=72)
    assert contact.marketing_consent == "unknown"
    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert event.source == "click_to_whatsapp"
    assert event.evidence["temporary_window_only"] is True


@skip_if_no_db
def test_ctwa_flag_does_not_persist_marketing_consent(db_session):
    account = _seed_account(db_session, ctwa_counts_as_consent=True)
    _run_webhook(db_session, _dm_payload(
        account, "16315551234", "hello", "wamid.ctwa-consent",
        referral={"source_url": "https://example.test/ad", "source_id": "ad-1", "source_type": "ad"},
    ))
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=account.id).one()
    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "unknown"
    assert contact.consent_source is None
    assert event.source == "click_to_whatsapp"


@skip_if_no_db
def test_ai_enabled_dispatches_whatsapp_turn(db_session):
    account = _seed_account(db_session, ai_enabled=True)
    _, mock_turn = _run_webhook(
        db_session, _dm_payload(account, "16315551234", "do you deliver?", "wamid.ai")
    )
    lead = db_session.query(Lead).filter_by(whatsapp_account_id=account.id).one()
    conversation = db_session.query(Conversation).filter_by(lead_id=lead.id).one()
    assert conversation.platform == "whatsapp"
    assert mock_turn.delay.called


@skip_if_no_db
def test_raw_only_event_is_recognized_and_stored_without_state_change(db_session):
    payload = {"object": "whatsapp_business_account", "entry": [{
        "id": "waba-raw", "time": 1700000000,
        "changes": [{"field": "account_update", "value": {"event": "DISABLED"}}],
    }]}
    event, mock_turn = _run_webhook(db_session, payload)
    assert event.processing_status == "processed"
    assert not mock_turn.delay.called


@skip_if_no_db
def test_unsupported_whatsapp_payload_is_skipped_only_after_family_parsing(db_session):
    payload = {"object": "whatsapp_business_account", "entry": [{
        "id": "waba-other", "changes": [{"field": "unknown_field", "value": {"x": 1}}],
    }]}
    event, _ = _run_webhook(db_session, payload)
    assert event.processing_status == "skipped"
