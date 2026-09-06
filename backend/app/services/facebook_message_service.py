import logging
import uuid

from sqlalchemy.orm import Session

from app.models.message import Message

logger = logging.getLogger(__name__)


def get_message_by_facebook_context(
    db: Session,
    facebook_campaign_id: uuid.UUID,
    facebook_comment_id: uuid.UUID | None,
    message_type: str,
) -> Message | None:
    return (
        db.query(Message)
        .filter(
            Message.facebook_campaign_id == facebook_campaign_id,
            Message.facebook_comment_id == facebook_comment_id,
            Message.message_type == message_type,
        )
        .first()
    )


def create_queued_facebook_message(
    db: Session,
    facebook_campaign_id: uuid.UUID,
    lead_id: uuid.UUID,
    facebook_comment_id: uuid.UUID | None,
    rendered_body: str,
    message_type: str = "final_delivery",
    source_media_id: str | None = None,
) -> Message:
    """Facebook equivalent of message_service.create_queued_message.

    A new function rather than an extension: Message.campaign_id/comment_id
    are FK'd strictly to campaigns/comments (Instagram-only) — see
    messages.facebook_campaign_id's model comment. Every other message
    lifecycle function in message_service.py (mark_message_sending,
    mark_message_sent, mark_message_failed, mark_message_expired,
    get_message_for_send, increment_retry_count) is already generic — it
    operates on Message.id only — so this file only needs the two functions
    that touch campaign_id/comment_id directly.
    """
    existing = get_message_by_facebook_context(db, facebook_campaign_id, facebook_comment_id, message_type)
    if existing:
        return existing

    message = Message(
        id=uuid.uuid4(),
        campaign_id=None,
        comment_id=None,
        facebook_campaign_id=facebook_campaign_id,
        facebook_comment_id=facebook_comment_id,
        lead_id=lead_id,
        source_media_id=source_media_id,
        rendered_body=rendered_body,
        content=rendered_body,
        message_type=message_type,
        status="queued",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    logger.info(
        "Facebook message queued",
        extra={
            "message_id": str(message.id),
            "facebook_campaign_id": str(facebook_campaign_id),
            "facebook_comment_id": str(facebook_comment_id) if facebook_comment_id else None,
            "message_type": message_type,
        },
    )
    return message
