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
# SaaS-side field caps; anything longer is a permanent signed 422 there, so the
# payload is trimmed here instead of losing the message.
MAX_EVENT_ID = 128
MAX_CONTACT_NAME = 200
MAX_CONTACT_PHONE = 100
MAX_CONTACT_HANDLE = 200
_CONTACT_CAPS = {"name": MAX_CONTACT_NAME, "phone": MAX_CONTACT_PHONE, "handle": MAX_CONTACT_HANDLE}
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


# Only a message Many actually got out can be the "text Many delivered" (A11);
# queued or failed campaign messages never count.
_DELIVERED_STATUSES = ("sent", "delivered", "read")


def _origin(db: Session, platform: str, lead) -> dict | None:
    """Campaign context (contract A11): campaign name and the text Many
    delivered. Sent on every forwarded message of such a conversation.

    Picks the newest campaign message that was really sent (queued or failed
    ones never count), with id as a stable tie-break."""
    query = db.query(Message).filter(
        Message.lead_id == lead.id,
        Message.direction == "outbound",
        Message.status.in_(_DELIVERED_STATUSES),
    )
    if platform == "whatsapp":
        message = (
            query.filter(Message.whatsapp_campaign_id.isnot(None)).order_by(Message.created_at.desc(), Message.id.desc()).first()
        )
        campaign = db.get(WhatsappCampaign, message.whatsapp_campaign_id) if message else None
    elif platform == "facebook":
        message = (
            query.filter(Message.facebook_campaign_id.isnot(None)).order_by(Message.created_at.desc(), Message.id.desc()).first()
        )
        campaign = db.get(FacebookCampaign, message.facebook_campaign_id) if message else None
    else:
        message = (
            query.filter(Message.campaign_id.isnot(None))
            .order_by(
                (Message.message_type == "final_delivery").desc(), Message.created_at.desc(), Message.id.desc()
            )
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
    if message_type == "text" and not text:
        message_type = "unsupported"  # never send `text` without a body
    payload = {
        "version": 1,
        "event_id": event_id[:MAX_EVENT_ID],
        "event_type": "message.received",
        "connection_id": connection_id,
        "occurred_at": _iso(occurred_at or datetime.now(timezone.utc)),
        "channel": CONTRACT_CHANNEL[platform],
        "external_contact_id": external_contact_id,
        "contact": {
            k: str(v)[: _CONTACT_CAPS.get(k, MAX_CONTACT_NAME)] for k, v in contact.items() if v
        },
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


# consent_action values that still mean "a genuine customer message": a
# click-to-WhatsApp referral is a normal first message. Only the opt-out and
# opt-in keywords are Many-owned (contract A5).
FORWARDED_CONSENT_ACTIONS = (None, "ctwa_referral")

# WhatsApp message types that are not customer DMs (contract A5: reactions
# are not forwarded; system notices are Meta's, not the customer's).
_WHATSAPP_NOT_FORWARDED = {"reaction", "system"}


# Button/list payloads Many generates itself and handles itself. Today the only
# one in the code base is Instagram's follow-gate button (`FOLLOW_CHECK:<id>`,
# integrations/meta/messaging.py); Many sends no WhatsApp or Messenger
# buttons and no WhatsApp interactive messages (templates go out with
# header/body parameters only), so no WhatsApp payload is Many-owned yet.
# Add a prefix here when Many starts generating button payloads.
MANY_OWNED_PAYLOAD_PREFIXES = ("FOLLOW_CHECK:",)


def whatsapp_customer_text(event) -> tuple[str, bool]:
    """(text to forward, payload is Many-owned) for one inbound WhatsApp
    message. For a button or interactive reply the customer's visible choice
    (button text / reply title) is preferred over the machine payload or id,
    which means nothing to the SaaS; consent keywords are handled before this
    runs. Non-delegated handling keeps using `event.text`."""
    raw = event.raw_event if isinstance(event.raw_event, dict) else {}
    if event.message_type == "button":
        button = raw.get("button") if isinstance(raw.get("button"), dict) else {}
        payload = str(button.get("payload") or "")
        if payload.startswith(MANY_OWNED_PAYLOAD_PREFIXES):
            return "", True
        return str(button.get("text") or payload), False
    if event.message_type in ("interactive_button_reply", "interactive_list_reply"):
        kind = event.message_type.removeprefix("interactive_")
        interactive = raw.get("interactive") if isinstance(raw.get("interactive"), dict) else {}
        reply = interactive.get(kind) if isinstance(interactive.get(kind), dict) else {}
        reply_id = str(reply.get("id") or "")
        if reply_id.startswith(MANY_OWNED_PAYLOAD_PREFIXES):
            return "", True
        return str(reply.get("title") or reply_id), False
    return event.text or "", False


def delegate_whatsapp_event(db: Session, result, event) -> bool:
    """Forward one genuine inbound WhatsApp message. `result` is the
    InboundWhatsappResult (account, lead, contact) after consent handling.
    Returns True if the event was forwarded."""
    from app.services.whatsapp_webhook_service import whatsapp_event_time
    from app.integrations.meta.whatsapp_ids import mask_wa_id

    account, lead, contact = result.account, result.lead, result.contact
    if event.message_type in _WHATSAPP_NOT_FORWARDED:
        return False
    # A disconnected account is still forwarded: the SaaS stores the message
    # and flags a human, and replies fail with channel_disconnected. Health is
    # reported separately (M-05).
    text, many_owned = whatsapp_customer_text(event)
    if many_owned:
        logger.info(
            "Delegated WhatsApp message not forwarded: payload is owned by a Many flow",
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
        text=text or None,
        message_type="text" if text else "unsupported",
        external_message_id=event.message_id,
        timestamp=event.timestamp,
        received_at=received_at,
        window_expires_at=window,
    )
    return True


def delegated_whatsapp_unparsed_events(db: Session, payload: dict) -> list:
    """Customer messages the regular WhatsApp parser drops, limited to
    accounts in delegated mode. For every other account this returns [], so
    a non-delegated channel sees exactly the events it always did."""
    from app.integrations.meta.whatsapp_webhooks import parse_whatsapp_unparsed_message_events
    from app.models.whatsapp_account import WhatsappAccount

    events = parse_whatsapp_unparsed_message_events(payload)
    if not events:
        return []
    delegated = {
        phone_number_id
        for (phone_number_id,) in db.query(WhatsappAccount.phone_number_id).filter(
            WhatsappAccount.phone_number_id.in_({e.phone_number_id for e in events}),
            WhatsappAccount.saas_delegation_enabled.is_(True),
        )
    }
    return [e for e in events if e.phone_number_id in delegated]


def process_delegated_whatsapp_unparsed(db: Session, events: list) -> None:
    """Identity, dedupe and consent exactly as for a regular inbound message,
    then forward as `unsupported`."""
    from app.services.whatsapp_webhook_service import process_inbound_whatsapp_event

    for event in events:
        result = process_inbound_whatsapp_event(db, event)
        if result is None or result.consent_action not in FORWARDED_CONSENT_ACTIONS:
            continue
        delegate_whatsapp_event(db, result, event)


def delegated_facebook_unsupported_events(db: Session, payload: dict) -> list:
    """Non-text Messenger messages, limited to Pages in delegated mode."""
    from app.integrations.meta.unsupported_messages import parse_facebook_unsupported_message_events
    from app.models.facebook_page import FacebookPage

    events = parse_facebook_unsupported_message_events(payload)
    if not events:
        return []
    delegated = {
        page_id
        for (page_id,) in db.query(FacebookPage.page_id).filter(
            FacebookPage.page_id.in_({e.facebook_page_id for e in events}),
            FacebookPage.saas_delegation_enabled.is_(True),
        )
    }
    return [e for e in events if e.facebook_page_id in delegated]


def delegated_instagram_unsupported_events(db: Session, payload: dict) -> list:
    """Non-text Instagram DMs, limited to accounts in delegated mode."""
    from app.integrations.meta.unsupported_messages import parse_instagram_unsupported_message_events
    from app.models.instagram_account import InstagramAccount

    events = parse_instagram_unsupported_message_events(payload)
    if not events:
        return []
    delegated = {
        ig_user_id
        for (ig_user_id,) in db.query(InstagramAccount.ig_user_id).filter(
            InstagramAccount.ig_user_id.in_({e.instagram_account_ig_user_id for e in events}),
            InstagramAccount.saas_delegation_enabled.is_(True),
        )
    }
    return [e for e in events if e.instagram_account_ig_user_id in delegated]
