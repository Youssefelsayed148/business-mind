"""Session revocation used by team, grant and credential changes (design 6.5)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import hash_token
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import Session, User


def revoke_user_sessions(
    db: OrmSession, user_id: UUID | list[UUID], *, except_token_hash: str | None = None
) -> int:
    """Revoke every live session of the user(s), optionally keeping the presented one."""
    ids = user_id if isinstance(user_id, list) else [user_id]
    if not ids:
        return 0
    statement = update(Session).where(Session.user_id.in_(ids), Session.revoked_at.is_(None))
    if except_token_hash is not None:
        statement = statement.where(Session.token_hash != except_token_hash)
    result = db.execute(statement.values(revoked_at=datetime.now(UTC)))
    return int(getattr(result, "rowcount", 0) or 0)


TOUCH_INTERVAL = timedelta(minutes=1)


def session_owner(db: OrmSession, token: str) -> UUID | None:
    """The user a live session token belongs to (None for unknown or revoked ones)."""
    return db.scalar(
        select(Session.user_id).where(
            Session.token_hash == hash_token(token), Session.revoked_at.is_(None)
        )
    )


def enforce_session_policy(
    db: OrmSession, settings: Settings, row: Session, user: User, now: datetime
) -> None:
    """Idle timeout for everyone, absolute lifetime for staff (design 6.5, D9).

    Clients: idle 12 h (the existing absolute 14 days stays in the session expiry).
    Staff: idle 30 min, absolute 12 h. ``last_seen_at`` is refreshed at most once a minute.
    Sessions that have no ``last_seen_at`` yet count from their creation time.
    """
    staff = user.is_platform_staff
    idle = settings.staff_session_idle_seconds if staff else settings.client_session_idle_seconds
    last_seen = row.last_seen_at or row.created_at
    expired = (now - last_seen).total_seconds() > idle
    if staff and (now - row.created_at).total_seconds() > settings.staff_session_absolute_seconds:
        expired = True
    if expired:
        row.revoked_at = now
        db.commit()
        raise ApiError(401, "SESSION_INVALID", "Session is invalid, expired or revoked.")
    if now - last_seen >= TOUCH_INTERVAL:
        row.last_seen_at = now
        db.commit()
