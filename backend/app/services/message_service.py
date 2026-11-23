import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.message import Message

logger = logging.getLogger(__name__)


def create_queued_message(
    db: Session,
    campaign_id: uuid.UUID,
    lead_id: uuid.UUID,
    comment_id: uuid.UUID | None,
    rendered_body: str,
    message_type: str = "final_delivery",
    source_media_id: str | None = None,
    source_media_type: str | None = None,
    source_media_label: str | None = None,
) -> Message:
    existing = get_message_by_context(db, campaign_id, comment_id, message_type)
    if existing:
        return existing

    message = Message(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        lead_id=lead_id,
        comment_id=comment_id,
        source_media_id=source_media_id,
        source_media_type=source_media_type,
        source_media_label=source_media_label,
        rendered_body=rendered_body,
        content=rendered_body,
        message_type=message_type,
        status="queued",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    logger.info(
        "Message queued",
        extra={
            "message_id": str(message.id),
            "campaign_id": str(campaign_id),
            "comment_id": str(comment_id) if comment_id else None,
            "message_type": message_type,
        },
    )
    return message


def get_message_by_context(
    db: Session,
    campaign_id: uuid.UUID,
    comment_id: uuid.UUID | None,
    message_type: str,
) -> Message | None:
    return (
        db.query(Message)
        .filter(
            Message.campaign_id == campaign_id,
            Message.comment_id == comment_id,
            Message.message_type == message_type,
        )
        .first()
    )


def mark_message_sending(db: Session, message_id: uuid.UUID) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.status = "sending"
        db.commit()
        db.refresh(message)
    return message


def mark_message_sent(
    db: Session, message_id: uuid.UUID, provider_message_id: str | None
) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.status = "sent"
        message.provider_message_id = provider_message_id
        db.commit()
        db.refresh(message)
    return message


def mark_message_failed(
    db: Session,
    message_id: uuid.UUID,
    error_code: str | None,
    error_message: str | None,
    retryable: bool,
) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.status = "failed"
        message.error_code = error_code
        message.error_message = error_message
        message.retryable = retryable
        db.commit()
        db.refresh(message)
    return message


def mark_message_expired(
    db: Session, message_id: uuid.UUID, error_code: str | None, error_message: str | None
) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.status = "expired"
        message.error_code = error_code
        message.error_message = error_message
        db.commit()
        db.refresh(message)
    return message


def mark_message_skipped(db: Session, message_id: uuid.UUID, reason: str) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.status = "skipped"
        message.error_message = reason
        db.commit()
        db.refresh(message)
    return message


def get_message_for_send(db: Session, message_id: uuid.UUID) -> Message | None:
    return db.query(Message).filter(Message.id == message_id).first()


def increment_retry_count(db: Session, message_id: uuid.UUID) -> Message | None:
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.retry_count += 1
        db.commit()
        db.refresh(message)
    return message
