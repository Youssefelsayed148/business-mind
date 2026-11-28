"""Phase 5 tables: the link between Many leads and SaaS contacts (docs/DATA-UNIFICATION.md).

``customer_links`` holds one row per person per channel. It stores a digest of the external id,
never the raw id. ``many_channel_claims`` says which organization owns a Many channel that no
workspace-scoped Many route can attribute (Instagram accounts); a channel belongs to one
organization at most.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

LINK_PLATFORMS = ("instagram", "facebook", "whatsapp")
LINK_STATES = ("linked", "many_only", "saas_only", "conflict", "erased")
LINK_SOURCES = ("delegated_event", "many_lead")


class CustomerLink(Base):
    __tablename__ = "customer_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "platform",
            "many_channel_id",
            "external_id_digest",
            name="uq_customer_links_identity",
        ),
        CheckConstraint(
            "platform IN ('instagram', 'facebook', 'whatsapp')", name="ck_customer_links_platform"
        ),
        CheckConstraint(
            "state IN ('linked', 'many_only', 'saas_only', 'conflict', 'erased')",
            name="ck_customer_links_state",
        ),
        CheckConstraint(
            "source IN ('delegated_event', 'many_lead')", name="ck_customer_links_source"
        ),
        CheckConstraint("length(external_id_digest) = 64", name="ck_customer_links_digest"),
        Index("ix_customer_links_tenant_contact", "tenant_id", "contact_id"),
        Index("ix_customer_links_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    many_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_id_digest: Mapped[str] = mapped_column(Text, nullable=False)
    many_lead_id: Mapped[str | None] = mapped_column(Text)
    # What a client sees for a person known only to Many (the username Many holds). Personal data:
    # erasure removes the whole row.
    display_name: Mapped[str | None] = mapped_column(Text)
    lead_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ManyChannelClaim(Base):
    __tablename__ = "many_channel_claims"
    __table_args__ = (
        UniqueConstraint("platform", "many_channel_id", name="uq_many_channel_claims_channel"),
        CheckConstraint(
            "platform IN ('instagram', 'facebook', 'whatsapp')",
            name="ck_many_channel_claims_platform",
        ),
        Index("ix_many_channel_claims_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    many_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
