import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    """Tracks an ongoing AI-assisted DM conversation with a lead.

    Created the first time a lead replies inside a DM thread after an
    AI-enabled campaign delivered them a message. One conversation per
    (lead, campaign) pair.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("lead_id", "campaign_id", name="uq_conversation_lead_campaign"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instagram_accounts.id"), nullable=False
    )
    # bot_active | handed_off | closed
    status: Mapped[str] = mapped_column(String(50), default="bot_active")
    # turn_limit | daily_cap_reached | manual | user_requested_human | ai_error | None
    handoff_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(
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
