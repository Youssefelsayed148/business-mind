import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.saas_delegation import SaasDelegationMixin


class FacebookPage(SaasDelegationMixin, Base):
    """A connected Facebook Page. Modeled on InstagramAccount's full shape
    (not WhatsappAccount's trimmed one) because Facebook Pages have a real
    campaign/comment-trigger concept, same as Instagram — unlike WhatsApp,
    which is reactive-only with no campaign concept in Phase 2.
    """

    __tablename__ = "facebook_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    page_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="connected")

    business_vertical: Mapped[str] = mapped_column(String(50), default="general")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Separate opt-in from ai_enabled, same precedent as InstagramAccount:
    # answer unsolicited Page-inbox messages from users with no prior
    # campaign interaction. Facebook has no equivalent of a follow-gate
    # (see phase-3 research spike), so this only gates cold-DM replies.
    ai_cold_dm_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    ai_business_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_tone_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_daily_message_cap: Mapped[int] = mapped_column(Integer, default=100)
    ai_handoff_after_turns: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    ai_messages_sent_today: Mapped[int] = mapped_column(Integer, default=0)
    ai_budget_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
