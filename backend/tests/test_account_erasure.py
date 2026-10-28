from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.models.account_erasure_job import AccountErasureJob
from app.models.meta_authorization import MetaAuthorization
from app.models.saas_forward_event import SaasForwardEvent
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.whatsapp_contact import WhatsappContact
from app.services import account_erasure as service
from app.services.meta_grant_identity import MetaGrantIdentity, save_grant
from app.core.config import settings
from app.services.saas_forwarder import purge_expired
from tests.test_contact_erasure import world, seed, IDENTITY  # reusable A/B graph
from tests.test_meta_compliance import _signed


@pytest.mark.parametrize("platform", ["facebook", "whatsapp"])
def test_owner_only_scoped_route_replay_and_two_phases(client, db_session, world, platform):
    target = world.channels[("a", platform)]
    other = world.channels[("b", platform)]
    own = seed(db_session, target, platform)
    preserved = seed(db_session, other, platform)
    own_ids = [(type(row), row.id) for row in own]
    other_ids = [(type(row), row.id) for row in preserved]
    route = f"/{platform}/accounts/{target.id}/hard"
    assert client.delete(route, headers=world.headers).status_code == 403  # admin
    membership = db_session.query(UserWorkspaceMembership).filter_by(user_id=world.user.id).one()
    membership.role = "owner"
    db_session.commit()
    assert client.delete(f"/{platform}/accounts/{other.id}/hard", headers=world.headers).status_code == 404
    response = client.delete(route, headers=world.headers)
    assert response.status_code == 202, response.text
    job_id = UUID(response.json()["job_id"])
    assert client.delete(route, headers=world.headers).json()["job_id"] == str(job_id)
    db_session.expire_all()
    assert target.status == "erasure_pending"
    assert not target.ai_enabled and not target.saas_delegation_enabled
    assert all(db_session.get(model, ident) is None for model, ident in own_ids)
    assert all(db_session.get(model, ident) is not None for model, ident in other_ids)
    job = service.advance_erasure(db_session, job_id)
    assert job.state == "waiting_remote_acceptance"
    events = db_session.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).all()
    assert len(events) == 1 and events[0].payload["external_contact_id"] == IDENTITY
    events[0].status = "sent"  # worker persists only HTTP 202 for A16
    events[0].payload = {}
    db_session.flush()
    service.advance_erasure(db_session, job_id)
    db_session.flush()
    assert db_session.get(type(target), target.id) is None
    assert job.state == "local_erased" and job.remote_verified_at is None
    # Acceptance never completes a public receipt or starts verified retention.
    assert client.delete(route, headers=world.headers).json()["job_id"] == str(job_id)
    assert db_session.get(type(other), other.id) is not None


@pytest.mark.parametrize("platform", ["instagram", "facebook", "whatsapp"])
def test_account_erasure_enumerates_queued_and_contact_only_identities(db_session, world, platform):
    channel = world.channels[("a", platform)]
    seed(db_session, channel, platform)
    db_session.add(SaasForwardEvent(event_id=str(uuid4()), ordering_key="queued-only", platform=platform,
        channel_id=channel.id, event_type="message.received", payload={"external_contact_id": "queued-only"}, status="pending"))
    if platform == "whatsapp":
        db_session.add(WhatsappContact(workspace_id=channel.workspace_id, whatsapp_account_id=channel.id,
                                      wa_id="201111111111", display_name="private"))
    db_session.flush()
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform=platform, channel_id=channel.id)
    events = db_session.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).all()
    expected = {IDENTITY, "queued-only"} | ({"201111111111"} if platform == "whatsapp" else set())
    assert {row.payload["external_contact_id"] for row in events} == expected
    assert db_session.query(SaasForwardEvent).filter(SaasForwardEvent.channel_id == channel.id).count() == len(expected)


def test_failure_rollback_and_failed_a16_retention(db_session, world, monkeypatch):
    channel = world.channels[("a", "whatsapp")]
    lead = seed(db_session, channel, "whatsapp")[0]
    lead_id = lead.id
    original = service.erase_owned_rows
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic rollback")
    with monkeypatch.context() as patch:
        patch.setattr(service, "erase_owned_rows", fail)
        with pytest.raises(RuntimeError), db_session.begin_nested():
            service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform="whatsapp", channel_id=channel.id)
    assert db_session.get(type(lead), lead_id) is not None
    assert db_session.query(AccountErasureJob).count() == 0
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform="whatsapp", channel_id=channel.id)
    event = db_session.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).one()
    event.status = "failed"
    event.completed_at = datetime.now(timezone.utc) - timedelta(days=90)
    db_session.flush()
    purge_expired(db_session)
    assert event.payload and db_session.get(SaasForwardEvent, event.id) is not None
    assert service.advance_erasure(db_session, job.id).state == "operator_action"


@pytest.mark.parametrize("reason", ["missing_signing_configuration", "unknown_remote_scope"])
def test_operator_verification_required(db_session, world, reason):
    channel = world.channels[("a", "facebook")]
    seed(db_session, channel, "facebook")
    if reason == "missing_signing_configuration":
        channel.saas_secret_encrypted = None
    else:
        db_session.query(SaasForwardEvent).filter_by(channel_id=channel.id).update({"payload": {}}, synchronize_session=False)
    db_session.flush()
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform="facebook", channel_id=channel.id)
    assert (job.state, job.error_code) == ("operator_action", reason)
    assert service.advance_erasure(db_session, job.id).state == "operator_action"
    assert service.advance_erasure(db_session, job.id, remote_cleanup_verified=True).state == "local_erased"
    assert job.remote_verified_at is not None


def test_stale_job_never_deletes_a_new_grant(db_session, world):
    channel = world.channels[("a", "whatsapp")]
    seed(db_session, channel, "whatsapp")
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform="whatsapp", channel_id=channel.id)
    channel.status = "connected"  # simulate stale/operator-corrupted state
    db_session.flush()
    assert service.advance_erasure(db_session, job.id, remote_cleanup_verified=True).state == "operator_action"
    assert db_session.get(type(channel), channel.id) is not None


@pytest.mark.parametrize("namespace", ["unresolved", "business_system_user"])
def test_callback_never_matches_unproven_namespaces(client, db_session, world, monkeypatch, namespace):
    from app.services.meta_compliance import subject_digest
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", "facebook-app")
    monkeypatch.setattr(settings, "FACEBOOK_APP_SECRET", "test-facebook-secret")
    channel = world.channels[("a", "facebook")]
    channel.status = "connected"
    db_session.add(MetaAuthorization(app_id=settings.facebook_app_id, subject_digest=subject_digest(settings.facebook_app_id, "12345"),
        subject_namespace=namespace, workspace_id=channel.workspace_id, platform="facebook", channel_id=channel.id,
        verification_source="synthetic"))
    db_session.commit()
    assert client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed()}).status_code == 200
    db_session.refresh(channel)
    assert channel.status == "connected"


@pytest.mark.parametrize("debug", [{}, {"is_valid": False}, {"is_valid": True, "app_id": "other", "user_id": "123"},
    {"is_valid": True, "app_id": "facebook-app", "type": "USER"},
    {"is_valid": True, "app_id": "facebook-app", "type": "PAGE", "user_id": "123"}])
def test_provider_identity_failure(debug, monkeypatch):
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", "facebook-app")
    with pytest.raises(ValueError):
        MetaGrantIdentity.facebook(debug, [{"id": "456"}])


def test_provider_context_and_grant_failures(db_session, world, monkeypatch):
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", "facebook-app")
    debug = {"is_valid": True, "app_id": "facebook-app", "user_id": "123", "type": "USER"}
    identity = MetaGrantIdentity.facebook(debug, [{"id": "456", "access_token": "must-not-store"}])
    channel = world.channels[("a", "facebook")]
    with pytest.raises(ValueError):
        save_grant(db_session, identity, channel, "wrong-grant")
    with pytest.raises(ValueError):
        save_grant(db_session, identity, channel, "456")  # different provider Page
    with pytest.raises(ValueError):
        save_grant(db_session, identity, world.channels[("a", "whatsapp")], "456")
    assert db_session.query(MetaAuthorization).count() == 0
    channel.page_id = "456"
    with pytest.raises(ValueError):
        MetaGrantIdentity.whatsapp(debug, {"id": "789"}, [{"id": "456"}], "other")
    with pytest.raises(ValueError):
        MetaGrantIdentity.instagram({"user_id": "1"}, {"provider_user_id": "2", "provider_profile_id": "3", "ig_user_id": "2"})
    save_grant(db_session, identity, channel, "456")
    from app.utils.crypto import decrypt_text
    mapping = db_session.query(MetaAuthorization).one()
    assert decrypt_text(mapping.subject_encrypted) == "123"
    assert "must-not-store" not in decrypt_text(mapping.provider_context_encrypted)
    replacement = MetaGrantIdentity.facebook({**debug, "user_id": "999"}, [{"id": "456"}])
    save_grant(db_session, replacement, channel, "456")
    db_session.refresh(mapping)
    assert decrypt_text(mapping.subject_encrypted) == "999" and db_session.query(MetaAuthorization).count() == 1


@pytest.mark.parametrize("platform", ["facebook", "whatsapp"])
def test_complete_fk_graph_and_proven_audit_scrub(db_session, world, platform):
    from app.models.audit_log import AuditLog
    from app.models.message import Message
    from app.models.facebook_campaign import FacebookCampaign
    from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
    from app.models.facebook_user_cooldown import FacebookUserCooldown
    from app.models.facebook_comment import FacebookComment
    from app.models.whatsapp_template import WhatsappTemplate
    from app.models.whatsapp_campaign import WhatsappCampaign
    from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
    from app.models.whatsapp_consent_event import WhatsappConsentEvent
    channel = world.channels[("a", platform)]
    lead, conversation, message, *_ = seed(db_session, channel, platform)
    owned = []
    if platform == "facebook":
        campaign = FacebookCampaign(workspace_id=channel.workspace_id, facebook_page_id=channel.id, name="Private campaign")
        comment = FacebookComment(facebook_page_id=channel.id, comment_id=str(uuid4()), from_id=IDENTITY, message="private")
        db_session.add_all([campaign, comment]); db_session.flush()
        message.facebook_campaign_id, message.facebook_comment_id = campaign.id, comment.id
        conversation.facebook_campaign_id = campaign.id
        keyword = FacebookCampaignKeyword(campaign_id=campaign.id, normalized_keyword="private")
        cooldown = FacebookUserCooldown(campaign_id=campaign.id, facebook_user_id=IDENTITY, expires_at=datetime.now(timezone.utc))
        db_session.add_all([keyword, cooldown]); owned += [campaign, comment, keyword, cooldown]
    else:
        template = WhatsappTemplate(workspace_id=channel.workspace_id, whatsapp_account_id=channel.id,
            name="private_template", language="en_US", category="marketing")
        contact = WhatsappContact(workspace_id=channel.workspace_id, whatsapp_account_id=channel.id, wa_id=IDENTITY)
        db_session.add_all([template, contact]); db_session.flush()
        campaign = WhatsappCampaign(workspace_id=channel.workspace_id, whatsapp_account_id=channel.id,
                                    template_id=template.id, name="private", created_by=world.user.id)
        db_session.add(campaign); db_session.flush()
        # Message-only outreach: no lead or conversation.
        outreach = Message(whatsapp_campaign_id=campaign.id, whatsapp_template_id=template.id, content="private outreach")
        db_session.add(outreach); db_session.flush()
        recipient = WhatsappCampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, message_id=outreach.id)
        consent = WhatsappConsentEvent(contact_id=contact.id, workspace_id=channel.workspace_id,
                                       event_type="import", source="csv_import", evidence={"name": "private"})
        db_session.add_all([recipient, consent]); owned += [template, contact, campaign, outreach, recipient, consent]
    audit = AuditLog(action="customer_changed", entity_id=lead.id, entity_name="private", message="private", metadata_={"body": "private"})
    other = AuditLog(action="customer_changed", entity_id=world.user.id, entity_name="preserved", message="preserved")
    db_session.add_all([audit, other]); db_session.flush()
    owned_ids = [(type(row), row.id) for row in owned]
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform=platform, channel_id=channel.id)
    db_session.expire_all()
    assert all(db_session.get(model, ident) is None for model, ident in owned_ids)
    db_session.refresh(audit); db_session.refresh(other)
    assert audit.message == "Account data erased" and audit.metadata_ is None and audit.entity_name is None
    assert other.message == "preserved" and db_session.get(type(world.user), world.user.id) is not None
    assert service.advance_erasure(db_session, job.id, remote_cleanup_verified=True).state == "local_erased"


@pytest.mark.parametrize("platform", ["facebook", "whatsapp"])
def test_mixed_account_webhook_payloads(db_session, world, platform):
    from app.models.webhook_event import WebhookEvent
    target, other = world.channels[("a", platform)], world.channels[("b", platform)]
    if platform == "facebook":
        payload = {"object": "page", "entry": [{"id": target.page_id, "messaging": [{"text": "erase"}]},
                                                 {"id": other.page_id, "messaging": [{"text": "preserve"}]}]}
    else:
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "shared-waba", "changes": [
            {"value": {"metadata": {"phone_number_id": target.phone_number_id}, "messages": [{"text": "erase"}]}},
            {"value": {"metadata": {"phone_number_id": other.phone_number_id}, "messages": [{"text": "preserve"}]}}]}]}
    event = WebhookEvent(provider="meta", external_event_id=str(uuid4()), payload=payload, processing_status="processed")
    db_session.add(event); db_session.flush()
    service.begin_erasure(db_session, workspace_id=target.workspace_id, platform=platform, channel_id=target.id)
    db_session.refresh(event)
    assert "erase" not in str(event.payload) and "preserve" in str(event.payload)


def test_concurrent_erasure_requests_share_job(db_session):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from tests.conftest import engine
    from app.models.workspace import Workspace
    from app.models.whatsapp_account import WhatsappAccount
    workspace_id, channel_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Workspace(id=workspace_id, name="Concurrent", slug=str(workspace_id))); db.flush()
        db.add(WhatsappAccount(id=channel_id, workspace_id=workspace_id, phone_number_id=str(channel_id)))
        db.commit()
    def begin(_):
        with Session(engine) as db:
            job = service.begin_erasure(db, workspace_id=workspace_id, platform="whatsapp", channel_id=channel_id)
            ident = job.id
            db.commit()
            return ident
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(begin, range(2)))
        assert results[0] == results[1]
        with Session(engine) as db:
            assert db.query(AccountErasureJob).filter_by(channel_id=channel_id).count() == 1
    finally:
        with Session(engine) as db:
            db.query(AccountErasureJob).filter_by(channel_id=channel_id).delete()
            db.query(WhatsappAccount).filter_by(id=channel_id).delete()
            db.query(Workspace).filter_by(id=workspace_id).delete()
            db.commit()


def test_a16_only_202_counts_as_acceptance(db_session, world):
    import httpx
    from app.services.saas_forwarder import _attempt
    channel = world.channels[("a", "whatsapp")]
    seed(db_session, channel, "whatsapp")
    job = service.begin_erasure(db_session, workspace_id=channel.workspace_id, platform="whatsapp", channel_id=channel.id)
    event = db_session.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).one()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        assert _attempt(db_session, event, channel, client, datetime.now(timezone.utc), None) == "failed"
    assert event.status == "failed" and service.advance_erasure(db_session, job.id).state == "operator_action"
