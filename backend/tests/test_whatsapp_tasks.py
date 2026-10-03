from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.config import settings
from app.integrations.meta.whatsapp_management_client import (
    WhatsappManagementResult,
    WhatsappPhoneNumberHealth,
)
from app.models.message import Message
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.workspace import Workspace
from app.services.outreach_service import OutreachSendResult
from app.workers import whatsapp_tasks
from app.workers.celery_app import celery_app
from tests.conftest import TestingSessionLocal, skip_if_no_db


ORIGINAL_BEAT_SHA256 = "6b39308be50ed1666bc50fbe0d5d1013894e79f9bdfa251733d8ec388eddb9e5"


@pytest.fixture(autouse=True)
def _use_test_session_for_worker_tasks(monkeypatch):
    if TestingSessionLocal is not None:
        monkeypatch.setattr(whatsapp_tasks, "SessionLocal", TestingSessionLocal)
    yield
    if TestingSessionLocal is None:
        return
    db = TestingSessionLocal()
    try:
        db.query(WhatsappCampaignRecipient).delete(synchronize_session=False)
        db.query(Message).filter(Message.whatsapp_campaign_id.isnot(None)).delete(
            synchronize_session=False
        )
        db.query(WhatsappCampaign).delete(synchronize_session=False)
        db.query(WhatsappTemplate).delete(synchronize_session=False)
        db.query(WhatsappContact).delete(synchronize_session=False)
        db.query(WhatsappAccount).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _seed(*, status="running", consent="opted_in", contacts=1, components=None, mapping=None):
    db = TestingSessionLocal()
    workspace = Workspace(name="Phase 4", slug=f"phase-4-{uuid4().hex}")
    user = User(email=f"phase4-{uuid4().hex}@example.test", password_hash="x", role="admin")
    db.add_all([workspace, user])
    db.flush()
    account = WhatsappAccount(
        workspace_id=workspace.id,
        phone_number_id=f"phone-{uuid4().hex}",
        whatsapp_business_account_id=f"waba-{uuid4().hex}",
        status="connected",
        quality_rating="GREEN",
        health_checked_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.flush()
    template = WhatsappTemplate(
        workspace_id=workspace.id,
        whatsapp_account_id=account.id,
        name=f"offer_{uuid4().hex}",
        language="en_US",
        category="marketing",
        status="approved",
        components=components or [],
    )
    db.add(template)
    db.flush()
    campaign = WhatsappCampaign(
        workspace_id=workspace.id,
        whatsapp_account_id=account.id,
        template_id=template.id,
        name="Launch",
        status=status,
        variable_mapping=mapping or {},
        created_by=user.id,
    )
    db.add(campaign)
    db.flush()
    recipients = []
    for index in range(contacts):
        contact = WhatsappContact(
            workspace_id=workspace.id,
            whatsapp_account_id=account.id,
            wa_id=f"1631555{3000 + index}",
            display_name=f"Contact {index}",
            marketing_consent=consent,
        )
        db.add(contact)
        db.flush()
        if status != "draft":
            recipient = WhatsappCampaignRecipient(
                campaign_id=campaign.id,
                contact_id=contact.id,
                status="pending",
            )
            db.add(recipient)
            recipients.append(recipient)
    db.commit()
    values = {
        "workspace_id": workspace.id,
        "account_id": account.id,
        "template_id": template.id,
        "campaign_id": campaign.id,
        "recipient_ids": [row.id for row in recipients],
    }
    db.close()
    return values


def _load(model, identity):
    db = TestingSessionLocal()
    try:
        return db.get(model, identity)
    finally:
        db.close()


def test_dispatch_batches_stay_well_below_visibility_timeout(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_DISPATCH_BATCH_SIZE", 20)
    monkeypatch.setattr(settings, "WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS", 300)
    monkeypatch.setattr(settings, "WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS", 3600)
    countdowns = whatsapp_tasks.dispatch_countdowns(1)
    assert len(countdowns) == 6
    assert max(countdowns) <= 300
    assert max(countdowns) < settings.WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS / 2

    monkeypatch.setattr(settings, "WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS", 1800)
    with pytest.raises(ValueError, match="under_half_visibility_timeout"):
        whatsapp_tasks.dispatch_countdowns(30)


def test_retry_allowlist_defaults_empty_and_always_excludes_frequency_codes(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_RETRYABLE_META_CODES", "")
    assert whatsapp_tasks.retryable_meta_codes() == set()
    monkeypatch.setattr(settings, "WHATSAPP_RETRYABLE_META_CODES", "130429,131048,131049")
    assert whatsapp_tasks.retryable_meta_codes() == {130429}


def test_redis_token_bucket_enforces_account_limit():
    try:
        client = whatsapp_tasks._redis()
        client.ping()
    except Exception:
        pytest.skip("Redis unavailable")
    account_id = uuid4()
    client.delete(whatsapp_tasks._bucket_key(account_id))
    try:
        results = [whatsapp_tasks.acquire_account_token(account_id, 2) for _ in range(3)]
        assert [result.allowed for result in results] == [True, True, False]
        assert results[-1].retry_after_seconds > 0
    finally:
        client.delete(whatsapp_tasks._bucket_key(account_id))


@skip_if_no_db
def test_start_is_idempotent_and_freezes_only_allowed_contacts(monkeypatch):
    seeded = _seed(status="draft")
    db = TestingSessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, seeded["campaign_id"])
        account = db.get(WhatsappAccount, seeded["account_id"])
        opted_out = WhatsappContact(
            workspace_id=account.workspace_id,
            whatsapp_account_id=account.id,
            wa_id="16315559991",
            marketing_consent="opted_out",
        )
        db.add(opted_out)
        db.commit()
    finally:
        db.close()
    dispatched = []
    monkeypatch.setattr(
        whatsapp_tasks.dispatch_whatsapp_campaign,
        "delay",
        lambda campaign_id: dispatched.append(campaign_id),
    )
    first = whatsapp_tasks.start_whatsapp_campaign.run(str(seeded["campaign_id"]))
    second = whatsapp_tasks.start_whatsapp_campaign.run(str(seeded["campaign_id"]))
    db = TestingSessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, seeded["campaign_id"])
        recipients = db.query(WhatsappCampaignRecipient).filter_by(campaign_id=campaign.id).all()
        assert first["changed"] is True
        assert second["changed"] is False
        assert campaign.status == "running"
        assert campaign.total_recipients == 1
        assert len(recipients) == 1
        assert dispatched == [str(campaign.id)]
    finally:
        db.close()


@pytest.mark.parametrize(
    "mapping,error",
    [
        ({}, "placeholders_mismatch"),
        ({"1": {"source": "contact.unknown"}}, "source_unsupported"),
        ({"1": {"source": "literal", "value": ""}}, "variable_1_unresolved"),
    ],
)
@skip_if_no_db
def test_start_rejects_structural_variable_mapping_errors(monkeypatch, mapping, error):
    seeded = _seed(
        status="draft",
        components=[{"type": "BODY", "text": "Hello {{1}}"}],
        mapping=mapping,
    )
    monkeypatch.setattr(whatsapp_tasks.dispatch_whatsapp_campaign, "delay", lambda *_: None)
    with pytest.raises(ValueError, match=error):
        whatsapp_tasks.start_whatsapp_campaign.run(str(seeded["campaign_id"]))
    assert _load(WhatsappCampaign, seeded["campaign_id"]).status == "draft"


@skip_if_no_db
def test_start_skips_only_contact_with_unresolved_value(monkeypatch):
    seeded = _seed(
        status="draft",
        components=[{"type": "BODY", "text": "Hello {{1}}"}],
        mapping={"1": {"source": "contact.display_name"}},
    )
    db = TestingSessionLocal()
    try:
        account = db.get(WhatsappAccount, seeded["account_id"])
        db.add_all(
            [
                WhatsappContact(
                    workspace_id=account.workspace_id,
                    whatsapp_account_id=account.id,
                    wa_id="16315559992",
                    display_name="Named contact",
                    marketing_consent="opted_in",
                ),
                WhatsappContact(
                    workspace_id=account.workspace_id,
                    whatsapp_account_id=account.id,
                    wa_id="16315559993",
                    display_name=None,
                    marketing_consent="opted_in",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(whatsapp_tasks.dispatch_whatsapp_campaign, "delay", lambda *_: None)
    result = whatsapp_tasks.start_whatsapp_campaign.run(str(seeded["campaign_id"]))
    db = TestingSessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, seeded["campaign_id"])
        recipients = db.query(WhatsappCampaignRecipient).filter_by(campaign_id=campaign.id).all()
        assert result["status"] == "running"
        assert campaign.total_recipients == 3
        assert campaign.skipped_count == 1
        assert [row.status for row in recipients].count("pending") == 2
        skipped = [row for row in recipients if row.status == "skipped_not_eligible"]
        assert len(skipped) == 1
        assert skipped[0].error_code == "variable_unresolved"
    finally:
        db.close()


@skip_if_no_db
def test_dispatcher_uses_bounded_spaced_batch_and_reschedules(monkeypatch):
    seeded = _seed(contacts=10)
    sends = []
    redispatches = []
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    monkeypatch.setattr(settings, "WHATSAPP_DISPATCH_BATCH_SIZE", 20)
    monkeypatch.setattr(settings, "WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS", 300)
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(whatsapp_tasks, "_mark_dispatch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        whatsapp_tasks.send_whatsapp_campaign_message,
        "apply_async",
        lambda *args, **kwargs: sends.append((args, kwargs)),
    )
    monkeypatch.setattr(
        whatsapp_tasks,
        "_schedule_dispatch",
        lambda *args: redispatches.append(args),
    )
    db = TestingSessionLocal()
    try:
        db.get(WhatsappCampaign, seeded["campaign_id"]).throttle_per_minute = 1
        db.commit()
    finally:
        db.close()
    result = whatsapp_tasks.dispatch_whatsapp_campaign.run(str(seeded["campaign_id"]))
    assert result["dispatched"] == 6
    assert [entry[1]["countdown"] for entry in sends] == [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
    assert redispatches == [(seeded["campaign_id"], 301)]


@skip_if_no_db
def test_resume_hook_clears_bounded_gates_and_kicks_dispatcher(monkeypatch):
    seeded = _seed()
    cleared = []
    dispatched = []
    monkeypatch.setattr(
        whatsapp_tasks,
        "clear_whatsapp_defer_gate",
        lambda **kwargs: cleared.append(kwargs),
    )
    monkeypatch.setattr(
        whatsapp_tasks.dispatch_whatsapp_campaign,
        "delay",
        lambda campaign_id: dispatched.append(campaign_id),
    )
    result = whatsapp_tasks.resume_whatsapp_campaign_dispatch.run(str(seeded["campaign_id"]))
    assert result["resumed"] is True
    assert cleared == [
        {"account_id": seeded["account_id"], "campaign_id": seeded["campaign_id"]}
    ]
    assert dispatched == [str(seeded["campaign_id"])]


@skip_if_no_db
def test_variable_unresolved_is_terminal_before_meta(monkeypatch):
    seeded = _seed(
        components=[{"type": "BODY", "text": "Hello {{1}}"}],
        mapping={"1": {"source": "contact.display_name"}},
    )
    db = TestingSessionLocal()
    try:
        contact = db.get(WhatsappContact, _load(WhatsappCampaignRecipient, seeded["recipient_ids"][0]).contact_id)
        contact.display_name = None
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(
        whatsapp_tasks,
        "acquire_account_token",
        lambda *_: (_ for _ in ()).throw(AssertionError("bucket should not be reached")),
    )
    monkeypatch.setattr(
        whatsapp_tasks,
        "send_outreach_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Meta path reached")),
    )
    result = whatsapp_tasks.send_whatsapp_campaign_message.run(str(seeded["recipient_ids"][0]))
    recipient = _load(WhatsappCampaignRecipient, seeded["recipient_ids"][0])
    assert result["reason"] == "variable_unresolved"
    assert recipient.status == "skipped_not_eligible"
    assert recipient.error_code == "variable_unresolved"


@skip_if_no_db
def test_bucket_redis_failure_is_fail_closed_mutation_guard(monkeypatch):
    seeded = _seed()
    scheduled = []
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(
        whatsapp_tasks,
        "acquire_account_token",
        lambda *_: (_ for _ in ()).throw(RedisError("down")),
    )
    monkeypatch.setattr(
        whatsapp_tasks.send_whatsapp_campaign_message,
        "apply_async",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    monkeypatch.setattr(
        whatsapp_tasks,
        "send_outreach_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fail-open send")),
    )
    result = whatsapp_tasks.send_whatsapp_campaign_message.run(str(seeded["recipient_ids"][0]))
    assert result["reason"] == "redis_unavailable"
    assert scheduled
    assert _load(WhatsappCampaignRecipient, seeded["recipient_ids"][0]).status == "pending"


@pytest.mark.parametrize("reason,meta_code", [("outcome_unknown", None), ("policy_error", 131049)])
@skip_if_no_db
def test_outcome_unknown_and_131049_never_retry(monkeypatch, reason, meta_code):
    seeded = _seed()
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(whatsapp_tasks, "acquire_account_token", lambda *_: whatsapp_tasks.BucketResult(True))
    monkeypatch.setattr(settings, "WHATSAPP_RETRYABLE_META_CODES", "131049")
    monkeypatch.setattr(
        whatsapp_tasks,
        "send_outreach_message",
        lambda *_args, **_kwargs: OutreachSendResult(
            False, reason, retryable=True, meta_error_code=meta_code
        ),
    )
    monkeypatch.setattr(
        whatsapp_tasks.send_whatsapp_campaign_message,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("forbidden retry")),
    )
    result = whatsapp_tasks.send_whatsapp_campaign_message.run(str(seeded["recipient_ids"][0]))
    assert result == {"sent": False, "reason": reason}


@skip_if_no_db
def test_131048_stops_batch_counts_toward_breaker_and_never_retries(monkeypatch):
    seeded = _seed()
    recipient_id = seeded["recipient_ids"][0]
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(whatsapp_tasks, "acquire_account_token", lambda *_: whatsapp_tasks.BucketResult(True))
    monkeypatch.setattr(settings, "WHATSAPP_RETRYABLE_META_CODES", "131048")
    monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_WINDOW", 1)
    monkeypatch.setattr(settings, "WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD", 0.0)
    gates = []
    monkeypatch.setattr(whatsapp_tasks, "_set_defer_gate", lambda **kwargs: gates.append(kwargs))

    def failed_send(db, **_kwargs):
        recipient = db.get(WhatsappCampaignRecipient, recipient_id)
        recipient.status = "failed"
        recipient.error_code = "retryable"
        recipient.sent_at = datetime.now(timezone.utc)
        db.commit()
        return OutreachSendResult(False, "retryable", retryable=True, meta_error_code=131048)

    monkeypatch.setattr(whatsapp_tasks, "send_outreach_message", failed_send)
    monkeypatch.setattr(
        whatsapp_tasks.send_whatsapp_campaign_message,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("131048 retried")),
    )
    whatsapp_tasks.send_whatsapp_campaign_message.run(str(recipient_id))
    assert _load(WhatsappCampaign, seeded["campaign_id"]).status == "paused"
    assert any(item["reason"] == "131048" for item in gates)


@skip_if_no_db
def test_daily_cap_deferral_leaves_pending_and_schedules_capacity_release(monkeypatch):
    seeded = _seed()
    recipient_id = seeded["recipient_ids"][0]
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(whatsapp_tasks, "acquire_account_token", lambda *_: whatsapp_tasks.BucketResult(True))
    monkeypatch.setattr(
        whatsapp_tasks,
        "send_outreach_message",
        lambda *_args, **_kwargs: OutreachSendResult(
            False, "daily_cap_reached", deferrable=True
        ),
    )
    monkeypatch.setattr(whatsapp_tasks, "_daily_cap_retry_seconds", lambda *_: 77)
    gates = []
    scheduled = []
    monkeypatch.setattr(whatsapp_tasks, "_set_defer_gate", lambda **kwargs: gates.append(kwargs))
    monkeypatch.setattr(
        whatsapp_tasks,
        "_schedule_deferred_dispatch_once",
        lambda *args: scheduled.append(args) or True,
    )
    result = whatsapp_tasks.send_whatsapp_campaign_message.run(str(recipient_id))
    assert result["deferred"] is True
    assert _load(WhatsappCampaignRecipient, recipient_id).status == "pending"
    assert gates[0]["reason"] == "daily_cap_reached"
    assert scheduled == [(seeded["campaign_id"], 77)]


@skip_if_no_db
def test_deferred_batch_schedules_only_one_dispatch(monkeypatch):
    seeded = _seed(contacts=3)
    monkeypatch.setattr(whatsapp_tasks, "_defer_ttl", lambda *_: 0)
    monkeypatch.setattr(whatsapp_tasks, "acquire_account_token", lambda *_: whatsapp_tasks.BucketResult(True))
    monkeypatch.setattr(
        whatsapp_tasks,
        "send_outreach_message",
        lambda *_args, **_kwargs: OutreachSendResult(
            False, "daily_cap_reached", deferrable=True
        ),
    )
    monkeypatch.setattr(whatsapp_tasks, "_daily_cap_retry_seconds", lambda *_: 77)
    monkeypatch.setattr(whatsapp_tasks, "_set_defer_gate", lambda **_kwargs: None)
    scheduled = []
    monkeypatch.setattr(whatsapp_tasks, "_schedule_dispatch", lambda *args: scheduled.append(args))

    class Redis:
        acquired = False

        def set(self, *_args, **_kwargs):
            if self.acquired:
                return False
            self.acquired = True
            return True

    redis = Redis()
    monkeypatch.setattr(whatsapp_tasks, "_redis", lambda: redis)
    for recipient_id in seeded["recipient_ids"]:
        result = whatsapp_tasks.send_whatsapp_campaign_message.run(str(recipient_id))
        assert result["deferred"] is True
    assert scheduled == [(seeded["campaign_id"], 77)]


@skip_if_no_db
def test_health_red_pauses_and_green_never_auto_unpauses(monkeypatch):
    red = _seed()
    green = _seed()
    db = TestingSessionLocal()
    try:
        green_account = db.get(WhatsappAccount, green["account_id"])
        green_account.outreach_paused = True
        green_account.outreach_paused_reason = "manual"
        db.commit()
    finally:
        db.close()

    class Client:
        def get_phone_number_health(self, _token, waba_id):
            account_id = red["account_id"] if str(red["account_id"]) in waba_id else green["account_id"]
            account = _load(WhatsappAccount, account_id)
            quality = "RED" if account_id == red["account_id"] else "GREEN"
            return WhatsappManagementResult(
                True,
                data=[WhatsappPhoneNumberHealth(account.phone_number_id, None, None, quality)],
            )

        def close(self):
            pass

    # Make the WABA values identify the seeded account for the fake client.
    db = TestingSessionLocal()
    try:
        for seeded in (red, green):
            db.get(WhatsappAccount, seeded["account_id"]).whatsapp_business_account_id = str(seeded["account_id"])
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(whatsapp_tasks, "get_decrypted_token", lambda *_: "secret")
    monkeypatch.setattr(whatsapp_tasks, "WhatsappManagementClient", Client)
    cleared = []
    monkeypatch.setattr(
        whatsapp_tasks,
        "clear_whatsapp_defer_gate",
        lambda **kwargs: cleared.append(kwargs),
    )
    whatsapp_tasks.poll_whatsapp_account_health.run()
    assert _load(WhatsappAccount, red["account_id"]).outreach_paused is True
    assert _load(WhatsappCampaign, red["campaign_id"]).status == "paused"
    refreshed_green = _load(WhatsappAccount, green["account_id"])
    assert refreshed_green.outreach_paused is True
    assert refreshed_green.outreach_paused_reason == "manual"
    assert {item["account_id"] for item in cleared} == {red["account_id"], green["account_id"]}


@skip_if_no_db
def test_failed_health_poll_leaves_timestamp_unchanged(monkeypatch):
    seeded = _seed()
    before = _load(WhatsappAccount, seeded["account_id"]).health_checked_at

    class Client:
        def get_phone_number_health(self, *_args):
            return WhatsappManagementResult(False, error_message="failed")

        def close(self):
            pass

    monkeypatch.setattr(whatsapp_tasks, "get_decrypted_token", lambda *_: "secret")
    monkeypatch.setattr(whatsapp_tasks, "WhatsappManagementClient", Client)
    whatsapp_tasks.poll_whatsapp_account_health.run()
    assert _load(WhatsappAccount, seeded["account_id"]).health_checked_at == before


@skip_if_no_db
def test_template_sync_isolates_accounts_and_skips_disconnected(monkeypatch):
    failing = _seed()
    succeeding = _seed()
    disconnected = _seed()
    db = TestingSessionLocal()
    try:
        db.get(WhatsappAccount, disconnected["account_id"]).status = "disconnected"
        db.commit()
    finally:
        db.close()
    calls = []

    def fake_sync(db, *, account, access_token):
        calls.append(account.id)
        if account.id == failing["account_id"]:
            raise RuntimeError("one account failed")
        return type("Result", (), {"success": True})()

    monkeypatch.setattr(whatsapp_tasks, "get_decrypted_token", lambda *_: "secret")
    monkeypatch.setattr(whatsapp_tasks, "sync_templates", fake_sync)
    result = whatsapp_tasks.sync_whatsapp_templates.run()
    assert result["succeeded"] == 1
    assert set(calls) == {failing["account_id"], succeeding["account_id"]}
    assert disconnected["account_id"] not in calls


@skip_if_no_db
def test_reaper_and_rollup_complete_campaign(monkeypatch):
    seeded = _seed()
    db = TestingSessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, seeded["campaign_id"])
        recipient = db.get(WhatsappCampaignRecipient, seeded["recipient_ids"][0])
        message = Message(
            whatsapp_campaign_id=campaign.id,
            whatsapp_template_id=campaign.template_id,
            direction="outbound",
            message_type="whatsapp_template",
            status="sending",
        )
        db.add(message)
        db.flush()
        recipient.status = "sending"
        recipient.message_id = message.id
        db.commit()
        db.execute(
            Message.__table__.update()
            .where(Message.id == message.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        db.commit()
    finally:
        db.close()
    assert whatsapp_tasks.reap_whatsapp_sending_messages.run()["reaped"] >= 1
    monkeypatch.setattr(whatsapp_tasks, "_watchdog_kick", lambda *_: False)
    result = whatsapp_tasks.rollup_whatsapp_campaigns.run()
    campaign = _load(WhatsappCampaign, seeded["campaign_id"])
    assert result["completed"] >= 1
    assert campaign.status == "completed"
    assert campaign.failed_count == 1
    assert campaign.completed_at is not None


@skip_if_no_db
def test_watchdog_kicks_stranded_campaign_mutation_guard(monkeypatch):
    seeded = _seed()
    scheduled = []

    class Redis:
        def get(self, _key):
            return None

        def set(self, *_args, **_kwargs):
            return True

    monkeypatch.setattr(whatsapp_tasks, "_redis", lambda: Redis())
    monkeypatch.setattr(whatsapp_tasks, "_schedule_dispatch", lambda *args: scheduled.append(args))
    monkeypatch.setattr(whatsapp_tasks, "_mark_dispatch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    result = whatsapp_tasks.rollup_whatsapp_campaigns.run()
    assert result["kicked"] >= 1
    assert (seeded["campaign_id"], 1) in scheduled


def test_beat_module_registers_exactly_four_whatsapp_entries_and_old_file_is_unchanged():
    names = {name for name in celery_app.conf.beat_schedule if name.startswith("whatsapp-")}
    assert names == {
        "whatsapp-health-poll",
        "whatsapp-template-sync",
        "whatsapp-stale-send-reaper",
        "whatsapp-campaign-rollup",
    }
    path = Path(__file__).parents[1] / "app" / "workers" / "beat_schedule.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ORIGINAL_BEAT_SHA256
