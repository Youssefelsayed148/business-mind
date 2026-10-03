from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Thread
from uuid import uuid4

from app.core.config import settings
from app.integrations.meta.messaging import MetaMessageResult
from app.integrations.meta.whatsapp_client import WhatsappMessageResult
from app.models.message import Message
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.workspace import Workspace
from app.services.outreach_service import (
    claim_pending_recipient,
    check_can_send,
    reap_stale_sending_messages,
    retryable_failed_recipients,
    send_outreach_message,
    should_pause_campaign,
)
from app.services.whatsapp_consent_service import import_contacts, is_marketing_allowed
from app.services.whatsapp_template_service import (
    TemplateInUseError,
    TemplateValidationError,
    delete_template_by_name,
    validate_for_campaign,
)
import pytest
from tests.conftest import TestingSessionLocal, skip_if_no_db


def _seed(db, *, contacts=1, daily_cap=250):
    workspace = Workspace(name="Outreach", slug=f"outreach-{uuid4().hex}")
    user = User(email=f"{uuid4().hex}@example.test", password_hash="x", role="admin")
    db.add_all([workspace, user])
    db.flush()
    account = WhatsappAccount(
        workspace_id=workspace.id,
        phone_number_id=f"phone-{uuid4().hex}",
        whatsapp_business_account_id="waba-test",
        status="connected",
        quality_rating="GREEN",
        health_checked_at=datetime.now(timezone.utc),
        outreach_daily_cap=daily_cap,
    )
    db.add(account)
    db.flush()
    template = WhatsappTemplate(
        workspace_id=workspace.id,
        whatsapp_account_id=account.id,
        name="campaign_offer",
        language="en_US",
        category="marketing",
        status="approved",
    )
    db.add(template)
    db.flush()
    campaign = WhatsappCampaign(
        workspace_id=workspace.id,
        whatsapp_account_id=account.id,
        template_id=template.id,
        name="Launch",
        status="running",
        created_by=user.id,
    )
    db.add(campaign)
    db.flush()
    recipients = []
    for index in range(contacts):
        contact = WhatsappContact(
            workspace_id=workspace.id,
            whatsapp_account_id=account.id,
            wa_id=f"1631555{1200 + index}",
            marketing_consent="opted_in",
        )
        db.add(contact)
        db.flush()
        recipient = WhatsappCampaignRecipient(
            campaign_id=campaign.id, contact_id=contact.id, status="pending"
        )
        db.add(recipient)
        recipients.append(recipient)
    db.flush()
    return workspace, user, account, template, campaign, recipients


def _success_result():
    return WhatsappMessageResult(
        MetaMessageResult(success=True, provider_message_id=f"wamid.{uuid4().hex}")
    )


class _Client:
    def __init__(self, result=None, callback=None):
        self.result = result or _success_result()
        self.callback = callback
        self.calls = 0

    def send_template_message(self, *_args):
        self.calls += 1
        if self.callback:
            self.callback()
        return self.result


@skip_if_no_db
def test_kill_switch_is_first_and_health_staleness_is_configurable(db_session, monkeypatch):
    _, _, account, template, campaign, recipients = _seed(db_session)
    contact = db_session.get(WhatsappContact, recipients[0].contact_id)
    account.status = "disconnected"
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", False)
    disabled = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    assert disabled.reason_code == "outreach_disabled"
    assert disabled.deferrable is True

    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    account.status = "connected"
    account.health_checked_at = datetime.now(timezone.utc) - timedelta(minutes=61)
    monkeypatch.setattr(settings, "WHATSAPP_HEALTH_STALE_MINUTES", 60)
    stale = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    assert stale.reason_code == "health_stale"
    assert stale.deferrable is True


@skip_if_no_db
def test_ctwa_is_temporary_consent_and_authentication_campaign_is_rejected(db_session, monkeypatch):
    _, _, account, template, campaign, recipients = _seed(db_session)
    contact = db_session.get(WhatsappContact, recipients[0].contact_id)
    contact.marketing_consent = "unknown"
    contact.free_entry_point_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    account.ctwa_counts_as_consent = True
    assert is_marketing_allowed(contact, account)

    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    template.category = "authentication"
    decision = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    assert decision.reason_code == "template_category_unsupported"


@skip_if_no_db
def test_import_attestation_evidence_and_opt_out_precedence(db_session):
    _, user, account, _, _, recipients = _seed(db_session)
    opted_out = db_session.get(WhatsappContact, recipients[0].contact_id)
    opted_out.marketing_consent = "opted_out"
    data = f"wa_id,name\n{opted_out.wa_id},Existing\n16315559999,New\n"
    result = import_contacts(
        db_session,
        account=account,
        csv_data=data,
        filename="contacts.csv",
        actor=user,
        attestation_text="I attest these contacts opted in.",
    )
    assert result.imported == 2
    assert opted_out.marketing_consent == "opted_out"
    new_contact = db_session.query(WhatsappContact).filter_by(wa_id="16315559999").one()
    assert new_contact.marketing_consent == "opted_in"
    events = {event.contact_id: event for event in new_contact_events(db_session, account.id)}
    assert events[new_contact.id].evidence["filename"] == "contacts.csv"
    assert len(events[new_contact.id].evidence["file_hash"]) == 64
    assert events[new_contact.id].evidence["attestation_text"].startswith("I attest")

    import_contacts(
        db_session,
        account=account,
        csv_data="wa_id\n16315558888\n",
        filename="unattested.csv",
        actor=user,
    )
    assert db_session.query(WhatsappContact).filter_by(wa_id="16315558888").one().marketing_consent == "unknown"


def new_contact_events(db, account_id):
    from app.models.whatsapp_consent_event import WhatsappConsentEvent

    return (
        db.query(WhatsappConsentEvent)
        .join(WhatsappContact, WhatsappContact.id == WhatsappConsentEvent.contact_id)
        .filter(WhatsappContact.whatsapp_account_id == account_id)
        .all()
    )


@skip_if_no_db
def test_sending_row_is_committed_before_http_and_unknown_is_not_retryable(monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session)
        campaign_id, recipient_id = campaign.id, recipients[0].id
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)

        def observe_committed_reservation():
            observer = TestingSessionLocal()
            try:
                row = observer.query(Message).filter_by(whatsapp_campaign_id=campaign_id).one()
                assert row.status == "sending"
            finally:
                observer.close()

        timeout = WhatsappMessageResult(
            MetaMessageResult(success=False, error_code="timeout", error_message="unknown", retryable=False)
        )
        result = send_outreach_message(
            session,
            recipient_id=recipient_id,
            components=[],
            access_token="token",
            client=_Client(timeout, observe_committed_reservation),
        )
        assert result.reason_code == "outcome_unknown"
        recipient = session.get(WhatsappCampaignRecipient, recipient_id)
        assert recipient.error_code == "outcome_unknown"
        assert retryable_failed_recipients(session, campaign_id=campaign_id) == []
    finally:
        session.close()


@skip_if_no_db
def test_reaper_marks_stale_sending_as_outcome_unknown(db_session):
    _, _, _, template, campaign, recipients = _seed(db_session)
    message = Message(
        whatsapp_campaign_id=campaign.id,
        whatsapp_template_id=template.id,
        message_type="whatsapp_template",
        direction="outbound",
        status="sending",
    )
    db_session.add(message)
    db_session.flush()
    recipients[0].status = "sending"
    recipients[0].message_id = message.id
    db_session.flush()
    db_session.execute(
        Message.__table__.update().where(Message.id == message.id).values(
            created_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
    )
    db_session.expire(message)
    assert reap_stale_sending_messages(db_session, older_than_minutes=15) == 1
    assert message.error_code == "outcome_unknown"
    assert recipients[0].error_code == "outcome_unknown"


@skip_if_no_db
def test_circuit_breaker_uses_strict_greater_than_threshold(db_session, monkeypatch):
    _, _, _, _, campaign, recipients = _seed(db_session, contacts=4)
    for index, recipient in enumerate(recipients):
        recipient.status = "failed" if index == 0 else "sent"
        recipient.sent_at = datetime.now(timezone.utc) - timedelta(seconds=index)
    monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_WINDOW", 4)
    monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD", 0.25)
    assert should_pause_campaign(db_session, campaign) is False
    monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD", 0.24)
    assert should_pause_campaign(db_session, campaign) is True
    assert campaign.status == "paused"


@skip_if_no_db
def test_account_lock_serializes_daily_cap_reservations(monkeypatch):
    seed = TestingSessionLocal()
    workspace = user = account = template = campaign = None
    try:
        workspace, user, account, template, campaign, recipients = _seed(seed, contacts=2, daily_cap=1)
        recipient_ids = [row.id for row in recipients]
        seed.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        barrier = Barrier(3)
        results = []

        def worker(recipient_id):
            session = TestingSessionLocal()
            try:
                barrier.wait()
                results.append(send_outreach_message(
                    session,
                    recipient_id=recipient_id,
                    components=[],
                    access_token="token",
                    client=_Client(),
                ))
            finally:
                session.close()

        threads = [Thread(target=worker, args=(recipient_id,)) for recipient_id in recipient_ids]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads)
        assert sorted(result.reason_code or "sent" for result in results) == ["daily_cap_reached", "sent"]
    finally:
        seed.rollback()
        seed.close()


@skip_if_no_db
def test_atomic_claim_prevents_concurrent_duplicate_send(monkeypatch):
    seed = TestingSessionLocal()
    try:
        _, _, _, _, _, recipients = _seed(seed)
        recipient_id = recipients[0].id
        seed.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        entered_http = Event()
        release_http = Event()
        results = []

        class BlockingClient(_Client):
            def send_template_message(self, *_args):
                entered_http.set()
                assert release_http.wait(timeout=10)
                return _success_result()

        def worker(client):
            session = TestingSessionLocal()
            try:
                results.append(send_outreach_message(
                    session,
                    recipient_id=recipient_id,
                    components=[],
                    access_token="token",
                    client=client,
                ))
            finally:
                session.close()

        first = Thread(target=worker, args=(BlockingClient(),))
        first.start()
        assert entered_http.wait(timeout=10)
        second = Thread(target=worker, args=(_Client(),))
        second.start()
        second.join(timeout=10)
        release_http.set()
        first.join(timeout=10)
        assert sorted(result.reason_code or "sent" for result in results) == [
            "already_sent_in_campaign",
            "sent",
        ]
    finally:
        seed.close()


@skip_if_no_db
def test_claim_requires_pending_status(db_session):
    _, _, _, _, _, recipients = _seed(db_session)
    recipient_id = recipients[0].id
    assert claim_pending_recipient(db_session, recipient_id) == recipient_id
    assert claim_pending_recipient(db_session, recipient_id) is None


@skip_if_no_db
def test_auth_template_validation_and_delete_refuses_active_reference(db_session):
    _, _, account, template, campaign, _ = _seed(db_session)
    template.category = "authentication"
    with pytest.raises(TemplateValidationError, match="template_category_unsupported"):
        validate_for_campaign(template)

    class ManagementClient:
        called = False

        def delete_template_by_name(self, *_args):
            self.called = True
            return object()

    client = ManagementClient()
    with pytest.raises(TemplateInUseError, match="template_in_use_by_active_campaign"):
        delete_template_by_name(
            db_session,
            account=account,
            name=template.name,
            access_token="token",
            client=client,
        )
    assert client.called is False

    campaign.status = "completed"
    delete_template_by_name(
        db_session,
        account=account,
        name=template.name,
        access_token="token",
        client=client,
    )
    assert client.called is True


def _send_all(session, recipients, client):
    return [
        send_outreach_message(
            session,
            recipient_id=recipient.id,
            components=[],
            access_token="token",
            client=client,
        )
        for recipient in recipients
    ]


@skip_if_no_db
def test_daily_cap_sends_one_and_releases_remaining_claims(monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session, contacts=3, daily_cap=1)
        recipient_ids = [recipient.id for recipient in recipients]
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        client = _Client()
        results = _send_all(session, recipients, client)

        assert client.calls == 1
        assert [result.reason_code for result in results] == [
            None,
            "daily_cap_reached",
            "daily_cap_reached",
        ]
        assert all(result.deferrable for result in results[1:])
        states = [session.get(WhatsappCampaignRecipient, value).status for value in recipient_ids]
        assert states == ["sent", "pending", "pending"]
        session.refresh(campaign)
        assert campaign.skipped_count == 0
    finally:
        session.close()


@pytest.mark.parametrize("gate", ["health_stale", "outreach_paused"])
@skip_if_no_db
def test_account_gate_releases_all_three_recipients(gate, monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, account, _, campaign, recipients = _seed(session, contacts=3)
        recipient_ids = [recipient.id for recipient in recipients]
        if gate == "health_stale":
            account.health_checked_at = datetime.now(timezone.utc) - timedelta(hours=2)
        else:
            account.outreach_paused = True
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        client = _Client()
        results = _send_all(session, recipients, client)

        assert client.calls == 0
        assert [result.reason_code for result in results] == [gate, gate, gate]
        assert all(result.deferrable for result in results)
        assert [session.get(WhatsappCampaignRecipient, value).status for value in recipient_ids] == [
            "pending", "pending", "pending"
        ]
        session.refresh(campaign)
        assert campaign.skipped_count == 0
    finally:
        session.close()


@skip_if_no_db
def test_terminal_refusal_increments_skipped_once(db_session, monkeypatch):
    _, _, account, template, campaign, recipients = _seed(db_session)
    contact = db_session.get(WhatsappContact, recipients[0].contact_id)
    contact.marketing_consent = "opted_out"
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)

    first = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    second = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    assert first.reason_code == second.reason_code == "contact_opted_out"
    assert first.deferrable is second.deferrable is False
    assert recipients[0].status == "skipped_not_eligible"
    assert campaign.skipped_count == 1


@skip_if_no_db
def test_paused_campaign_releases_claim_without_http(monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session)
        recipient_id = recipients[0].id
        campaign.status = "paused"
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        client = _Client()
        result = send_outreach_message(
            session,
            recipient_id=recipient_id,
            components=[],
            access_token="token",
            client=client,
        )
        assert result.reason_code == "campaign_not_running"
        assert result.deferrable is True
        assert client.calls == 0
        assert session.get(WhatsappCampaignRecipient, recipient_id).status == "pending"
    finally:
        session.close()


@skip_if_no_db
def test_breaker_paused_campaign_sends_nothing(monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session, contacts=5)
        for index, recipient in enumerate(recipients[:4]):
            recipient.status = "failed" if index < 2 else "sent"
            recipient.sent_at = datetime.now(timezone.utc) - timedelta(seconds=index)
        pending_id = recipients[4].id
        monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_WINDOW", 4)
        monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD", 0.25)
        assert should_pause_campaign(session, campaign) is True
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        client = _Client()
        result = send_outreach_message(
            session,
            recipient_id=pending_id,
            components=[],
            access_token="token",
            client=client,
        )
        assert result.reason_code == "campaign_not_running"
        assert client.calls == 0
        assert session.get(WhatsappCampaignRecipient, pending_id).status == "pending"
    finally:
        session.close()


@skip_if_no_db
def test_outcome_unknown_counts_toward_daily_cap(db_session, monkeypatch):
    _, _, account, template, campaign, recipients = _seed(db_session, contacts=2, daily_cap=1)
    unknown = Message(
        whatsapp_campaign_id=campaign.id,
        whatsapp_template_id=template.id,
        message_type="whatsapp_template",
        direction="outbound",
        status="failed",
        error_code="outcome_unknown",
        retryable=False,
    )
    db_session.add(unknown)
    db_session.flush()
    recipients[0].status = "failed"
    recipients[0].error_code = "outcome_unknown"
    recipients[0].message_id = unknown.id
    contact = db_session.get(WhatsappContact, recipients[1].contact_id)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    decision = check_can_send(
        db_session, contact=contact, template=template, account=account, campaign=campaign
    )
    assert decision.reason_code == "daily_cap_reached"
    assert decision.deferrable is True


@pytest.mark.parametrize(
    "error_code",
    ["timeout", "network_error", "invalid_json", "invalid_response", "http_error", "client_other"],
)
@skip_if_no_db
def test_client_side_failures_are_outcome_unknown(error_code, monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session)
        campaign_id, recipient_id = campaign.id, recipients[0].id
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        failure = WhatsappMessageResult(
            MetaMessageResult(
                success=False,
                error_code=error_code,
                error_message="client failure",
                retryable=True,
            )
        )
        result = send_outreach_message(
            session,
            recipient_id=recipient_id,
            components=[],
            access_token="token",
            client=_Client(failure),
        )
        message = session.get(Message, result.message_id)
        assert result.reason_code == "outcome_unknown"
        assert message.retryable is False
        assert retryable_failed_recipients(session, campaign_id=campaign_id) == []
    finally:
        session.close()


@skip_if_no_db
def test_meta_error_body_is_known_failure_and_can_be_retried(monkeypatch):
    session = TestingSessionLocal()
    try:
        _, _, _, _, campaign, recipients = _seed(session)
        campaign_id = campaign.id
        session.commit()
        monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
        api_failure = WhatsappMessageResult(
            MetaMessageResult(
                success=False,
                error_code="retryable",
                error_message="Meta unavailable",
                raw_response={"error": {"message": "Meta unavailable", "code": 131048}},
                retryable=True,
            ),
            meta_error_code=131048,
        )
        result = send_outreach_message(
            session,
            recipient_id=recipients[0].id,
            components=[],
            access_token="token",
            client=_Client(api_failure),
        )
        assert result.reason_code == "retryable"
        assert len(retryable_failed_recipients(session, campaign_id=campaign_id)) == 1
    finally:
        session.close()
