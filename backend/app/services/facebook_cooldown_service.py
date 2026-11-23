import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.facebook_user_cooldown import FacebookUserCooldown
from app.utils.db import is_unique_violation

logger = logging.getLogger(__name__)


def is_in_cooldown(db: Session, campaign_id, facebook_user_id: str) -> bool:
    cooldown = (
        db.query(FacebookUserCooldown)
        .filter(
            FacebookUserCooldown.campaign_id == campaign_id,
            FacebookUserCooldown.facebook_user_id == facebook_user_id,
        )
        .first()
    )
    if not cooldown:
        return False
    return cooldown.expires_at > datetime.now(timezone.utc)


def record_cooldown(db: Session, campaign_id, facebook_user_id: str, hours: int) -> None:
    """Unlike the per-comment webhook dedup, uq_facebook_user_cooldown_campaign_user
    is keyed on (campaign_id, facebook_user_id) -- two *different* comments
    from the same user on the same campaign (distinct comment_ids, so both
    pass the dedup) can still reach here concurrently on two workers. Insert
    via a savepoint so a lost race falls back to updating the winner's row
    instead of raising an uncaught IntegrityError.
    """
    existing = (
        db.query(FacebookUserCooldown)
        .filter(
            FacebookUserCooldown.campaign_id == campaign_id,
            FacebookUserCooldown.facebook_user_id == facebook_user_id,
        )
        .first()
    )
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    if existing:
        existing.expires_at = expires
        db.commit()
        return

    try:
        with db.begin_nested():
            db.add(
                FacebookUserCooldown(
                    campaign_id=campaign_id, facebook_user_id=facebook_user_id, expires_at=expires
                )
            )
            db.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc):
            raise
        winner = (
            db.query(FacebookUserCooldown)
            .filter(
                FacebookUserCooldown.campaign_id == campaign_id,
                FacebookUserCooldown.facebook_user_id == facebook_user_id,
            )
            .first()
        )
        if winner is None:
            logger.exception(
                "Cooldown insert conflicted but no matching row is visible",
                extra={"campaign_id": str(campaign_id), "facebook_user_id": facebook_user_id},
            )
            return
        winner.expires_at = expires

    db.commit()
