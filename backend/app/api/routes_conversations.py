import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.db.session import get_db
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.models.user import User
from app.services import conversation_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _conversation_response(db: Session, conversation: Conversation) -> dict:
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == conversation.campaign_id).first()
    last_message = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .first()
    )
    return {
        "id": str(conversation.id),
        "lead_id": str(conversation.lead_id),
        "lead_username": lead.ig_username or lead.ig_user_id if lead else None,
        "campaign_id": str(conversation.campaign_id),
        "campaign_name": campaign.name if campaign else None,
        "instagram_account_id": str(conversation.instagram_account_id),
        "status": conversation.status,
        "handoff_reason": conversation.handoff_reason,
        "turn_count": conversation.turn_count,
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        "last_message_preview": (last_message.rendered_body or last_message.content or "")[:140] if last_message else None,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
    }


def _message_response(message: Message) -> dict:
    return {
        "id": str(message.id),
        "direction": message.direction,
        "content": message.rendered_body or message.content,
        "status": message.status,
        "error_message": message.error_message,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.get("/conversations")
async def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversations = db.query(Conversation).order_by(Conversation.last_message_at.desc().nullslast()).all()
    return [_conversation_response(db, c) for c in conversations]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    response = _conversation_response(db, conversation)
    response["messages"] = [_message_response(m) for m in messages]
    return response


@router.post("/conversations/{conversation_id}/take-over")
async def take_over_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    """Manually stop the AI from replying in this conversation. Independent
    of the automatic handoff triggers (turn limit, daily cap) — this is the
    dashboard's emergency-stop / human-takeover action."""
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_service.hand_off(db, conversation, "manual")
    logger.info("Conversation manually taken over", extra={"conversation_id": str(conversation_id), "user_id": str(current_user.id)})
    return _conversation_response(db, conversation)


@router.post("/conversations/{conversation_id}/resume-bot")
async def resume_bot_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    """Hand a conversation back to the AI after a manual take-over."""
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_service.resume_bot(db, conversation)
    logger.info("Conversation bot resumed", extra={"conversation_id": str(conversation_id), "user_id": str(current_user.id)})
    return _conversation_response(db, conversation)
