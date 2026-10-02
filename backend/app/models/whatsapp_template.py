import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhatsappTemplate(Base):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_whatsapp_templates"),
        UniqueConstraint(
            "whatsapp_account_id",
            "name",
            "language",
            name="uq_whatsapp_templates_account_name_language",
        ),
        CheckConstraint(
            "category IN ('marketing', 'utility', 'authentication')",
            name="ck_whatsapp_templates_category",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled')",
            name="ck_whatsapp_templates_status",
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
        ForeignKey("workspaces.id", name="fk_whatsapp_templates_workspace_id"),
        nullable=False,
    )
    whatsapp_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "whatsapp_accounts.id",
            name="fk_whatsapp_templates_whatsapp_account_id",
        ),
        nullable=False,
    )
    meta_template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    components: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    quality_score: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
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
