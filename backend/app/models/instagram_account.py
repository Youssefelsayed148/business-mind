import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    ig_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ig_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="connected")

    # --- AI continuation layer: scoped per account, shared across its campaigns ---
    # general | restaurant | real_estate | clinical
    business_vertical: Mapped[str] = mapped_column(String(50), default="general")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Separate opt-in from ai_enabled: answer unsolicited DMs from users who
    # never went through a campaign. Requires ai_enabled to also be true.
    ai_cold_dm_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    ai_business_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_tone_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_daily_message_cap: Mapped[int] = mapped_column(Integer, default=100)
    # Account-level turn cap for the cold-DM path (campaign path uses
    # campaigns.ai_handoff_after_turns instead).
    ai_handoff_after_turns: Mapped[int] = mapped_column(
        Integer, default=8, server_default="8"
    )
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
