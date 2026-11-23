import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.lead import Lead

logger = logging.getLogger(__name__)


def upsert_lead_from_facebook_comment(
    db: Session,
    workspace_id: uuid.UUID,
    facebook_page_id: uuid.UUID,
    campaign_id: uuid.UUID,
    facebook_comment_row_id: uuid.UUID | None,
    commenter_id: str,
    commenter_name: str | None,
    source_post_id: str | None = None,
) -> Lead:
    """Mirrors lead_service.upsert_lead_from_comment. Lead itself is already
    multi-platform (Phase 1/2), so this writes platform='facebook' /
    facebook_page_id directly rather than needing a new Lead-like table —
    unlike Campaign/Comment/Message, Lead was designed for this from Phase 1.
    """
    lead = (
        db.query(Lead)
        .filter(
            Lead.workspace_id == workspace_id,
            Lead.facebook_page_id == facebook_page_id,
            Lead.ig_user_id == commenter_id,
        )
        .first()
    )

    if lead:
        lead.last_seen_at = datetime.now(timezone.utc)
        lead.ig_username = commenter_name or lead.ig_username
        lead.source_media_id = lead.source_media_id or source_post_id
        db.commit()
        db.refresh(lead)
        logger.info("Facebook lead updated", extra={"lead_id": str(lead.id)})
        return lead

    lead = Lead(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        platform="facebook",
        facebook_page_id=facebook_page_id,
        instagram_account_id=None,
        # source_campaign_id/source_comment_id are FK'd to Instagram's
        # campaigns/comments tables — left NULL here, same as they are for
        # WhatsApp leads. The originating facebook_campaigns/facebook_comments
        # row is instead recorded on the Message row itself
        # (facebook_campaign_id/facebook_comment_id).
        ig_user_id=commenter_id,
        ig_username=commenter_name,
        last_seen_at=datetime.now(timezone.utc),
        source_media_id=source_post_id,
        lead_source="campaign",
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info("Facebook lead created", extra={"lead_id": str(lead.id)})
    return lead
