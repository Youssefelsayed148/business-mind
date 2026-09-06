import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
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
        # Postgres treats NULL as distinct from every other NULL in a unique
        # constraint, so this only actually constrains rows where
        # whatsapp_account_id is set (i.e. WhatsApp leads) — Instagram rows
        # (whatsapp_account_id always NULL) are untouched by it, same as the
        # constraint above is untouched by WhatsApp rows.
        UniqueConstraint(
            "workspace_id",
            "whatsapp_account_id",
            "ig_user_id",
            name="uq_lead_workspace_whatsapp_user",
        ),
        # Same NULL-distinctness reasoning as the WhatsApp constraint above —
        # only actually constrains rows where facebook_page_id is set.
        UniqueConstraint(
            "workspace_id",
            "facebook_page_id",
            "ig_user_id",
            name="uq_lead_workspace_facebook_user",
        ),
        CheckConstraint(
            "(platform = 'instagram' AND instagram_account_id IS NOT NULL"
            " AND whatsapp_account_id IS NULL AND facebook_page_id IS NULL)"
            " OR (platform = 'whatsapp' AND whatsapp_account_id IS NOT NULL"
            " AND instagram_account_id IS NULL AND facebook_page_id IS NULL)"
            " OR (platform = 'facebook' AND facebook_page_id IS NOT NULL"
            " AND instagram_account_id IS NULL AND whatsapp_account_id IS NULL)",
            name="ck_leads_platform_account_fk",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    # Nullable as of Phase 2 — NULL for platform='whatsapp'/'facebook' rows.
    # Still populated for every existing (and future) Instagram row.
    instagram_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instagram_accounts.id"), nullable=True
    )
    # 'instagram' | 'whatsapp' | 'facebook' — which platform account this lead
    # belongs to. Exactly one of instagram_account_id / whatsapp_account_id /
    # facebook_page_id is set per row, enforced by ck_leads_platform_account_fk.
    platform: Mapped[str] = mapped_column(String(50), default="instagram", server_default="instagram")
    # Explicit constraint name matching the 0012 migration's, so a fresh DB
    # (whose tables are created from these live models by 0001_initial.py's
    # create_all(), not incrementally) doesn't end up with two differently-
    # named FK constraints for the same relationship.
    whatsapp_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("whatsapp_accounts.id", name="fk_leads_whatsapp_account_id"),
        nullable=True,
    )
    # Explicit constraint name matching the 0013 migration's — see
    # whatsapp_account_id above for why.
    facebook_page_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facebook_pages.id", name="fk_leads_facebook_page_id"),
        nullable=True,
    )
    # For platform='whatsapp' rows, this stores the WhatsApp user's WA ID
    # (phone number in E.164); for platform='facebook' rows, the commenter's
    # Facebook user ID. ig_username stores the corresponding display name
    # (WhatsApp profile name / Facebook commenter name) — deliberate reuse
    # of the Instagram-named columns rather than a rename, since ~22 backend
    # files read ig_user_id for Instagram leads.
    ig_user_id: Mapped[str] = mapped_column(String(255))
    ig_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Facebook only. Facebook uses two distinct ID namespaces for the same
    # human: a Page-feed comment webhook's `value.from.id` is app-scoped
    # (ASID), while a Messenger webhook's `messaging[].sender.id` and the
    # Send API's `recipient.id` are page-scoped (PSID). They are NOT
    # interchangeable, unlike Instagram where the comment `from.id` and the
    # IGSID are unified -- which is why ig_user_id alone cannot serve both
    # comment-identity and messaging-identity for Facebook leads.
    #
    # For a campaign lead (created from a comment) ig_user_id holds the ASID
    # and this stays NULL until the private reply succeeds: the Send API's
    # response carries `recipient_id`, which is the PSID, and that is when
    # this gets populated. For a cold-DM lead (created from a Messenger
    # event) ig_user_id already IS the PSID, so this is set at creation.
    facebook_psid: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
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
