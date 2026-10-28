from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.automation_log import AutomationLog
from app.models.conversation import Conversation
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_contact import WhatsappContact
from app.services import contact_erasure as service, saas_forwarder as forwarder
from app.services.saas_delegation_service import apply_config

IDENTITY = "201234567890"


@pytest.fixture
def world(db_session):
    from app.models.workspace import Workspace
    workspaces = [Workspace(name=name, slug="erase-" + name) for name in ("a", "b")]
    db_session.add_all(workspaces)
    db_session.flush()
    user = User(email="privacy@test.invalid", password_hash="unused", role="admin", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserWorkspaceMembership(user_id=user.id, workspace_id=workspaces[0].id, role="admin"))
    channels = {}
    for workspace in workspaces:
        for platform, model, key in (("instagram", InstagramAccount, "ig_user_id"), ("facebook", FacebookPage, "page_id"), ("whatsapp", WhatsappAccount, "phone_number_id")):
            channel = model(workspace_id=workspace.id, **{key: platform + str(workspace.id)})
            apply_config(channel, {"saas_connection_id": str(uuid4()), "saas_base_url": "https://saas.example.com", "secret": "synthetic-signing-key-" + "s" * 32, "saas_delegation_enabled": True})
            db_session.add(channel)
            channels[(workspace.slug[-1], platform)] = channel
    db_session.commit()
    headers = {"Authorization": "Bearer " + create_access_token(str(user.id)), "X-Workspace-Id": str(workspaces[0].id)}
    return SimpleNamespace(workspace=workspaces[0], other=workspaces[1], user=user, channels=channels, headers=headers)


def seed(db, channel, platform, identity=IDENTITY):
    fk = service.ACCOUNT_FK[platform]
    lead = Lead(workspace_id=channel.workspace_id, platform=platform, ig_user_id=identity, ig_username="private name", **{fk: channel.id})
    db.add(lead)
    db.flush()
    conversation = Conversation(workspace_id=channel.workspace_id, platform=platform, lead_id=lead.id, **{fk: channel.id})
    db.add(conversation)
    db.flush()
    message = Message(lead_id=lead.id, conversation_id=conversation.id, content="private body", rendered_body="private body", provider_message_id="private-provider-" + str(uuid4()))
    db.add(message)
    db.flush()
    log = AutomationLog(lead_id=lead.id, action="customer_message", details={"text": "private body"}, **{fk: channel.id})
    link = SaasOutboundMessage(connection_id=channel.saas_connection_id, message_id=str(uuid4()), platform=platform, channel_id=channel.id, kind="reply", message_pk=message.id)
    db.add_all([log, link])
    for status in ("pending", "failed", "sent"):
        event = SaasForwardEvent(event_id=str(uuid4()), ordering_key=str(conversation.id), platform=platform, channel_id=channel.id, event_type="message.received", payload={"external_contact_id": identity, "text": "private body"}, status=status)
        db.add(event)
    db.commit()
    return lead, conversation, message, log, link


def url(platform, channel):
    return f"/privacy/contact-erasure/{platform}/{channel.id}"


def erase(client, world, platform="instagram", identity=IDENTITY, request_id=None):
    return client.post(url(platform, world.channels[("a", platform)]), json={"request_id": str(request_id or uuid4()), "external_contact_id": identity}, headers=world.headers)


@pytest.mark.parametrize("platform", ["instagram", "facebook", "whatsapp"])
def test_erasure_is_scoped_atomic_and_durably_queued(client, db_session, world, platform):
    target_channel = world.channels[("a", platform)]
    target = seed(db_session, target_channel, platform)
    other_workspace = seed(db_session, world.channels[("b", platform)], platform)
    other_platform = "facebook" if platform != "facebook" else "instagram"
    other_channel = seed(db_session, world.channels[("a", other_platform)], other_platform)
    target_ids = [(type(row), row.id) for row in target]
    preserved_ids = [(type(row), row.id) for row in other_workspace + other_channel]
    response = erase(client, world, platform)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["local_status"] == "erased" and result["remote_status"] == "queued"
    db_session.expire_all()
    for model, key in target_ids:
        assert db_session.query(model).filter(model.id == key).count() == 0
    for model, key in preserved_ids:
        assert db_session.query(model).filter(model.id == key).count() == 1
    event = db_session.query(SaasForwardEvent).filter_by(event_id=result["event_id"]).one()
    assert event.event_type == "contact.erasure" and event.channel_id == target_channel.id
    assert set(event.payload) == {"version", "event_id", "event_type", "connection_id", "occurred_at", "external_contact_id"}
    assert event.payload["external_contact_id"] == IDENTITY
    ordinary = db_session.query(SaasForwardEvent).filter(SaasForwardEvent.channel_id == target_channel.id, SaasForwardEvent.event_type != "contact.erasure").all()
    assert len(ordinary) == 3 and all(row.payload == {} for row in ordinary)
    assert next(row for row in ordinary if row.status == "dropped").last_error == "contact_erased"
    audit = db_session.query(AuditLog).filter_by(action="contact_erasure_local").one()
    assert IDENTITY not in str(audit.metadata_) and "private body" not in str(audit.metadata_)


def test_workspace_and_admin_authorization(client, db_session, world):
    a, b = world.channels[("a", "instagram")], world.channels[("b", "instagram")]
    body = {"request_id": str(uuid4()), "external_contact_id": IDENTITY}
    assert client.post(url("instagram", b), json=body, headers=world.headers).status_code == 404
    missing = dict(world.headers); missing.pop("X-Workspace-Id")
    assert client.post(url("instagram", a), json=body, headers=missing).status_code == 400
    other = {**world.headers, "X-Workspace-Id": str(world.other.id)}
    assert client.post(url("instagram", a), json=body, headers=other).status_code == 403
    membership = db_session.query(UserWorkspaceMembership).filter_by(user_id=world.user.id).one()
    membership.role = "viewer"; db_session.commit()
    assert client.post(url("instagram", a), json=body, headers=world.headers).status_code == 403
    assert db_session.query(SaasForwardEvent).count() == 0


@pytest.mark.parametrize("identity", ["", " ", " trailing", "trailing ", "control\n", "x" * 256])
def test_invalid_identity_is_rejected(client, world, identity):
    assert erase(client, world, identity=identity).status_code == 422


def test_queue_failure_rolls_back_every_local_change(client, db_session, world, monkeypatch):
    target = seed(db_session, world.channels[("a", "instagram")], "instagram")
    lead_id = target[0].id
    original = service._erase_webhooks
    def fail_after_queue(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after local changes")
    monkeypatch.setattr(service, "_erase_webhooks", fail_after_queue)
    assert erase(client, world).status_code == 500
    assert db_session.get(Lead, lead_id) is not None
    assert db_session.query(SaasForwardEvent).filter_by(event_type="contact.erasure").count() == 0
    assert db_session.query(AuditLog).filter_by(action="contact_erasure_local").count() == 0
    assert all(row.payload for row in db_session.query(SaasForwardEvent).all())


def test_repeat_request_and_missing_identity_are_idempotent(client, db_session, world):
    request_id = uuid4()
    first = erase(client, world, request_id=request_id)
    second = erase(client, world, request_id=request_id)
    assert first.status_code == second.status_code == 202
    assert first.json()["event_id"] == second.json()["event_id"]
    assert second.json()["duplicate"] is True
    assert db_session.query(SaasForwardEvent).count() == 1
    assert db_session.query(AuditLog).filter_by(action="contact_erasure_local").count() == 1


def test_missing_signing_config_requires_operator_and_status_is_scoped(client, db_session, world):
    channel = world.channels[("a", "instagram")]
    channel.saas_connection_id = None; channel.saas_secret_encrypted = None
    db_session.commit()
    response = erase(client, world)
    assert response.status_code == 202 and response.json()["remote_status"] == "operator_action_required"
    event_id = response.json()["event_id"]
    status_url = url("instagram", channel) + "/" + event_id
    assert client.get(status_url, headers=world.headers).json()["operator_action_required"] is True
    assert client.post(status_url + "/retry", headers=world.headers).status_code == 409
    assert client.get(url("instagram", world.channels[("b", "instagram")]) + "/" + event_id, headers=world.headers).status_code == 404


def test_disabled_delegation_does_not_block_explicit_erasure_replay(client, db_session, world):
    channel = world.channels[("a", "instagram")]
    response = erase(client, world)
    event = db_session.query(SaasForwardEvent).filter_by(event_id=response.json()["event_id"]).one()
    event.status = "failed"; event.last_error = "http_401"
    channel.saas_delegation_enabled = False; db_session.commit()
    retry = client.post(url("instagram", channel) + "/" + event.event_id + "/retry", headers=world.headers)
    assert retry.status_code == 202 and retry.json()["remote_status"] == "queued"
    db_session.refresh(event)
    assert event.status == "pending" and event.attempts == 0
    event.status = "sent"; event.payload = {}; db_session.commit()
    result = client.get(url("instagram", channel) + "/" + event.event_id, headers=world.headers).json()
    assert result["remote_status"] == "accepted_not_completed"
    assert client.post(url("instagram", channel) + "/" + event.event_id + "/retry", headers=world.headers).status_code == 409


@pytest.mark.parametrize("platform", ["instagram", "facebook", "whatsapp"])
def test_raw_payload_scrubbing_preserves_other_account_and_customer(client, db_session, world, platform):
    channel, other = world.channels[("a", platform)], world.channels[("b", platform)]
    if platform != "whatsapp":
        ref = channel.ig_user_id if platform == "instagram" else channel.page_id
        other_ref = other.ig_user_id if platform == "instagram" else other.page_id
        payload = {"object": "instagram" if platform == "instagram" else "page", "entry": [
            {"id": ref, "messaging": [{"sender": {"id": IDENTITY}, "message": {"text": "erase me"}}, {"sender": {"id": "other-customer"}, "message": {"text": "keep"}}]},
            {"id": other_ref, "messaging": [{"sender": {"id": IDENTITY}, "message": {"text": "keep other tenant"}}]},
        ]}
    else:
        def change(number):
            return {"field": "messages", "value": {"metadata": {"phone_number_id": number}, "messages": [{"from": IDENTITY, "text": {"body": "erase me"}}, {"from": "other-customer", "text": {"body": "keep"}}], "contacts": [{"wa_id": IDENTITY, "profile": {"name": "private"}}, {"wa_id": "other-customer"}], "statuses": [{"recipient_id": IDENTITY}, {"recipient_id": "other-customer"}]}}
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "shared-waba", "changes": [change(channel.phone_number_id), change(other.phone_number_id)]}]}
    event = WebhookEvent(provider="meta", external_event_id=str(uuid4()), payload=payload)
    db_session.add(event); db_session.commit()
    assert erase(client, world, platform).status_code == 202
    db_session.refresh(event)
    if platform != "whatsapp":
        assert len(event.payload["entry"][0]["messaging"]) == 1
        assert event.payload["entry"][1] == payload["entry"][1]
    else:
        changes = event.payload["entry"][0]["changes"]
        assert all(len(changes[0]["value"][key]) == 1 for key in ("messages", "contacts", "statuses"))
        assert changes[1] == payload["entry"][0]["changes"][1]


def test_whatsapp_contact_without_lead_is_erased(client, db_session, world):
    channel = world.channels[("a", "whatsapp")]
    contact = WhatsappContact(workspace_id=channel.workspace_id, whatsapp_account_id=channel.id, wa_id=IDENTITY, display_name="private")
    db_session.add(contact); db_session.commit(); key = contact.id
    assert erase(client, world, "whatsapp").status_code == 202
    assert db_session.query(WhatsappContact).filter_by(id=key).count() == 0


def test_facebook_psid_erases_campaign_asid_alias(client, db_session, world):
    channel = world.channels[("a", "facebook")]
    lead = seed(db_session, channel, "facebook", identity="campaign-asid")[0]
    lead.facebook_psid = IDENTITY; db_session.commit(); key = lead.id
    response = erase(client, world, "facebook", identity="campaign-asid")
    assert response.status_code == 202
    event = db_session.query(SaasForwardEvent).filter_by(event_id=response.json()["event_id"]).one()
    assert event.payload["external_contact_id"] == IDENTITY
    assert db_session.query(Lead).filter_by(id=key).count() == 0


@pytest.mark.parametrize("platform", ["instagram", "facebook", "whatsapp"])
def test_same_identity_on_second_channel_in_same_workspace_is_preserved(client, db_session, world, platform):
    model = forwarder.CHANNEL_MODELS[platform]
    key = {"instagram": "ig_user_id", "facebook": "page_id", "whatsapp": "phone_number_id"}[platform]
    channel = model(workspace_id=world.workspace.id, saas_connection_id=str(uuid4()), **{key: "second-" + str(uuid4())})
    db_session.add(channel); db_session.commit()
    preserved = seed(db_session, channel, platform)[0].id
    seed(db_session, world.channels[("a", platform)], platform)
    assert erase(client, world, platform).status_code == 202
    assert db_session.query(Lead).filter_by(id=preserved).count() == 1


@pytest.mark.parametrize("platform", ["instagram", "facebook"])
def test_comments_cooldowns_and_identifiable_automation_logs_are_erased(client, db_session, world, platform):
    from datetime import timedelta
    from app.models.campaign import Campaign
    from app.models.comment import Comment
    from app.models.facebook_campaign import FacebookCampaign
    from app.models.facebook_comment import FacebookComment
    from app.models.facebook_user_cooldown import FacebookUserCooldown
    from app.models.user_cooldown import UserCooldown
    channel = world.channels[("a", platform)]
    lead, conversation, message, _, _ = seed(db_session, channel, platform)
    if platform == "instagram":
        campaign = Campaign(workspace_id=world.workspace.id, instagram_account_id=channel.id, name="preserved business campaign", message_template="business template")
        comment = Comment(instagram_account_id=channel.id, comment_id="comment-" + str(uuid4()), ig_user_id=IDENTITY, message="private comment")
    else:
        campaign = FacebookCampaign(workspace_id=world.workspace.id, facebook_page_id=channel.id, name="preserved business campaign")
        comment = FacebookComment(facebook_page_id=channel.id, comment_id="comment-" + str(uuid4()), from_id=IDENTITY, message="private comment")
    db_session.add_all([campaign, comment]); db_session.flush()
    if platform == "instagram":
        message.comment_id = comment.id
        lead.source_comment_id = comment.id
        cooldown = UserCooldown(campaign_id=campaign.id, instagram_user_id=IDENTITY, expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    else:
        message.facebook_comment_id = comment.id
        cooldown = FacebookUserCooldown(campaign_id=campaign.id, facebook_user_id=IDENTITY, expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    identifying_log = AutomationLog(action="message_event", details={"message_id": str(message.id), "body": "private"}, **{service.ACCOUNT_FK[platform]: channel.id})
    other_log = AutomationLog(action="message_event", details={"external_contact_id": "different-customer", "body": IDENTITY}, **{service.ACCOUNT_FK[platform]: channel.id})
    db_session.add_all([cooldown, identifying_log, other_log]); db_session.commit()
    comment_type, comment_id = type(comment), comment.id
    cooldown_type, cooldown_id = type(cooldown), cooldown.id
    log_id, preserved_log_id, campaign_id = identifying_log.id, other_log.id, campaign.id
    assert erase(client, world, platform).status_code == 202
    assert db_session.query(comment_type).filter_by(id=comment_id).count() == 0
    assert db_session.query(cooldown_type).filter_by(id=cooldown_id).count() == 0
    assert db_session.query(AutomationLog).filter_by(id=log_id).count() == 0
    assert db_session.query(AutomationLog).filter_by(id=preserved_log_id).count() == 1
    assert db_session.query(type(campaign)).filter_by(id=campaign_id).count() == 1


def test_whatsapp_outreach_messages_recipients_and_consent_are_erased(client, db_session, world):
    from app.models.whatsapp_template import WhatsappTemplate
    from app.models.whatsapp_campaign import WhatsappCampaign
    from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
    from app.models.whatsapp_consent_event import WhatsappConsentEvent
    channel = world.channels[("a", "whatsapp")]
    template = WhatsappTemplate(workspace_id=world.workspace.id, whatsapp_account_id=channel.id, name="retained", language="en", category="utility")
    db_session.add(template); db_session.flush()
    campaign = WhatsappCampaign(workspace_id=world.workspace.id, whatsapp_account_id=channel.id, template_id=template.id, name="retained", created_by=world.user.id)
    contact = WhatsappContact(workspace_id=world.workspace.id, whatsapp_account_id=channel.id, wa_id=IDENTITY)
    message = Message(lead_id=None, whatsapp_campaign_id=campaign.id, content="private outreach body")
    db_session.add_all([campaign, contact]); db_session.flush()
    message.whatsapp_campaign_id = campaign.id
    db_session.add(message); db_session.flush()
    recipient = WhatsappCampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, message_id=message.id)
    consent = WhatsappConsentEvent(contact_id=contact.id, workspace_id=world.workspace.id, event_type="opt_in", source="manual", evidence={"name": "private"})
    db_session.add_all([recipient, consent]); db_session.commit()
    removed = [(type(row), row.id) for row in (contact, recipient, consent, message)]
    assert erase(client, world, "whatsapp").status_code == 202
    for model, key in removed:
        assert db_session.query(model).filter_by(id=key).count() == 0
    assert db_session.query(WhatsappCampaign).filter_by(id=campaign.id).count() == 1
    assert db_session.query(WhatsappTemplate).filter_by(id=template.id).count() == 1


def test_only_customer_webhook_body_is_sql_null_and_pending_work_is_skipped(client, db_session, world):
    channel = world.channels[("a", "instagram")]
    event = WebhookEvent(provider="meta", external_event_id=str(uuid4()), payload={"object": "instagram", "entry": [{"id": channel.ig_user_id, "messaging": [{"sender": {"id": IDENTITY}, "message": {"text": "erase"}}]}]}, processing_status="pending")
    db_session.add(event); db_session.commit(); key = event.id
    assert erase(client, world).status_code == 202
    db_session.expire_all()
    assert db_session.query(WebhookEvent).filter(WebhookEvent.id == key, WebhookEvent.payload.is_(None)).count() == 1
    assert db_session.get(WebhookEvent, key).processing_status == "skipped"
