import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.oauth import build_oauth_url
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
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
async def hard_delete_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delete_accounts")),
):
    """
    Permanently delete an Instagram account and all associated data.

    Full dependency graph discovered from FK constraints:
      instagram_accounts
      ├── comments            (NOT NULL FK) ← messages.comment_id (nullable)
      │                                     ← leads.comment_id (nullable)
      ├── leads               (NOT NULL FK)
      ├── meta_tokens         (NOT NULL FK)
      ├── campaigns           (NOT NULL FK)
      │   ├── messages        (NOT NULL FK) → also refs comments (nullable, nullified above)
      │   ├── user_cooldowns  (NOT NULL FK)
      │   └── keywords        (cascade via ORM relationship)
      └── automation_logs     (nullable FK → nullify, preserve for audit history)

    Deletion order:
      1. Nullify messages.comment_id   — breaks comments → messages cycle
      2. Nullify leads.comment_id      — breaks comments → leads cycle
      3. Delete messages               — FK → campaigns
      4. Delete user_cooldowns         — FK → campaigns
      5. Delete leads                  — FK → instagram_accounts
      6. Delete comments               — FK → instagram_accounts
      7. Delete campaigns              — FK → instagram_accounts (keywords cascade via ORM)
      8. Delete meta_tokens            — FK → instagram_accounts
      9. Nullify automation_logs       — preserve rows, remove FK reference
     10. Delete instagram_account row
    """
    _limit_account_mutation(current_user)

    account = db.query(InstagramAccount).filter(InstagramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account_name = _account_name(account)
    ig_user_id = account.ig_user_id

    # Collect campaign IDs — needed for message/cooldown deletion scoping.
    campaign_ids = [
        row[0]
        for row in db.query(Campaign.id)
        .filter(Campaign.instagram_account_id == account_id)
        .all()
    ]

    # Collect comment IDs for this account — needed to nullify FK references before deletion.
    comment_ids = [
        row[0]
        for row in db.query(Comment.id)
        .filter(Comment.instagram_account_id == account_id)
        .all()
    ]

    # 1. Nullify messages.comment_id (nullable FK → comments).
    if comment_ids:
        db.query(Message).filter(Message.comment_id.in_(comment_ids)).update(
            {"comment_id": None}, synchronize_session=False
        )

    # 3. Delete messages (FK → campaigns).
    if campaign_ids:
        db.query(Message).filter(Message.campaign_id.in_(campaign_ids)).delete(
            synchronize_session=False
        )

    # 4. Delete user_cooldowns (FK → campaigns).
    if campaign_ids:
        db.query(UserCooldown).filter(UserCooldown.campaign_id.in_(campaign_ids)).delete(
            synchronize_session=False
        )

    # 5. Delete leads (FK → instagram_accounts, NOT NULL).
    db.query(Lead).filter(Lead.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 6. Delete comments (FK → instagram_accounts, NOT NULL).
    db.query(Comment).filter(Comment.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 7. Delete campaigns (keywords cascade via ORM cascade="all, delete-orphan").
    db.query(Campaign).filter(Campaign.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 8. Delete meta_tokens (FK → instagram_accounts, NOT NULL).
    db.query(MetaToken).filter(MetaToken.instagram_account_id == account_id).delete(
        synchronize_session=False
    )

    # 9. Nullify automation_logs (nullable FK — preserve rows for audit history).
    db.query(AutomationLog).filter(
        AutomationLog.instagram_account_id == account_id
    ).update({"instagram_account_id": None}, synchronize_session=False)

    # 10. Delete the account row itself.
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