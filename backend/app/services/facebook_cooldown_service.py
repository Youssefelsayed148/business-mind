from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.facebook_user_cooldown import FacebookUserCooldown


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
    else:
        db.add(
            FacebookUserCooldown(
                campaign_id=campaign_id, facebook_user_id=facebook_user_id, expires_at=expires
            )
        )
    db.commit()
