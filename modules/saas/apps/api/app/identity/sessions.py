"""Session revocation used by team, grant and credential changes (design 6.5)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Session


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
