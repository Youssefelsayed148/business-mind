import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount

logger = logging.getLogger(__name__)


def get_or_create_conversation(
    db: Session,
    workspace_id: uuid.UUID,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    instagram_account_id: uuid.UUID | None = None,
    *,
    platform: str = "instagram",
    whatsapp_account_id: uuid.UUID | None = None,
    facebook_page_id: uuid.UUID | None = None,
    facebook_campaign_id: uuid.UUID | None = None,
) -> Conversation:
    """Fetch or create the conversation for this lead.

    campaign_id is None for Instagram cold-DM conversations (no originating
    campaign); facebook_campaign_id plays the same role for Facebook, since
    Conversation.campaign_id is FK'd strictly to Instagram's campaigns table
    and can't represent a Facebook campaign. Exactly one of
    campaign_id/facebook_campaign_id is ever set per conversation.

    platform/whatsapp_account_id/facebook_page_id/facebook_campaign_id
    default to Instagram's existing behavior — every pre-Phase-2 call site
    (positional instagram_account_id, no other kwargs) is unaffected."""
    if campaign_id is not None:
        campaign_filter = Conversation.campaign_id == campaign_id
    elif facebook_campaign_id is not None:
        campaign_filter = Conversation.facebook_campaign_id == facebook_campaign_id
    else:
        # Both campaign columns must be NULL, not just campaign_id. Every
        # Facebook conversation has campaign_id NULL (that column is FK'd
        # strictly to Instagram's campaigns table), so testing campaign_id
        # alone would let a cold-DM lookup match -- and silently continue
        # inside -- a Facebook *campaign* conversation.
        campaign_filter = and_(
            Conversation.campaign_id.is_(None),
            Conversation.facebook_campaign_id.is_(None),
        )
    def _lookup() -> Conversation | None:
        return (
            db.query(Conversation)
            .filter(Conversation.lead_id == lead_id, campaign_filter)
            .first()
        )

    conversation = _lookup()
    if conversation:
        return conversation

    # Insert defensively rather than optimistically. Two workers handling two
    # near-simultaneous inbound messages from the same person both reach this
    # point having seen no conversation; a plain INSERT would give that lead
    # two conversations (split history, halved AI context, doubled effective
    # turn limit). ON CONFLICT DO NOTHING lets the database arbitrate: the
    # loser inserts nothing and re-reads the winner's row below.
    #
    # No conflict target is named, so this covers every constraint that can
    # fire here -- uq_conversation_lead_campaign,
    # uq_conversation_lead_facebook_campaign, and (the case none of those
    # cover, because Postgres treats NULLs as distinct) the partial index
    # uq_conversation_lead_cold_dm for NULL-campaign conversations.
    stmt = (
        pg_insert(Conversation)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            facebook_campaign_id=facebook_campaign_id,
            platform=platform,
            instagram_account_id=instagram_account_id,
            whatsapp_account_id=whatsapp_account_id,
            facebook_page_id=facebook_page_id,
            status="bot_active",
            turn_count=0,
        )
        .on_conflict_do_nothing()
        .returning(Conversation.id)
    )
    inserted_id = db.execute(stmt).scalar_one_or_none()
    db.commit()

    if inserted_id is not None:
        conversation = db.query(Conversation).filter(Conversation.id == inserted_id).one()
        logger.info("Conversation created", extra={"conversation_id": str(conversation.id)})
        return conversation

    # Lost the race: the concurrent insert's row is now visible.
    conversation = _lookup()
    if conversation is None:
        # Only reachable if the conflict came from a constraint that our
        # lookup filter does not describe -- a real inconsistency worth
        # surfacing rather than returning None into the caller's happy path.
        raise RuntimeError(
            f"Conversation insert conflicted but no matching row is visible (lead_id={lead_id})"
        )
    logger.info(
        "Conversation creation lost a race; reusing the concurrently-created row",
        extra={"conversation_id": str(conversation.id)},
    )
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
