import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.user import User
from app.services.token_service import get_decrypted_token
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instagram")


def _limit_account_mutation(current_user: User) -> None:
    enforce_user_rate_limit(
        current_user,
        "account_mutation",
        settings.ACCOUNT_MUTATION_USER_LIMIT,
        settings.ACCOUNT_MUTATION_USER_WINDOW_SECONDS,
        "Too many account changes. Please wait a moment and try again.",
    )


def _account_response(account: InstagramAccount) -> dict:
    return {
        "id": str(account.id),
        "ig_user_id": account.ig_user_id,
        "username": account.ig_username,
        "status": account.status,
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
    return [_account_response(account) for account in accounts]


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
    return _account_response(account)


@router.post("/accounts/{account_id}/reconnect")
async def reconnect_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    _limit_account_mutation(current_user)
    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if settings.APP_ENV != "development":
        # TODO: Trigger real Meta OAuth reconnection flow.
        raise HTTPException(status_code=501, detail="Real OAuth reconnect is not implemented yet")

    account.status = "connected"
    account.updated_at = datetime.now(timezone.utc)
    (
        db.query(MetaToken)
        .filter(MetaToken.instagram_account_id == account.id)
        .update({"status": "active"}, synchronize_session=False)
    )
    _add_account_log(
        db,
        "account_reconnected",
        account,
        details={"message": "Instagram account reconnected in development mock mode"},
    )
    write_audit_log(
        db,
        "account_reconnected",
        f"{current_user.email} reconnected account {_account_name(account)}",
        actor=current_user,
        entity_type="account",
        entity_id=account.id,
        entity_name=_account_name(account),
        metadata={"ig_user_id": account.ig_user_id},
        commit=False,
    )
    db.commit()
    db.refresh(account)
    logger.info("Account reconnected", extra={"account_id": str(account_id)})
    return _account_response(account)


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
    return _account_response(account)


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
