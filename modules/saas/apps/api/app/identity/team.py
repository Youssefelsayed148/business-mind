"""Client team management (design 6.1, 6.2, 10): invitations v2, role change, deactivate.

Rules enforced here, server side, on top of the route permission:
- no editing yourself, no editing a person above your authority;
- only an Owner (team.manage_admins) assigns Owner or Admin, or edits one;
- the last Owner cannot be demoted or removed, and the organization is never left
  without an Owner or Admin;
- a role change or deactivation revokes the target's sessions;
- invitations answer the same whether or not the address has an account.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import generate_session_token, hash_password, hash_token
from app.auth.service import AuthService
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ratelimit import enforce_or_429
from app.core.tenancy import TenantContext
from app.db.models import Invitation, Membership, User
from app.identity.mailer import MailMessage, get_mailer, link
from app.identity.roles import ORG_ROLES, ORG_TO_LEGACY_ROLE, org_role_of
from app.identity.sessions import revoke_user_sessions
from app.quotas.service import lock_tenant, require_capacity

PRIVILEGED_ROLES = frozenset({"owner", "admin"})
INVITE_MESSAGE = "If this address can be invited, an email was sent."
ACCOUNT_EXISTS = "An account already exists for this address. Log in to accept."


@dataclass(frozen=True)
class InviteResult:
    link_path: str | None


def _require_team_actor(ctx: TenantContext) -> None:
    ctx.require_permission("team.manage")
    if ctx.via_agency is not None:  # defense in depth: agency people never hold team.*
        raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")


def _require_assignable(ctx: TenantContext, role: str) -> None:
    if role not in ORG_ROLES:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown role: {role}.")
    if role in PRIVILEGED_ROLES and not ctx.has_permission("team.manage_admins"):
        raise ApiError(403, "OWNER_REQUIRED", "Only an Owner can assign the Owner or Admin role.")


def _require_may_edit(ctx: TenantContext, current_role: str) -> None:
    if current_role in PRIVILEGED_ROLES and not ctx.has_permission("team.manage_admins"):
        raise ApiError(403, "OWNER_REQUIRED", "Only an Owner can change an Owner or an Admin.")


def _active_memberships(db: OrmSession, tenant_id: UUID) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership).where(
                Membership.tenant_id == tenant_id, Membership.status == "active"
            )
        )
    )


def _guard_last_privileged(
    db: OrmSession, tenant_id: UUID, target: Membership, new_role: str | None
) -> None:
    """Refuse to remove or demote the last Owner, or the last Owner/Admin overall."""
    current = org_role_of(target.role, target.org_role)
    others = [m for m in _active_memberships(db, tenant_id) if m.user_id != target.user_id]
    roles = [org_role_of(m.role, m.org_role) for m in others]
    if current == "owner" and new_role != "owner" and "owner" not in roles:
        raise ApiError(403, "LAST_OWNER", "The last Owner cannot be demoted or removed.")
    if (
        current in PRIVILEGED_ROLES
        and new_role not in PRIVILEGED_ROLES
        and not any(r in PRIVILEGED_ROLES for r in roles)
    ):
        raise ApiError(403, "LAST_ADMIN", "The last admin cannot be demoted or removed.")


def _target(ctx: TenantContext, user_id: UUID) -> Membership:
    membership = ctx.db.scalar(
        select(Membership).where(
            Membership.tenant_id == ctx.tenant_id,
            Membership.user_id == user_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    return membership


def list_members(ctx: TenantContext) -> list[tuple[Membership, User]]:
    ctx.require_permission("team.read")
    rows = ctx.db.execute(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.tenant_id == ctx.tenant_id, Membership.status == "active")
        .order_by(Membership.created_at)
    ).all()
    return [(membership, user) for membership, user in rows]


def invite(
    ctx: TenantContext,
    settings: Settings,
    *,
    email: str,
    role: str,
    expiry_days: int,
) -> InviteResult:
    """Create a one-time invitation. The caller answers INVITE_MESSAGE in every case."""
    _require_team_actor(ctx)
    _require_assignable(ctx, role)
    db = ctx.db
    tenant = lock_tenant(db, ctx.tenant_id)
    require_capacity(db, tenant, "seats")  # tenant state only, never email dependent
    address = email.strip().lower()
    user = db.scalar(select(User).where(User.email == address))
    if user is not None:
        member = db.scalar(
            select(Membership.user_id).where(
                Membership.tenant_id == ctx.tenant_id,
                Membership.user_id == user.id,
                Membership.status == "active",
            )
        )
        if member is not None:
            return InviteResult(link_path=None)  # already a member: same answer, no mail
    # A new invitation supersedes older pending ones for this address (rotation).
    db.execute(
        update(Invitation)
        .where(
            Invitation.tenant_id == ctx.tenant_id,
            Invitation.email == address,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    token = generate_session_token()
    invitation = Invitation(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        email=address,
        role=ORG_TO_LEGACY_ROLE[role],
        org_role=role,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=expiry_days),
        created_by=ctx.user.id,
        new_account=user is None,
    )
    db.add(invitation)
    record_audit(
        db,
        action="team.invited",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        target_type="invitation",
        target_id=str(invitation.id),
        metadata={"role": role, "new_account": user is None},
    )
    db.commit()
    path = "/accept-invite"
    get_mailer(settings).send(
        MailMessage(
            kind="invitation",
            to=address,
            subject=f"You were invited to {tenant.name}",
            body=f"Open this link to join {tenant.name}: {link(settings, path, token)}",
        )
    )
    # Console backend only: the inviter delivers the link (no provider yet, D4).
    shown = f"{path}?token={token}" if settings.mailer_backend == "console" else None
    return InviteResult(link_path=shown)


def change_role(ctx: TenantContext, user_id: UUID, new_role: str) -> Membership:
    _require_team_actor(ctx)
    if user_id == ctx.user.id:
        raise ApiError(403, "SELF_EDIT", "You cannot change your own role.")
    lock_tenant(ctx.db, ctx.tenant_id)
    target = _target(ctx, user_id)
    current = org_role_of(target.role, target.org_role)
    _require_assignable(ctx, new_role)
    _require_may_edit(ctx, current)
    if new_role == current and target.org_role == new_role:
        return target
    _guard_last_privileged(ctx.db, ctx.tenant_id, target, new_role)
    target.org_role = new_role
    target.role = ORG_TO_LEGACY_ROLE[new_role]  # type: ignore[assignment]
    ctx.db.add(target)  # dual-write: the legacy column stays truthful
    record_audit(
        ctx.db,
        action="team.role_changed",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        target_type="membership",
        target_id=str(user_id),
        metadata={"from": current, "to": new_role},
    )
    revoke_user_sessions(ctx.db, user_id)
    ctx.db.commit()
    return target


def deactivate(ctx: TenantContext, user_id: UUID) -> None:
    """Organization-level deactivation: the membership is revoked, the account is untouched."""
    _require_team_actor(ctx)
    if user_id == ctx.user.id:
        raise ApiError(403, "SELF_EDIT", "You cannot deactivate yourself.")
    lock_tenant(ctx.db, ctx.tenant_id)
    target = _target(ctx, user_id)
    current = org_role_of(target.role, target.org_role)
    _require_may_edit(ctx, current)
    _guard_last_privileged(ctx.db, ctx.tenant_id, target, None)
    target.status = "revoked"
    ctx.db.add(target)
    member = ctx.db.get(User, user_id)
    assert member is not None  # the membership foreign key guarantees it
    # An older outstanding invitation must not restore the access just removed.
    ctx.db.execute(
        update(Invitation)
        .where(
            Invitation.tenant_id == ctx.tenant_id,
            Invitation.email == member.email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    record_audit(
        ctx.db,
        action="team.deactivated",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        target_type="membership",
        target_id=str(user_id),
        metadata={"was_role": current},
    )
    revoke_user_sessions(ctx.db, user_id)
    ctx.db.commit()


def accept_into_new_account(
    db: OrmSession, settings: Settings, *, token: str, password: str, client_ip: str
) -> tuple[User, str]:
    """The link, not an email claim, authorizes creating the account (design 6.1)."""
    enforce_or_429(
        db,
        key=f"invite-accept:{client_ip}",
        limit=10,
        window_seconds=900,
        message="Too many attempts. Try again later.",
    )
    db.commit()
    token_hash = hash_token(token.strip())
    tenant_id = db.scalar(select(Invitation.tenant_id).where(Invitation.token_hash == token_hash))
    if tenant_id is None:
        raise ApiError(404, "NOT_FOUND", "Invitation not found or no longer valid.")
    tenant = lock_tenant(db, tenant_id)
    invitation = db.execute(
        select(Invitation)
        .where(Invitation.tenant_id == tenant_id, Invitation.token_hash == token_hash)
        .with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if invitation is None:
        raise ApiError(404, "NOT_FOUND", "Invitation not found or no longer valid.")
    if invitation.accepted_at is not None:
        raise ApiError(409, "INVITATION_USED", "This invitation was already accepted.")
    if invitation.revoked_at is not None:
        raise ApiError(409, "INVITATION_REVOKED", "This invitation was revoked.")
    if invitation.expires_at <= now:
        raise ApiError(409, "INVITATION_EXPIRED", "This invitation has expired.")
    if db.scalar(select(User.id).where(User.email == invitation.email)) is not None:
        raise ApiError(409, "ACCOUNT_EXISTS", ACCOUNT_EXISTS)
    require_capacity(db, tenant, "seats", amount=0)  # the pending invitation holds the seat
    user = User(
        id=uuid4(),
        email=invitation.email,
        password_hash=hash_password(password),
        is_platform_staff=False,
    )
    try:
        with db.begin_nested():
            db.add(user)
    except IntegrityError:
        raise ApiError(409, "ACCOUNT_EXISTS", ACCOUNT_EXISTS) from None
    db.add(
        Membership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=invitation.role,
            org_role=invitation.org_role,
            status="active",
        )
    )
    invitation.accepted_at = now
    db.add(invitation)
    record_audit(
        db,
        action="team.accepted",
        tenant_id=tenant_id,
        actor_user_id=user.id,
        target_type="invitation",
        target_id=str(invitation.id),
        metadata={"role": invitation.org_role or invitation.role, "new_account": True},
    )
    _session, cookie_token = AuthService(db, settings).start_session(user)
    db.commit()
    return user, cookie_token
