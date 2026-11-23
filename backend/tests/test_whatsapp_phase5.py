from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import jwt
from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.requests import Request

from app.api import routes_whatsapp_outreach as routes
from app.authz import ROLE_PERMISSIONS, WorkspaceContext
from app.core.config import settings
from app.core.security import hash_password
from app.integrations.meta.whatsapp_management_client import (
    WhatsappManagementResult,
    WhatsappPhoneNumberHealth,
)
from app.integrations.meta.whatsapp_webhooks import (
    ParsedWhatsappMessageEvent,
    parse_whatsapp_phone_quality_events,
)
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.workspace import Workspace
from app.services.whatsapp_webhook_service import (
    process_inbound_whatsapp_event,
    process_whatsapp_phone_quality_events,
)
from app.workers import whatsapp_tasks
from tests.conftest import skip_if_no_db


def _seed(db, *, campaign_status="draft"):
    workspace = Workspace(name="Phase 5", slug=f"phase-5-{uuid4().hex}")
    user = User(email=f"phase5-{uuid4().hex}@example.test", password_hash="x", role="admin")
    db.add_all([workspace, user]); db.flush()
    account = WhatsappAccount(workspace_id=workspace.id, phone_number_id=f"pn-{uuid4().hex}",
        display_phone_number="+15551234567", whatsapp_business_account_id=f"waba-{uuid4().hex}",
        status="connected", quality_rating="GREEN", health_checked_at=datetime.now(timezone.utc),
        opt_in_keywords=["JOIN"], outreach_daily_cap=1)
    db.add(account); db.flush()
    template = WhatsappTemplate(workspace_id=workspace.id, whatsapp_account_id=account.id,
        name=f"phase5_{uuid4().hex}", language="en_US", category="marketing",
        status="approved", components=[])
    db.add(template); db.flush()
    campaign = WhatsappCampaign(workspace_id=workspace.id, whatsapp_account_id=account.id,
        template_id=template.id, name="Phase 5 campaign", status=campaign_status,
        variable_mapping={}, created_by=user.id)
    opted_in = WhatsappContact(workspace_id=workspace.id, whatsapp_account_id=account.id,
        wa_id="15550000001", marketing_consent="opted_in")
    opted_out = WhatsappContact(workspace_id=workspace.id, whatsapp_account_id=account.id,
        wa_id="15550000002", marketing_consent="opted_out")
    db.add_all([campaign, opted_in, opted_out]); db.commit()
    return workspace, user, account, template, campaign, opted_in, opted_out


def test_phase5_permissions_are_owner_admin_only():
    for permission in ("manage_contacts", "manage_templates", "run_campaigns"):
        assert permission in ROLE_PERMISSIONS["owner"]
        assert permission in ROLE_PERMISSIONS["admin"]
        assert permission not in ROLE_PERMISSIONS["operator"]
        assert permission not in ROLE_PERMISSIONS["viewer"]


@skip_if_no_db
def test_dry_run_is_zero_write_and_splits_terminal_from_deferrable(db_session, monkeypatch):
    workspace, user, _, _, campaign, _, _ = _seed(db_session)
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    before = {
        model: db_session.query(model).count()
        for model in (WhatsappContact, WhatsappCampaignRecipient, WhatsappConsentEvent, AuditLog)
    }
    db_session.expire_all()
    result = routes.dry_run(campaign.id, db=db_session, ctx=ctx)
    after = {model: db_session.query(model).count() for model in before}
    assert result["eligible"] == 1
    assert result["terminal_skips"]["reasons"] == {"contact_opted_out": 1}
    assert result["deferrable_blocks"]["count"] == 0
    assert result["estimated_days_to_finish"] == 1
    assert before == after
    assert not db_session.new and not db_session.dirty and not db_session.deleted


@skip_if_no_db
def test_resume_rechecks_health_commits_audit_then_dispatches(db_session, monkeypatch):
    workspace, user, account, _, campaign, _, _ = _seed(db_session, campaign_status="paused")
    account.outreach_paused = True; account.outreach_paused_reason = "operator"
    account.outreach_paused_at = account.health_checked_at - timedelta(seconds=1)
    db_session.commit()
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    observed = []
    def after_commit(campaign_id):
        db_session.expire_all()
        observed.append((db_session.get(WhatsappCampaign, campaign.id).status,
            db_session.query(AuditLog).filter_by(entity_id=campaign.id).count(), campaign_id))
    monkeypatch.setattr(routes.resume_whatsapp_campaign_dispatch, "delay", after_commit)
    result = routes.resume_campaign(campaign.id, routes.ResumePayload(note="health reviewed"),
                                    db=db_session, ctx=ctx)
    assert result["status"] == "running"
    assert observed == [("running", 1, str(campaign.id))]
    db_session.refresh(account)
    assert account.outreach_paused is False
    assert account.outreach_paused_at is None

    campaign.status = "paused"
    account.health_checked_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        routes.resume_campaign(campaign.id, routes.ResumePayload(note="try stale"),
                               db=db_session, ctx=ctx)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "health_stale"


@skip_if_no_db
def test_cancel_leaves_pending_recipients(db_session):
    workspace, user, _, _, campaign, contact, _ = _seed(db_session, campaign_status="running")
    recipient = WhatsappCampaignRecipient(campaign_id=campaign.id, contact_id=contact.id,
                                          status="pending")
    db_session.add(recipient); db_session.commit()
    result = routes.cancel_campaign(campaign.id, db=db_session,
        ctx=WorkspaceContext(user=user, workspace_id=workspace.id))
    assert result["status"] == "cancelled"
    assert db_session.get(WhatsappCampaignRecipient, recipient.id).status == "pending"


@skip_if_no_db
def test_opt_in_link_requires_keyword_and_rotation_revokes_old_token(db_session, monkeypatch):
    workspace, user, account, _, _, _, _ = _seed(db_session)
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    account.opt_in_keywords = None; db_session.commit()
    with pytest.raises(HTTPException) as exc:
        routes.opt_in_link(account.id, routes.OptInLinkPayload(), db=db_session, ctx=ctx)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "opt_in_keyword_required"

    account.opt_in_keywords = ["JOIN"]; db_session.commit()
    monkeypatch.setattr(settings, "DASHBOARD_BASE_URL", "https://dashboard.example.test")
    first = routes.opt_in_link(account.id, routes.OptInLinkPayload(), db=db_session, ctx=ctx)
    second = routes.opt_in_link(account.id, routes.OptInLinkPayload(rotate=True), db=db_session, ctx=ctx)
    assert first["older_links_revoked"] is False
    assert first["url"].startswith("https://dashboard.example.test/opt-in/")
    assert second["older_links_revoked"] is True
    old_token = first["url"].rsplit("/", 1)[-1]
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                       "client": ("127.0.0.1", 1234), "scheme": "http", "server": ("test", 80),
                       "query_string": b""})
    with pytest.raises(HTTPException) as exc:
        routes.public_opt_in(old_token, routes.PublicOptInPayload(phone="+15550009999"),
                             request, db=db_session)
    assert exc.value.status_code == 404
    assert second["rotated"] is True


@skip_if_no_db
def test_public_opt_in_records_unverified_without_granting_consent(db_session, monkeypatch):
    workspace, user, account, _, _, _, _ = _seed(db_session)
    link = routes.opt_in_link(account.id, routes.OptInLinkPayload(), db=db_session,
        ctx=WorkspaceContext(user=user, workspace_id=workspace.id))
    token = link["url"].rsplit("/", 1)[-1]
    monkeypatch.setattr(routes, "_strict_public_limit", lambda *_: None)
    request = Request({"type": "http", "method": "POST", "path": "/public/whatsapp/opt-in/x",
        "raw_path": b"/public/whatsapp/opt-in/x", "headers": [(b"user-agent", b"test")],
        "client": ("127.0.0.1", 1234), "scheme": "https", "server": ("test", 443),
        "query_string": b""})
    response = routes.public_opt_in(token, routes.PublicOptInPayload(phone="+15550008888"),
                                    request, db=db_session)
    contact = db_session.query(WhatsappContact).filter_by(
        whatsapp_account_id=account.id, wa_id="15550008888").one()
    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert response["accepted"] is True
    assert response["click_to_chat_url"].endswith("?text=JOIN")
    assert contact.marketing_consent == "unknown"
    assert event.event_type == "opt_in_unverified"
    assert event.evidence["request_host"] == "test"
    assert event.evidence["request_path"] == "/public/whatsapp/opt-in/{token}"
    assert token not in str(event.evidence)
    claims = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=["HS256"],
                        audience="whatsapp_opt_in")
    assert claims["aud"] == "whatsapp_opt_in"


@skip_if_no_db
def test_test_send_exception_leaves_terminal_campaign_and_recipient(db_session, monkeypatch):
    workspace, user, _, template, _, contact, _ = _seed(db_session)
    db_session.add(WhatsappConsentEvent(contact_id=contact.id, workspace_id=workspace.id,
        event_type="opt_in", source="manual", evidence={"proof": "Owned test number"},
        actor_user_id=user.id))
    db_session.commit()
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    monkeypatch.setattr(routes, "_strict_daily_test_limit", lambda *_: None)
    monkeypatch.setattr(routes, "send_outreach_message",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("send exploded")))

    with pytest.raises(RuntimeError, match="send exploded"):
        routes.test_send(template.id, routes.TestSendPayload(contact_id=contact.id, variables=[]),
                         db=db_session,
                         ctx=WorkspaceContext(user=user, workspace_id=workspace.id))

    campaign = db_session.query(WhatsappCampaign).filter(
        WhatsappCampaign.name.like("Test send %")).one()
    recipient = db_session.query(WhatsappCampaignRecipient).filter_by(
        campaign_id=campaign.id).one()
    assert campaign.status == "failed"
    assert campaign.completed_at is not None
    assert recipient.status == "failed"
    assert recipient.error_code == "test_send_exception"


@skip_if_no_db
def test_flagged_resume_requires_new_successful_health_poll(db_session, monkeypatch):
    workspace, user, account, _, campaign, _, _ = _seed(
        db_session, campaign_status="paused"
    )
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    monkeypatch.setattr(settings, "WHATSAPP_OUTREACH_ENABLED", True)
    payload = {"object": "whatsapp_business_account", "entry": [{
        "id": account.whatsapp_business_account_id, "time": 1700000500,
        "changes": [{"field": "phone_number_quality_update", "value": {
            "display_phone_number": account.display_phone_number,
            "event": "FLAGGED", "current_limit": "TIER_1K"}}],
    }]}
    process_whatsapp_phone_quality_events(
        db_session, parse_whatsapp_phone_quality_events(payload)
    )
    db_session.refresh(account)
    assert account.outreach_paused_at is not None
    with pytest.raises(HTTPException) as exc:
        routes.resume_campaign(campaign.id, routes.ResumePayload(note="too soon"),
                               db=db_session, ctx=ctx)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "health_unconfirmed"

    class SessionProxy:
        def __getattr__(self, name):
            return getattr(db_session, name)
        def close(self):
            pass

    class Client:
        def get_phone_number_health(self, *_args):
            return WhatsappManagementResult(True, data=[WhatsappPhoneNumberHealth(
                account.phone_number_id, None, account.display_phone_number, "GREEN")])
        def close(self):
            pass

    monkeypatch.setattr(whatsapp_tasks, "SessionLocal", lambda: SessionProxy())
    monkeypatch.setattr(whatsapp_tasks, "get_decrypted_token", lambda *_: "token")
    monkeypatch.setattr(whatsapp_tasks, "WhatsappManagementClient", Client)
    monkeypatch.setattr(whatsapp_tasks, "clear_whatsapp_defer_gate", lambda **_: None)
    monkeypatch.setattr(routes.resume_whatsapp_campaign_dispatch, "delay", lambda *_: None)
    assert whatsapp_tasks.poll_whatsapp_account_health.run()["succeeded"] == 1
    db_session.refresh(account)
    assert account.health_checked_at > account.outreach_paused_at
    result = routes.resume_campaign(campaign.id, routes.ResumePayload(note="poll confirmed"),
                                    db=db_session, ctx=ctx)
    assert result["status"] == "running"


@skip_if_no_db
def test_public_opt_in_then_uppercase_configured_keyword_grants_consent(db_session, monkeypatch):
    workspace, user, account, _, _, _, _ = _seed(db_session)
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    routes.update_outreach_settings(
        account.id, routes.OutreachSettings(opt_in_keywords=["JoIn"]),
        db=db_session, ctx=ctx,
    )
    db_session.refresh(account)
    assert account.opt_in_keywords == ["JOIN"]
    link = routes.opt_in_link(account.id, routes.OptInLinkPayload(), db=db_session, ctx=ctx)
    token = link["url"].rsplit("/", 1)[-1]
    monkeypatch.setattr(routes, "_strict_public_limit", lambda *_: None)
    request = Request({"type": "http", "method": "POST",
        "path": f"/public/whatsapp/opt-in/{token}", "headers": [],
        "client": ("127.0.0.1", 1234), "scheme": "https", "server": ("test", 443),
        "query_string": b""})
    routes.public_opt_in(token, routes.PublicOptInPayload(phone="+15550007777"),
                         request, db=db_session)
    contact = db_session.query(WhatsappContact).filter_by(
        whatsapp_account_id=account.id, wa_id="15550007777").one()
    assert contact.marketing_consent == "unknown"
    assert db_session.query(WhatsappConsentEvent).filter_by(
        contact_id=contact.id, event_type="opt_in_unverified").count() == 1

    result = process_inbound_whatsapp_event(db_session, ParsedWhatsappMessageEvent(
        phone_number_id=account.phone_number_id, sender_wa_id=contact.wa_id,
        text="join", sender_profile_name="Opt In", message_id=f"wamid.{uuid4().hex}",
        timestamp="1700000600", message_type="text", referral=None, raw_event={},
    ))
    db_session.refresh(contact)
    assert result is not None and result.consent_action == "opt_in"
    assert contact.marketing_consent == "opted_in"
    assert db_session.query(WhatsappConsentEvent).filter_by(
        contact_id=contact.id, event_type="opt_in").count() == 1


@skip_if_no_db
def test_health_response_exposes_current_outreach_settings(db_session):
    workspace, user, account, _, _, _, _ = _seed(db_session)
    account.ctwa_counts_as_consent = True
    account.transactional_utility_attested = True
    account.opt_in_keywords = ["JOIN", "YES"]
    account.opt_out_keywords = ["STOP"]
    account.outreach_daily_cap = 321
    db_session.commit()

    response = routes.outreach_health(
        account.id,
        db=db_session,
        ctx=WorkspaceContext(user=user, workspace_id=workspace.id),
    )

    assert response["ctwa_counts_as_consent"] is True
    assert response["transactional_utility_attested"] is True
    assert response["opt_in_keywords"] == ["JOIN", "YES"]
    assert response["opt_out_keywords"] == ["STOP"]
    assert response["outreach_daily_cap"] == 321


@skip_if_no_db
def test_health_refresh_permission_is_workspace_scoped(client, db_session, monkeypatch):
    workspace, _, account, _, _, _, _ = _seed(db_session)
    viewer = User(
        email=f"viewer-{uuid4().hex}@example.test",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(viewer)
    db_session.flush()
    db_session.add(UserWorkspaceMembership(
        user_id=viewer.id, workspace_id=workspace.id, role="viewer"
    ))
    db_session.commit()
    login = client.post(
        "/auth/login", data={"username": viewer.email, "password": "secret"}
    )
    token = login.json()["access_token"]
    monkeypatch.setattr(routes, "_strict_health_refresh_limit", lambda *_: None)
    monkeypatch.setattr(routes.poll_whatsapp_account_health, "delay", lambda *_: None)

    response = client.post(
        f"/whatsapp/accounts/{account.id}/health-refresh",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-Id": str(workspace.id),
        },
    )

    assert response.status_code == 403


@skip_if_no_db
def test_health_refresh_rate_limit_fails_closed(db_session, monkeypatch):
    workspace, user, account, _, _, _, _ = _seed(db_session)
    ctx = WorkspaceContext(user=user, workspace_id=workspace.id)
    queued = []

    class RedisOnce:
        def __init__(self):
            self.calls = 0

        def set(self, *_args, **_kwargs):
            self.calls += 1
            return self.calls == 1

    monkeypatch.setattr(routes, "_redis_client", RedisOnce())
    monkeypatch.setattr(
        routes.poll_whatsapp_account_health, "delay", lambda account_id: queued.append(account_id)
    )
    assert routes.refresh_account_health(account.id, db=db_session, ctx=ctx)["accepted"] is True
    assert queued == [str(account.id)]
    with pytest.raises(HTTPException) as exc:
        routes.refresh_account_health(account.id, db=db_session, ctx=ctx)
    assert exc.value.status_code == 429

    class RedisDown:
        def set(self, *_args, **_kwargs):
            raise RedisError("down")

    monkeypatch.setattr(routes, "_redis_client", RedisDown())
    with pytest.raises(HTTPException) as exc:
        routes.refresh_account_health(account.id, db=db_session, ctx=ctx)
    assert exc.value.status_code == 503


@skip_if_no_db
def test_manual_health_poll_is_scoped_to_one_account(db_session, monkeypatch):
    workspace, _, account, _, _, _, _ = _seed(db_session)
    other = WhatsappAccount(
        workspace_id=workspace.id,
        phone_number_id=f"pn-{uuid4().hex}",
        whatsapp_business_account_id=f"waba-{uuid4().hex}",
        status="connected",
    )
    db_session.add(other)
    db_session.commit()
    requested = []

    class SessionProxy:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    class Client:
        def get_phone_number_health(self, _token, waba_id):
            requested.append(waba_id)
            return WhatsappManagementResult(False, error_message="test stop")

        def close(self):
            pass

    monkeypatch.setattr(whatsapp_tasks, "SessionLocal", lambda: SessionProxy())
    monkeypatch.setattr(whatsapp_tasks, "get_decrypted_token", lambda *_: "token")
    monkeypatch.setattr(whatsapp_tasks, "WhatsappManagementClient", Client)

    result = whatsapp_tasks.poll_whatsapp_account_health.run(str(account.id))

    assert result == {"succeeded": 0, "paused": 0}
    assert requested == [account.whatsapp_business_account_id]
