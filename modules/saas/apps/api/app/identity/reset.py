"""Self-service password reset (design 6.3, 6.7): generic answers, hashed single-use token.

The request answers the same for known, unknown and inactive addresses. The token is
random (256 bit), only its SHA-256 is stored, it lasts 30 minutes and works once. The
link is built from PUBLIC_BASE_URL, never from a Host header. Using it sets the
password, revokes every session of the user and writes an audit event.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import generate_session_token, hash_password, hash_token
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ratelimit import enforce_or_429, rate_limit
from app.db.base import utcnow
from app.db.models import User
from app.db.models.identity import PasswordResetToken
from app.identity.login import ip_digest
from app.identity.mailer import MailMessage, get_mailer, link
from app.identity.sessions import revoke_user_sessions

REQUEST_MESSAGE = "If an account exists for this address, an email was sent."
RESET_PATH = "/reset-password"


def request_reset(db: OrmSession, settings: Settings, *, email: str, ip: str) -> None:
    """Never raises for an unknown or inactive address; only the per-IP limit can refuse."""
    enforce_or_429(
        db,
        key=f"reset-request-ip:{ip_digest(ip)}",
        limit=settings.reset_ip_attempts,
        window_seconds=settings.reset_window_seconds,
        message="Too many attempts. Try again later.",
    )
    address = email.strip()
    per_email, _ = rate_limit(
        db,
        key=f"reset-request-email:{address.lower()}",
        limit=settings.reset_email_attempts,
        window_seconds=3600,
    )
    db.commit()
    if per_email > settings.reset_email_attempts:
        return  # same answer; the mailbox is not flooded
    user = db.scalar(select(User).where(User.email == address))
    if user is None or not user.is_active:
        return
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    token = generate_session_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(seconds=settings.password_reset_ttl_seconds),
        )
    )
    record_audit(
        db,
        action="auth.password_reset_requested",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata={"ip": ip_digest(ip)},
    )
    db.commit()
    get_mailer(settings).send(
        MailMessage(
            kind="password_reset",
            to=user.email,
            subject="Reset your password",
            body=f"Open this link to choose a new password: {link(settings, RESET_PATH, token)}",
        )
    )


def confirm_reset(
    db: OrmSession, settings: Settings, *, token: str, new_password: str, ip: str
) -> None:
    enforce_or_429(
        db,
        key=f"reset-confirm-ip:{ip_digest(ip)}",
        limit=settings.reset_ip_attempts,
        window_seconds=settings.reset_window_seconds,
        message="Too many attempts. Try again later.",
    )
    db.commit()
    invalid = ApiError(400, "INVALID_RESET_TOKEN", "This reset link is invalid or has expired.")
    row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(token.strip()))
        .with_for_update()
    )
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise invalid
    user = db.scalar(select(User).where(User.id == row.user_id).with_for_update())
    if user is None or not user.is_active:
        raise invalid
    user.password_hash = hash_password(new_password)
    db.add(user)
    row.used_at = now
    revoke_user_sessions(db, user.id)
    record_audit(
        db,
        action="auth.password_reset_completed",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata={"ip": ip_digest(ip)},
    )
    db.commit()
