import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent
from app.models.webhook_health import WebhookHealth

logger = logging.getLogger(__name__)


def derive_external_event_id(payload: dict, raw_body: bytes) -> str:
    """Derive a stable external event ID from payload or raw body hash."""
    # Try common Meta webhook id fields
    for key in ("id", "message_id", "comment_id", "post_id", "story_id"):
        if key in payload:
            return str(payload[key])

    # Fallback: deterministic SHA256 of raw body
    return hashlib.sha256(raw_body).hexdigest()


def derive_event_type(payload: dict) -> str:
    """Derive event type from payload structure."""
    if "object" in payload:
        obj = payload.get("object", "")
        entries = payload.get("entry", [])
        if entries and "changes" in entries[0]:
            changes = entries[0]["changes"]
            if changes:
                return f"{obj}.{changes[0].get('field', 'unknown')}"
        return obj
    return "unknown"


def store_webhook_event(
    db: Session,
    payload: dict,
    raw_body: bytes,
    signature_valid: bool,
) -> WebhookEvent | None:
    provider = "meta"
    external_event_id = derive_external_event_id(payload, raw_body)
    event_type = derive_event_type(payload)

    event = WebhookEvent(
        provider=provider,
        external_event_id=external_event_id,
        event_type=event_type,
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
        update_webhook_health(db, provider, success=True)
        logger.info(
            "Webhook event stored",
            extra={
                "event_id": str(event.id),
                "external_event_id": external_event_id,
                "event_type": event_type,
            },
        )
        return event
    except IntegrityError:
        db.rollback()
        logger.info(
            "Duplicate webhook event ignored",
            extra={"external_event_id": external_event_id},
        )
        return None


def update_webhook_health(db: Session, provider: str, success: bool) -> None:
    record = db.query(WebhookHealth).filter(WebhookHealth.provider == provider).first()
    now = datetime.now(timezone.utc)
    if not record:
        record = WebhookHealth(provider=provider)
        db.add(record)
    record.last_webhook_at = now
    if success:
        record.last_success_at = now
        record.consecutive_failures = 0
    else:
        record.consecutive_failures += 1
    db.commit()


def mark_webhook_event_processed(db: Session, event_id) -> None:
    event = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
    if event:
        event.processing_status = "processed"
        db.commit()


def mark_webhook_event_skipped(db: Session, event_id) -> None:
    event = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
    if event:
        event.processing_status = "skipped"
        db.commit()


def mark_webhook_event_failed(db: Session, event_id) -> None:
    event = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
    if event:
        event.processing_status = "failed"
        db.commit()
