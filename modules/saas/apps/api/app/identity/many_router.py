"""POST/GET/PATCH/DELETE /api/v1/many/...: the browser's only way to the Many API (Phase 4A, P1).

Two families, both off (404, like an unknown route) unless MANY_PROXY_ENABLED, IDENTITY_V2_ENABLED
and SSO_ISSUER_ENABLED are on:
  /api/v1/many/orgs/{tenant_id}/{path}   workspace-scoped Many routes for one organization
  /api/v1/many/staff/{path}              global Many routes, platform staff only

Authorization happens here, from the SaaS database, on every request: session, CSRF for writes,
membership or agency grant, location scope, and the permission the allowlist names. Only then
is one allowlisted call forwarded with a server-minted Many token.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import cookies
from app.auth.security import hash_token
from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.models import Membership, Tenant, User
from app.db.session import get_session
from app.identity import many_proxy, many_routes
from app.identity.access import resolve_access

router = APIRouter(prefix="/api/v1/many", tags=["many"])

DbSession = Annotated[OrmSession, Depends(get_session)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[User, Depends(cookies.get_current_user)]
METHODS = ["GET", "POST", "PATCH", "DELETE"]
MAX_QUERY_CHARS = 2000


def _proxy_enabled(settings: CurrentSettings) -> None:
    """Answer exactly like an unknown route while the proxy (or what it needs) is off."""
    if not (
        settings.many_proxy_enabled and settings.identity_v2_enabled and settings.sso_issuer_enabled
    ):
        raise StarletteHTTPException(status_code=404, detail="Not Found")


ProxyOn = Annotated[None, Depends(_proxy_enabled)]


def _csrf_if_write(request: Request, settings: CurrentSettings) -> None:
    if request.method != "GET":
        cookies.require_csrf(request, settings)


CsrfIfWrite = Annotated[None, Depends(_csrf_if_write)]


def _not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Resource not found.")


def _query(request: Request) -> str:
    raw = request.url.query
    if len(raw) > MAX_QUERY_CHARS or any(ord(c) < 33 or ord(c) > 126 for c in raw.replace(" ", "")):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid query string.")
    return raw


async def _body(request: Request, limit: int) -> bytes | None:
    if request.method not in {"POST", "PATCH", "DELETE"}:
        return None
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
    return bytes(received) or None


def _session_hash(request: Request, settings: Settings) -> str | None:
    token = cookies.read_session_token(request, settings)
    return hash_token(token) if token else None


def _respond(result: many_proxy.ManyResponse) -> Response:
    headers = {**result.headers, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    return Response(content=result.body, status_code=result.status, headers=headers)


def _call_many(
    *,
    db: OrmSession,
    settings: Settings,
    request: Request,
    user: User,
    org_id: UUID | None,
    staff: bool,
    fingerprint: str,
    workspace_id: UUID | None,
    path: str,
    query: str,
    body: bytes | None,
) -> many_proxy.ManyResponse:
    session_hash = _session_hash(request, settings)
    headers = dict(request.headers)
    for attempt in (1, 2):
        try:
            token = many_proxy.many_token(
                db,
                settings,
                user,
                org_id=org_id,
                staff=staff,
                fingerprint=fingerprint,
                session_token_hash=session_hash,
            )
            result = many_proxy.forward(
                settings,
                token=token,
                workspace_id=workspace_id,
                method=request.method,
                path=path,
                query=query,
                request_headers=headers,
                body=body,
            )
        except many_proxy.ManyUnavailable as exc:
            raise many_proxy.unavailable() from exc
        if result.status == 401 and attempt == 1:
            many_proxy.clear_token_cache()  # a token Many no longer accepts: exchange once more
            continue
        if result.status == 401:
            raise many_proxy.unavailable()
        return result
    raise many_proxy.unavailable()  # pragma: no cover


def _org_call(
    *,
    db: OrmSession,
    settings: Settings,
    request: Request,
    user: User,
    tenant_id: UUID,
    path: str,
    query: str,
    body: bytes | None,
) -> Response:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise _not_found()
    membership = db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant.id,
            Membership.user_id == user.id,
            Membership.status == "active",
        )
    )
    access = resolve_access(db, user=user, tenant=tenant, membership=membership)
    route = many_routes.match(request.method, path, many_routes.ORG)
    if access is None or route is None or tenant.many_workspace_id is None:
        raise _not_found()
    staff = user.is_platform_staff
    if route.staff_only and not staff:
        raise _not_found()
    if not staff:
        if access.location_ids is not None:
            raise ApiError(
                403,
                "LOCATION_SCOPE_UNSUPPORTED",
                "Location-limited access does not include the Many workspace.",
            )
        if route.permission is None or route.permission not in access.permissions:
            raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")
    result = _call_many(
        db=db,
        settings=settings,
        request=request,
        user=user,
        org_id=tenant.id,
        staff=staff,
        fingerprint="staff" if staff else f"{access.org_role}:{access.via_agency}",
        workspace_id=tenant.many_workspace_id,
        path=path,
        query=query,
        body=body,
    )
    if request.method != "GET":
        record_audit(
            db,
            action="many.proxy_write",
            tenant_id=tenant.id,
            actor_user_id=user.id,
            target_type="many_route",
            target_id=route.template,
            metadata={
                "method": request.method,
                "status": result.status,
                "via_agency": str(access.via_agency) if access.via_agency else None,
            },
        )
        db.commit()
    return _respond(result)


def _staff_call(
    *,
    db: OrmSession,
    settings: Settings,
    request: Request,
    user: User,
    path: str,
    query: str,
    body: bytes | None,
) -> Response:
    if not user.is_platform_staff:
        raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")
    route = many_routes.match(request.method, path, many_routes.GLOBAL)
    if route is None:
        raise _not_found()
    result = _call_many(
        db=db,
        settings=settings,
        request=request,
        user=user,
        org_id=None,
        staff=True,
        fingerprint="staff",
        workspace_id=None,
        path=path,
        query=query,
        body=body,
    )
    if request.method != "GET":
        record_audit(
            db,
            action="many.proxy_write",
            tenant_id=None,
            actor_user_id=user.id,
            target_type="many_route",
            target_id=route.template,
            metadata={"method": request.method, "status": result.status, "scope": "global"},
        )
        db.commit()
    return _respond(result)


@router.api_route("/orgs/{tenant_id}/{many_path:path}", methods=METHODS, include_in_schema=False)
async def proxy_org(
    tenant_id: UUID,
    many_path: str,
    _on: ProxyOn,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfIfWrite,
) -> Response:
    query = _query(request)
    body = await _body(request, settings.many_proxy_max_body_bytes)
    return await run_in_threadpool(
        _org_call,
        db=db,
        settings=settings,
        request=request,
        user=user,
        tenant_id=tenant_id,
        path=many_path,
        query=query,
        body=body,
    )


@router.api_route("/staff/{many_path:path}", methods=METHODS, include_in_schema=False)
async def proxy_staff(
    many_path: str,
    _on: ProxyOn,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfIfWrite,
) -> Response:
    query = _query(request)
    body = await _body(request, settings.many_proxy_max_body_bytes)
    return await run_in_threadpool(
        _staff_call,
        db=db,
        settings=settings,
        request=request,
        user=user,
        path=many_path,
        query=query,
        body=body,
    )
