"""Team, invitation v2 and agency-grant routes (identity v2; flag off answers 404)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session as OrmSession

from app.auth import cookies
from app.auth.schemas import MembershipOut, MeResponse
from app.auth.service import AuthService
from app.core.config import Settings, get_settings
from app.core.ratelimit import client_ip
from app.core.tenancy import CurrentUserDep, TenantContextDep
from app.db.models import AgencyGrant
from app.db.models import User as UserRow
from app.db.session import get_session
from app.identity import agency as agency_service
from app.identity import team as team_service
from app.identity.gate import IdentityV2On
from app.identity.roles import org_role_of
from app.identity.schemas import (
    AcceptNewAccountRequest,
    GrantAssigneeRequest,
    GrantCreateRequest,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberOut,
    TeamRoleChangeRequest,
)

router = APIRouter(tags=["identity"])

DbSession = Annotated[OrmSession, Depends(get_session)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
CsrfOk = Annotated[None, Depends(cookies.require_csrf)]
_T = "/api/v1/tenants/{tenant_id}"


def _member_out(membership: object, user: UserRow) -> TeamMemberOut:
    from app.db.models import Membership

    assert isinstance(membership, Membership)
    return TeamMemberOut(
        user_id=user.id,
        email=user.email,
        role=org_role_of(membership.role, membership.org_role),  # type: ignore[arg-type]
        status=membership.status,
        location_scope=membership.location_scope,
        joined_at=membership.created_at,
    )


@router.get(_T + "/team/members", response_model=list[TeamMemberOut])
def list_team(_on: IdentityV2On, context: TenantContextDep) -> list[TeamMemberOut]:
    return [_member_out(m, u) for m, u in team_service.list_members(context)]


@router.post(_T + "/team/invitations", response_model=TeamInviteResponse, status_code=202)
def team_invite(
    _on: IdentityV2On,
    body: TeamInviteRequest,
    context: TenantContextDep,
    settings: CurrentSettings,
    _csrf: CsrfOk,
) -> TeamInviteResponse:
    """Always the same answer, whether or not the address has an account."""
    result = team_service.invite(
        context, settings, email=body.email, role=body.role, expiry_days=body.expiry_days
    )
    return TeamInviteResponse(message=team_service.INVITE_MESSAGE, link_path=result.link_path)


@router.patch(_T + "/team/members/{user_id}", response_model=TeamMemberOut)
def team_change_role(
    _on: IdentityV2On,
    user_id: UUID,
    body: TeamRoleChangeRequest,
    context: TenantContextDep,
    _csrf: CsrfOk,
) -> TeamMemberOut:
    membership = team_service.change_role(context, user_id, body.role)
    member = context.db.get(UserRow, membership.user_id)
    assert member is not None
    return _member_out(membership, member)


@router.delete(_T + "/team/members/{user_id}", status_code=204)
def team_deactivate(
    _on: IdentityV2On, user_id: UUID, context: TenantContextDep, _csrf: CsrfOk
) -> Response:
    team_service.deactivate(context, user_id)
    return Response(status_code=204)


@router.get(_T + "/agency/grants")
def list_grants(_on: IdentityV2On, context: TenantContextDep) -> list[dict[str, object]]:
    return agency_service.list_grants(context)


@router.post(_T + "/agency/grants", status_code=201)
def create_grant(
    _on: IdentityV2On, body: GrantCreateRequest, context: TenantContextDep, _csrf: CsrfOk
) -> dict[str, object]:
    """Only the client's real Owner. No location restriction can be set yet (decision 2)."""
    grant = agency_service.create_grant(
        context, agency_id=body.agency_id, role_cap=body.role_cap, expires_at=body.expires_at
    )
    context.db.commit()
    return next(g for g in agency_service.list_grants(context) if g["id"] == str(grant.id))


@router.delete(_T + "/agency/grants/{grant_id}", status_code=204)
def revoke_grant(
    _on: IdentityV2On, grant_id: UUID, context: TenantContextDep, _csrf: CsrfOk
) -> Response:
    agency_service.revoke_grant(context, grant_id=grant_id)
    context.db.commit()
    return Response(status_code=204)


@router.post("/api/v1/agencies/grants/{grant_id}/assignees", status_code=204)
def assign_grantee(
    _on: IdentityV2On,
    grant_id: UUID,
    body: GrantAssigneeRequest,
    db: DbSession,
    user: CurrentUserDep,
    _csrf: CsrfOk,
) -> Response:
    """An admin of the grant's agency chooses which of its people use the grant."""
    agency_service.assign_grantee(db, actor=user, grant_id=grant_id, user_id=body.user_id)
    db.commit()
    return Response(status_code=204)


@router.post("/api/v1/invitations/accept-new", response_model=MeResponse)
def accept_new_account(
    _on: IdentityV2On,
    body: AcceptNewAccountRequest,
    response: Response,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
) -> MeResponse:
    """Public: the one-time token authorizes creating the account for the invited email."""
    user, token = team_service.accept_into_new_account(
        db, settings, token=body.token, password=body.password, client_ip=client_ip(request)
    )
    cookies.set_session_cookie(
        response, settings, token=token, max_age_seconds=settings.session_lifetime_seconds
    )
    cookies.ensure_csrf_cookie(request, response, settings)
    service = AuthService(db, settings)
    return MeResponse(
        id=user.id,
        email=user.email,
        is_platform_staff=user.is_platform_staff,
        memberships=[
            MembershipOut(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                role=membership.role,
            )
            for membership, tenant in service.memberships_of(user.id)
        ],
    )


__all__ = ["AgencyGrant", "router"]
