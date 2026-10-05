"""Real PostgreSQL/Redis, eager Celery deliveries, HTTP mocked at Meta clients.

Never point either DATABASE_URL or TEST_DATABASE_URL at a persistent database.
The broker queue is captured so countdowns can be inspected without sleeping.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import routes_whatsapp_outreach as routes
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.integrations.meta.whatsapp_client import WhatsappClient
from app.integrations.meta.whatsapp_management_client import WhatsappManagementClient
from app.integrations.meta.whatsapp_webhooks import ParsedWhatsappMessageEvent
from app.main import app
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.message import Message
from app.services import whatsapp_consent_service as consent
from app.services import whatsapp_template_service as templates
from app.services.outreach_service import send_outreach_message, _daily_recipient_count
from app.services.whatsapp_webhook_service import process_inbound_whatsapp_event
from app.workers import whatsapp_tasks as tasks
from tests.conftest import TestingSessionLocal, skip_if_no_db

pytestmark = skip_if_no_db
SECRET = "phase7-access-token-canary"


@pytest.fixture
def system(monkeypatch, request):
    db = TestingSessionLocal()
    request.addfinalizer(db.close)
    workspace = Workspace(name="E2E", slug=f"e2e-{uuid4().hex}")
    other = Workspace(name="Other", slug=f"other-{uuid4().hex}")
    user = User(email=f"e2e-{uuid4().hex}@example.test", password_hash="x", role="admin", is_active=True)
    db.add_all([workspace, other, user]); db.flush()
    db.add_all([UserWorkspaceMembership(user_id=user.id, workspace_id=w.id, role="owner")
                for w in (workspace, other)])
    account = WhatsappAccount(workspace_id=workspace.id, phone_number_id=uuid4().hex,
        whatsapp_business_account_id=uuid4().hex, display_phone_number="+15551234567",
        status="connected", quality_rating="GREEN", health_checked_at=datetime.now(timezone.utc),
        opt_in_keywords=["JOIN"], outreach_daily_cap=10)
    db.add(account); db.flush()
    template = templates.create_draft(db, account=account, name=f"e2e_{uuid4().hex}",
        language="en_US", category="marketing", components=[{"type": "BODY", "text": "Hello {{1}}",
            "example": {"body_text": [["Internal"]]}}])
    template.status = "approved"
    campaign = WhatsappCampaign(workspace_id=workspace.id, whatsapp_account_id=account.id,
        template_id=template.id, created_by=user.id, name="E2E", status="draft",
        throttle_per_minute=30, variable_mapping={"1": {"source": "contact.display_name"}})
    db.add(campaign); db.commit()
    queue, calls = [], []
    redis = tasks._redis()
    redis.ping()  # Required infrastructure: never silently skip Redis coverage.
    monkeypatch.setattr(tasks, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", False)
    monkeypatch.setattr(settings, "WHATSAPP_RETRYABLE_META_CODES", "131048,131049")
    monkeypatch.setattr(tasks, "get_decrypted_token", lambda *_: SECRET)
    monkeypatch.setattr(routes, "get_decrypted_token", lambda *_: SECRET)
    from app.services import whatsapp_token_service
    monkeypatch.setattr(whatsapp_token_service, "get_decrypted_token", lambda *_: SECRET)
    response_kind = ["success"]

    def meta_http(request):
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        if request.url.path.endswith("/messages"):
            payload = json.loads(request.content)
            calls.append(payload)
            kind = response_kind[0]
            if kind == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            if kind == "invalid_json":
                return httpx.Response(200, text=SECRET)
            if kind == "echo_error":
                return httpx.Response(400, json={"error": {"code": 131049, "message": f"Rejected token {SECRET}"}})
            if isinstance(kind, int):
                return httpx.Response(400, json={"error": {"code": kind, "message": "rejected"}})
            return httpx.Response(200, json={"messages": [{"id": f"wamid.{uuid4().hex}"}]})
        if request.url.path.endswith("/message_templates"):
            if response_kind[0] == "echo_error":
                return httpx.Response(400, json={"error": {"code": 190, "message": f"Rejected token {SECRET}"}})
            if request.method == "POST":
                return httpx.Response(200, json={"id": "meta-template", "status": "PENDING"})
            return httpx.Response(200, json={"data": [{"id": "meta-template", "name": template.name,
                "language": template.language, "category": "MARKETING", "status": "APPROVED",
                "components": template.components}]})
        if request.url.path.endswith("/phone_numbers"):
            return httpx.Response(200, json={"data": [{"id": account.phone_number_id, "quality_rating": "GREEN"}]})
        raise AssertionError(f"Unexpected Meta request: {request.method} {request.url.path}")

    for cls in (WhatsappClient, WhatsappManagementClient):
        original = cls.__init__
        def initialize(self, *args, _original=original, **kwargs):
            _original(self, *args, **kwargs)
            self._client.close()
            self._client = httpx.Client(transport=httpx.MockTransport(meta_http))
        monkeypatch.setattr(cls, "__init__", initialize)
    for task in (tasks.start_whatsapp_campaign, tasks.dispatch_whatsapp_campaign,
                 tasks.send_whatsapp_campaign_message, tasks.resume_whatsapp_campaign_dispatch,
                 tasks.poll_whatsapp_account_health):
        monkeypatch.setattr(task, "apply_async", lambda args=None, countdown=0, _task=task, **kw:
                            queue.append((_task, args or [], countdown)))
        monkeypatch.setattr(task, "delay", lambda *args, _task=task, **kw: queue.append((_task, list(args), 0)))

    app.dependency_overrides[get_db] = lambda: db
    api = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}", "X-Workspace-Id": str(workspace.id)}
    s = SimpleNamespace(db=db, api=api, workspace=workspace, other=other, user=user,
        account=account, template=template, campaign=campaign, queue=queue, calls=calls,
        kind=response_kind, redis=redis, headers=headers)

    def contact(index=1, state="opted_in", name="Internal"):
        row = WhatsappContact(workspace_id=workspace.id, whatsapp_account_id=account.id,
            wa_id=f"1555000{index:04d}", display_name=name, marketing_consent="unknown")
        db.add(row); db.flush()
        if state == "opted_in":
            consent.grant(db, contact=row, actor=user, evidence={"proof": "Internal number"})
        elif state == "opted_out":
            consent.revoke(db, contact=row, actor=user)
        db.commit()
        return row
    s.contact = contact

    def deliver(task, *args):
        return task.apply(args=list(args), throw=True).get()
    s.deliver = deliver

    def drain(limit=50):
        for _ in range(limit):
            if not queue:
                return
            task, args, countdown = queue.pop(0)
            assert countdown < settings.WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS / 2
            deliver(task, *args)
        pytest.fail("Dispatcher did not settle within bounded deliveries")
    s.drain = drain
    yield s
    account_id, campaign_id = account.id, campaign.id
    api.close()
    app.dependency_overrides.pop(get_db, None)
    db.rollback()
    # Delete only this fixture's rows, in FK order (including inbound lead messages).
    campaign_ids = select(WhatsappCampaign.id).where(WhatsappCampaign.workspace_id == workspace.id)
    lead_table = Base.metadata.tables["leads"]
    lead_ids = select(lead_table.c.id).where(lead_table.c.workspace_id == workspace.id)
    db.query(WhatsappCampaignRecipient).filter(WhatsappCampaignRecipient.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
    db.query(Message).filter((Message.whatsapp_campaign_id.in_(campaign_ids)) | (Message.lead_id.in_(lead_ids))).delete(synchronize_session=False)
    for table in reversed(Base.metadata.sorted_tables):
        if "workspace_id" in table.c:
            db.execute(table.delete().where(table.c.workspace_id.in_([workspace.id, other.id])))
    db.delete(workspace); db.delete(other); db.delete(user); db.commit(); db.close()
    keys = redis.keys(f"whatsapp:*{account_id}*") + redis.keys(f"whatsapp:*{campaign_id}*")
    if keys:
        redis.delete(*keys)


def recipients(s):
    s.db.expire_all()
    return s.db.query(WhatsappCampaignRecipient).filter_by(campaign_id=s.campaign.id).all()


def start(s):
    result = s.api.post(f"/whatsapp/campaigns/{s.campaign.id}/start", headers=s.headers)
    assert result.status_code == 202, result.text
    s.deliver(tasks.start_whatsapp_campaign, str(s.campaign.id))
    return recipients(s)


def inbound(s, contact, text, timestamp=None):
    return ParsedWhatsappMessageEvent(phone_number_id=s.account.phone_number_id,
        sender_wa_id=contact.wa_id, text=text, message_id=f"wamid.{uuid4().hex}",
        timestamp=str(timestamp or datetime.now(timezone.utc).timestamp()), message_type="text",
        sender_profile_name="Internal", referral=None, raw_event={})


def test_consent_page_keyword_stop_and_duplicate_webhook(system):
    s = system
    link = s.api.post(f"/whatsapp/accounts/{s.account.id}/opt-in-link", json={}, headers=s.headers)
    token = link.json()["url"].rsplit("/", 1)[-1]
    result = s.api.post(f"/public/whatsapp/opt-in/{token}", json={"phone": "+15550000001"})
    assert result.status_code == 202
    contact = s.db.query(WhatsappContact).filter_by(whatsapp_account_id=s.account.id).one()
    assert contact.marketing_consent == "unknown"
    assert [e.event_type for e in s.db.query(WhatsappConsentEvent).filter_by(contact_id=contact.id)] == ["opt_in_unverified"]
    from app.services.outreach_service import evaluate_can_send
    assert evaluate_can_send(s.db, contact=contact, account=s.account, template=s.template).reason_code == "marketing_consent_required"
    event = inbound(s, contact, "JOIN")
    assert process_inbound_whatsapp_event(s.db, event).consent_action == "opt_in"
    assert process_inbound_whatsapp_event(s.db, event) is None
    s.db.refresh(contact)
    assert contact.marketing_consent == "opted_in"
    stop = inbound(s, contact, "STOP")
    process_inbound_whatsapp_event(s.db, stop)
    s.db.refresh(contact)
    # Late delivery of earlier opt-in evidence cannot undo STOP.
    process_inbound_whatsapp_event(s.db, inbound(s, contact, "JOIN", float(event.timestamp) - 10))
    process_inbound_whatsapp_event(s.db, inbound(s, contact, "JOIN", float(stop.timestamp)))
    consent.import_contacts(s.db, account=s.account, csv_data="phone\n+15550000001\n",
                            filename="later.csv", actor=s.user, attestation_text="Later imported evidence")
    assert contact.marketing_consent == "opted_out"
    with pytest.raises(consent.ConsentValidationError, match="resubscribe_evidence_required"):
        consent.grant(s.db, contact=contact, source="inbound_keyword")
    assert s.calls == []


def test_template_import_campaign_bucket_cap_and_rollup(system):
    s = system
    s.template.status = "draft"; s.account.outreach_daily_cap = 2; s.db.commit()
    assert s.api.post(f"/whatsapp/templates/{s.template.id}/submit", headers=s.headers).status_code == 200
    assert s.deliver(tasks.sync_whatsapp_templates)["succeeded"] >= 1
    response = s.api.post("/whatsapp/contacts/import", headers=s.headers,
        data={"account_id": str(s.account.id), "attestation": "Internal numbers consented"},
        files={"file": ("internal.csv", "phone,display_name\n+15550000001,One\n+15550000002,Two\n", "text/csv")})
    assert response.status_code == 201, response.text
    created = s.api.post("/whatsapp/campaigns", headers=s.headers, json={
        "account_id": str(s.account.id), "template_id": str(s.template.id), "name": "Full lifecycle",
        "variable_mapping": {"1": {"source": "contact.display_name"}}})
    assert created.status_code == 201, created.text
    from uuid import UUID
    s.campaign = s.db.get(WhatsappCampaign, UUID(created.json()["id"]))
    start(s); s.drain()
    assert {r.status for r in recipients(s)} == {"sent"}
    assert len(s.calls) == 2
    assert _daily_recipient_count(s.db, s.account, datetime.now(timezone.utc)) == 2
    assert s.deliver(tasks.rollup_whatsapp_campaigns)["completed"] >= 1
    s.db.refresh(s.campaign)
    assert (s.campaign.total_recipients, s.campaign.sent_count, s.campaign.failed_count, s.campaign.skipped_count) == (2, 2, 0, 0)
    assert s.campaign.status == "completed" and s.campaign.completed_at is not None
    # Two eager deliveries spent two tokens in the real 30/minute bucket.
    remaining = float(s.redis.hget(tasks._bucket_key(s.account.id), "tokens"))
    assert 28 <= remaining < 29


def test_mixed_audience_reason_codes_and_once_only_skips(system):
    s = system
    rows = [s.contact(1), s.contact(2, "unknown"), s.contact(3, "opted_out"),
            s.contact(4, "unknown"), s.contact(5, name=None)]
    rows[3].consent_source = "imported_attested"  # Legacy import without a consent grant.
    s.db.commit()
    # Freeze a sendable audience, then include contacts whose consent changed before delivery.
    s.campaign.status = "running"
    s.db.add_all([WhatsappCampaignRecipient(campaign_id=s.campaign.id, contact_id=r.id, status="pending") for r in rows])
    s.db.commit()
    for row in recipients(s):
        s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
        s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
    observed = {r.contact_id: (r.status, r.error_code) for r in recipients(s)}
    assert observed[rows[0].id] == ("sent", None)
    for index, reason in [(1, "marketing_consent_required"), (2, "contact_opted_out"),
                          (3, "marketing_consent_required"), (4, "variable_unresolved")]:
        assert observed[rows[index].id] == ("skipped_not_eligible", reason)
    s.db.refresh(s.campaign)
    assert s.campaign.skipped_count == 4 and len(s.calls) == 1
    assert s.deliver(tasks.rollup_whatsapp_campaigns)["completed"] >= 1
    s.db.refresh(s.campaign)
    assert s.campaign.skipped_count == 4


@pytest.mark.parametrize("block,reason", [("red", "quality_red"), ("stale", "health_stale"),
    ("disabled", "outreach_disabled"), ("paused", "outreach_paused"), ("cap", "daily_cap_reached")])
def test_deferral_preserves_pending_tokens_and_bounded_dispatch(system, monkeypatch, block, reason):
    s = system
    s.contact(1); s.contact(2)
    rows = start(s); s.queue.clear()
    if block == "red": s.account.quality_rating = "RED"
    if block == "stale": s.account.health_checked_at -= timedelta(hours=2)
    if block == "disabled": monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", False)
    if block == "paused": s.account.outreach_paused = True
    if block == "cap":
        s.account.outreach_daily_cap = 1; s.db.commit()
        assert s.deliver(tasks.send_whatsapp_campaign_message, str(rows[0].id))["sent"]
        rows = rows[1:]
    s.db.commit()
    before = s.redis.hgetall(tasks._bucket_key(s.account.id))
    sent_before = len(s.calls)
    result = s.deliver(tasks.send_whatsapp_campaign_message, str(rows[0].id))
    assert result["reason"] == reason
    assert s.redis.hgetall(tasks._bucket_key(s.account.id)) == before
    assert all(r.status == "pending" for r in recipients(s) if r.id == rows[0].id)
    assert len(s.calls) == sent_before
    for _ in range(5): s.deliver(tasks.dispatch_whatsapp_campaign, str(s.campaign.id))
    assert not any(task is tasks.send_whatsapp_campaign_message for task, _, _ in s.queue)
    assert len(s.queue) <= 1


def test_resume_requires_confirmed_health_then_continues(system):
    s = system
    s.contact(); rows = start(s); s.queue.clear()
    s.campaign.status = "paused"; s.account.outreach_paused = True
    s.account.outreach_paused_at = datetime.now(timezone.utc); s.db.commit()
    path = f"/whatsapp/campaigns/{s.campaign.id}/resume"
    result = s.api.post(path, json={"note": "reviewed"}, headers=s.headers)
    assert result.status_code == 409 and result.json()["detail"]["code"] == "health_unconfirmed"
    assert s.deliver(tasks.poll_whatsapp_account_health, str(s.account.id))["succeeded"] == 1
    s.db.expire_all()  # The poll uses a different committed worker session.
    assert s.api.post(path, json={"note": "fresh poll"}, headers=s.headers).status_code == 200
    s.drain()
    assert len(s.calls) == 1 and recipients(s)[0].status == "sent"


def test_operator_pause_can_resume_after_new_health_poll(system):
    s = system
    s.contact(); start(s); s.queue.clear()
    path = f"/whatsapp/campaigns/{s.campaign.id}"
    assert s.api.post(f"{path}/pause", headers=s.headers).status_code == 200
    s.db.expire_all()
    assert s.account.outreach_paused is False and s.account.outreach_paused_at is None
    blocked = s.api.post(f"{path}/resume", json={"note": "old poll"}, headers=s.headers)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "health_unconfirmed"
    s.deliver(tasks.poll_whatsapp_account_health, str(s.account.id)); s.db.expire_all()
    result = s.api.post(f"{path}/resume", json={"note": "new poll"}, headers=s.headers)
    assert result.status_code == 200, result.text
    s.drain()
    assert len(s.calls) == 1


@pytest.mark.parametrize("kind", [131048, 131049, "timeout", "invalid_json"])
def test_failure_semantics_no_retry_and_unknown_counts_cap(system, kind):
    s = system
    s.contact(); row = start(s)[0]; s.queue.clear(); s.kind[0] = kind
    result = s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
    assert result["sent"] is False
    assert not any(t is tasks.send_whatsapp_campaign_message for t, _, _ in s.queue)
    assert s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))["reason"] == "recipient_not_pending"
    row = recipients(s)[0]
    message = s.db.get(Message, row.message_id)
    assert row.status == "failed" and message.retryable is False
    unknown = isinstance(kind, str)
    assert _daily_recipient_count(s.db, s.account, datetime.now(timezone.utc)) == int(unknown)
    if unknown: assert row.error_code == message.error_code == "outcome_unknown"
    assert len(s.calls) == 1


def test_stale_sending_reaped_once_without_resend(system):
    s = system
    s.contact(); row = start(s)[0]; s.queue.clear()
    message = Message(whatsapp_campaign_id=s.campaign.id, whatsapp_template_id=s.template.id,
        direction="outbound", message_type="whatsapp_template", status="sending",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30))
    s.db.add(message); s.db.flush(); row.message_id = message.id; row.status = "sending"; s.db.commit()
    assert s.deliver(tasks.reap_whatsapp_sending_messages) == {"reaped": 1}
    assert s.deliver(tasks.reap_whatsapp_sending_messages) == {"reaped": 0}
    assert s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))["sent"] is False
    s.db.refresh(s.campaign)
    assert s.campaign.failed_count == 1 and s.calls == []
    assert _daily_recipient_count(s.db, s.account, datetime.now(timezone.utc)) == 1


@pytest.mark.parametrize("same_recipient", [True, False])
def test_two_workers_single_claim_and_cap_reservation(system, same_recipient):
    s = system
    s.contact(1); s.contact(2); s.contact(3)
    rows = start(s); s.queue.clear()
    s.account.outreach_daily_cap = 2; s.db.commit()
    assert s.deliver(tasks.send_whatsapp_campaign_message, str(rows[0].id))["sent"]
    s.calls.clear()  # Both workers now race with one of two daily slots left.
    barrier = Barrier(2)
    def worker(identity):
        db = TestingSessionLocal()
        try:
            # Load before either claims, reproducing independently cached ORM rows.
            db.get(WhatsappCampaignRecipient, identity)
            db.get(WhatsappAccount, s.account.id)
            barrier.wait(timeout=10)
            return send_outreach_message(db, recipient_id=identity,
                components=[{"type": "body", "parameters": [{"type": "text", "text": "Internal"}]}])
        finally:
            db.rollback(); db.close()
    ids = [rows[1].id, rows[1].id if same_recipient else rows[2].id]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ids))
    assert sum(r.sent for r in results) == 1 and len(s.calls) == 1
    assert _daily_recipient_count(s.db, s.account, datetime.now(timezone.utc)) == 2


def test_double_start_and_task_delivery_are_idempotent(system):
    s = system
    s.contact()
    path = f"/whatsapp/campaigns/{s.campaign.id}/start"
    assert s.api.post(path, headers=s.headers).status_code == 202
    assert s.api.post(path, headers=s.headers).status_code == 202
    s.drain()
    row = recipients(s)[0]
    s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
    assert len(s.calls) == 1 and len(recipients(s)) == 1


def test_send_reloads_account_and_consent_changed_by_another_session(system):
    s = system
    contact = s.contact(); row = start(s)[0]; s.queue.clear()
    assert s.account.outreach_paused is False and contact.marketing_consent == "opted_in"
    with TestingSessionLocal() as other:
        account = other.get(WhatsappAccount, s.account.id)
        account.outreach_paused = True
        other.commit()
    result = send_outreach_message(s.db, recipient_id=row.id, components=[])
    assert result.deferrable and result.reason_code == "outreach_paused"
    assert s.calls == []
    with TestingSessionLocal() as other:
        other.get(WhatsappAccount, s.account.id).outreach_paused = False
        other.commit()
    s.db.refresh(s.account)
    assert s.account.outreach_paused is False
    assert contact.marketing_consent == "opted_in"  # Keep an independently cached consent row.
    with TestingSessionLocal() as other:
        consent.revoke(other, contact=other.get(WhatsappContact, contact.id), source="inbound_keyword")
        other.commit()
    result = send_outreach_message(s.db, recipient_id=row.id, components=[])
    assert result.reason_code == "contact_opted_out" and s.calls == []


def test_public_opt_in_rate_limit_and_jwt_audience_expiry(system, monkeypatch):
    s = system
    monkeypatch.setattr(settings, "WHATSAPP_PUBLIC_OPT_IN_IP_LIMIT", 1)
    s.redis.delete("whatsapp:public-opt-in:ip:testclient")
    token = s.api.post(f"/whatsapp/accounts/{s.account.id}/opt-in-link", json={}, headers=s.headers).json()["url"].rsplit("/", 1)[-1]
    claims = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=["HS256"], audience="whatsapp_opt_in")
    for patch in ({"aud": "access"}, {"exp": 1}):
        bad = jwt.encode({**claims, **patch}, settings.APP_SECRET_KEY, algorithm="HS256")
        assert s.api.post(f"/public/whatsapp/opt-in/{bad}", json={"phone": "+15550000001"}).status_code == 404
    assert s.api.post(f"/public/whatsapp/opt-in/{token}", json={"phone": "+15550000001"}).status_code == 202
    assert s.api.post(f"/public/whatsapp/opt-in/{token}", json={"phone": "+15550000001"}).status_code == 429
    s.redis.delete("whatsapp:public-opt-in:ip:testclient")


def test_access_token_absent_from_logs_evidence_and_responses(system, caplog):
    s = system
    s.contact(); row = start(s)[0]; s.kind[0] = "invalid_json"
    s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
    responses = [s.api.get(path, headers=s.headers).text for path in
        ("/whatsapp/contacts", "/whatsapp/templates", f"/whatsapp/campaigns/{s.campaign.id}/stats",
         f"/whatsapp/accounts/{s.account.id}/outreach-health")]
    evidence = [e.evidence for e in s.db.query(WhatsappConsentEvent).filter_by(workspace_id=s.workspace.id)]
    assert SECRET not in repr([r.__dict__ for r in caplog.records])
    assert SECRET not in json.dumps(evidence) and SECRET not in repr(responses)


AUTH_ROUTES = [(method, route.path) for route in routes.router.routes for method in sorted(route.methods)]


@pytest.mark.parametrize("method,path", AUTH_ROUTES)
def test_route_authorization_matrix(system, method, path):
    s = system
    contact = s.contact()
    actual = path.format(account_id=s.account.id, contact_id=contact.id,
                         template_id=s.template.id, campaign_id=s.campaign.id)

    def prepare():
        s.db.expire_all()
        s.template.status = "draft" if (method == "PATCH" and "/templates/" in path) or path.endswith("/submit") or method == "DELETE" else "approved"
        s.template.meta_template_id = None
        s.campaign.status = "running" if path.endswith("/pause") else "paused" if path.endswith("/resume") else "completed" if method == "DELETE" else "draft"
        s.account.outreach_paused_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        s.account.health_checked_at = datetime.now(timezone.utc)
        s.db.commit()
        if path.endswith("/health-refresh"):
            s.redis.delete(f"whatsapp:health-refresh:{s.account.id}")

    def request(headers):
        payload = {}
        if path.endswith("/grant") or path.endswith("/revoke"): payload = {"proof": "Internal consent"}
        if path.endswith("/preview"): payload = {"variables": ["Internal"]}
        if path.endswith("/test-send"): payload = {"variables": ["Internal"], "contact_id": str(contact.id)}
        if path.endswith("/resume"): payload = {"note": "Fresh health reviewed"}
        if path.endswith("/outreach-settings"): payload = {"outreach_daily_cap": 10}
        if path == "/whatsapp/templates" and method == "POST":
            payload = {"account_id": str(s.account.id), "name": f"created_{uuid4().hex}",
                       "language": "en_US", "category": "marketing", "components": []}
        if path == "/whatsapp/campaigns" and method == "POST":
            payload = {"account_id": str(s.account.id), "template_id": str(s.template.id), "name": "Created"}
        if path.endswith("/contacts/import"):
            return s.api.post(actual, headers=headers, data={"account_id": str(s.account.id), "attestation": "Internal consent"},
                files={"file": ("internal.csv", "phone,display_name\n+15550000001,Internal\n", "text/csv")})
        return s.api.request(method, actual, headers=headers, **({"json": payload} if method in {"POST", "PATCH"} else {}))

    membership = s.db.query(UserWorkspaceMembership).filter_by(user_id=s.user.id, workspace_id=s.workspace.id).one()
    # Exercise membership authorization even though the global user role is admin.
    for role in ("member", "operator", "viewer", "owner", "admin"):
        prepare()
        if path.endswith("/test-send") or path.endswith("/revoke"):
            consent.grant(s.db, contact=contact, actor=s.user, evidence={"proof": "Internal"})
        membership.role = role; s.db.commit()
        response = request(s.headers)
        assert response.status_code == (403 if role in {"member", "operator", "viewer"} else (201 if method == "POST" and path in {"/whatsapp/templates", "/whatsapp/campaigns", "/whatsapp/contacts/import"} else 202 if path.endswith(("/start", "/health-refresh", "/templates/sync")) else 200)), (role, method, path, response.text)
    if "{" in path:
        prepare()
        foreign = {**s.headers, "X-Workspace-Id": str(s.other.id)}
        response = request(foreign)
        assert response.status_code == 404, (method, path, response.text)
    else:
        # Resource IDs in query/body/form receive the same workspace protection.
        foreign = {**s.headers, "X-Workspace-Id": str(s.other.id)}
        if method == "GET":
            response = s.api.get(actual, params={"account_id": str(s.account.id)}, headers=foreign)
        else:
            response = request(foreign)
        assert response.status_code == 404, (method, path, response.text)


def test_authorization_matrix_covers_all_authenticated_routes():
    assert len(AUTH_ROUTES) == 28


def test_meta_echo_cannot_persist_access_token(system, caplog):
    s = system
    s.contact(); row = start(s)[0]; s.kind[0] = "echo_error"
    s.deliver(tasks.send_whatsapp_campaign_message, str(row.id))
    row = recipients(s)[0]
    assert SECRET not in (row.error_message or "")
    assert SECRET not in (s.db.get(Message, row.message_id).error_message or "")
    assert SECRET not in repr([r.__dict__ for r in caplog.records])
    response = s.api.post(f"/whatsapp/accounts/{s.account.id}/templates/sync", headers=s.headers)
    assert response.status_code == 502 and SECRET not in response.text
