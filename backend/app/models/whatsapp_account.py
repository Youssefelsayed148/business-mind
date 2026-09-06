import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhatsappAccount(Base):
    """A connected WhatsApp Cloud API phone number for a workspace.

    Modeled on InstagramAccount's shape, but WhatsApp has no campaign concept
    in this phase — every conversation is cold-DM-shaped (reactive-only), so
    there's no ai_cold_dm_enabled toggle to gate: ai_enabled alone controls
    whether the bot replies at all.
    """

    __tablename__ = "whatsapp_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_business_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="connected")

    # --- AI continuation layer: same shape as InstagramAccount's ---
    business_vertical: Mapped[str] = mapped_column(String(50), default="general")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
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
