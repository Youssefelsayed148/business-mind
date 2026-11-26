"""Shadow user and membership sync for the SSO exchange (identity design 3, 5.4).

The SaaS `users` row is the identity; Many keeps a shadow row so its authz layer
(which works on an ORM User and workspace memberships) stays unchanged. Rows are
created from a SaaS-authenticated `sub` only, never looked up or linked by email.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from app.roles import ROLE_ADMIN, ROLE_VIEWER
from app.services.sso_assertion import Assertion, SSOAssertionError

# Organization role -> Many workspace role (design 5.4).
ORG_TO_WORKSPACE_ROLE = {
    "owner": "owner",
    "admin": "admin",
    "manager": "operator",
    "agent": "viewer",
    "viewer": "viewer",
}
SSO_SOURCE = "sso"
# An SSO membership stays usable this long after its last exchange, then the next exchange for
# the same user removes it. Longer than the Many token (10 minutes) plus clock skew, so a person
# working in two organizations does not lose one when the other is opened (Phase 4A, gap 3),
# and an organization they lost access to is gone from Many within the same window as before.
MEMBERSHIP_GRACE = timedelta(minutes=15)


def _shadow_email(db: Session, a: Assertion) -> str:
    """The assertion email if no Many row already uses it, else a placeholder.

    A collision never links to the existing row: that would be exactly the
    email-based account linking the design forbids at runtime.
    """
    if a.email and db.query(User.id).filter(User.email == a.email).first() is None:
        return a.email
    return f"{a.sub}@sso.invalid"


def _find_by_subject(db: Session, sub) -> User | None:
    return db.query(User).filter(User.sso_subject == sub).first()


def sync_shadow_user(db: Session, a: Assertion) -> User:
    user = _find_by_subject(db, a.sub)
    if user is None:
        user = User(
            email=_shadow_email(db, a),
            name=None,
            # A real hash of a random secret nobody sees: verify_password() works
            # (and fails) instead of raising on an unparseable value, so a shadow
            # row can never log in through /auth/login.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=ROLE_ADMIN if a.scope == "staff" else ROLE_VIEWER,
            is_active=True,
            sso_subject=a.sub,
            auth_source=SSO_SOURCE,
        )
        # Savepoint: two first exchanges for the same sub (or the same email) can
        # race. The loser must not 500 or poison the request's transaction.
        try:
            with db.begin_nested():
                db.add(user)
        except IntegrityError:
            user = _find_by_subject(db, a.sub)
            if user is None:
                raise SSOAssertionError("user_conflict")
            if not user.is_active:
                raise SSOAssertionError("user_inactive")
    elif not user.is_active:
        raise SSOAssertionError("user_inactive")
    elif user.auth_source == SSO_SOURCE:
        # Global role follows the scope: client sessions never carry a global
        # admin role (keeps global-permission routes closed even if the
        # client-scope guard were bypassed); staff mirror today's global admin.
        user.role = ROLE_ADMIN if a.scope == "staff" else ROLE_VIEWER

    sync_memberships(db, user, a)
    return user


def sync_memberships(db: Session, user: User, a: Assertion) -> None:
    """Keep the user's SSO-owned memberships to the ones used recently, plus the one named now.

    A client assertion names its workspace with the role mapped from the organization role; a
    staff assertion may name one (Phase 4A) and gets the admin role there. A staff assertion with
    no workspace names none (same as a global admin today). Memberships from earlier exchanges
    stay for MEMBERSHIP_GRACE and are removed by the first exchange after that. Rows with
    source != "sso" are never touched except the one the assertion explicitly targets.
    """
    target = None
    role = None
    if a.workspace is not None:
        workspace = db.query(Workspace).filter(Workspace.id == a.workspace).first()
        # Both sides must agree on the organization (confused-deputy guard, design 4.1).
        if workspace is None or workspace.saas_tenant_id is None or workspace.saas_tenant_id != a.org:
            raise SSOAssertionError("workspace_mapping_mismatch")
        target = workspace.id
        role = ORG_TO_WORKSPACE_ROLE[a.role] if a.scope == "client" else ROLE_ADMIN

    existing = db.query(UserWorkspaceMembership).filter(UserWorkspaceMembership.user_id == user.id).all()
    cutoff = datetime.now(timezone.utc) - MEMBERSHIP_GRACE
    for membership in existing:
        if membership.source == SSO_SOURCE and membership.workspace_id != target and membership.updated_at < cutoff:
            db.delete(membership)

    if target is not None:
        row = next((m for m in existing if m.workspace_id == target), None)
        if row is None:
            db.add(UserWorkspaceMembership(user_id=user.id, workspace_id=target, role=role, source=SSO_SOURCE))
        else:
            row.role = role
            row.source = SSO_SOURCE
            row.updated_at = datetime.now(timezone.utc)
    db.flush()
