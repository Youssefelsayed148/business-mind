"""Client routes for the customer link (Phase 5B). Owner and Admin of the organization only.

A client sees the people Many and the SaaS know in this organization, across WhatsApp, Instagram
and Facebook (owner decision 2026-11-28). The data is the SaaS ``customer_links`` table, filled
by the staff sync: the browser never reaches Many's global routes. Whole-organization data, so a
location-limited access is refused. Every route answers 404 while the flag is off.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import cookies
from app.auth.security import hash_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.tenancy import TenantContext, TenantContextDep
from app.db.models import Contact, CustomerLink, ErasureCase
from app.linking import erasure, overview

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["customer-links"])

CurrentSettings = Annotated[Settings, Depends(get_settings)]
Platform = Literal["instagram", "facebook", "whatsapp"]
State = Literal["linked", "many_only", "saas_only", "conflict"]


def _flag(settings: CurrentSettings) -> None:
    if not settings.data_unification_enabled:
        raise StarletteHTTPException(status_code=404, detail="Not Found")


FlagOn = Annotated[None, Depends(_flag)]


def _allowed(context: TenantContext) -> None:
    context.require_role("admin")
    if context.location_ids is not None:
        raise ApiError(
            403,
            "LOCATION_SCOPE_UNSUPPORTED",
            "Location-limited access does not include cross-channel people.",
        )


def _item(link: CustomerLink, contact_name: str | None) -> dict[str, object]:
    return {
        "id": str(link.id),
        "platform": link.platform,
        "state": link.state,
        "display_name": link.display_name,
        "contact_id": str(link.contact_id) if link.contact_id else None,
        "contact_name": contact_name,
        "seen_at": link.lead_seen_at.isoformat() if link.lead_seen_at else None,
    }


@router.get("/customer-links")
def list_customer_links(
    context: TenantContextDep,
    _flag_on: FlagOn,
    platform: Annotated[Platform | None, Query()] = None,
    state: Annotated[State | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    _allowed(context)
    where = [CustomerLink.tenant_id == context.tenant_id, CustomerLink.state != "erased"]
    if platform:
        where.append(CustomerLink.platform == platform)
    if state:
        where.append(CustomerLink.state == state)
    if q:
        needle = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            CustomerLink.display_name.ilike(needle, escape="\\")
            | Contact.display_name.ilike(needle, escape="\\")
        )
    base = (
        select(CustomerLink, Contact.display_name)
        .outerjoin(
            Contact,
            (Contact.id == CustomerLink.contact_id) & (Contact.tenant_id == CustomerLink.tenant_id),
        )
        .where(*where)
    )
    total = context.db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = context.db.execute(
        base.order_by(CustomerLink.created_at.desc(), CustomerLink.id).limit(limit).offset(offset)
    ).all()
    return {"total": total, "items": [_item(link, name) for link, name in rows]}


@router.get("/contacts/{contact_id}/customer-links")
def contact_customer_links(
    contact_id: UUID, context: TenantContextDep, _flag_on: FlagOn
) -> dict[str, object]:
    _allowed(context)
    contact = context.db.execute(
        select(Contact).where(Contact.tenant_id == context.tenant_id, Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    rows = context.db.scalars(
        select(CustomerLink)
        .where(
            CustomerLink.tenant_id == context.tenant_id,
            CustomerLink.contact_id == contact.id,
            CustomerLink.state != "erased",
        )
        .order_by(CustomerLink.platform, CustomerLink.created_at)
    )
    return {"items": [_item(link, contact.display_name) for link in rows]}


# --- Phase 5C: one erasure request for one person --------------------------------------------

CsrfOk = Annotated[None, Depends(cookies.require_csrf)]


class EraseIn(BaseModel):
    request_id: UUID


def _case_out(case: ErasureCase) -> dict[str, object]:
    reason = case.reason
    return {
        "id": str(case.id),
        "platform": case.platform,
        "state": case.state,
        "reason": reason,
        "message": erasure.REASON_TEXT.get(reason or "", None),
        "created_at": case.created_at.isoformat(),
        "completed_at": case.completed_at.isoformat() if case.completed_at else None,
    }


def _session_hash(request: Request, settings: Settings) -> str | None:
    token = cookies.read_session_token(request, settings)
    return hash_token(token) if token else None


def _erase_allowed(context: TenantContext) -> None:
    context.require_permission("org.customer_erase")
    if context.location_ids is not None:
        raise ApiError(
            403,
            "LOCATION_SCOPE_UNSUPPORTED",
            "Location-limited access does not include erasing people.",
        )


@router.post("/customer-links/{link_id}/erase", status_code=202)
def erase_person(
    link_id: UUID,
    body: EraseIn,
    request: Request,
    context: TenantContextDep,
    settings: CurrentSettings,
    _flag_on: FlagOn,
    _csrf: CsrfOk,
) -> dict[str, object]:
    context.require_role("admin")
    _erase_allowed(context)
    link = context.db.scalar(
        select(CustomerLink).where(
            CustomerLink.tenant_id == context.tenant_id, CustomerLink.id == link_id
        )
    )
    if link is None:
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    case = erasure.start(
        context.db,
        settings,
        context.user,
        context.tenant,
        link,
        body.request_id,
        _session_hash(request, settings),
    )
    return _case_out(case)


@router.get("/erasure-cases")
def list_erasure_cases(
    context: TenantContextDep,
    _flag_on: FlagOn,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    context.require_role("admin")
    _erase_allowed(context)
    rows = context.db.scalars(
        select(ErasureCase)
        .where(ErasureCase.tenant_id == context.tenant_id)
        .order_by(ErasureCase.created_at.desc())
        .limit(limit)
    )
    return {"items": [_case_out(c) for c in rows]}


@router.post("/erasure-cases/{case_id}/retry", status_code=202)
def retry_erasure_case(
    case_id: UUID,
    request: Request,
    context: TenantContextDep,
    settings: CurrentSettings,
    _flag_on: FlagOn,
    _csrf: CsrfOk,
) -> dict[str, object]:
    context.require_role("admin")
    _erase_allowed(context)
    case = context.db.scalar(
        select(ErasureCase).where(
            ErasureCase.tenant_id == context.tenant_id, ErasureCase.id == case_id
        )
    )
    if case is None:
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    result = erasure.resume(
        context.db,
        settings,
        context.user,
        context.tenant,
        case,
        _session_hash(request, settings),
    )
    return _case_out(result)


@router.get("/customer-overview")
def customer_overview(
    context: TenantContextDep,
    _flag_on: FlagOn,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, object]:
    _allowed(context)
    return overview.overview(context.db, context.tenant_id, days)
