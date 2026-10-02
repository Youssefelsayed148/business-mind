import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "comment_id", "message_type", name="uq_message_campaign_comment_type"
        ),
        # campaign_id/comment_id are FK'd strictly to Instagram's
        # campaigns/comments tables, so Facebook needs its own pair of
        # columns below — this is what actually enforces "one private reply
        # per comment" for Facebook rows (NULL-distinctness means the
        # constraint above never sees non-NULL values for Facebook messages).
        UniqueConstraint(
            "facebook_campaign_id",
            "facebook_comment_id",
            "message_type",
            name="uq_message_facebook_campaign_comment_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable for cold-DM AI conversation messages, which have no campaign.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("comments.id"), nullable=True
    )
    # Facebook equivalents of campaign_id/comment_id — see class-level
    # UniqueConstraint comment above for why these exist as separate columns
    # rather than reusing the Instagram-locked ones.
    facebook_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facebook_campaigns.id", name="fk_messages_facebook_campaign_id"),
        nullable=True,
    )
    facebook_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facebook_comments.id", name="fk_messages_facebook_comment_id"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    whatsapp_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("whatsapp_campaigns.id", name="fk_messages_whatsapp_campaign_id"),
        nullable=True,
    )
    whatsapp_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("whatsapp_templates.id", name="fk_messages_whatsapp_template_id"),
        nullable=True,
    )
    # inbound (from lead) | outbound (from us, includes AI replies)
    direction: Mapped[str] = mapped_column(String(20), default="outbound")
    source_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_media_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rendered_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(50), default="final_delivery")
    status: Mapped[str] = mapped_column(String(50), default="queued")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
