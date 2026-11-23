"""Explicit operator-verified authorization ownership, never inferred from channel IDs."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetaAuthorization(Base):
    __tablename__ = "meta_authorizations"
    __table_args__ = (
        UniqueConstraint("platform", "channel_id", name="uq_meta_authorization_channel"),
        CheckConstraint("subject_namespace IN ('app_user', 'business_system_user', 'unresolved')", name="ck_meta_authorizations_subject_namespace"),
        Index("ix_meta_authorizations_app_namespace_digest", "app_id", "subject_namespace", "subject_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_namespace: Mapped[str] = mapped_column(String(30), nullable=False, server_default="unresolved")
    subject_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_context_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    verification_source: Mapped[str] = mapped_column(String(80), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
