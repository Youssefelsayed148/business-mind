"""Staff routes for the customer link (Phase 5A). All answer 404 while the flag is off.

Staff only. The routes return states, counts and ids, never a raw external id.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import cookies
from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.models import CustomerLink, ManyChannelClaim, Tenant
from app.db.session import get_session
from app.identity import many_proxy
from app.linking import audit_view, fetch, service
from app.platform.staff import PlatformStaffDep

router = APIRouter(prefix="/api/v1/platform/tenants/{tenant_id}", tags=["customer-links"])

DbSession = Annotated[OrmSession, Depends(get_session)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
CsrfOk = Annotated[None, Depends(cookies.require_csrf)]
Platform = Literal["instagram", "facebook", "whatsapp"]


def _flag(settings: CurrentSettings) -> None:
    if not settings.data_unification_enabled:
        raise StarletteHTTPException(status_code=404, detail="Not Found")


FlagOn = Annotated[None, Depends(_flag)]


def _tenant(db: OrmSession, tenant_id: UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    return tenant


@router.post("/customer-links/sync")
def sync_links(
    tenant_id: UUID,
    staff: PlatformStaffDep,
    db: DbSession,
    settings: CurrentSettings,
    _flag_on: FlagOn,
    _csrf: CsrfOk,
    dry_run: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    tenant = _tenant(db, tenant_id)
    try:
        snapshot = fetch.fetch_snapshot(db, settings, staff, tenant)
    except many_proxy.ManyUnavailable as exc:
        raise many_proxy.unavailable() from exc
    result = service.sync(db, tenant.id, snapshot, dry_run=dry_run)
    if not dry_run:
        record_audit(
            db,
            action="customer_links.sync",
            tenant_id=tenant.id,
            actor_user_id=staff.id,
            target_type="tenant",
            target_id=str(tenant.id),
            metadata=result.as_dict(),
        )
    db.commit()
    return {"dry_run": dry_run, **result.as_dict()}


class LinkOut(BaseModel):
    id: UUID
    platform: str
    many_channel_id: str
    state: str
    source: str
    contact_id: UUID | None
    many_lead_id: str | None


@router.get("/customer-links")
def list_links(
    tenant_id: UUID,
    _staff: PlatformStaffDep,
    db: DbSession,
    _flag_on: FlagOn,
    state: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    _tenant(db, tenant_id)
    where = [CustomerLink.tenant_id == tenant_id]
    if state:
        where.append(CustomerLink.state == state)
    total = db.scalar(select(func.count()).select_from(CustomerLink).where(*where)) or 0
    rows = db.scalars(
        select(CustomerLink)
        .where(*where)
        .order_by(CustomerLink.created_at, CustomerLink.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "total": total,
        "items": [
            LinkOut(
                id=r.id,
                platform=r.platform,
                many_channel_id=r.many_channel_id,
                state=r.state,
                source=r.source,
                contact_id=r.contact_id,
                many_lead_id=r.many_lead_id,
            ).model_dump(mode="json")
            for r in rows
        ],
    }


class ClaimIn(BaseModel):
    platform: Platform
    many_channel_id: UUID = Field(description="The Many account or page id.")


@router.get("/many-channel-claims")
def list_claims(
    tenant_id: UUID, _staff: PlatformStaffDep, db: DbSession, _flag_on: FlagOn
) -> list[dict[str, str]]:
    _tenant(db, tenant_id)
    rows = db.scalars(
        select(ManyChannelClaim)
        .where(ManyChannelClaim.tenant_id == tenant_id)
        .order_by(ManyChannelClaim.created_at)
    )
    return [{"platform": r.platform, "many_channel_id": r.many_channel_id} for r in rows]


@router.post("/many-channel-claims", status_code=201)
def add_claim(
    tenant_id: UUID,
    body: ClaimIn,
    staff: PlatformStaffDep,
    db: DbSession,
    _flag_on: FlagOn,
    _csrf: CsrfOk,
) -> dict[str, str]:
    tenant = _tenant(db, tenant_id)
    channel = str(body.many_channel_id)
    db.add(
        ManyChannelClaim(
            tenant_id=tenant.id,
            platform=body.platform,
            many_channel_id=channel,
            created_by=staff.id,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # The channel already belongs to an organization (maybe this one). Say nothing about whom.
        raise ApiError(
            409, "CHANNEL_ALREADY_CLAIMED", "This channel is already assigned."
        ) from None
    record_audit(
        db,
        action="many_channel.claim",
        tenant_id=tenant.id,
        actor_user_id=staff.id,
        target_type="many_channel",
        target_id=f"{body.platform}:{channel}",
        metadata={"platform": body.platform},
    )
    db.commit()
    return {"platform": body.platform, "many_channel_id": channel}


@router.delete("/many-channel-claims/{platform}/{many_channel_id}", status_code=204)
def remove_claim(
    tenant_id: UUID,
    platform: Platform,
    many_channel_id: UUID,
    staff: PlatformStaffDep,
    db: DbSession,
    _flag_on: FlagOn,
    _csrf: CsrfOk,
) -> Response:
    tenant = _tenant(db, tenant_id)
    row = db.scalar(
        select(ManyChannelClaim).where(
            ManyChannelClaim.tenant_id == tenant.id,
            ManyChannelClaim.platform == platform,
            ManyChannelClaim.many_channel_id == str(many_channel_id),
        )
    )
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    db.delete(row)
    record_audit(
        db,
        action="many_channel.unclaim",
        tenant_id=tenant.id,
        actor_user_id=staff.id,
        target_type="many_channel",
        target_id=f"{platform}:{many_channel_id}",
        metadata={"platform": platform},
    )
    db.commit()
    return Response(status_code=204)


audit_router = APIRouter(prefix="/api/v1/platform", tags=["customer-links"])


@audit_router.get("/audit")
def combined_audit(
    staff: PlatformStaffDep,
    db: DbSession,
    settings: CurrentSettings,
    _flag_on: FlagOn,
    tenant_id: Annotated[UUID | None, Query()] = None,
    source: Annotated[Literal["all", "saas", "many"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, object]:
    if tenant_id is not None:
        _tenant(db, tenant_id)
    return audit_view.combined(db, settings, staff, tenant_id=tenant_id, source=source, limit=limit)
