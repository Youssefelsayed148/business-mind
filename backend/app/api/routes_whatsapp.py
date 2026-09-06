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

from app.api.routes_auth import get_current_user
from app.authz import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.whatsapp_oauth import (
    exchange_code_for_token,
    exchange_for_long_lived_token,
    fetch_phone_number_metadata,
    subscribe_app_to_waba,
)
from app.models.automation_log import AutomationLog
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit
from app.services.whatsapp_token_service import store_encrypted_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp")

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


def _account_response(account: WhatsappAccount) -> dict:
    return {
        "id": str(account.id),
        "phone_number_id": account.phone_number_id,
        "display_phone_number": account.display_phone_number,
        "whatsapp_business_account_id": account.whatsapp_business_account_id,
        "status": account.status,
        "business_vertical": account.business_vertical,
        "ai_enabled": account.ai_enabled,
        "ai_business_profile": account.ai_business_profile,
        "ai_tone_instructions": account.ai_tone_instructions,
        "ai_daily_message_cap": account.ai_daily_message_cap,
        "ai_messages_sent_today": account.ai_messages_sent_today,
        "ai_handoff_after_turns": account.ai_handoff_after_turns,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


@router.get("/connect/start")
async def whatsapp_connect_start(
    current_user: User = Depends(require_permission("manage_accounts")),
):
    """Return what the frontend needs to kick off Embedded Signup's
    FB.login() call. Unlike Instagram Login, there is no server-driven
    redirect URL here — Meta hosts the entire popup flow client-side; our
    backend only issues a CSRF state nonce (verified in the callback POST)
    and hands back the app/config identifiers the JS SDK needs.
    """
    if not settings.WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID:
        raise HTTPException(
            status_code=503,
            detail="WhatsApp Embedded Signup is not configured (WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID unset).",
        )
    state = secrets.token_urlsafe(24)
    try:
        _redis().setex(f"whatsapp_oauth_state:{state}", 600, "1")
    except RedisError:
        logger.error("Failed to store WhatsApp OAuth state in Redis")
        raise HTTPException(status_code=503, detail="Could not start WhatsApp connect flow")

    return {
        "app_id": settings.META_APP_ID,
        "config_id": settings.WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID,
        "graph_api_version": settings.META_GRAPH_API_VERSION,
        "state": state,
    }


class WhatsappConnectCallback(BaseModel):
    code: str
    phone_number_id: str
    waba_id: str
    state: str


@router.post("/connect/callback")
async def whatsapp_connect_callback(
    payload: WhatsappConnectCallback,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    """Finish Embedded Signup: exchange the code for a token, subscribe our
    app to the WABA's webhooks, fetch the number's display info, and
    upsert the WhatsappAccount + encrypted token.

    The frontend posts here with the `code`, `phone_number_id`, and
    `waba_id` it received from FB.login()'s response and the
    "WA_EMBEDDED_SIGNUP" postMessage event, plus the `state` nonce from
    /connect/start.
    """
    _limit_account_mutation(current_user)

    try:
        state_value = _redis().get(f"whatsapp_oauth_state:{payload.state}")
        if not state_value:
            raise HTTPException(status_code=400, detail="Invalid or expired connect session")
        _redis().delete(f"whatsapp_oauth_state:{payload.state}")
    except RedisError:
        logger.error("Failed to validate WhatsApp OAuth state in Redis")
        raise HTTPException(status_code=503, detail="Could not verify WhatsApp connect session")

    try:
        short_lived = await exchange_code_for_token(payload.code)
        long_lived = await exchange_for_long_lived_token(short_lived["access_token"])
        await subscribe_app_to_waba(long_lived["access_token"], payload.waba_id)
        metadata = await fetch_phone_number_metadata(long_lived["access_token"], payload.phone_number_id)
    except MetaAPIError as exc:
        logger.error("WhatsApp Embedded Signup error", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"WhatsApp connect failed: {exc}")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=long_lived.get("expires_in", 5184000))

    workspace = db.query(Workspace).filter(Workspace.slug == "default").first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Default workspace not found")

    account = (
        db.query(WhatsappAccount)
        .filter(WhatsappAccount.phone_number_id == payload.phone_number_id)
        .first()
    )
    is_new = account is None
    if account is None:
        account = WhatsappAccount(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            phone_number_id=payload.phone_number_id,
        )
        db.add(account)

    account.whatsapp_business_account_id = payload.waba_id
    account.display_phone_number = metadata.get("display_phone_number")
    account.status = "connected"
    db.commit()
    db.refresh(account)

    store_encrypted_token(db, account.id, long_lived["access_token"], expires_at=expires_at)

    write_audit_log(
        db,
        "whatsapp_account_connected" if is_new else "whatsapp_account_reconnected",
        f"WhatsApp number connected: {account.display_phone_number or account.phone_number_id}",
        actor=current_user,
        entity_type="whatsapp_account",
        entity_id=account.id,
        entity_name=account.display_phone_number or account.phone_number_id,
        metadata={"phone_number_id": account.phone_number_id, "waba_id": payload.waba_id},
    )

    return _account_response(account)


@router.get("/accounts")
async def list_whatsapp_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    accounts = db.query(WhatsappAccount).all()
    return [_account_response(account) for account in accounts]


@router.get("/accounts/{account_id}")
async def get_whatsapp_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(WhatsappAccount).filter(WhatsappAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_response(account)


class WhatsappAISettingsUpdate(BaseModel):
    business_vertical: Literal["general", "restaurant", "real_estate", "clinical"] | None = None
    ai_enabled: bool | None = None
    ai_business_profile: str | None = Field(default=None, max_length=4000)
    ai_tone_instructions: str | None = Field(default=None, max_length=1000)
    ai_daily_message_cap: int | None = Field(default=None, ge=0, le=5000)
    ai_handoff_after_turns: int | None = Field(default=None, ge=1, le=50)


@router.patch("/accounts/{account_id}/ai-settings")
async def update_whatsapp_ai_settings(
    account_id: UUID,
    payload: WhatsappAISettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    _limit_account_mutation(current_user)
    account = db.query(WhatsappAccount).filter(WhatsappAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)

    db.add(
        AutomationLog(
            whatsapp_account_id=account.id,
            action="ai_settings_updated",
            details=update_data,
        )
    )
    db.commit()

    return _account_response(account)


@router.delete("/accounts/{account_id}")
async def disconnect_whatsapp_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_accounts")),
):
    _limit_account_mutation(current_user)
    account = db.query(WhatsappAccount).filter(WhatsappAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.status = "disconnected"
    db.commit()

    write_audit_log(
        db,
        "whatsapp_account_disconnected",
        f"WhatsApp number disconnected: {account.display_phone_number or account.phone_number_id}",
        actor=current_user,
        entity_type="whatsapp_account",
        entity_id=account.id,
        entity_name=account.display_phone_number or account.phone_number_id,
        metadata={"phone_number_id": account.phone_number_id},
    )

    return _account_response(account)
