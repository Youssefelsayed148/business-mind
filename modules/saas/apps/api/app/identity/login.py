"""Login with the identity-v2 hardening (design 6.6, 6.7); used only while the flag is on.

- Buckets are counted before any lookup, so an unknown address behaves exactly like a
  known one: 5 attempts per 15 minutes per (email, IP) is a hard stop; 20 per hour
  per email only slows (no hard lock, so an attacker cannot lock a victim out).
- An unknown address (or one with an unreadable hash) still runs a full Argon2
  verification, so response time does not reveal whether the account exists.
- A second factor is asked for only after the password was right.
"""

import hashlib
import time
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import hash_password, verify_password
from app.auth.service import AuthService
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ratelimit import rate_limit
from app.db.base import utcnow
from app.db.models import User
from app.identity import mfa as mfa_service

MAX_SLOWDOWN_SECONDS = 2.0
USER_AGENT_LIMIT = 200


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("not-a-real-password-used-only-for-timing")


def ip_digest(ip: str) -> str:
    """A short one-way digest for audit and session metadata (never the address itself)."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _invalid() -> ApiError:
    return ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")


def _failed(db: OrmSession, user: User | None, ip: str, reason: str) -> None:
    record_audit(
        db,
        action="auth.login_failed",
        tenant_id=None,
        actor_user_id=user.id if user is not None else None,
        target_type="user" if user is not None else None,
        target_id=str(user.id) if user is not None else None,
        metadata={"reason": reason, "ip": ip_digest(ip)},
    )
    db.commit()


def login(
    db: OrmSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    mfa_code: str | None,
    rotate_token: str | None,
    ip: str,
    user_agent: str | None,
) -> tuple[User, str]:
    address = email.strip()
    key = address.lower()
    digest = ip_digest(ip)
    per_pair, _ = rate_limit(
        db,
        key=f"login-email-ip:{key}:{digest}",
        limit=settings.login_email_ip_attempts,
        window_seconds=settings.login_email_ip_window_seconds,
    )
    per_email, _ = rate_limit(
        db,
        key=f"login-email:{key}",
        limit=settings.login_email_attempts,
        window_seconds=settings.login_email_window_seconds,
    )
    db.commit()
    if per_pair > settings.login_email_ip_attempts:
        raise ApiError(429, "RATE_LIMITED", "Too many login attempts. Try again later.")
    if per_email > settings.login_email_attempts:
        over = per_email - settings.login_email_attempts
        time.sleep(min(MAX_SLOWDOWN_SECONDS, 0.25 * over))

    service = AuthService(db, settings)
    user = db.scalar(select(User).where(User.email == address).with_for_update())
    if user is None:
        verify_password(password, _dummy_hash())  # same cost as a real check
        _failed(db, None, ip, "credentials")
        raise _invalid()
    if not verify_password(password, user.password_hash):
        _failed(db, user, ip, "credentials")
        raise _invalid()
    try:
        service.require_login_eligible(user)
    except ApiError:
        _failed(db, user, ip, "ineligible")
        raise
    if user.mfa_enrolled_at is not None:
        if not mfa_code:
            raise ApiError(401, "MFA_REQUIRED", "A verification code is required.")
        if not mfa_service.verify_second_factor(db, settings, user, mfa_code):
            _failed(db, user, ip, "mfa")
            raise ApiError(401, "INVALID_MFA_CODE", "The verification code is not correct.")
    row, token = service.start_session(user)
    row.last_seen_at = utcnow()
    row.ip_hash = digest
    row.user_agent = (user_agent or "")[:USER_AGENT_LIMIT] or None
    if rotate_token:
        service.revoke_token(rotate_token)
    user.last_login_at = utcnow()
    db.add(user)
    record_audit(
        db,
        action="auth.login_success",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata={"ip": digest, "mfa": user.mfa_enrolled_at is not None},
    )
    db.commit()
    return user, token
