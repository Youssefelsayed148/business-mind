"""Delegated-mode inbound handling shared by all three platforms (M-02).

One helper, called from one early branch per platform: it resolves (or
creates) the conversation, stores the inbound message exactly as the AI
dispatch functions do, and queues a `message.received` event for the SaaS.
It never generates a reply and never calls ai_service.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.message import Message
from app.models.whatsapp_campaign import WhatsappCampaign
from app.services import conversation_service
from app.services.saas_forwarder import CONTRACT_CHANNEL, enqueue_event

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4000
WINDOW = timedelta(hours=24)


def derived_message_id(platform: str, channel_id, sender_id: str, timestamp, text: str) -> str:
    """Stable id for platforms that gave no message id (contract A6)."""
    raw = f"{platform}|{channel_id}|{sender_id}|{timestamp}|{text}".encode("utf-8")
    return "many-" + hashlib.sha256(raw).hexdigest()[:40]


def _find_or_create_conversation(db: Session, platform: str, channel, lead) -> Conversation:
    """One conversation per lead per channel, whichever campaign it began
    from. An existing row (e.g. from a comment-to-DM campaign) is reused so
    the thread and its external_conversation_id stay stable."""
    column = {
        "instagram": Conversation.instagram_account_id,
        "whatsapp": Conversation.whatsapp_account_id,
        "facebook": Conversation.facebook_page_id,
    }[platform]
    existing = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead.id, column == channel.id)
        .order_by(Conversation.created_at)
        .first()
    )
    if existing is not None:
        return existing
    kwargs = {
        "instagram": {"instagram_account_id": channel.id},
        "whatsapp": {"platform": "whatsapp", "whatsapp_account_id": channel.id},
        "facebook": {"platform": "facebook", "facebook_page_id": channel.id},
    }[platform]
    return conversation_service.get_or_create_conversation(
        db,
        workspace_id=channel.workspace_id,
        lead_id=lead.id,
        campaign_id=None,
        **kwargs,
    )


def _origin(db: Session, platform: str, lead) -> dict | None:
    """Campaign context (contract A11): campaign name and the text Many
    delivered. Sent on every forwarded message of such a conversation."""
    query = db.query(Message).filter(Message.lead_id == lead.id, Message.direction == "outbound")
    if platform == "whatsapp":
        message = (
            query.filter(Message.whatsapp_campaign_id.isnot(None)).order_by(Message.created_at.desc()).first()
        )
        campaign = db.get(WhatsappCampaign, message.whatsapp_campaign_id) if message else None
    elif platform == "facebook":
        message = (
            query.filter(Message.facebook_campaign_id.isnot(None)).order_by(Message.created_at.desc()).first()
        )
        campaign = db.get(FacebookCampaign, message.facebook_campaign_id) if message else None
    else:
        message = (
            query.filter(Message.campaign_id.isnot(None))
            .order_by((Message.message_type == "final_delivery").desc(), Message.created_at.desc())
            .first()
        )
        campaign = db.get(Campaign, message.campaign_id) if message else None
    if message is None or campaign is None:
        return None
    return {
        "type": "campaign",
        "campaign_name": (campaign.name or "")[:120],
        "opening_message_text": (message.rendered_body or message.content or "")[:2000],
        "campaign_ref": str(campaign.id)[:128],
    }


def build_message_received_payload(
    *,
    platform: str,
    connection_id: str,
    event_id: str,
    external_contact_id: str,
    contact: dict,
    conversation_id,
    external_message_id: str,
    message_type: str,
    text: str | None,
    received_at: datetime,
    window_expires_at: datetime | None,
    origin: dict | None,
    occurred_at: datetime | None = None,
) -> dict:
    payload = {
        "version": 1,
        "event_id": event_id,
        "event_type": "message.received",
        "connection_id": connection_id,
        "occurred_at": _iso(occurred_at or datetime.now(timezone.utc)),
        "channel": CONTRACT_CHANNEL[platform],
        "external_contact_id": external_contact_id,
        "contact": {k: v for k, v in contact.items() if v},
        "external_conversation_id": str(conversation_id),
        "external_message_id": external_message_id,
        "type": message_type,
        "received_at": _iso(received_at),
    }
    if message_type == "text" and text:
        payload["text"] = text[:MAX_TEXT_CHARS]
    if window_expires_at is not None:
        payload["window_expires_at"] = _iso(window_expires_at)
    if origin:
        payload["origin"] = origin
    return payload


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def delegate_inbound(
    db: Session,
    *,
    platform: str,
    channel,
    lead,
    external_contact_id: str,
    contact: dict,
    text: str | None,
    message_type: str,
    external_message_id: str | None,
    timestamp,
    received_at: datetime,
    window_expires_at: datetime | None = None,
    kick: bool = True,
) -> Conversation:
    """Store the inbound message and queue it for the SaaS. Commits."""
    conversation = _find_or_create_conversation(db, platform, channel, lead)
    stored_text = text if message_type == "text" else None
    db.add(
        Message(
            campaign_id=None,
            lead_id=lead.id,
            conversation_id=conversation.id,
            direction="inbound",
            content=stored_text or "[unsupported message type]",
            rendered_body=stored_text or "[unsupported message type]",
            message_type="ai_conversation",
            status="received",
            provider_message_id=external_message_id,
        )
    )
    conversation_service.touch_conversation(db, conversation)

    ext_id = external_message_id or derived_message_id(
        platform, channel.id, external_contact_id, timestamp, text or ""
    )
    event_id = f"in:{platform}:{ext_id}"[:128]
    payload = build_message_received_payload(
        platform=platform,
        connection_id=channel.saas_connection_id,
        event_id=event_id,
        external_contact_id=external_contact_id,
        contact=contact,
        conversation_id=conversation.id,
        external_message_id=ext_id,
        message_type=message_type,
        text=text,
        received_at=received_at,
        window_expires_at=window_expires_at or received_at + WINDOW,
        origin=_origin(db, platform, lead),
    )
    key = str(conversation.id)
    enqueue_event(
        db,
        platform=platform,
        channel=channel,
        ordering_key=key,
        event_id=event_id,
        event_type="message.received",
        payload=payload,
    )
    db.commit()
    if kick:
        _kick(key)
    return conversation


def _kick(ordering_key: str) -> None:
    """Start delivery. A broker outage must not fail webhook processing: the
    beat sweep picks up any pending event that was not started."""
    try:
        from app.workers.saas_forward_tasks import forward_events

        forward_events.delay(ordering_key)
    except Exception:
        logger.warning("Could not start SaaS forward task; sweep will retry", exc_info=True)


# WhatsApp message types that are not customer DMs (contract A5: reactions
# are not forwarded; system notices are Meta's, not the customer's).
_WHATSAPP_NOT_FORWARDED = {"reaction", "system"}


def delegate_whatsapp_event(db: Session, result, event) -> bool:
    """Forward one genuine inbound WhatsApp message. `result` is the
    InboundWhatsappResult (account, lead, contact) after consent handling.
    Returns True if the event was forwarded."""
    from app.services.whatsapp_webhook_service import whatsapp_event_time
    from app.integrations.meta.whatsapp_ids import mask_wa_id

    account, lead, contact = result.account, result.lead, result.contact
    if event.message_type in _WHATSAPP_NOT_FORWARDED:
        return False
    if account.status != "connected":
        # Nothing could be sent back; reported as degraded health (M-05).
        logger.info(
            "Delegated WhatsApp message not forwarded: account is not connected",
            extra={"whatsapp_account_id": str(account.id), "sender_wa_id": mask_wa_id(event.sender_wa_id)},
        )
        return False
    received_at = whatsapp_event_time(event.timestamp)
    window = contact.last_inbound_at + WINDOW if contact.last_inbound_at else None
    delegate_inbound(
        db,
        platform="whatsapp",
        channel=account,
        lead=lead,
        external_contact_id=contact.wa_id,
        contact={
            "name": event.sender_profile_name,
            "phone": f"+{contact.wa_id}",
        },
        text=event.text or None,
        message_type="text" if event.text else "unsupported",
        external_message_id=event.message_id,
        timestamp=event.timestamp,
        received_at=received_at,
        window_expires_at=window,
    )
    return True
