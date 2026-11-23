"""`message.status` events for messages the SaaS asked Many to send (A2).

Only messages with a saas_outbound_messages link produce events; everything
else in Many (campaigns, automations, Many's own AI replies) is untouched.
Events ride the same ordered, retried outbox as message.received, keyed by
conversation.
"""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.saas_outbound_message import SaasOutboundMessage
from app.services import saas_inbound
from app.services.saas_forwarder import CHANNEL_MODELS, enqueue_event

logger = logging.getLogger(__name__)

STATUSES = {"sent", "delivered", "read", "failed"}


def _event_id(message_id: str, status: str) -> str:
    base = message_id if len(message_id) <= 100 else "h" + hashlib.sha256(message_id.encode()).hexdigest()[:40]
    return f"st:{base}:{status}"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def emit_message_status(
    db: Session,
    message: Message,
    status: str,
    *,
    error_code: str | None = None,
    error_detail: str | None = None,
    occurred_at: datetime | None = None,
    kick: bool = True,
) -> bool:
    """Queue a status event for `message` if it is a SaaS message on a
    delegated channel. Commits. Returns True if an event was queued."""
    if status not in STATUSES:
        return False
    link = db.query(SaasOutboundMessage).filter(SaasOutboundMessage.message_pk == message.id).first()
    if link is None:
        return False
    channel = db.get(CHANNEL_MODELS[link.platform], link.channel_id)
    if channel is None or not channel.saas_delegation_enabled or channel.saas_connection_id != link.connection_id:
        # A13: delegation off (or re-pointed) -> nothing more goes to the SaaS.
        return False

    event_id = _event_id(link.message_id, status)
    payload = {
        "version": 1,
        "event_id": event_id,
        "event_type": "message.status",
        "connection_id": link.connection_id,
        "occurred_at": _iso(datetime.now(timezone.utc)),
        "message_id": link.message_id,
        "status": status,
    }
    if message.provider_message_id:
        payload["external_message_id"] = message.provider_message_id
    if status == "failed":
        payload["error_code"] = error_code or "unknown"
        if error_detail:
            payload["error_detail"] = error_detail[:200]
    if occurred_at is not None:
        payload["occurred_at"] = _iso(occurred_at)

    key = str(message.conversation_id)
    queued = enqueue_event(
        db,
        platform=link.platform,
        channel=channel,
        ordering_key=key,
        event_id=event_id,
        event_type="message.status",
        payload=payload,
    )
    db.commit()
    if queued and kick:
        saas_inbound._kick(key)
    return queued
