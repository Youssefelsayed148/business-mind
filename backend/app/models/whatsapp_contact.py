import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhatsappContact(Base):
    __tablename__ = "whatsapp_contacts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_whatsapp_contacts"),
        UniqueConstraint(
            "whatsapp_account_id",
            "wa_id",
            name="uq_whatsapp_contacts_account_wa_id",
        ),
        CheckConstraint(
            "marketing_consent IN ('unknown', 'opted_in', 'opted_out')",
            name="ck_whatsapp_contacts_marketing_consent",
        ),
        CheckConstraint(
            "consent_source IS NULL OR consent_source IN "
            "('web_form', 'click_to_whatsapp', 'inbound_keyword', 'in_store', "
            "'imported_attested', 'manual')",
            name="ck_whatsapp_contacts_consent_source",
        ),
        CheckConstraint(
            "wa_id ~ '^[0-9]{6,20}$'",
            name="ck_whatsapp_contacts_wa_id",
        ),
        Index(
            "ix_whatsapp_contacts_workspace_consent",
            "workspace_id",
            "marketing_consent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", name="fk_whatsapp_contacts_workspace_id"),
        nullable=False,
    )
    whatsapp_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "whatsapp_accounts.id",
            name="fk_whatsapp_contacts_whatsapp_account_id",
        ),
        nullable=False,
    )
    wa_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "leads.id",
            name="fk_whatsapp_contacts_lead_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    marketing_consent: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    consent_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    free_entry_point_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )
