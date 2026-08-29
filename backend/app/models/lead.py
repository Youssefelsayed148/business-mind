import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "instagram_account_id",
            "ig_user_id",
            name="uq_lead_workspace_instagram_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instagram_accounts.id"), nullable=False
    )
    ig_user_id: Mapped[str] = mapped_column(String(255))
    ig_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 'campaign' — came through a comment-trigger -> DM campaign pipeline
    # 'cold_dm'  — DM'd the business directly, no prior campaign interaction
    lead_source: Mapped[str] = mapped_column(String(50), default="campaign", server_default="campaign")
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True
    )
    source_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("comments.id"), nullable=True
    )
    source_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_media_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
