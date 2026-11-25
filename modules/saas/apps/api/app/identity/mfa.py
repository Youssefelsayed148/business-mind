"""TOTP multi-factor authentication (design 6.4): RFC 6238, encrypted secret, recovery codes.

SHA-1, 30 s step, 6 digits, one step of drift either side. The secret is stored
encrypted (Fernet keys from MFA_SECRET_ENCRYPTION_KEYS, the same pattern as channel
secrets). A code can be used once: the matched time step is remembered and an equal or
older step is refused. Recovery codes are 64-bit random values stored as SHA-256
hashes and single use. Verification attempts are limited per user.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.channels.secrets import decrypt_secret, encrypt_secret
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ratelimit import rate_limit
from app.db.base import utcnow
from app.db.models import Membership, User
from app.db.models.identity import UserMfa, UserRecoveryCode

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
ISSUER = "Business Mind"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def totp(secret_b32: str, at: float) -> str:
    return _hotp(secret_b32, int(at // STEP_SECONDS))


def match_totp(secret_b32: str, code: str, *, at: float, last_used_step: int | None) -> int | None:
    """The matched time step, or None. A step at or before the last used one never matches."""
    candidate = code.strip().replace(" ", "")
    if len(candidate) != DIGITS or not candidate.isdigit():
        return None
    current = int(at // STEP_SECONDS)
    matched: int | None = None
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        # Compare every step (no early exit) so timing does not reveal which one matched.
        if hmac.compare_digest(_hotp(secret_b32, step), candidate) and matched is None:
            matched = step
    if matched is None or (last_used_step is not None and matched <= last_used_step):
        return None
    return matched


def otpauth_uri(email: str, secret_b32: str) -> str:
    label = quote(f"{ISSUER}:{email}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _normalize_recovery(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def _recovery_hash(code: str) -> str:
    return hashlib.sha256(_normalize_recovery(code).encode("ascii", "ignore")).hexdigest()


def _new_recovery_codes() -> list[str]:
    return ["-".join(secrets.token_hex(2) for _ in range(4)) for _ in range(RECOVERY_CODE_COUNT)]


def _require_available(settings: Settings) -> None:
    if settings.mfa_secret_encryption_keys is None:
        raise ApiError(503, "MFA_UNAVAILABLE", "Multi-factor authentication is not configured.")


def throttle_verification(db: OrmSession, settings: Settings, user_id: UUID) -> None:
    """5 attempts per 5 minutes per user; the counter is committed so failures count."""
    count, _ = rate_limit(
        db,
        key=f"mfa-verify:{user_id}",
        limit=settings.mfa_verify_attempts,
        window_seconds=settings.mfa_verify_window_seconds,
    )
    db.commit()
    if count > settings.mfa_verify_attempts:
        raise ApiError(429, "RATE_LIMITED", "Too many attempts. Try again later.")


def begin_enrollment(db: OrmSession, settings: Settings, user: User) -> tuple[str, str]:
    _require_available(settings)
    row = db.get(UserMfa, user.id)
    if row is not None and row.confirmed_at is not None:
        raise ApiError(409, "MFA_ALREADY_ENROLLED", "Multi-factor authentication is already on.")
    secret = new_secret()
    ciphertext = encrypt_secret(secret, settings.mfa_secret_encryption_keys)
    if row is None:
        db.add(UserMfa(user_id=user.id, secret_ciphertext=ciphertext))
    else:  # an unconfirmed attempt is replaced
        row.secret_ciphertext = ciphertext
        row.last_used_step = None
    db.commit()
    return secret, otpauth_uri(user.email, secret)


def confirm_enrollment(db: OrmSession, settings: Settings, user: User, code: str) -> list[str]:
    _require_available(settings)
    throttle_verification(db, settings, user.id)
    row = db.get(UserMfa, user.id)
    if row is None or row.confirmed_at is not None:
        raise ApiError(409, "MFA_NOT_PENDING", "There is no enrollment waiting for a code.")
    secret = decrypt_secret(row.secret_ciphertext, settings.mfa_secret_encryption_keys)
    step = match_totp(secret, code, at=time.time(), last_used_step=None)
    if step is None:
        record_audit(
            db,
            action="auth.mfa_failed",
            tenant_id=None,
            actor_user_id=user.id,
            target_type="user",
            target_id=str(user.id),
            metadata={"stage": "enrollment"},
        )
        db.commit()
        raise ApiError(400, "INVALID_MFA_CODE", "The code is not correct.")
    row.confirmed_at = utcnow()
    row.last_used_step = step
    user.mfa_enrolled_at = row.confirmed_at
    db.add(user)
    codes = _new_recovery_codes()
    for existing in db.scalars(select(UserRecoveryCode).where(UserRecoveryCode.user_id == user.id)):
        db.delete(existing)
    db.flush()
    for value in codes:
        db.add(UserRecoveryCode(user_id=user.id, code_hash=_recovery_hash(value)))
    record_audit(
        db,
        action="auth.mfa_enrolled",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
    )
    db.commit()
    return codes


def verify_second_factor(db: OrmSession, settings: Settings, user: User, code: str) -> bool:
    """A valid TOTP code, or an unused recovery code (which is then spent)."""
    throttle_verification(db, settings, user.id)
    row = db.get(UserMfa, user.id)
    if row is None or row.confirmed_at is None:
        return False
    if settings.mfa_secret_encryption_keys is not None:
        secret = decrypt_secret(row.secret_ciphertext, settings.mfa_secret_encryption_keys)
        step = match_totp(secret, code, at=time.time(), last_used_step=row.last_used_step)
        if step is not None:
            row.last_used_step = step
            db.commit()
            return True
    recovery = db.scalar(
        select(UserRecoveryCode).where(
            UserRecoveryCode.user_id == user.id,
            UserRecoveryCode.code_hash == _recovery_hash(code),
            UserRecoveryCode.used_at.is_(None),
        )
    )
    if recovery is None:
        return False
    recovery.used_at = utcnow()
    record_audit(
        db,
        action="auth.mfa_recovery_used",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
    )
    db.commit()
    return True


def status(db: OrmSession, settings: Settings, user: User) -> dict[str, object]:
    row = db.get(UserMfa, user.id)
    remaining = len(
        list(
            db.scalars(
                select(UserRecoveryCode.id).where(
                    UserRecoveryCode.user_id == user.id, UserRecoveryCode.used_at.is_(None)
                )
            )
        )
    )
    from app.identity.sso import mfa_required

    memberships = list(
        db.scalars(
            select(Membership).where(Membership.user_id == user.id, Membership.status == "active")
        )
    )
    from app.identity.roles import org_role_of

    required = any(
        mfa_required(settings, user, role=org_role_of(m.role, m.org_role), membership=m)
        for m in memberships
    ) or (user.is_platform_staff and settings.mfa_enforce_staff)
    return {
        "enrolled": user.mfa_enrolled_at is not None,
        "pending": row is not None and row.confirmed_at is None,
        "recovery_codes_remaining": remaining if user.mfa_enrolled_at is not None else 0,
        "required": required,
        "available": settings.mfa_secret_encryption_keys is not None,
    }


def reset(db: OrmSession, *, actor: User, tenant_id: UUID, target: User, was_role: str) -> None:
    """Remove a person's MFA (the caller has checked authority). Audited, sessions revoked."""
    from app.identity.sessions import revoke_user_sessions

    row = db.get(UserMfa, target.id)
    if row is not None:
        db.delete(row)
    for code in db.scalars(select(UserRecoveryCode).where(UserRecoveryCode.user_id == target.id)):
        db.delete(code)
    target.mfa_enrolled_at = None
    db.add(target)
    record_audit(
        db,
        action="auth.mfa_reset",
        tenant_id=tenant_id,
        actor_user_id=actor.id,
        target_type="user",
        target_id=str(target.id),
        metadata={"target_role": was_role},
    )
    revoke_user_sessions(db, target.id)
