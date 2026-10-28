import logging
import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import WorkspaceContext, require_workspace_permission, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.accounts import fetch_instagram_account_metadata
from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.oauth import build_oauth_url, exchange_code_for_short_lived_token, exchange_for_long_lived_token
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.auth import MeResponse
from app.services.token_service import store_encrypted_token
from app.services.meta_grant_identity import MetaGrantIdentity, save_grant
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit
from app.utils.crypto import encrypt_text

logger = logging.getLogger(__name__)

router = APIRouter()

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


@router.get("/meta/connect/start")
async def meta_connect_start(
    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_accounts")),
):
    _limit_account_mutation(ctx.user)
    state = str(uuid.uuid4())
    try:
        # Value "1" = fresh connect (no existing account_id).
        _redis().setex(f"oauth_state:{state}", 600, json.dumps({"workspace_id": str(ctx.workspace_id)}))
    except RedisError:
        logger.error("Failed to store OAuth state in Redis")
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
    oauth_url = build_oauth_url(state)
    return {"oauth_url": oauth_url}


@router.get("/meta/connect/callback")
async def meta_connect_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    params = request.query_params
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")
    error_code = params.get("error_code")
    error_message = params.get("error_message")

    # Instagram Login sends error=access_denied (plus error_reason/error_description)
    # when the user denies the flow; the old Facebook flow sent error_code.
    if error or error_code or not code or not state:
        logger.warning(
            "OAuth callback error from Meta",
            extra={"error": error, "error_code": error_code, "error_message": error_message},
        )
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")
    logger.info("Meta OAuth callback received", extra={"state": state})

    # CSRF check
    try:
        _r = _redis()
        state_value = _r.get(f"oauth_state:{state}")
        if not state_value:
            logger.warning("OAuth state not found or expired", extra={"state": state})
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")
        _r.delete(f"oauth_state:{state}")
    except RedisError:
        logger.error("Failed to validate OAuth state in Redis")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")

    try:
        scope = json.loads(state_value)
        workspace_id = uuid.UUID(scope["workspace_id"])
        reconnect_account_id = scope.get("account_id")
    except (ValueError, TypeError, KeyError):
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")

    redirect_uri = f"{settings.APP_BASE_URL}/meta/connect/callback"

    try:
        short_lived = await exchange_code_for_short_lived_token(code, redirect_uri)
        long_lived = await exchange_for_long_lived_token(short_lived["access_token"])
        metadata = await fetch_instagram_account_metadata(long_lived["access_token"])
        identity = MetaGrantIdentity.instagram(short_lived, metadata)
    except (MetaAPIError, ValueError):
        logger.error("Provider OAuth grant verification failed")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")

    expires_at = datetime.utcnow() + timedelta(seconds=long_lived.get("expires_in", 5184000))

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    account = db.query(InstagramAccount).filter(
        InstagramAccount.ig_user_id == metadata["ig_user_id"]
    ).with_for_update().first()
    if account and account.workspace_id != workspace_id:
        raise HTTPException(status_code=409, detail="Account already connected")
    if reconnect_account_id and (not account or str(account.id) != reconnect_account_id):
        raise HTTPException(status_code=409, detail="Reconnect grant mismatch")
    if account and account.status == "erasure_pending":
        raise HTTPException(status_code=409, detail="Account erasure pending")
    try:
        if account is None:
            account = InstagramAccount(id=uuid.uuid4(), workspace_id=workspace.id,
                                       ig_user_id=metadata["ig_user_id"])
            db.add(account)
        account.ig_username = metadata["username"]
        account.status = "connected"
        db.flush()
        store_encrypted_token(db, workspace.id, account.id, long_lived["access_token"],
                              expires_at=expires_at, commit=False)
        save_grant(db, identity, account, metadata["ig_user_id"])
        write_audit_log(db, "account_connected", "Provider grant connected", actor=None,
                        entity_type="account", entity_id=account.id, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = "reconnected" if reconnect_account_id else "connected"
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?{result}=true")


class MockConnectRequest:
    def __init__(self, ig_user_id: str, username: str, account_type: str, access_token: str, expires_at: str | None = None):
        self.ig_user_id = ig_user_id
        self.username = username
        self.account_type = account_type
        self.access_token = access_token
        self.expires_at = expires_at


if settings.APP_ENV == "development":
    from pydantic import BaseModel

    class MockConnectBody(BaseModel):
        ig_user_id: str
        username: str
        account_type: str
        access_token: str
        expires_at: str | None = None

    @router.post("/meta/connect/mock")
    async def meta_connect_mock(
        body: MockConnectBody,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission("manage_accounts")),
    ):
        _limit_account_mutation(current_user)
        workspace = db.query(Workspace).filter(Workspace.slug == "default").first()
        if not workspace:
            raise HTTPException(status_code=404, detail="Default workspace not found")

        existing = (
            db.query(InstagramAccount)
            .filter(InstagramAccount.ig_user_id == body.ig_user_id)
            .first()
        )
        if existing:
            account = existing
            account.ig_username = body.username
            account.status = "connected"
        else:
            account = InstagramAccount(
                workspace_id=workspace.id,
                ig_user_id=body.ig_user_id,
                ig_username=body.username,
                status="connected",
            )
            db.add(account)

        db.commit()
        db.refresh(account)

        store_encrypted_token(
            db=db,
            workspace_id=workspace.id,
            instagram_account_id=account.id,
            access_token=body.access_token,
        )
        write_audit_log(
            db,
            "account_connected",
            f"{current_user.email} connected account {account.ig_username or account.ig_user_id}",
            actor=current_user,
            entity_type="account",
            entity_id=account.id,
            entity_name=account.ig_username or account.ig_user_id,
            metadata={"ig_user_id": account.ig_user_id, "mock": True},
        )

        logger.info(
            "Mock Meta account connected",
            extra={"ig_user_id": body.ig_user_id, "username": body.username},
        )
        return {
            "status": "connected",
            "account_id": str(account.id),
            "ig_user_id": body.ig_user_id,
        }