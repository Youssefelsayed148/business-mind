import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.db.session import get_db
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.message import Message
from app.models.user import User
from app.services.message_service import get_message_for_send, mark_message_skipped

logger = logging.getLogger(__name__)

router = APIRouter()


def _trigger_keyword_for_message(db: Session, message: Message) -> str | None:
    if not message.comment_id:
        return None

    comment = db.query(Comment).filter(Comment.id == message.comment_id).first()
    if not comment:
        return None

    log = (
        db.query(AutomationLog)
        .filter(
            AutomationLog.campaign_id == message.campaign_id,
            AutomationLog.action == "campaign_matched",
            AutomationLog.details["comment_id"].astext == comment.comment_id,
        )
        .order_by(AutomationLog.created_at.desc())
        .first()
    )
    if not log or not log.details:
        return None

    keyword = log.details.get("matched_keyword")
    return keyword if isinstance(keyword, str) else None


def _message_response(db: Session, message: Message) -> dict:
    return {
        "id": str(message.id),
        "campaign_id": str(message.campaign_id),
        "lead_id": str(message.lead_id),
        "comment_id": str(message.comment_id) if message.comment_id else None,
        "source_media_id": message.source_media_id,
        "source_media_type": message.source_media_type,
        "source_media_label": message.source_media_label,
        "status": message.status,
        "rendered_body": message.rendered_body,
        "message_type": message.message_type,
        "provider_message_id": message.provider_message_id,
        "error_code": message.error_code,
        "error_message": message.error_message,
        "trigger_keyword": _trigger_keyword_for_message(db, message),
        "retryable": message.retryable,
        "retry_count": message.retry_count,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.get("/messages")
async def list_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    messages = db.query(Message).order_by(Message.created_at.desc()).all()
    return [_message_response(db, message) for message in messages]


@router.get("/messages/{message_id}")
async def get_message(
    message_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = get_message_for_send(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return _message_response(db, message)


@router.post("/messages/{message_id}/retry")
async def retry_message(
    message_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("retry_messages")),
):
    message = get_message_for_send(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.status in ("sent", "expired"):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot retry message with status '{message.status}'",
        )

    if message.status == "skipped":
        raise HTTPException(
            status_code=422,
            detail="Cannot retry a skipped message",
        )

    # Enqueue send task
    try:
        from app.workers.tasks import send_final_delivery_after_follow_prompt, send_follow_prompt_card, send_private_reply

        campaign = db.query(Campaign).filter(Campaign.id == message.campaign_id).first()
        if message.message_type == "follow_prompt":
            send_follow_prompt_card.delay(str(message.id))
        elif message.message_type == "final_delivery" and campaign and campaign.delivery_mode == "follow_prompt":
            send_final_delivery_after_follow_prompt.delay(str(message.id))
        else:
            send_private_reply.delay(str(message.id))
        logger.info("Message retry enqueued", extra={"message_id": str(message.id)})
    except Exception:
        logger.exception("Failed to enqueue message retry", extra={"message_id": str(message.id)})
        raise HTTPException(status_code=500, detail="Failed to enqueue retry")

    return {"status": "retry_enqueued", "message_id": str(message.id)}
