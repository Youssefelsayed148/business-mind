import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhatsappCampaignRecipient(Base):
    __tablename__ = "whatsapp_campaign_recipients"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_whatsapp_campaign_recipients"),
        UniqueConstraint(
            "campaign_id",
            "contact_id",
            name="uq_whatsapp_campaign_recipients_campaign_contact",
        ),
        CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'read', 'failed', "
            "'skipped_no_consent', 'skipped_opted_out', 'skipped_not_eligible')",
            name="ck_whatsapp_campaign_recipients_status",
        ),
        Index(
            "ix_whatsapp_campaign_recipients_campaign_status",
            "campaign_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "whatsapp_campaigns.id",
            name="fk_whatsapp_campaign_recipients_campaign_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "whatsapp_contacts.id",
            name="fk_whatsapp_campaign_recipients_contact_id",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", name="fk_whatsapp_campaign_recipients_message_id"),
        nullable=True,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
