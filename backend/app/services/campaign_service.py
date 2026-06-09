import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.lead import Lead
from app.models.message import Message
from app.models.user_cooldown import UserCooldown
from app.models.user import User
from app.models.instagram_account import InstagramAccount
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.services.token_service import get_decrypted_token
from app.services.audit_service import write_audit_log
from app.utils.normalization import normalize_comment
from app.utils.templates import validate_template

logger = logging.getLogger(__name__)


def _log_campaign_action(
    db: Session, campaign_id: uuid.UUID, action: str, details: dict | None = None
):
    log = AutomationLog(
        campaign_id=campaign_id,
        action=action,
        details=details or {},
    )
    db.add(log)
    db.commit()


def _actor_label(actor: User | None) -> str:
    return actor.email if actor else "System"


def create_campaign(
    db: Session, workspace_id: uuid.UUID, payload: CampaignCreate, actor: User | None = None
) -> Campaign:
    # Validate template
    try:
        validate_template(payload.message_template)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    campaign = Campaign(
        workspace_id=workspace_id,
        instagram_account_id=payload.instagram_account_id,
        name=payload.name,
        description=payload.description,
        media_id=payload.media_id,
        media_url=payload.media_url,
        target_scope=payload.target_scope,
        target_media_url=payload.target_media_url,
        target_media_shortcode=payload.target_media_shortcode,
        target_media_id=payload.target_media_id,
        target_media_type=payload.target_media_type,
        target_media_label=payload.target_media_label,
        match_type=payload.match_type,
        message_template=payload.message_template,
        link_url=payload.link_url,
        cooldown_hours=payload.cooldown_hours,
        status=payload.status,
        delivery_mode=payload.delivery_mode,
        follow_prompt_title=payload.follow_prompt_title,
        follow_prompt_description=payload.follow_prompt_description,
        follow_prompt_profile_url=payload.follow_prompt_profile_url,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    for keyword in payload.keywords:
        normalized = normalize_comment(keyword)
        if normalized:
            ck = CampaignKeyword(
                campaign_id=campaign.id,
                normalized_keyword=normalized,
            )
            db.add(ck)

    db.commit()
    db.refresh(campaign)
    _ = campaign.keywords
    target_metadata = {
        "target_scope": campaign.target_scope,
        "target_media_label": campaign.target_media_label,
        "target_media_type": campaign.target_media_type,
        "target_media_url": campaign.target_media_url,
    }
    _log_campaign_action(db, campaign.id, "created", {"name": campaign.name, **target_metadata})
    write_audit_log(
        db,
        "campaign_created",
        f"{_actor_label(actor)} created campaign {campaign.name}",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        entity_name=campaign.name,
        metadata={
            "account_id": str(campaign.instagram_account_id),
            "keyword_count": len(campaign.keywords),
            "created_by": actor.email if actor else "System",
            **target_metadata,
        },
    )
    logger.info("Campaign created", extra={"campaign_id": str(campaign.id)})
    return campaign


def get_campaign(db: Session, campaign_id: uuid.UUID) -> Campaign | None:
    return db.query(Campaign).filter(Campaign.id == campaign_id).first()


def list_campaigns(db: Session, workspace_id: uuid.UUID | None = None) -> list[Campaign]:
    query = db.query(Campaign)
    if workspace_id:
        query = query.filter(Campaign.workspace_id == workspace_id)
    return query.all()


def update_campaign(
    db: Session, campaign_id: uuid.UUID, payload: CampaignUpdate, actor: User | None = None
) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if payload.message_template is not None:
        try:
            validate_template(payload.message_template)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )

    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("target_scope") == "any_media":
        update_data.update(
            {
                "target_media_url": None,
                "target_media_shortcode": None,
                "target_media_id": None,
                "target_media_label": None,
                "target_media_type": "unknown",
                "media_id": None,
                "media_url": None,
            }
        )
    for field, value in update_data.items():
        setattr(campaign, field, value)

    if campaign.target_scope == "specific_media" and not campaign.target_media_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Post/Reel URL is required for a specific post or reel.",
        )

    _validate_follow_prompt_config(campaign)

    db.commit()
    db.refresh(campaign)
    target_metadata = {
        "target_scope": campaign.target_scope,
        "target_media_label": campaign.target_media_label,
        "target_media_type": campaign.target_media_type,
        "target_media_url": campaign.target_media_url,
    }
    _log_campaign_action(db, campaign.id, "updated", target_metadata)
    write_audit_log(
        db,
        "campaign_updated",
        f"{_actor_label(actor)} updated campaign {campaign.name}",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        entity_name=campaign.name,
        metadata={"fields": sorted(update_data.keys()), **target_metadata},
    )
    return campaign


def _validate_follow_prompt_config(campaign: Campaign) -> None:
    if campaign.delivery_mode != "follow_prompt":
        return

    if not campaign.follow_prompt_title or not campaign.follow_prompt_title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="follow_prompt_title is required for follow_prompt delivery",
        )
    if not campaign.follow_prompt_description or not campaign.follow_prompt_description.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="follow_prompt_description is required for follow_prompt delivery",
        )
    if not campaign.follow_prompt_profile_url or not campaign.follow_prompt_profile_url.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="follow_prompt_profile_url is required for follow_prompt delivery",
        )


def _validate_campaign_can_activate(db: Session, campaign: Campaign) -> None:
    if not campaign.keywords:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign cannot be activated without keywords",
        )

    try:
        validate_template(campaign.message_template)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    account = (
        db.query(InstagramAccount)
        .filter(InstagramAccount.id == campaign.instagram_account_id)
        .first()
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Instagram account not found",
        )

    token = get_decrypted_token(db, campaign.instagram_account_id)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Instagram account is not connected (no valid token)",
        )

    if campaign.target_scope == "specific_media" and not campaign.target_media_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign must have a Post/Reel URL to target a specific post or reel",
        )

    _validate_follow_prompt_config(campaign)


def _audit_campaign_status(db: Session, campaign: Campaign, action: str, actor: User | None) -> None:
    verb = action.replace("campaign_", "").replace("ed", "ed")
    write_audit_log(
        db,
        action,
        f"{_actor_label(actor)} {verb.replace('_', ' ')} campaign {campaign.name}",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        entity_name=campaign.name,
        severity="warning" if action in {"campaign_archived", "campaign_deleted"} else "info",
        metadata={
            "account_id": str(campaign.instagram_account_id),
            "status": campaign.status,
            "target_scope": campaign.target_scope,
            "target_media_label": campaign.target_media_label,
            "target_media_type": campaign.target_media_type,
            "target_media_url": campaign.target_media_url,
        },
    )


def activate_campaign(db: Session, campaign_id: uuid.UUID, actor: User | None = None) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    _validate_campaign_can_activate(db, campaign)

    campaign.status = "active"
    db.commit()
    db.refresh(campaign)
    _log_campaign_action(db, campaign.id, "activated")
    _audit_campaign_status(db, campaign, "campaign_activated", actor)
    logger.info("Campaign activated", extra={"campaign_id": str(campaign.id)})
    return campaign


def pause_campaign(db: Session, campaign_id: uuid.UUID, actor: User | None = None) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = "paused"
    db.commit()
    db.refresh(campaign)
    _log_campaign_action(db, campaign.id, "paused")
    _audit_campaign_status(db, campaign, "campaign_paused", actor)
    logger.info("Campaign paused", extra={"campaign_id": str(campaign.id)})
    return campaign


def archive_campaign(db: Session, campaign_id: uuid.UUID, actor: User | None = None) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = "archived"
    db.commit()
    db.refresh(campaign)
    _log_campaign_action(db, campaign.id, "archived")
    _audit_campaign_status(db, campaign, "campaign_archived", actor)
    logger.info("Campaign archived", extra={"campaign_id": str(campaign.id)})
    return campaign


def unarchive_campaign(db: Session, campaign_id: uuid.UUID, actor: User | None = None) -> Campaign:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = "paused"
    db.commit()
    db.refresh(campaign)
    _log_campaign_action(db, campaign.id, "unarchived", {"restored_status": "paused"})
    _audit_campaign_status(db, campaign, "campaign_unarchived", actor)
    logger.info("Campaign unarchived", extra={"campaign_id": str(campaign.id)})
    return campaign


def hard_delete_campaign(
    db: Session,
    campaign_id: uuid.UUID,
    actor: User,
) -> None:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only archived campaigns can be permanently deleted",
        )

    message_count = db.query(Message).filter(Message.campaign_id == campaign_id).count()
    if message_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This campaign has message history. Keep it archived to preserve the Messages page.",
        )

    entity_name = campaign.name
    account_id = campaign.instagram_account_id
    previous_status = campaign.status
    keyword_count = len(campaign.keywords)

    db.query(UserCooldown).filter(UserCooldown.campaign_id == campaign_id).delete(
        synchronize_session=False
    )
    db.query(Lead).filter(Lead.source_campaign_id == campaign_id).update(
        {Lead.source_campaign_id: None},
        synchronize_session=False,
    )
    db.query(AutomationLog).filter(AutomationLog.campaign_id == campaign_id).update(
        {AutomationLog.campaign_id: None},
        synchronize_session=False,
    )
    db.delete(campaign)
    write_audit_log(
        db,
        "campaign_deleted",
        f"{actor.email} permanently deleted campaign {entity_name}",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign_id,
        entity_name=entity_name,
        severity="danger",
        metadata={
            "account_id": str(account_id),
            "previous_status": previous_status,
            "keyword_count": keyword_count,
        },
        commit=False,
    )
    db.commit()
    logger.info("Campaign permanently deleted", extra={"campaign_id": str(campaign_id)})


def add_keyword(db: Session, campaign_id: uuid.UUID, keyword: str) -> CampaignKeyword:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    normalized = normalize_comment(keyword)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Keyword cannot be empty after normalization",
        )

    # Check for duplicate
    existing = (
        db.query(CampaignKeyword)
        .filter(
            CampaignKeyword.campaign_id == campaign_id,
            CampaignKeyword.normalized_keyword == normalized,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Keyword '{keyword}' already exists in this campaign",
        )

    ck = CampaignKeyword(
        campaign_id=campaign_id,
        normalized_keyword=normalized,
    )
    db.add(ck)
    db.commit()
    db.refresh(ck)
    return ck


def delete_keyword(db: Session, campaign_id: uuid.UUID, keyword_id: uuid.UUID) -> None:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    ck = (
        db.query(CampaignKeyword)
        .filter(
            CampaignKeyword.id == keyword_id,
            CampaignKeyword.campaign_id == campaign_id,
        )
        .first()
    )
    if not ck:
        raise HTTPException(status_code=404, detail="Keyword not found")

    db.delete(ck)
    db.commit()
