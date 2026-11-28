"""Mint the short-lived SSO assertion Many exchanges for its own token (design 2).

The SaaS holds the only private key. An assertion is a compact EdDSA JWT valid for
60 seconds. Everything it asserts is read from the SaaS database at mint time:
active session user, active membership or an active, assigned, unexpired agency
grant, the role, MFA state. Nothing here trusts a client claim.

Signed with ``cryptography`` directly (already a dependency); Many verifies with
PyJWT in ``backend/app/services/sso_assertion.py``.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ratelimit import rate_limit
from app.db.base import utcnow
from app.db.models import Membership, Session, Tenant, User
from app.identity.access import resolve_access
from app.identity.roles import ORG_ROLES

ALGORITHM = "EdDSA"
LIFETIME_SECONDS = 60  # Many refuses anything longer (design 2.2)
# Owner and Admin are the roles MFA enforcement applies to (design 6.4, D9).
MFA_ENFORCED_ROLES = frozenset({"owner", "admin"})
MFA_ADMIN_GRACE = timedelta(days=14)

Scope = Literal["client", "staff"]


@dataclass(frozen=True)
class Minted:
    token: str
    scope: Scope
    workspace_id: UUID | None
    expires_in: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def load_signing_key(settings: Settings) -> Ed25519PrivateKey:
    """The configured Ed25519 key; ValueError (never the key material) when unusable."""
    secret = settings.sso_signing_key_pem
    if secret is None or not settings.sso_signing_kid:
        raise ValueError("SSO_SIGNING_KEY_PEM and SSO_SIGNING_KID must both be set")
    # Env files carry PEM on one line with literal \n sequences.
    pem = secret.get_secret_value().replace("\\n", "\n").strip().encode("utf-8")
    try:
        key = load_pem_private_key(pem, password=None)
    except Exception as exc:
        raise ValueError("SSO_SIGNING_KEY_PEM is not a readable PEM private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("SSO_SIGNING_KEY_PEM must be an Ed25519 key")
    return key


def sign_assertion(settings: Settings, claims: dict[str, Any]) -> str:
    header = {"alg": ALGORITHM, "typ": "JWT", "kid": settings.sso_signing_kid}
    signing_input = f"{_b64(_json(header))}.{_b64(_json(claims))}"
    signature = load_signing_key(settings).sign(signing_input.encode("ascii"))
    return f"{signing_input}.{_b64(signature)}"


def mfa_required(
    settings: Settings,
    user: User,
    *,
    role: str | None,
    membership: Membership | None,
    now: datetime | None = None,
) -> bool:
    """Whether this caller must have MFA enrolled to be issued an assertion."""
    if user.is_platform_staff:
        return settings.mfa_enforce_staff
    if not settings.mfa_enforce_admins or role not in MFA_ENFORCED_ROLES:
        return False
    if membership is None:  # agency access never carries Owner/Admin of the client
        return False
    # Client Owners and Admins get a grace period counted from when they joined.
    return (now or utcnow()) >= membership.created_at + MFA_ADMIN_GRACE


def _session_id_prefix(db: OrmSession, token_hash: str) -> str | None:
    session_id = db.scalar(select(Session.id).where(Session.token_hash == token_hash))
    if session_id is None:
        return None
    return hashlib.sha256(str(session_id).encode("ascii")).hexdigest()[:16]


def mint_assertion(
    db: OrmSession,
    settings: Settings,
    user: User,
    *,
    scope: Scope,
    org_id: UUID | None,
    session_token_hash: str | None,
) -> Minted:
    count, _ = rate_limit(
        db,
        key=f"sso-mint:{user.id}",
        limit=settings.sso_mint_rate_limit_attempts,
        window_seconds=settings.sso_mint_rate_limit_window_seconds,
    )
    db.commit()
    if count > settings.sso_mint_rate_limit_attempts:
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Try again later.")

    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": settings.sso_issuer,
        "aud": settings.sso_audience,
        "sub": str(user.id),
        "jti": secrets.token_hex(16),
        "iat": now,
        "nbf": now,
        "exp": now + LIFETIME_SECONDS,
        "email": user.email.lower(),
        "scope": scope,
        "mfa": user.mfa_enrolled_at is not None,
    }
    if session_token_hash is not None:
        sid = _session_id_prefix(db, session_token_hash)
        if sid is not None:
            claims["sid"] = sid

    audit: dict[str, Any] = {"scope": scope}
    tenant_id: UUID | None = None
    workspace_id: UUID | None = None

    if scope == "staff":
        if not user.is_platform_staff:
            raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")
        if mfa_required(settings, user, role=None, membership=None) and not claims["mfa"]:
            raise ApiError(403, "MFA_ENROLLMENT_REQUIRED", "Enroll in MFA to continue.")
        if org_id is not None:
            # Staff may name one organization (Phase 4A, P2): the assertion then carries its
            # mapped workspace, and Many gives the staff user an admin membership there.
            tenant = db.get(Tenant, org_id)
            if tenant is None or tenant.status != "active" or tenant.many_workspace_id is None:
                raise ApiError(404, "NOT_FOUND", "Resource not found.")
            tenant_id = tenant.id
            workspace_id = tenant.many_workspace_id
            claims.update(org=str(tenant.id), workspace=str(workspace_id))
            audit.update(org=str(tenant.id))
    else:
        if org_id is None:
            raise ApiError(422, "VALIDATION_ERROR", "An organization is required.")
        tenant = db.get(Tenant, org_id)
        if tenant is None or tenant.status != "active" or tenant.many_workspace_id is None:
            raise ApiError(404, "NOT_FOUND", "Resource not found.")
        membership = db.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant.id,
                Membership.user_id == user.id,
                Membership.status == "active",
            )
        )
        access = resolve_access(db, user=user, tenant=tenant, membership=membership)
        # Staff without a real membership enter Many with the staff scope instead.
        if access is None or access.org_role not in ORG_ROLES:
            raise ApiError(404, "NOT_FOUND", "Resource not found.")
        if access.location_ids is not None:
            # Location-limited people get no Many access in this phase (design 4.2).
            raise ApiError(
                403,
                "LOCATION_SCOPE_UNSUPPORTED",
                "Location-limited access does not include the Many workspace.",
            )
        if (
            mfa_required(settings, user, role=access.org_role, membership=membership)
            and not claims["mfa"]
        ):
            raise ApiError(403, "MFA_ENROLLMENT_REQUIRED", "Enroll in MFA to continue.")
        tenant_id = tenant.id
        workspace_id = tenant.many_workspace_id
        claims.update(
            org=str(tenant.id),
            workspace=str(workspace_id),
            role=access.org_role,
            locations=None,
            via_agency=str(access.via_agency) if access.via_agency else None,
        )
        audit.update(
            org=str(tenant.id),
            role=access.org_role,
            via_agency=str(access.via_agency) if access.via_agency else None,
        )

    audit["mfa"] = claims["mfa"]
    record_audit(
        db,
        action="sso.assertion_minted",
        tenant_id=tenant_id,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata=audit,
    )
    db.commit()
    return Minted(
        token=sign_assertion(settings, claims),
        scope=scope,
        workspace_id=workspace_id,
        expires_in=LIFETIME_SECONDS,
    )
