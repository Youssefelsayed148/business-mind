import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    """Tracks an ongoing AI-assisted DM conversation with a lead.

    Two origins:
    - campaign: created the first time a lead replies inside a DM thread after
      an AI-enabled campaign delivered them a message. One conversation per
      (lead, campaign) pair.
    - cold_dm: created when an unknown user DMs an account that has
      ai_cold_dm_enabled. campaign_id is NULL for these.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("lead_id", "campaign_id", name="uq_conversation_lead_campaign"),
        # campaign_id is FK'd to campaigns.id (Instagram-only), so a Facebook
        # campaign-triggered conversation needs its own campaign reference —
        # same reasoning as messages.facebook_campaign_id.
        UniqueConstraint(
            "lead_id", "facebook_campaign_id", name="uq_conversation_lead_facebook_campaign"
        ),
        # Postgres treats NULL as distinct in a unique constraint, so neither
        # constraint above constrains anything when its campaign column is
        # NULL -- the case for every WhatsApp conversation and every cold-DM
        # conversation on any platform. This partial index closes exactly that
        # gap: one cold-DM-style conversation per lead. lead_id alone is
        # enough because a Lead belongs to exactly one platform
        # (ck_leads_platform_account_fk), so adding platform would only weaken
        # it. Campaign-backed rows are excluded by the WHERE clause and keep
        # behaving exactly as before.
        # Postgres treats NULL as distinct in a unique constraint, so neither
        # constraint above constrains anything when its campaign column is
        # NULL -- the case for every WhatsApp conversation and every cold-DM
        # conversation on any platform. This partial index closes exactly that
        # gap: one cold-DM-style conversation per lead. lead_id alone is
        # enough because a Lead belongs to exactly one platform
        # (ck_leads_platform_account_fk), so adding platform would only weaken
        # it. Campaign-backed rows are excluded by the WHERE clause and keep
        # behaving exactly as before.
        Index(
            "uq_conversation_lead_cold_dm",
            "lead_id",
            unique=True,
            postgresql_where=text("campaign_id IS NULL AND facebook_campaign_id IS NULL"),
        ),
        CheckConstraint(
            "(platform = 'instagram' AND instagram_account_id IS NOT NULL"
            " AND whatsapp_account_id IS NULL AND facebook_page_id IS NULL)"
            " OR (platform = 'whatsapp' AND whatsapp_account_id IS NOT NULL"
            " AND instagram_account_id IS NULL AND facebook_page_id IS NULL)"
            " OR (platform = 'facebook' AND facebook_page_id IS NOT NULL"
            " AND instagram_account_id IS NULL AND whatsapp_account_id IS NULL)",
            name="ck_conversations_platform_account_fk",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True
    )
    # Facebook-campaign equivalent of campaign_id, which is FK'd strictly to
    # Instagram's campaigns table. Mutually exclusive with campaign_id — set
    # only for platform='facebook' conversations that originated from a
    # facebook_campaigns row (NULL for Facebook cold-DM conversations, same
    # as campaign_id is NULL for Instagram cold-DM ones).
    facebook_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facebook_campaigns.id", name="fk_conversations_facebook_campaign_id"),
        nullable=True,
    )
    # Nullable as of Phase 2 — NULL for platform='whatsapp'/'facebook' rows.
    instagram_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instagram_accounts.id"), nullable=True
    )
    # 'instagram' | 'whatsapp' | 'facebook' — see Lead.platform docstring;
    # same exactly-one-account-fk invariant, enforced by
    # ck_conversations_platform_account_fk.
    platform: Mapped[str] = mapped_column(String(50), default="instagram", server_default="instagram")
    # Explicit constraint name matching the 0012 migration's — see
    # Lead.whatsapp_account_id for why.
    whatsapp_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("whatsapp_accounts.id", name="fk_conversations_whatsapp_account_id"),
        nullable=True,
    )
    # Explicit constraint name matching the 0013 migration's.
    facebook_page_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facebook_pages.id", name="fk_conversations_facebook_page_id"),
        nullable=True,
    )
    # bot_active | handed_off | closed
    status: Mapped[str] = mapped_column(String(50), default="bot_active")
    # turn_limit | daily_cap_reached | manual | user_requested_human | ai_error | None
    handoff_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(
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
