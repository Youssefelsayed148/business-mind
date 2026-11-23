"""Accepting and delivering messages the SaaS asks Many to send (M-03).

accept_message() validates the request against the channel and stores a
queued messages row plus the idempotency record. deliver_message() performs
the actual send through the existing Meta clients and records the outcome on
the messages row; it never raises for a send failure. message.status
callbacks (M-04) read that outcome.
"""

import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.meta.facebook_client import FacebookClient
from app.integrations.meta.messaging import MetaMessagingClient
from app.integrations.meta.whatsapp_client import WhatsappClient
from app.models.conversation import Conversation
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_contact import WhatsappContact
from app.services import conversation_service, facebook_token_service, token_service, whatsapp_token_service
from app.services.saas_error_mapping import error_detail, is_rate_limited, map_meta_error
from app.services.saas_status import emit_message_status
from app.services.whatsapp_window_service import in_free_entry_window, in_service_window

logger = logging.getLogger(__name__)

KINDS = {"reply", "agent", "handoff"}
MESSAGE_TYPE = "saas_message"
WINDOW = timedelta(hours=24)
# Seconds to wait before each retry of a send that Meta rejected with a
# rate-limit error (up to 3 retries). Only a definite Meta rate-limit response
# is retried: the request was refused, so nothing was sent. A timeout, a
# network error or an unreadable response is never retried (the message may
# have been delivered).
RATE_LIMIT_RETRY_DELAYS = (2.0, 5.0, 15.0)
_TRANSPORT_ERRORS = ("network_error", "timeout", "invalid_json")

# Meta's real per-message text limits (contract: Many enforces them and never
# truncates). Instagram is counted in UTF-8 bytes, the others in characters.
# Values from Meta's Send API docs as last known; re-verify before staging.
TEXT_LIMITS = {
    "whatsapp": ("chars", 4096),
    "facebook": ("chars", 2000),
    "instagram": ("bytes", 1000),
}

CHANNEL_MODELS = {
    "instagram": InstagramAccount,
    "whatsapp": WhatsappAccount,
    "facebook": FacebookPage,
}


class RequestRejected(Exception):
    """The signed request is well-formed but cannot be accepted (404-class)."""


@dataclass
class Accepted:
    many_id: uuid.UUID
    duplicate: bool
    message_pk: uuid.UUID


def find_channel(db: Session, connection_id: str):
    """(platform, channel) for an enabled delegated channel linked to this
    connection id, else None. Ambiguity (two channels claiming one id) is
    treated as not found."""
    if not connection_id:
        return None
    matches = []
    for platform, model in CHANNEL_MODELS.items():
        for channel in db.query(model).filter(
            model.saas_connection_id == connection_id, model.saas_delegation_enabled.is_(True)
        ):
            matches.append((platform, channel))
    if len(matches) != 1:
        if len(matches) > 1:
            logger.error("Several channels share one SaaS connection id", extra={"count": len(matches)})
        return None
    return matches[0]


def _conversation_for(db: Session, platform: str, channel, conversation_id: str, contact_id: str):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise RequestRejected("conversation")
    column = {
        "instagram": Conversation.instagram_account_id,
        "whatsapp": Conversation.whatsapp_account_id,
        "facebook": Conversation.facebook_page_id,
    }[platform]
    conversation = db.query(Conversation).filter(Conversation.id == conv_uuid, column == channel.id).first()
    lead = db.get(Lead, conversation.lead_id) if conversation else None
    if conversation is None or lead is None:
        raise RequestRejected("conversation")
    contact_ids = {lead.ig_user_id, getattr(lead, "facebook_psid", None)} - {None}
    if contact_id not in contact_ids:
        raise RequestRejected("contact")
    return conversation, lead


def accept_message(
    db: Session,
    *,
    platform: str,
    channel,
    connection_id: str,
    message_id: str,
    external_contact_id: str,
    external_conversation_id: str,
    text: str,
    kind: str,
) -> Accepted:
    """Idempotent on (connection_id, message_id). Commits."""
    existing = _existing(db, connection_id, message_id)
    if existing is not None:
        return Accepted(existing.message_pk, True, existing.message_pk)

    conversation, lead = _conversation_for(db, platform, channel, external_conversation_id, external_contact_id)
    message = Message(
        id=uuid.uuid4(),
        campaign_id=None,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="outbound",
        content=text,
        rendered_body=text,
        message_type=MESSAGE_TYPE,
        status="queued",
    )
    db.add(message)
    db.flush()
    db.add(
        SaasOutboundMessage(
            id=uuid.uuid4(),
            connection_id=connection_id,
            message_id=message_id,
            platform=platform,
            channel_id=channel.id,
            kind=kind,
            message_pk=message.id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent identical request: answer with theirs.
        db.rollback()
        existing = _existing(db, connection_id, message_id)
        if existing is None:
            raise
        return Accepted(existing.message_pk, True, existing.message_pk)
    return Accepted(message.id, False, message.id)


def _existing(db: Session, connection_id: str, message_id: str) -> SaasOutboundMessage | None:
    return (
        db.query(SaasOutboundMessage)
        .filter(
            SaasOutboundMessage.connection_id == connection_id,
            SaasOutboundMessage.message_id == message_id,
        )
        .first()
    )


# --- delivery ---------------------------------------------------------------


def text_too_long(platform: str, text: str) -> bool:
    unit, limit = TEXT_LIMITS[platform]
    size = len(text.encode("utf-8")) if unit == "bytes" else len(text)
    return size > limit


def _fail(db: Session, message: Message, code: str, detail: str) -> str:
    message.status = "failed"
    message.error_code = code
    message.error_message = detail[:500]
    message.retryable = False
    db.commit()
    return "failed"


def _window_open(db: Session, platform: str, channel, conversation: Conversation, lead: Lead, now: datetime) -> bool:
    if platform == "whatsapp":
        contact = (
            db.query(WhatsappContact)
            .filter(
                WhatsappContact.whatsapp_account_id == channel.id,
                WhatsappContact.wa_id == lead.ig_user_id,
            )
            .first()
        )
        return bool(contact) and (in_service_window(contact, now=now) or in_free_entry_window(contact, now=now))
    last_inbound = (
        db.query(Message.created_at)
        .filter(Message.conversation_id == conversation.id, Message.direction == "inbound")
        .order_by(Message.created_at.desc())
        .first()
    )
    return bool(last_inbound and last_inbound[0] >= now - WINDOW)


def deliver_message(db: Session, message_pk, *, now: datetime | None = None) -> str:
    """Send one accepted message and report the outcome to the SaaS as a
    `message.status` event (sent / failed). Returns 'sent', 'failed' or
    'skipped'. A failed event is final for the SaaS, so a send is never
    retried here: after a timeout the message may already have reached Meta."""
    outcome = _deliver(db, message_pk, now=now)
    if outcome in ("sent", "failed"):
        message = db.get(Message, message_pk)
        emit_message_status(
            db,
            message,
            outcome,
            error_code=message.error_code if outcome == "failed" else None,
            error_detail=message.error_message if outcome == "failed" else None,
        )
    return outcome


def _deliver(db: Session, message_pk, *, now: datetime | None = None) -> str:
    """Send one accepted message. Returns 'sent', 'failed' or 'skipped'.

    Claims the row first (queued -> sending), so a duplicate task or a retry
    after a crash cannot send twice. The window, the length limit and the
    channel state are checked before anything is sent; a failed check records
    the error on the row and sends nothing (no truncation, no template
    substitution).
    """
    now = now or datetime.now(timezone.utc)
    claimed = (
        db.query(Message)
        .filter(Message.id == message_pk, Message.status == "queued")
        .update({"status": "sending"}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        return "skipped"
    message = db.get(Message, message_pk)
    link = db.query(SaasOutboundMessage).filter(SaasOutboundMessage.message_pk == message_pk).one()
    platform = link.platform
    channel = db.get(CHANNEL_MODELS[platform], link.channel_id)
    conversation = db.get(Conversation, message.conversation_id)
    lead = db.get(Lead, message.lead_id)
    text = message.content or ""

    if channel is None or not channel.saas_delegation_enabled:
        return _fail(db, message, "channel_disconnected", "delegation disabled before send")
    if channel.status != "connected":
        return _fail(db, message, "channel_disconnected", "channel is not connected")
    if text_too_long(platform, text):
        return _fail(db, message, "message_too_long", "text exceeds the platform limit")
    if not _window_open(db, platform, channel, conversation, lead, now):
        return _fail(db, message, "window_closed", "outside the messaging window")

    result = _send_with_rate_limit_retries(db, platform, channel, lead, text)
    if result is None:
        return _fail(db, message, "channel_disconnected", "no active access token")
    if result.success:
        message.status = "sent"
        message.provider_message_id = result.provider_message_id
        message.error_code = None
        message.error_message = None
        conversation_service.touch_conversation(db, conversation)
        db.commit()
        return "sent"

    code, subcode = _meta_error(result)
    transport = result.error_code if result.error_code in _TRANSPORT_ERRORS else None
    message.status = "failed"
    message.error_code = map_meta_error(platform, code, subcode)
    message.error_message = error_detail(code, subcode, transport)
    message.retryable = bool(result.retryable)
    db.commit()
    return "failed"


def _meta_error(result) -> tuple[object, object]:
    body = (result.raw_response or {}).get("error", {}) if isinstance(result.raw_response, dict) else {}
    if not isinstance(body, dict):
        return None, None
    return body.get("code"), body.get("error_subcode")


def definite_rate_limit(platform: str, result) -> bool:
    """True only when Meta answered with a rate-limit error code."""
    if result is None or result.success or result.error_code in _TRANSPORT_ERRORS:
        return False
    code, subcode = _meta_error(result)
    return code is not None and is_rate_limited(platform, code, subcode)


def _send_with_rate_limit_retries(db: Session, platform: str, channel, lead: Lead, text: str):
    result = _send(db, platform, channel, lead, text)
    for delay in RATE_LIMIT_RETRY_DELAYS:
        if not definite_rate_limit(platform, result):
            break
        logger.info("Meta rate limit on a delegated send; retrying", extra={"platform": platform, "delay": delay})
        time.sleep(delay + random.uniform(0, delay / 2))
        result = _send(db, platform, channel, lead, text)
    return result


def _send(db: Session, platform: str, channel, lead: Lead, text: str):
    """Call the existing send path for the platform. None if no token."""
    if platform == "instagram":
        token = token_service.get_decrypted_token(db, channel.id)
        if not token:
            return None
        client = MetaMessagingClient()
        try:
            return client.send_direct_message(token, channel.ig_user_id, lead.ig_user_id, text)
        finally:
            client.close()
    if platform == "facebook":
        token = facebook_token_service.get_decrypted_token(db, channel.id)
        if not token:
            return None
        client = FacebookClient()
        try:
            return client.send_direct_message(token, channel.page_id, lead.facebook_psid or lead.ig_user_id, text)
        finally:
            client.close()
    token = whatsapp_token_service.get_decrypted_token(db, channel.id)
    if not token:
        return None
    client = WhatsappClient()
    try:
        return client.send_text_message(token, channel.phone_number_id, lead.ig_user_id, text)
    finally:
        client.close()
