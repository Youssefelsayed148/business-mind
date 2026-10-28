import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.authz import WorkspaceContext, require_workspace_permission, require_workspace_role
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.facebook_oauth import (
    exchange_for_long_lived_token,
    list_granted_pages,
    subscribe_app_to_page,
    verify_user_access_token,
)
from app.models.automation_log import AutomationLog
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
from app.models.facebook_page import FacebookPage
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_service import write_audit_log
from app.services.facebook_token_service import store_encrypted_token
from app.services.meta_grant_identity import MetaGrantIdentity, save_grant
from app.services.rate_limit_service import enforce_user_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/facebook")

_redis_client: Redis | None = None


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _limit_mutation(current_user: User) -> None:
    enforce_user_rate_limit(
        current_user,
        "account_mutation",
        settings.ACCOUNT_MUTATION_USER_LIMIT,
        settings.ACCOUNT_MUTATION_USER_WINDOW_SECONDS,
        "Too many changes. Please wait a moment and try again.",
    )


def _page_response(page: FacebookPage) -> dict:
    return {
        "id": str(page.id),
        "page_id": page.page_id,
        "page_name": page.page_name,
        "status": page.status,
        "business_vertical": page.business_vertical,
        "ai_enabled": page.ai_enabled,
        "ai_cold_dm_enabled": page.ai_cold_dm_enabled,
        "ai_business_profile": page.ai_business_profile,
        "ai_tone_instructions": page.ai_tone_instructions,
        "ai_daily_message_cap": page.ai_daily_message_cap,
        "ai_messages_sent_today": page.ai_messages_sent_today,
        "ai_handoff_after_turns": page.ai_handoff_after_turns,
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


# --- Connect flow (Facebook Login for Business — see research spike) -------


@router.get("/connect/start")
async def facebook_connect_start(
    _ctx: WorkspaceContext = Depends(require_workspace_permission("manage_accounts")),
):
    if not settings.FACEBOOK_LOGIN_CONFIG_ID:
        raise HTTPException(
            status_code=503,
            detail="Facebook Login for Business is not configured (FACEBOOK_LOGIN_CONFIG_ID unset).",
        )
    state = secrets.token_urlsafe(24)
    try:
        _redis().setex(f"facebook_oauth_state:{state}", 600, "1")
    except RedisError:
        logger.error("Failed to store Facebook OAuth state in Redis")
        raise HTTPException(status_code=503, detail="Could not start Facebook connect flow")

    return {
        "app_id": settings.facebook_app_id,
        "config_id": settings.FACEBOOK_LOGIN_CONFIG_ID,
        "graph_api_version": settings.META_GRAPH_API_VERSION,
        "state": state,
    }


class FacebookConnectCallback(BaseModel):
    access_token: str
    state: str


@router.post("/connect/callback")
async def facebook_connect_callback(
    payload: FacebookConnectCallback,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_accounts")),
):
    """Verify the user token from FB.login(), list every Page the user granted access to via
    GET /me/accounts, and connect all of them (each already carries its own
    Page Access Token — no per-Page exchange step needed). Unlike WhatsApp's
    single-number flow, this can connect more than one Page in one pass.
    """
    _limit_mutation(ctx.user)

    try:
        state_value = _redis().get(f"facebook_oauth_state:{payload.state}")
        if not state_value:
            raise HTTPException(status_code=400, detail="Invalid or expired connect session")
        _redis().delete(f"facebook_oauth_state:{payload.state}")
    except RedisError:
        logger.error("Failed to validate Facebook OAuth state in Redis")
        raise HTTPException(status_code=503, detail="Could not verify Facebook connect session")

    try:
        debug = await verify_user_access_token(payload.access_token)
        long_lived = await exchange_for_long_lived_token(payload.access_token)
        granted_pages = await list_granted_pages(long_lived["access_token"])
        identity = MetaGrantIdentity.facebook(debug, granted_pages)
    except ValueError:
        raise HTTPException(status_code=502, detail="Provider grant could not be verified") from None
    except MetaAPIError as exc:
        logger.error("Facebook Login for Business error", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Facebook connect failed: {exc}")

    if not granted_pages:
        raise HTTPException(status_code=400, detail="No Facebook Pages were granted in this connection")

    workspace = db.query(Workspace).filter(Workspace.id == ctx.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    connected: list[dict] = []
    conflicts: list[dict] = []

    for page_data in granted_pages:
        page_id = page_data.get("id")
        page_access_token = page_data.get("access_token")
        if not page_id or not page_access_token:
            continue

        # page_id is globally unique in Meta — if the Page is already
        # connected to a different workspace, don't silently re-point the
        # row (and don't even subscribe our app to it). Collect it as a
        # conflict and keep connecting the rest of the batch.
        page = db.query(FacebookPage).filter(FacebookPage.page_id == page_id).with_for_update().first()
        if page is not None and page.workspace_id != ctx.workspace_id:
            conflicts.append(
                {
                    "page_id": page_id,
                    "page_name": page_data.get("name"),
                    "reason": "Already connected to a different workspace",
                }
            )
            continue

        if page is not None and page.status == "erasure_pending":
            raise HTTPException(status_code=409, detail="Account erasure pending")

        try:
            await subscribe_app_to_page(page_access_token, page_id)
        except MetaAPIError as exc:
            logger.error("Failed to subscribe app to Facebook Page", extra={"page_id": page_id, "error": str(exc)})
            continue

        is_new = page is None
        if page is None:
            page = FacebookPage(id=uuid.uuid4(), workspace_id=workspace.id, page_id=page_id)
            db.add(page)

        page.page_name = page_data.get("name")
        page.status = "connected"
        db.flush()

        # Page Access Tokens from Facebook Login for Business don't expire
        # the way user tokens do as long as the user token backing them stays
        # valid — no expires_at tracked here (mirrors how granted Pages don't
        # come back with an expires_in field).
        store_encrypted_token(db, page.id, page_access_token, commit=False)
        save_grant(db, identity, page, page_id)

        write_audit_log(
            db,
            "facebook_page_connected" if is_new else "facebook_page_reconnected",
            f"Facebook Page connected: {page.page_name or page.page_id}",
            actor=ctx.user,
            entity_type="facebook_page",
            entity_id=page.id,
            entity_name=page.page_name or page.page_id,
            metadata={"page_id": page.page_id},
            commit=False,
        )
        connected.append(_page_response(page))

    db.commit()
    return {"connected": connected, "conflicts": conflicts}


# --- Accounts ---------------------------------------------------------------


@router.delete("/accounts/{page_id}/hard", status_code=202)
async def hard_delete_facebook_page(
    page_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("delete_accounts")),
):
    from app.services.account_erasure import begin_erasure
    job = begin_erasure(db, workspace_id=ctx.workspace_id, platform="facebook", channel_id=page_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Account not found")
    db.commit()
    return {"job_id": str(job.id), "status": job.state}


@router.get("/accounts")
async def list_facebook_pages(
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_role()),
):
    pages = (
        db.query(FacebookPage).filter(FacebookPage.workspace_id == ctx.workspace_id).all()
    )
    return [_page_response(page) for page in pages]


@router.get("/accounts/{page_id}")
async def get_facebook_page(
    page_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_role()),
):
    # Filtering by workspace_id (rather than fetching then comparing) means a
    # cross-workspace id is indistinguishable from a nonexistent one: 404
    # either way, no existence leak across workspaces.
    page = (
        db.query(FacebookPage)
        .filter(
            FacebookPage.id == page_id,
            FacebookPage.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return _page_response(page)


class FacebookAISettingsUpdate(BaseModel):
    business_vertical: Literal["general", "restaurant", "real_estate", "clinical"] | None = None
    ai_enabled: bool | None = None
    ai_cold_dm_enabled: bool | None = None
    ai_business_profile: str | None = Field(default=None, max_length=4000)
    ai_tone_instructions: str | None = Field(default=None, max_length=1000)
    ai_daily_message_cap: int | None = Field(default=None, ge=0, le=5000)
    ai_handoff_after_turns: int | None = Field(default=None, ge=1, le=50)


@router.patch("/accounts/{page_id}/ai-settings")
async def update_facebook_ai_settings(
    page_id: UUID,
    payload: FacebookAISettingsUpdate,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_accounts")),
):
    _limit_mutation(ctx.user)
    page = (
        db.query(FacebookPage)
        .filter(
            FacebookPage.id == page_id,
            FacebookPage.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(page, field, value)
    db.commit()
    db.refresh(page)

    db.add(AutomationLog(facebook_page_id=page.id, action="ai_settings_updated", details=update_data))
    db.commit()

    return _page_response(page)


@router.delete("/accounts/{page_id}")
async def disconnect_facebook_page(
    page_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_accounts")),
):
    _limit_mutation(ctx.user)
    page = (
        db.query(FacebookPage)
        .filter(
            FacebookPage.id == page_id,
            FacebookPage.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    if page.status == "erasure_pending":
        raise HTTPException(status_code=409, detail="Account erasure pending")
    page.status = "disconnected"
    db.commit()

    write_audit_log(
        db,
        "facebook_page_disconnected",
        f"Facebook Page disconnected: {page.page_name or page.page_id}",
        actor=ctx.user,
        entity_type="facebook_page",
        entity_id=page.id,
        entity_name=page.page_name or page.page_id,
        metadata={"page_id": page.page_id},
    )
    return _page_response(page)


# --- Campaigns ---------------------------------------------------------------


def _campaign_response(campaign: FacebookCampaign) -> dict:
    return {
        "id": str(campaign.id),
        "facebook_page_id": str(campaign.facebook_page_id),
        "name": campaign.name,
        "description": campaign.description,
        "post_id": campaign.post_id,
        "target_scope": campaign.target_scope,
        "target_post_id": campaign.target_post_id,
        "target_post_label": campaign.target_post_label,
        "match_type": campaign.match_type,
        "message_template": campaign.message_template,
        "link_url": campaign.link_url,
        "cooldown_hours": campaign.cooldown_hours,
        "status": campaign.status,
        "delivery_mode": campaign.delivery_mode,
        "comment_reply_enabled": campaign.comment_reply_enabled,
        "comment_reply_text": campaign.comment_reply_text,
        "ai_enabled": campaign.ai_enabled,
        "ai_handoff_after_turns": campaign.ai_handoff_after_turns,
        "total_triggers": campaign.total_triggers,
        "successful_sends": campaign.successful_sends,
        "failed_sends": campaign.failed_sends,
        "keywords": [
            {"id": str(kw.id), "normalized_keyword": kw.normalized_keyword} for kw in campaign.keywords
        ],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


class FacebookCampaignCreate(BaseModel):
    facebook_page_id: UUID
    name: str = Field(max_length=255)
    description: str | None = None
    target_scope: Literal["any_post", "specific_post"] = "any_post"
    target_post_id: str | None = None
    target_post_label: str | None = None
    match_type: Literal["contains", "exact", "starts_with"] = "contains"
    message_template: str = ""
    link_url: str | None = None
    cooldown_hours: int = Field(default=168, ge=0)
    comment_reply_enabled: bool = False
    comment_reply_text: str | None = None
    ai_enabled: bool = False
    ai_handoff_after_turns: int = Field(default=8, ge=1, le=50)
    keywords: list[str] = Field(default_factory=list)


class FacebookCampaignUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    target_scope: Literal["any_post", "specific_post"] | None = None
    target_post_id: str | None = None
    target_post_label: str | None = None
    match_type: Literal["contains", "exact", "starts_with"] | None = None
    message_template: str | None = None
    link_url: str | None = None
    cooldown_hours: int | None = Field(default=None, ge=0)
    status: Literal["draft", "active", "paused", "archived"] | None = None
    comment_reply_enabled: bool | None = None
    comment_reply_text: str | None = None
    ai_enabled: bool | None = None
    ai_handoff_after_turns: int | None = Field(default=None, ge=1, le=50)


@router.get("/campaigns")
async def list_facebook_campaigns(
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_role()),
):
    campaigns = (
        db.query(FacebookCampaign)
        .filter(FacebookCampaign.workspace_id == ctx.workspace_id)
        .all()
    )
    return [_campaign_response(c) for c in campaigns]


@router.post("/campaigns", status_code=201)
async def create_facebook_campaign(
    payload: FacebookCampaignCreate,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_campaigns")),
):
    page = (
        db.query(FacebookPage)
        .filter(
            FacebookPage.id == payload.facebook_page_id,
            FacebookPage.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Facebook Page not found")

    data = payload.model_dump(exclude={"keywords"})
    campaign = FacebookCampaign(id=uuid.uuid4(), workspace_id=page.workspace_id, **data)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    for keyword in payload.keywords:
        normalized = keyword.strip().lower()
        if not normalized:
            continue
        db.add(FacebookCampaignKeyword(id=uuid.uuid4(), campaign_id=campaign.id, normalized_keyword=normalized))
    db.commit()
    db.refresh(campaign)

    return _campaign_response(campaign)


@router.get("/campaigns/{campaign_id}")
async def get_facebook_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_role()),
):
    campaign = (
        db.query(FacebookCampaign)
        .filter(
            FacebookCampaign.id == campaign_id,
            FacebookCampaign.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_response(campaign)


@router.patch("/campaigns/{campaign_id}")
async def update_facebook_campaign(
    campaign_id: UUID,
    payload: FacebookCampaignUpdate,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_campaigns")),
):
    campaign = (
        db.query(FacebookCampaign)
        .filter(
            FacebookCampaign.id == campaign_id,
            FacebookCampaign.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(campaign, field, value)
    db.commit()
    db.refresh(campaign)
    return _campaign_response(campaign)


@router.delete("/campaigns/{campaign_id}")
async def delete_facebook_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("delete_campaigns")),
):
    campaign = (
        db.query(FacebookCampaign)
        .filter(
            FacebookCampaign.id == campaign_id,
            FacebookCampaign.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(campaign)
    db.commit()
    return {"status": "deleted", "campaign_id": str(campaign_id)}


class FacebookCampaignKeywordCreate(BaseModel):
    keyword: str = Field(max_length=255)


@router.post("/campaigns/{campaign_id}/keywords", status_code=201)
async def add_facebook_campaign_keyword(
    campaign_id: UUID,
    payload: FacebookCampaignKeywordCreate,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_campaigns")),
):
    campaign = (
        db.query(FacebookCampaign)
        .filter(
            FacebookCampaign.id == campaign_id,
            FacebookCampaign.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    normalized = payload.keyword.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")

    keyword = FacebookCampaignKeyword(id=uuid.uuid4(), campaign_id=campaign.id, normalized_keyword=normalized)
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return {"id": str(keyword.id), "normalized_keyword": keyword.normalized_keyword}


@router.delete("/campaigns/{campaign_id}/keywords/{keyword_id}")
async def delete_facebook_campaign_keyword(
    campaign_id: UUID,
    keyword_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_campaigns")),
):
    # FacebookCampaignKeyword carries no workspace_id of its own — scope it
    # through its parent campaign's workspace_id.
    keyword = (
        db.query(FacebookCampaignKeyword)
        .join(
            FacebookCampaign,
            FacebookCampaign.id == FacebookCampaignKeyword.campaign_id,
        )
        .filter(
            FacebookCampaignKeyword.id == keyword_id,
            FacebookCampaignKeyword.campaign_id == campaign_id,
            FacebookCampaign.workspace_id == ctx.workspace_id,
        )
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(keyword)
    db.commit()
    return {"status": "deleted", "keyword_id": str(keyword_id)}
