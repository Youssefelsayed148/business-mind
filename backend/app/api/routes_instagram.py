import logging
import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.accounts import fetch_instagram_media
from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.oauth import build_oauth_url
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.comment import Comment
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.user_cooldown import UserCooldown
from app.services.token_service import get_decrypted_token
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instagram")

_redis_client: Redis | None = None


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _limit_account_mutation(current_user: User) -> None:
    enforce_user_rate_limit(
        current_user,
        "account_mutation",
        settings.ACCOUNT_MUTATION_USER_LIMIT,
        settings.ACCOUNT_MUTATION_USER_WINDOW_SECONDS,
        "Too many account changes. Please wait a moment and try again.",
    )


def _account_response(account: InstagramAccount, db: Session) -> dict:
    # The dashboard's expiry badge reads expires_at; it comes from the newest token.
    token_expires_at = (
        db.query(MetaToken.expires_at)
        .filter(MetaToken.instagram_account_id == account.id)
        .order_by(MetaToken.created_at.desc())
        .limit(1)
        .scalar()
    )
    return {
        "id": str(account.id),
        "ig_user_id": account.ig_user_id,
        "username": account.ig_username,
        "status": account.status,
        "business_vertical": account.business_vertical,
        "ai_enabled": account.ai_enabled,
        "ai_cold_dm_enabled": account.ai_cold_dm_enabled,
        "ai_business_profile": account.ai_business_profile,
        "ai_tone_instructions": account.ai_tone_instructions,
        "ai_daily_message_cap": account.ai_daily_message_cap,
        "ai_messages_sent_today": account.ai_messages_sent_today,
        "ai_handoff_after_turns": account.ai_handoff_after_turns,
        "expires_at": token_expires_at.isoformat() if token_expires_at else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


def _add_account_log(
    db: Session,
    action: str,
    account: InstagramAccount,
    campaign_id: UUID | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AutomationLog(
            campaign_id=campaign_id,
            instagram_account_id=account.id,
            action=action,
            details=details or {},
        )
    )


def _account_name(account: InstagramAccount) -> str:
    return account.ig_username or account.ig_user_id


@router.get("/accounts")
async def list_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    accounts = db.query(InstagramAccount).all()
    return [_account_response(account, db) for account in accounts]


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _limit_account_mutation(current_user)
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_response(account, db)


class AISettingsUpdate(BaseModel):
    business_vertical: Literal["general", "restaurant", "real_estate", "clinical"] | None = None
    ai_enabled: bool | None = None
    ai_cold_dm_enabled: bool | None = None
    ai_business_profile: str | None = Field(default=None, max_length=4000)
    ai_tone_instructions: str | None = Field(default=None, max_length=1000)
    ai_daily_message_cap: int | None = Field(default=None, ge=0, le=5000)
    ai_handoff_after_turns: int | None = Field(default=None, ge=1, le=50)


@router.patch("/accounts/{account_id}/ai-settings")
async def update_ai_settings(
    account_id: UUID,
    payload: AISettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    _limit_account_mutation(current_user)
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)

    _add_account_log(db, "ai_settings_updated", account, details=update_data)
    db.commit()

    return _account_response(account, db)


@router.post("/accounts/{account_id}/reconnect")
async def reconnect_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    """
    Initiate OAuth reconnect for an existing account.

    Returns an oauth_url the frontend should redirect to.
    The callback (/meta/connect/callback) already handles upsert on existing
    accounts by ig_user_id, so the account row will be updated in place.
    We store the account_id in Redis alongside the state so the callback
    can mark this as a reconnect rather than a new connection.
    """
    _limit_account_mutation(current_user)
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    state = str(uuid.uuid4())
    try:
        _r = _redis()
        # Store state with the account_id so the callback knows which account to refresh.
        # TTL 10 minutes — same as the connect flow.
        _r.setex(f"oauth_state:{state}", 600, str(account_id))
    except RedisError:
        logger.error("Failed to store OAuth reconnect state in Redis")
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")

    oauth_url = build_oauth_url(state)

    write_audit_log(
        db,
        "account_reconnect_initiated",
        f"{current_user.email} initiated reconnect for account {_account_name(account)}",
        actor=current_user,
        entity_type="account",
        entity_id=account.id,
        entity_name=_account_name(account),
        metadata={"ig_user_id": account.ig_user_id},
    )

    logger.info("OAuth reconnect initiated", extra={"account_id": str(account_id)})
    return {"oauth_url": oauth_url}


@router.delete("/accounts/{account_id}/hard")
async def hard_delete_account(  # noqa: C901
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delete_accounts")),
):
    """
    Permanently delete an Instagram account and all associated data.

    Full FK map (from DB introspection of instagram_automation):
      automation_logs   → campaigns (nullable), instagram_accounts (nullable), leads (nullable)
      campaign_keywords → campaigns
      campaigns         → instagram_accounts
      comments          → instagram_accounts
      leads             → instagram_accounts, campaigns (source, nullable), comments (source, nullable)
      messages          → campaigns, comments (nullable), leads
      meta_tokens       → instagram_accounts
      user_cooldowns    → campaigns

    Deletion order:
      1.  Nullify automation_logs.lead_id           (leads about to be deleted)
      2.  Nullify automation_logs.campaign_id       (campaigns about to be deleted)
      3.  Nullify automation_logs.instagram_account_id
      4.  Nullify messages.comment_id               (comments about to be deleted)
      5.  Nullify leads.source_comment_id           (comments about to be deleted)
      6.  Nullify leads.source_campaign_id          (campaigns about to be deleted)
      7.  Delete  messages                          (FK → campaigns, leads)
      8.  Delete  user_cooldowns                    (FK → campaigns)
      9.  Delete  campaign_keywords                 (FK → campaigns)
      10. Delete  leads                             (FK → instagram_accounts)
      11. Delete  comments                          (FK → instagram_accounts)
      12. Delete  campaigns                         (FK → instagram_accounts)
      13. Delete  meta_tokens                       (FK → instagram_accounts)
      14. Delete  instagram_account row
    """
    _limit_account_mutation(current_user)

    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account_name = _account_name(account)
    ig_user_id = account.ig_user_id

    # Collect IDs needed for scoped deletes/nullifies.
    campaign_ids = [
        row[0] for row in db.query(Campaign.id)
        .filter(Campaign.instagram_account_id == account_id).all()
    ]
    comment_ids = [
        row[0] for row in db.query(Comment.id)
        .filter(Comment.instagram_account_id == account_id).all()
    ]
    lead_ids = [
        row[0] for row in db.query(Lead.id)
        .filter(Lead.instagram_account_id == account_id).all()
    ]

    # 1. Nullify automation_logs.lead_id
    if lead_ids:
        db.query(AutomationLog).filter(AutomationLog.lead_id.in_(lead_ids)).update(
            {"lead_id": None}, synchronize_session=False
        )

    # 2. Nullify automation_logs.campaign_id
    if campaign_ids:
        db.query(AutomationLog).filter(AutomationLog.campaign_id.in_(campaign_ids)).update(
            {"campaign_id": None}, synchronize_session=False
        )

    # 3. Nullify automation_logs.instagram_account_id
    db.query(AutomationLog).filter(
        AutomationLog.instagram_account_id == account_id
    ).update({"instagram_account_id": None}, synchronize_session=False)

    # 4. Nullify messages.comment_id
    if comment_ids:
        db.query(Message).filter(Message.comment_id.in_(comment_ids)).update(
            {"comment_id": None}, synchronize_session=False
        )

    # 5. Nullify leads.source_comment_id
    if comment_ids:
        db.query(Lead).filter(Lead.source_comment_id.in_(comment_ids)).update(
            {"source_comment_id": None}, synchronize_session=False
        )

    # 6. Nullify leads.source_campaign_id
    if campaign_ids:
        db.query(Lead).filter(Lead.source_campaign_id.in_(campaign_ids)).update(
            {"source_campaign_id": None}, synchronize_session=False
        )

    # 7. Delete messages (FK → campaigns NOT NULL, FK → leads NOT NULL)
    if campaign_ids:
        db.query(Message).filter(Message.campaign_id.in_(campaign_ids)).delete(
            synchronize_session=False
        )
    if lead_ids:
        db.query(Message).filter(Message.lead_id.in_(lead_ids)).delete(
            synchronize_session=False
        )

    # 8. Delete user_cooldowns (FK → campaigns)
    if campaign_ids:
        db.query(UserCooldown).filter(UserCooldown.campaign_id.in_(campaign_ids)).delete(
            synchronize_session=False
        )

    # 9. Delete campaign_keywords (FK → campaigns)
    if campaign_ids:
        db.query(CampaignKeyword).filter(CampaignKeyword.campaign_id.in_(campaign_ids)).delete(
            synchronize_session=False
        )

    # 10. Delete leads (FK → instagram_accounts)
    db.query(Lead).filter(Lead.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 11. Delete comments (FK → instagram_accounts)
    db.query(Comment).filter(Comment.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 12. Delete campaigns (FK → instagram_accounts)
    db.query(Campaign).filter(Campaign.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 13. Delete meta_tokens (FK → instagram_accounts)
    db.query(MetaToken).filter(MetaToken.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 14. Delete the account row itself.
    db.delete(account)

    write_audit_log(
        db,
        "account_deleted",
        f"{current_user.email} permanently deleted account {account_name}",
        actor=current_user,
        entity_type="account",
        entity_id=account_id,
        entity_name=account_name,
        severity="critical",
        metadata={
            "ig_user_id": ig_user_id,
            "deleted_campaigns": len(campaign_ids),
            "deleted_comments": len(comment_ids),
            "deleted_leads": len(lead_ids),
        },
        commit=False,
    )

    db.commit()
    logger.info(
        "Account hard-deleted",
        extra={"account_id": str(account_id), "ig_user_id": ig_user_id},
    )
    return {"status": "deleted", "account_id": str(account_id)}


@router.delete("/accounts/{account_id}")
async def disconnect_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("disconnect_accounts")),
):
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.status = "disconnected"
    account.updated_at = datetime.now(timezone.utc)
    (
        db.query(MetaToken)
        .filter(MetaToken.instagram_account_id == account.id)
        .update({"status": "expired"}, synchronize_session=False)
    )
    active_campaigns = (
        db.query(Campaign)
        .filter(
            Campaign.instagram_account_id == account.id,
            Campaign.status == "active",
        )
        .all()
    )
    for campaign in active_campaigns:
        campaign.status = "paused"
        campaign.updated_at = datetime.now(timezone.utc)
        _add_account_log(
            db,
            "campaign_paused_account_disconnected",
            account,
            campaign_id=campaign.id,
            details={
                "message": "Campaign paused because Instagram account was disconnected",
                "campaign_name": campaign.name,
            },
        )
    _add_account_log(
        db,
        "account_disconnected",
        account,
        details={
            "message": "Instagram account disconnected",
            "paused_campaigns": len(active_campaigns),
        },
    )
    write_audit_log(
        db,
        "account_disconnected",
        f"{current_user.email} disconnected account {_account_name(account)}",
        actor=current_user,
        entity_type="account",
        entity_id=account.id,
        entity_name=_account_name(account),
        severity="warning",
        metadata={"ig_user_id": account.ig_user_id, "paused_campaigns": len(active_campaigns)},
        commit=False,
    )
    db.commit()
    db.refresh(account)
    logger.info("Account disconnected", extra={"account_id": str(account_id)})
    return _account_response(account, db)


@router.get("/accounts/{account_id}/health")
async def account_health(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    token = get_decrypted_token(db, account.id)
    return {
        "account_id": str(account_id),
        "has_token": token is not None,
        "status": "healthy" if token else "missing_token",
    }

@router.get("/accounts/{account_id}/media")
async def list_account_media(
    account_id: UUID,
    limit: int = 25,
    after: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the connected account's published media, for the campaign post picker.

    Returns Instagram's numeric media ids so a selected post can be matched
    against incoming comment webhooks.
    """
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    access_token = get_decrypted_token(db, account.id)
    if not access_token:
        raise HTTPException(
            status_code=400,
            detail="This Instagram account has no valid access token. Please reconnect it.",
        )

    limit = max(1, min(limit, 50))

    try:
        result = await fetch_instagram_media(access_token, limit=limit, after=after)
    except MetaAPIError as exc:
        logger.warning(
            "Failed to fetch Instagram media",
            extra={"account_id": str(account_id), "error": str(exc), "status_code": exc.status_code},
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not load posts from Instagram: {exc}",
        )

    return {
        "account_id": str(account_id),
        "media": result["media"],
        "next_cursor": result["next_cursor"],
    }
