"""Shadow user and membership sync for the SSO exchange (identity design 3, 5.4).

The SaaS `users` row is the identity; Many keeps a shadow row so its authz layer
(which works on an ORM User and workspace memberships) stays unchanged. Rows are
created from a SaaS-authenticated `sub` only, never looked up or linked by email.
"""
from __future__ import annotations

import secrets

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


def _shadow_email(db: Session, a: Assertion) -> str:
    """The assertion email if no Many row already uses it, else a placeholder.

    A collision never links to the existing row: that would be exactly the
    email-based account linking the design forbids at runtime.
    """
    if a.email and db.query(User.id).filter(User.email == a.email).first() is None:
        return a.email
    return f"{a.sub}@sso.invalid"


def sync_shadow_user(db: Session, a: Assertion) -> User:
    user = db.query(User).filter(User.sso_subject == a.sub).first()
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
        db.add(user)
        db.flush()
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
    """Make the user's SSO-owned memberships exactly the one this assertion names.

    Client scope: one membership in the mapped workspace. Staff scope: none
    (same as a global admin today). Rows with source != "sso" are never touched
    except the one the assertion explicitly targets.
    """
    target = None
    if a.scope == "client":
        workspace = db.query(Workspace).filter(Workspace.id == a.workspace).first()
        # Both sides must agree on the organization (confused-deputy guard, design 4.1).
        if workspace is None or workspace.saas_tenant_id is None or workspace.saas_tenant_id != a.org:
            raise SSOAssertionError("workspace_mapping_mismatch")
        target = workspace.id

    existing = db.query(UserWorkspaceMembership).filter(UserWorkspaceMembership.user_id == user.id).all()
    for membership in existing:
        if membership.source == SSO_SOURCE and membership.workspace_id != target:
            db.delete(membership)

    if target is not None:
        role = ORG_TO_WORKSPACE_ROLE[a.role]
        row = next((m for m in existing if m.workspace_id == target), None)
        if row is None:
            db.add(UserWorkspaceMembership(user_id=user.id, workspace_id=target, role=role, source=SSO_SOURCE))
        else:
            row.role = role
            row.source = SSO_SOURCE
    db.flush()
