import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.utils.normalization import normalize_comment

logger = logging.getLogger(__name__)


def upsert_lead_from_comment(
    db: Session,
    workspace_id: uuid.UUID,
    instagram_account_id: uuid.UUID,
    campaign_id: uuid.UUID,
    comment_id: uuid.UUID | None,
    commenter_ig_id: str,
    username: str | None,
    source_media_id: str | None = None,
    source_media_type: str | None = None,
    source_media_label: str | None = None,
) -> Lead:
    lead = (
        db.query(Lead)
        .filter(
            Lead.workspace_id == workspace_id,
            Lead.instagram_account_id == instagram_account_id,
            Lead.ig_user_id == commenter_ig_id,
        )
        .first()
    )

    if lead:
        lead.last_seen_at = datetime.now(timezone.utc)
        lead.ig_username = username or lead.ig_username
        lead.source_campaign_id = campaign_id
        lead.source_comment_id = comment_id
        lead.source_media_id = lead.source_media_id or source_media_id
        lead.source_media_type = lead.source_media_type or source_media_type
        lead.source_media_label = lead.source_media_label or source_media_label
        db.commit()
        db.refresh(lead)
        logger.info("Lead updated", extra={"lead_id": str(lead.id)})
        return lead

    lead = Lead(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        instagram_account_id=instagram_account_id,
        ig_user_id=commenter_ig_id,
        ig_username=username,
        last_seen_at=datetime.now(timezone.utc),
        source_campaign_id=campaign_id,
        source_comment_id=comment_id,
        source_media_id=source_media_id,
        source_media_type=source_media_type,
        source_media_label=source_media_label,
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info("Lead created", extra={"lead_id": str(lead.id)})
    return lead
