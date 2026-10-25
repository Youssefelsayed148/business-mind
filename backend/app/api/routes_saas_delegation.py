"""Admin endpoints for per-channel SaaS delegation settings (M-01).

Mounted under each platform's existing prefix so the dashboard keeps its
current workspace-header behaviour: /whatsapp and /facebook are
workspace-scoped, /instagram uses the global role like its other routes.
Owner and admin roles only. Nothing here sends or forwards anything.
"""

import logging
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.authz import WorkspaceContext, require_role, require_workspace_role
from app.core.config import settings
from app.db.session import get_db
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.roles import ROLE_ADMIN, ROLE_OWNER
from app.schemas.saas_delegation import SaasDelegationUpdate
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit
from app.services.saas_forwarder import drop_pending
from app.services.saas_health import sync_channel
from app.services.saas_delegation_service import (
    DelegationConfigError,
    apply_config,
    config_response,
)

logger = logging.getLogger(__name__)

_ADMIN_ROLES = (ROLE_OWNER, ROLE_ADMIN)


def _limit(user: User) -> None:
    enforce_user_rate_limit(
        user,
        "account_mutation",
        settings.ACCOUNT_MUTATION_USER_LIMIT,
        settings.ACCOUNT_MUTATION_USER_WINDOW_SECONDS,
        "Too many account changes. Please wait a moment and try again.",
    )


def _update(
    db: Session, channel, user: User, payload: SaasDelegationUpdate, channel_name: str, platform: str
) -> dict:
    _limit(user)
    data = payload.model_dump(exclude_unset=True)
    was_enabled = bool(channel.saas_delegation_enabled)
    try:
        apply_config(channel, data)
    except DelegationConfigError as exc:
        db.refresh(channel)  # discard the partial, uncommitted changes
        raise HTTPException(status_code=422, detail=str(exc))
    if was_enabled and not channel.saas_delegation_enabled:
        # A13: queued, unsent forwards are dropped, never sent after the switch.
        drop_pending(db, platform=platform, channel_id=channel.id)
    db.commit()
    db.refresh(channel)
    if channel.saas_delegation_enabled and not was_enabled:
        # Give the SaaS an initial channel.status right away; the sweep
        # covers it if this fails.
        try:
            sync_channel(db, platform, channel, force=True)
        except Exception:
            db.rollback()
            logger.warning("Initial channel.status push failed", exc_info=True)
            db.refresh(channel)

    if "saas_delegation_enabled" in data and bool(channel.saas_delegation_enabled) != was_enabled:
        action = "saas_delegation_enabled" if channel.saas_delegation_enabled else "saas_delegation_disabled"
    else:
        action = "saas_delegation_updated"
    # Field names only: never the secret, URL credentials or message text.
    write_audit_log(
        db,
        action,
        f"SaaS delegation settings changed for {channel_name} channel",
        actor=user,
        entity_type=channel_name,
        entity_id=channel.id,
        metadata={"fields": sorted(k for k in data if k != "secret"), "secret_rotated": bool(data.get("secret"))},
    )
    return config_response(channel)


def _build(prefix: str, platform: str, model, channel_name: str, role_dep: Callable, user_of: Callable, scope: Callable) -> APIRouter:
    router = APIRouter(prefix=prefix)

    def _load(db: Session, channel_id: UUID, ctx):
        channel = scope(db.query(model).filter(model.id == channel_id), ctx).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Account not found")
        return channel

    @router.get("/accounts/{channel_id}/saas-delegation")
    async def get_delegation(channel_id: UUID, db: Session = Depends(get_db), ctx=Depends(role_dep)):
        return config_response(_load(db, channel_id, ctx))

    @router.patch("/accounts/{channel_id}/saas-delegation")
    async def patch_delegation(
        channel_id: UUID,
        payload: SaasDelegationUpdate,
        db: Session = Depends(get_db),
        ctx=Depends(role_dep),
    ):
        return _update(db, _load(db, channel_id, ctx), user_of(ctx), payload, channel_name, platform)

    return router


instagram_router = _build(
    "/instagram",
    "instagram",
    InstagramAccount,
    "instagram_account",
    require_role(*_ADMIN_ROLES),
    lambda user: user,
    lambda query, _user: query,
)
whatsapp_router = _build(
    "/whatsapp",
    "whatsapp",
    WhatsappAccount,
    "whatsapp_account",
    require_workspace_role(*_ADMIN_ROLES),
    lambda ctx: ctx.user,
    lambda query, ctx: query.filter(WhatsappAccount.workspace_id == ctx.workspace_id),
)
facebook_router = _build(
    "/facebook",
    "facebook",
    FacebookPage,
    "facebook_page",
    require_workspace_role(*_ADMIN_ROLES),
    lambda ctx: ctx.user,
    lambda query, ctx: query.filter(FacebookPage.workspace_id == ctx.workspace_id),
)
