import logging
import uuid

from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    action: str,
    campaign_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    instagram_account_id: uuid.UUID | None = None,
    whatsapp_account_id: uuid.UUID | None = None,
    facebook_page_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AutomationLog:
    log = AutomationLog(
        campaign_id=campaign_id,
        lead_id=lead_id,
        instagram_account_id=instagram_account_id,
        whatsapp_account_id=whatsapp_account_id,
        facebook_page_id=facebook_page_id,
        action=action,
        details=details or {},
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
