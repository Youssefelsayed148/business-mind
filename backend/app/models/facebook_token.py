import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FacebookToken(Base):
    """Encrypted Page Access Token for a Facebook Page.

    Separate table from MetaToken by design: MetaToken.instagram_account_id
    is NOT NULL and FK'd strictly to instagram_accounts, so it cannot
    represent a Facebook Page token without touching Instagram's token
    storage. Same precedent as WhatsappToken.
    """

    __tablename__ = "facebook_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    facebook_page_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facebook_pages.id"), nullable=False
    )
    access_token: Mapped[str] = mapped_column(Text)
    token_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    expires_at: Mapped[datetime | None] = mapped_column(
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
