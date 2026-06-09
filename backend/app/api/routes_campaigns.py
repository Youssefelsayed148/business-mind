from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.campaign import (
    CampaignCreate,
    CampaignKeywordResponse,
    CampaignResponse,
    CampaignSimulateRequest,
    CampaignSimulateResponse,
    CampaignUpdate,
)
from app.services.campaign_matcher import find_matching_keyword
from app.services.campaign_service import (
    activate_campaign,
    add_keyword,
    archive_campaign,
    create_campaign,
    delete_keyword,
    get_campaign,
    hard_delete_campaign,
    list_campaigns,
    pause_campaign,
    unarchive_campaign,
    update_campaign,
)
from app.services.rate_limit_service import enforce_user_rate_limit
from app.utils.templates import render_template

router = APIRouter()


def _limit_campaign_mutation(current_user: User) -> None:
    enforce_user_rate_limit(
        current_user,
        "campaign_mutation",
        settings.MUTATION_USER_LIMIT,
        settings.MUTATION_USER_WINDOW_SECONDS,
        "Too many campaign changes. Please wait a moment and try again.",
    )


def _get_default_workspace(db: Session) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.slug == "default").first()
    if not ws:
        raise HTTPException(status_code=404, detail="Default workspace not found")
    return ws


@router.get("/campaigns", response_model=list[CampaignResponse])
async def get_campaigns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _limit_campaign_mutation(current_user)
    ws = _get_default_workspace(db)
    return list_campaigns(db, ws.id)


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
async def post_campaign(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    ws = _get_default_workspace(db)
    return create_campaign(db, ws.id, payload, current_user)


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_single_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def patch_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return update_campaign(db, campaign_id, payload, current_user)


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delete_campaigns")),
):
    _limit_campaign_mutation(current_user)
    hard_delete_campaign(db, campaign_id, current_user)
    return {"status": "deleted", "campaign_id": str(campaign_id)}


@router.post("/campaigns/{campaign_id}/activate", response_model=CampaignResponse)
async def post_activate(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return activate_campaign(db, campaign_id, current_user)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignResponse)
async def post_pause(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return pause_campaign(db, campaign_id, current_user)


@router.post("/campaigns/{campaign_id}/archive", response_model=CampaignResponse)
async def post_archive(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return archive_campaign(db, campaign_id, current_user)


@router.post("/campaigns/{campaign_id}/unarchive", response_model=CampaignResponse)
async def post_unarchive(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return unarchive_campaign(db, campaign_id, current_user)


@router.get("/campaigns/{campaign_id}/keywords", response_model=list[CampaignKeywordResponse])
async def get_keywords(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign.keywords


@router.post("/campaigns/{campaign_id}/keywords", response_model=CampaignKeywordResponse, status_code=201)
async def post_keyword(
    campaign_id: UUID,
    keyword: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    return add_keyword(db, campaign_id, keyword)


@router.delete("/campaigns/{campaign_id}/keywords/{keyword_id}")
async def del_keyword(
    campaign_id: UUID,
    keyword_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_campaigns")),
):
    _limit_campaign_mutation(current_user)
    delete_keyword(db, campaign_id, keyword_id)
    return {"status": "deleted"}


@router.post("/campaigns/{campaign_id}/simulate", response_model=CampaignSimulateResponse)
async def post_simulate(
    campaign_id: UUID,
    payload: CampaignSimulateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    keywords = [ck.normalized_keyword for ck in campaign.keywords]
    matched = find_matching_keyword(payload.comment_text, keywords, campaign.match_type)

    if matched:
        context = {
            "username": payload.username,
            "campaign_name": campaign.name,
            "keyword": matched,
            "link": campaign.link_url or "",
            "media_url": campaign.media_url or "",
        }
        rendered = render_template(campaign.message_template, context)
        return CampaignSimulateResponse(
            matched=True,
            matched_keyword=matched,
            rendered_message=rendered,
        )

    return CampaignSimulateResponse(
        matched=False,
        matched_keyword=None,
        rendered_message=None,
    )
