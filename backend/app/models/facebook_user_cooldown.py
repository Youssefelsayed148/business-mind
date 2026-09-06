import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FacebookUserCooldown(Base):
    """Facebook equivalent of UserCooldown — that table's campaign_id is FK'd
    strictly to campaigns.id (Instagram-only), so Facebook needs its own.
    """

    __tablename__ = "facebook_user_cooldowns"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "facebook_user_id",
            name="uq_facebook_user_cooldown_campaign_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facebook_campaigns.id"), nullable=False
    )
    facebook_user_id: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
