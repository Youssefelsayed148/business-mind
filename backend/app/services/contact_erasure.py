"""Transactional, channel-scoped customer erasure and A16 outbox creation.

No commit, network operation, AI generation or Meta delivery occurs here.
The caller commits the local erase, durable outbox and audit together.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import JSON, null, or_, text
from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_comment import FacebookComment
from app.models.facebook_user_cooldown import FacebookUserCooldown
from app.models.lead import Lead
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.user_cooldown import UserCooldown
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.services import saas_forwarder as forwarder

ACCOUNT_FK = {"instagram": "instagram_account_id", "facebook": "facebook_page_id", "whatsapp": "whatsapp_account_id"}
WEBHOOK_RETENTION = timedelta(days=30)


def erasure_event_id(platform: str, channel_id: UUID, external_id: str, request_id: UUID) -> str:
    # Stable opaque id: retries cannot enqueue a second erasure after lead deletion.
    return str(uuid5(NAMESPACE_URL, f"many-contact-erasure:{platform}:{channel_id}:{external_id}:{request_id}"))


def remote_status(event: SaasForwardEvent) -> str:
    if event.status == "sent":
        return "accepted_not_completed"
    if event.status == "pending":
        return "queued"
    return "operator_action_required"


def _mentions_identity(value, identities: set[str]) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("external_contact_id", "sender_id", "sender_ig_id", "sender_wa_id", "wa_id", "recipient_id", "ig_user_id", "facebook_psid"):
        if str(value.get(key, "")) in identities:
            return True
    for key in ("from", "sender", "recipient"):
        nested = value.get(key)
        if isinstance(nested, dict) and str(nested.get("id", "")) in identities:
            return True
        if isinstance(nested, str) and nested in identities:
            return True
    return False


def scrub_webhook_payload(payload, platform: str, channel, identities: set[str]):
    """Return a scrubbed copy; only matching account AND customer items change."""
    if not isinstance(payload, dict):
        return payload, False
    expected = {"instagram": "instagram", "facebook": "page", "whatsapp": "whatsapp_business_account"}[platform]
    if payload.get("object") != expected or not isinstance(payload.get("entry"), list):
        return payload, False
    result = deepcopy(payload)
    changed = False
    entries = []
    for entry in result["entry"]:
        if not isinstance(entry, dict):
            entries.append(entry)
            continue
        if platform in ("instagram", "facebook"):
            account_ref = channel.ig_user_id if platform == "instagram" else channel.page_id
            if str(entry.get("id", "")) != account_ref:
                entries.append(entry)
                continue
            entry_changed = False
            for field in ("messaging", "changes"):
                items = entry.get(field)
                if not isinstance(items, list):
                    continue
                retained = [item for item in items if not _mentions_identity(
                    item.get("value", item) if isinstance(item, dict) else item, identities
                )]
                if len(retained) != len(items):
                    entry[field] = retained
                    entry_changed = True
            changed |= entry_changed
            if not entry_changed or any(entry.get(key) for key in ("messaging", "changes")):
                entries.append(entry)
        else:
            changes = entry.get("changes")
            if not isinstance(changes, list):
                entries.append(entry)
                continue
            retained_changes = []
            entry_changed = False
            for change in changes:
                value = change.get("value") if isinstance(change, dict) else None
                metadata = value.get("metadata") if isinstance(value, dict) else None
                if not isinstance(metadata, dict) or str(metadata.get("phone_number_id", "")) != channel.phone_number_id:
                    retained_changes.append(change)
                    continue
                value_changed = False
                for field in ("messages", "contacts", "statuses"):
                    items = value.get(field)
                    if not isinstance(items, list):
                        continue
                    retained = [item for item in items if not _mentions_identity(item, identities)]
                    if len(retained) != len(items):
                        value[field] = retained
                        value_changed = True
                entry_changed |= value_changed
                if not value_changed or any(value.get(key) for key in ("messages", "contacts", "statuses")):
                    retained_changes.append(change)
            changed |= entry_changed
            entry["changes"] = retained_changes
            if not entry_changed or retained_changes:
                entries.append(entry)
    if not changed:
        return payload, False
    result["entry"] = entries
    return (result if entries else None), True


def _contains_reference(value, references: set[str]) -> bool:
    if isinstance(value, dict):
        if _mentions_identity(value, references):
            return True
        for key, item in value.items():
            if key in {"message_id", "comment_id", "lead_id", "conversation_id", "external_message_id", "provider_message_id"}:
                if isinstance(item, (str, int)) and str(item) in references:
                    return True
            if isinstance(item, (dict, list)) and _contains_reference(item, references):
                return True
    elif isinstance(value, list):
        return any(_contains_reference(item, references) for item in value)
    return False


def _erase_webhooks(db: Session, platform: str, channel, identities: set[str]) -> int:
    count = 0
    expected = {"instagram": "instagram", "facebook": "page", "whatsapp": "whatsapp_business_account"}[platform]
    # Raw deliveries have no workspace column: derive scope through exact
    # provider account IDs inside the payload, never by customer identity alone.
    account_selector = (
        [{"id": channel.ig_user_id if platform == "instagram" else channel.page_id}]
        if platform != "whatsapp" else
        [{"changes": [{"value": {"metadata": {"phone_number_id": channel.phone_number_id}}}]}]
    )
    rows = db.query(WebhookEvent).filter(
        WebhookEvent.provider == "meta", WebhookEvent.payload["object"].astext == expected,
        WebhookEvent.payload["entry"].contains(account_selector),
    ).with_for_update().yield_per(100)
    for event in rows:
        payload, changed = scrub_webhook_payload(event.payload, platform, channel, identities)
        if changed:
            event.payload = payload if payload is not None else null()
            if payload is None:
                event.processing_status = "skipped"
            count += 1
    return count


def erase_contact(db: Session, *, workspace_id: UUID, platform: str, channel,
                  external_contact_id: str, request_id: UUID,
                  now: datetime | None = None) -> dict:
    """Erase local customer rows and atomically persist one idempotent A16 event.

    The channel must already be selected by the authenticated workspace.
    Missing signing config produces a durable operator-action row, not a
    pretend remote completion. Existing ordinary forwards are never replayed.
    """
    now = now or datetime.now(timezone.utc)
    if platform not in ACCOUNT_FK or channel.workspace_id != workspace_id:
        raise ValueError("Channel scope mismatch")
    event_id = erasure_event_id(platform, channel.id, external_contact_id, request_id)
    identity_lock = str(uuid5(NAMESPACE_URL, f"many-erasure-lock:{platform}:{channel.id}:{external_contact_id}"))
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "erasure:" + identity_lock})
    existing = db.query(SaasForwardEvent).filter(
        SaasForwardEvent.event_id == event_id, SaasForwardEvent.platform == platform,
        SaasForwardEvent.channel_id == channel.id,
    ).first()
    if existing is not None:
        return {"event_id": event_id, "local_status": "erased", "remote_status": remote_status(existing), "duplicate": True}

    fk = getattr(Lead, ACCOUNT_FK[platform])
    identity_match = Lead.ig_user_id == external_contact_id
    if platform == "facebook":
        identity_match = or_(identity_match, Lead.facebook_psid == external_contact_id)
    leads = db.query(Lead).filter(
        Lead.workspace_id == workspace_id, Lead.platform == platform,
        fk == channel.id, identity_match,
    ).all()
    lead_ids = [lead.id for lead in leads]
    identities = {external_contact_id}
    identities.update(lead.ig_user_id for lead in leads)
    identities.update(lead.facebook_psid for lead in leads if lead.facebook_psid)
    # Facebook campaign comments use ASID; delegated DMs use PSID.
    remote_identity = next((lead.facebook_psid for lead in leads if lead.facebook_psid), external_contact_id)
    conversations = db.query(Conversation).filter(
        Conversation.workspace_id == workspace_id, Conversation.platform == platform,
        getattr(Conversation, ACCOUNT_FK[platform]) == channel.id,
        Conversation.lead_id.in_(lead_ids),
    ).all()
    conversation_ids = [row.id for row in conversations]
    # Match the existing forward worker's session advisory lock before changing
    # its queue; never hold the channel row lock while waiting on this lock.
    for key in sorted(str(value) for value in conversation_ids):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    payload = {"version": 1, "event_id": event_id, "event_type": "contact.erasure",
               "connection_id": channel.saas_connection_id,
               "external_contact_id": remote_identity,
               "occurred_at": now.isoformat().replace("+00:00", "Z")}
    forwarder.enqueue_event(db, platform=platform, channel=channel,
                            ordering_key="erasure:" + event_id, event_id=event_id,
                            event_type="contact.erasure", payload=payload, now=now)
    erasure = db.query(SaasForwardEvent).filter(SaasForwardEvent.event_id == event_id).one()
    if not (channel.saas_connection_id and channel.saas_base_url and channel.saas_secret_encrypted):
        erasure.status = "failed"
        erasure.last_error = "erasure_operator_action_required: missing_signing_configuration"
        erasure.completed_at = now
        erasure.next_attempt_at = None

    messages = db.query(Message).filter(or_(
        Message.lead_id.in_(lead_ids), Message.conversation_id.in_(conversation_ids)
    )).all()
    message_ids = [message.id for message in messages]
    forward_rows = db.query(SaasForwardEvent).filter(
        SaasForwardEvent.platform == platform, SaasForwardEvent.channel_id == channel.id,
        SaasForwardEvent.event_type != "contact.erasure",
        or_(SaasForwardEvent.ordering_key.in_([str(value) for value in conversation_ids]),
            SaasForwardEvent.payload["external_contact_id"].astext.in_(identities)),
    ).all()
    for event in forward_rows:
        event.payload = {}
        event.last_error = "contact_erased"
        if event.status == "pending":
            event.status = "dropped"
            event.completed_at = now
            event.next_attempt_at = None

    references = identities | {str(value) for value in message_ids + lead_ids + conversation_ids}
    references.update(message.provider_message_id for message in messages if message.provider_message_id)
    if platform == "whatsapp":
        contacts = db.query(WhatsappContact).filter(
            WhatsappContact.workspace_id == workspace_id, WhatsappContact.whatsapp_account_id == channel.id,
            or_(WhatsappContact.wa_id.in_(identities), WhatsappContact.lead_id.in_(lead_ids)),
        ).all()
        contact_ids = [contact.id for contact in contacts]
        recipients = db.query(WhatsappCampaignRecipient).filter(WhatsappCampaignRecipient.contact_id.in_(contact_ids))
        # Outreach messages can have no Lead/conversation at all.
        message_ids.extend(row[0] for row in recipients.with_entities(WhatsappCampaignRecipient.message_id).all() if row[0])
        recipients.delete(synchronize_session=False)
        db.query(WhatsappConsentEvent).filter(
            WhatsappConsentEvent.workspace_id == workspace_id, WhatsappConsentEvent.contact_id.in_(contact_ids)
        ).delete(synchronize_session=False)
        db.query(WhatsappContact).filter(
            WhatsappContact.workspace_id == workspace_id, WhatsappContact.id.in_(contact_ids)
        ).delete(synchronize_session=False)
    else:
        comment_model = Comment if platform == "instagram" else FacebookComment
        comment_fk = comment_model.instagram_account_id if platform == "instagram" else comment_model.facebook_page_id
        author = comment_model.ig_user_id if platform == "instagram" else comment_model.from_id
        comment_ids = [row[0] for row in db.query(comment_model.id).filter(comment_fk == channel.id, author.in_(identities)).all()]
        references.update(str(value) for value in comment_ids)
        references.update(row[0] for row in db.query(comment_model.comment_id).filter(comment_model.id.in_(comment_ids)).all())
        # Null references held by scoped records rather than widening scope.
        if platform == "instagram":
            db.query(Message).filter(Message.id.in_(message_ids), Message.comment_id.in_(comment_ids)).update({Message.comment_id: None}, synchronize_session=False)
            db.query(Lead).filter(Lead.workspace_id == workspace_id, Lead.instagram_account_id == channel.id, Lead.source_comment_id.in_(comment_ids)).update({Lead.source_comment_id: None}, synchronize_session=False)
            campaigns = db.query(Campaign.id).filter(Campaign.workspace_id == workspace_id, Campaign.instagram_account_id == channel.id)
            db.query(UserCooldown).filter(UserCooldown.campaign_id.in_(campaigns), UserCooldown.instagram_user_id.in_(identities)).delete(synchronize_session=False)
        else:
            db.query(Message).filter(Message.id.in_(message_ids), Message.facebook_comment_id.in_(comment_ids)).update({Message.facebook_comment_id: None}, synchronize_session=False)
            campaigns = db.query(FacebookCampaign.id).filter(FacebookCampaign.workspace_id == workspace_id, FacebookCampaign.facebook_page_id == channel.id)
            db.query(FacebookUserCooldown).filter(FacebookUserCooldown.campaign_id.in_(campaigns), FacebookUserCooldown.facebook_user_id.in_(identities)).delete(synchronize_session=False)
        db.query(comment_model).filter(comment_fk == channel.id, comment_model.id.in_(comment_ids)).delete(synchronize_session=False)

    db.query(SaasOutboundMessage).filter(
        SaasOutboundMessage.platform == platform, SaasOutboundMessage.channel_id == channel.id,
        SaasOutboundMessage.message_pk.in_(message_ids),
    ).delete(synchronize_session=False)

    references.update(str(value) for value in message_ids)
    # Log details can contain rendered text; erase customer-linked entries.
    account_fk = getattr(AutomationLog, ACCOUNT_FK[platform])
    logs = db.query(AutomationLog).filter(or_(
        AutomationLog.lead_id.in_(lead_ids), account_fk == channel.id,
    )).all()
    for log in logs:
        if log.lead_id in lead_ids or _contains_reference(log.details, references):
            db.delete(log)
    db.flush()
    db.query(Message).filter(Message.id.in_(message_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(
        Conversation.workspace_id == workspace_id, Conversation.id.in_(conversation_ids)
    ).delete(synchronize_session=False)
    db.query(Lead).filter(Lead.workspace_id == workspace_id, Lead.id.in_(lead_ids)).delete(synchronize_session=False)
    webhook_count = _erase_webhooks(db, platform, channel, identities)
    db.flush()
    return {"event_id": event_id, "local_status": "erased", "remote_status": remote_status(erasure),
            "duplicate": False, "counts": {"leads": len(lead_ids), "conversations": len(conversation_ids),
                                           "messages": len(set(message_ids)), "forward_payloads": len(forward_rows),
                                           "webhook_payloads": webhook_count}}


def retry_erasure(db: Session, event: SaasForwardEvent, channel, *, now: datetime | None = None) -> None:
    """Explicit operator replay; never repoint an event to a different tenant connection."""
    if event.event_type != "contact.erasure" or event.status != "failed" or not event.payload:
        raise ValueError("Erasure is not replayable")
    if not (channel.saas_connection_id and channel.saas_base_url and channel.saas_secret_encrypted):
        raise ValueError("Signing configuration requires operator repair")
    if event.payload.get("connection_id") != channel.saas_connection_id:
        raise ValueError("Original connection must be verified; submit a new erasure after repair")
    now = now or datetime.now(timezone.utc)
    event.status = "pending"
    event.last_error = None
    event.attempts = 0
    event.created_at = now
    event.completed_at = None
    event.next_attempt_at = now


def purge_webhook_payloads(db: Session, *, now: datetime | None = None) -> int:
    """Clear 30-day raw payloads, retaining non-content dedupe/status rows; no commit."""
    now = now or datetime.now(timezone.utc)
    return db.query(WebhookEvent).filter(
        WebhookEvent.created_at <= now - WEBHOOK_RETENTION, WebhookEvent.payload.isnot(None),
        WebhookEvent.payload != JSON.NULL
    ).update({WebhookEvent.payload: null()}, synchronize_session=False)
