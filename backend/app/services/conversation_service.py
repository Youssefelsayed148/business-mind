import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount

logger = logging.getLogger(__name__)


def get_or_create_conversation(
    db: Session,
    workspace_id: uuid.UUID,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    instagram_account_id: uuid.UUID,
) -> Conversation:
    """Fetch or create the conversation for this lead.

    campaign_id is None for cold-DM conversations (no originating campaign);
    there is exactly one such conversation per lead."""
    campaign_filter = (
        Conversation.campaign_id.is_(None)
        if campaign_id is None
        else Conversation.campaign_id == campaign_id
    )
    conversation = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead_id, campaign_filter)
        .first()
    )
    if conversation:
        return conversation

    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        instagram_account_id=instagram_account_id,
        status="bot_active",
        turn_count=0,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    logger.info("Conversation created", extra={"conversation_id": str(conversation.id)})
    return conversation


def touch_conversation(db: Session, conversation: Conversation) -> None:
    conversation.last_message_at = datetime.now(timezone.utc)
    db.commit()


def increment_turn(db: Session, conversation: Conversation) -> None:
    conversation.turn_count += 1
    db.commit()
    db.refresh(conversation)


def hand_off(db: Session, conversation: Conversation, reason: str) -> None:
    """Stop the AI from replying in this conversation. Idempotent — safe to
    call even if already handed off."""
    if conversation.status == "handed_off":
        return
    conversation.status = "handed_off"
    conversation.handoff_reason = reason
    db.commit()
    logger.info(
        "Conversation handed off",
        extra={"conversation_id": str(conversation.id), "reason": reason},
    )


def resume_bot(db: Session, conversation: Conversation) -> None:
    """Manual dashboard action: let the bot take conversations back over."""
    conversation.status = "bot_active"
    conversation.handoff_reason = None
    db.commit()


# --- Per-account shared AI budget -----------------------------------------

def reset_daily_budget_if_needed(db: Session, account: InstagramAccount) -> None:
    now = datetime.now(timezone.utc)
    if account.ai_budget_reset_at is None or account.ai_budget_reset_at.date() < now.date():
        account.ai_messages_sent_today = 0
        account.ai_budget_reset_at = now
        db.commit()


def is_budget_exhausted(db: Session, account: InstagramAccount) -> bool:
    reset_daily_budget_if_needed(db, account)
    return account.ai_messages_sent_today >= account.ai_daily_message_cap


def record_ai_send(db: Session, account: InstagramAccount) -> None:
    reset_daily_budget_if_needed(db, account)
    account.ai_messages_sent_today += 1
    db.commit()
