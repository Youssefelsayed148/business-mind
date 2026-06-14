import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.authz import require_permission
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
    current_user: User = Depends(require_permission("manage_accounts")),
):
    _limit_account_mutation(current_user)
    state = str(uuid.uuid4())
    try:
        # Value "1" = fresh connect (no existing account_id).
        _redis().setex(f"oauth_state:{state}", 600, "1")
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
    error_code = params.get("error_code")
    error_message = params.get("error_message")

    # Meta sends error_code when user denies or scopes are invalid.
    if error_code or not code or not state:
        logger.warning(
            "OAuth callback error from Meta",
            extra={"error_code": error_code, "error_message": error_message},
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

    # state_value == "1"  → fresh connect (no target account)
    # state_value == "<uuid>"  → reconnect for a specific existing account
    is_reconnect = state_value != "1"
    reconnect_account_id = state_value if is_reconnect else None

    redirect_uri = f"{settings.APP_BASE_URL}/meta/connect/callback"

    try:
        short_lived = await exchange_code_for_short_lived_token(code, redirect_uri)
        long_lived = await exchange_for_long_lived_token(short_lived["access_token"])
        metadata = await fetch_instagram_account_metadata(long_lived["access_token"])
    except MetaAPIError as exc:
        logger.error("Meta OAuth error during account connection", extra={"error": str(exc)})
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?error=oauth_failed")

    expires_at = datetime.utcnow() + timedelta(seconds=long_lived.get("expires_in", 5184000))

    # Exchange user token for page token — private_replies requires a PAGE token not a USER token.
    # Fetch pages managed by this user and find the one linked to this IG account.
    import httpx as _httpx
    token_to_store = long_lived["access_token"]  # fallback to user token if page token fetch fails
    try:
        async with _httpx.AsyncClient(timeout=15.0) as _http:
            pages_resp = await _http.get(
                f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/me/accounts",
                params={
                    "access_token": long_lived["access_token"],
                    "fields": "id,name,access_token,instagram_business_account",
                },
            )
        if pages_resp.status_code == 200:
            pages = pages_resp.json().get("data", [])
            for page in pages:
                iba = page.get("instagram_business_account", {})
                if iba.get("id") == metadata["ig_user_id"]:
                    token_to_store = page["access_token"]
                    logger.info(
                        "Stored page token for private_replies",
                        extra={"page_id": page["id"], "ig_user_id": metadata["ig_user_id"]},
                    )
                    break
            else:
                logger.warning(
                    "No page matched IG account — falling back to user token",
                    extra={"ig_user_id": metadata["ig_user_id"]},
                )
        else:
            logger.warning("Failed to fetch pages — falling back to user token", extra={"status": pages_resp.status_code})
    except Exception as exc:
        logger.warning("Page token fetch error — falling back to user token", extra={"error": str(exc)})

    workspace = db.query(Workspace).filter(Workspace.slug == "default").first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Default workspace not found")

    if is_reconnect and reconnect_account_id:
        # Reconnect: find the specific account by its DB id, update it in place.
        # If the returned ig_user_id differs from what's stored (user authed wrong account),
        # we fall through to the normal upsert-by-ig_user_id path so we don't corrupt data.
        import uuid as _uuid
        try:
            target_id = _uuid.UUID(reconnect_account_id)
            account = db.query(InstagramAccount).filter(InstagramAccount.id == target_id).first()
            if account and account.ig_user_id == metadata["ig_user_id"]:
                account.ig_username = metadata["username"]
                account.status = "connected"
                db.commit()
                db.refresh(account)
                store_encrypted_token(
                    db=db,
                    workspace_id=workspace.id,
                    instagram_account_id=account.id,
                    access_token=token_to_store,
                    expires_at=expires_at,
                )
                write_audit_log(
                    db,
                    "account_reconnected",
                    f"OAuth reconnected account {account.ig_username or account.ig_user_id}",
                    actor=None,
                    entity_type="account",
                    entity_id=account.id,
                    entity_name=account.ig_username or account.ig_user_id,
                    metadata={"ig_user_id": account.ig_user_id, "mock": False},
                )
                logger.info(
                    "Meta account reconnected via OAuth",
                    extra={"ig_user_id": metadata["ig_user_id"], "username": metadata["username"]},
                )
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?reconnected=true")
            else:
                logger.warning(
                    "Reconnect ig_user_id mismatch — falling through to upsert",
                    extra={
                        "expected": account.ig_user_id if account else "not_found",
                        "received": metadata["ig_user_id"],
                    },
                )
        except (ValueError, AttributeError):
            logger.error("Invalid reconnect_account_id in Redis state", extra={"value": reconnect_account_id})

    # Normal connect flow: upsert by ig_user_id.
    existing = (
        db.query(InstagramAccount)
        .filter(InstagramAccount.ig_user_id == metadata["ig_user_id"])
        .first()
    )
    if existing:
        account = existing
        account.ig_username = metadata["username"]
        account.status = "connected"
    else:
        account = InstagramAccount(
            workspace_id=workspace.id,
            ig_user_id=metadata["ig_user_id"],
            ig_username=metadata["username"],
            status="connected",
        )
        db.add(account)

    db.commit()
    db.refresh(account)

    store_encrypted_token(
        db=db,
        workspace_id=workspace.id,
        instagram_account_id=account.id,
        access_token=token_to_store,
        expires_at=expires_at,
    )
    write_audit_log(
        db,
        "account_connected",
        f"OAuth connected account {account.ig_username or account.ig_user_id}",
        actor=None,
        entity_type="account",
        entity_id=account.id,
        entity_name=account.ig_username or account.ig_user_id,
        metadata={"ig_user_id": account.ig_user_id, "mock": False},
    )

    logger.info(
        "Meta account connected via OAuth",
        extra={"ig_user_id": metadata["ig_user_id"], "username": metadata["username"]},
    )
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/accounts?connected=true")


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