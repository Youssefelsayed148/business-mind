from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user_cooldown import UserCooldown


def is_user_on_cooldown(
    db: Session, campaign_id, instagram_user_id: str
) -> bool:
    cooldown = (
        db.query(UserCooldown)
        .filter(
            UserCooldown.campaign_id == campaign_id,
            UserCooldown.instagram_user_id == instagram_user_id,
        )
        .first()
    )
    if not cooldown:
        return False
    return cooldown.expires_at > datetime.now(timezone.utc)


def set_user_cooldown(
    db: Session, campaign_id, instagram_user_id: str, hours: int
) -> None:
    existing = (
        db.query(UserCooldown)
        .filter(
            UserCooldown.campaign_id == campaign_id,
            UserCooldown.instagram_user_id == instagram_user_id,
        )
        .first()
    )
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    if existing:
        existing.expires_at = expires
    else:
        cooldown = UserCooldown(
            campaign_id=campaign_id,
            instagram_user_id=instagram_user_id,
            expires_at=expires,
        )
        db.add(cooldown)
    db.commit()


# Alias names used by Phase 4 task code
is_in_cooldown = is_user_on_cooldown
record_cooldown = set_user_cooldown
