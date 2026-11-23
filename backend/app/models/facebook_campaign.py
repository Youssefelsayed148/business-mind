import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FacebookCampaign(Base):
    """Comment-to-DM campaign for a Facebook Page. Mirrors Campaign's shape,
    scoped to Facebook's post/comment model, with no follow-prompt fields —
    per the phase-3 research spike, Facebook has no documented equivalent of
    Instagram's is_user_follow_business consent check, so only
    delivery_mode='instant' is supported.
    """

    __tablename__ = "facebook_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    facebook_page_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facebook_pages.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Facebook's post identifier — same concept as Campaign.media_id, named
    # to match the Graph API's own terminology for a Page feed post.
    post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_scope: Mapped[str] = mapped_column(String(50), default="any_post")
    target_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_post_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    match_type: Mapped[str] = mapped_column(String(50), default="contains")
    message_template: Mapped[str] = mapped_column(Text, default="")
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=168)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    # Only "instant" is supported this phase — no follow-gate equivalent
    # exists for Facebook Pages (see research spike). Column kept (rather
    # than omitted) so a future phase can add a real alternative without a
    # schema migration, but nothing should ever write anything but "instant".
    delivery_mode: Mapped[str] = mapped_column(String(50), default="instant")
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

    keywords: Mapped[list["FacebookCampaignKeyword"]] = relationship(
        "FacebookCampaignKeyword", backref="campaign", cascade="all, delete-orphan"
    )
