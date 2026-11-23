import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instagram_accounts.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_scope: Mapped[str] = mapped_column(String(50), default="any_media")
    target_media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_media_shortcode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_media_type: Mapped[str] = mapped_column(String(50), default="unknown")
    target_media_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    match_type: Mapped[str] = mapped_column(String(50), default="contains")
    message_template: Mapped[str] = mapped_column(Text, default="")
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=168)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    delivery_mode: Mapped[str] = mapped_column(String(50), default="instant")
    follow_prompt_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_prompt_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_prompt_profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    comment_reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_handoff_after_turns: Mapped[int] = mapped_column(Integer, default=8)
    total_triggers: Mapped[int] = mapped_column(Integer, default=0)
    successful_sends: Mapped[int] = mapped_column(Integer, default=0)
    failed_sends: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    keywords: Mapped[list["CampaignKeyword"]] = relationship(
        "CampaignKeyword", backref="campaign", cascade="all, delete-orphan"
    )
