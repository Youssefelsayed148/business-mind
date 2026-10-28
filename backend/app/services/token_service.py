import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.token_refresh import refresh_long_lived_token
from app.models.meta_token import MetaToken
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


def store_encrypted_token(
    db: Session,
    workspace_id,
    instagram_account_id,
    access_token: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> MetaToken:
    encrypted = encrypt_text(access_token)
    token = MetaToken(
        instagram_account_id=instagram_account_id,
        access_token=encrypted,
        token_type="long_lived",
        status="active",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    if expires_at is not None and hasattr(token, "expires_at"):
        token.expires_at = expires_at
        db.commit()
    logger.info("Stored encrypted token", extra={"token_id": str(token.id)})
    return token


def get_decrypted_token(db: Session, instagram_account_id) -> str | None:
    token = (
        db.query(MetaToken)
        .filter(
            MetaToken.instagram_account_id == instagram_account_id,
            MetaToken.status == "active",
        )
        .order_by(MetaToken.created_at.desc())
        .first()
    )
    if not token:
        return None
    return decrypt_text(token.access_token)


def mark_token_expiring_soon(db: Session, token_id) -> None:
    token = db.query(MetaToken).filter(MetaToken.id == token_id).first()
    if token:
        token.status = "expiring_soon"
        db.commit()
        logger.info("Marked token expiring soon", extra={"token_id": str(token_id)})


def mark_token_expired(db: Session, token_id) -> None:
    token = db.query(MetaToken).filter(MetaToken.id == token_id).first()
    if token:
        token.status = "expired"
        db.commit()
        logger.info("Marked token expired", extra={"token_id": str(token_id)})


def get_tokens_expiring_within(db: Session, days: int) -> list[MetaToken]:
    """Active tokens whose expires_at falls within `days` (or already passed).

    Tokens with no expires_at are skipped: there is nothing to compare against.
    """
    cutoff = datetime.now(timezone.utc) + timedelta(days=days)
    return (
        db.query(MetaToken)
        .filter(
            MetaToken.status == "active",
            MetaToken.expires_at.isnot(None),
            MetaToken.expires_at <= cutoff,
        )
        .order_by(MetaToken.expires_at.asc())
        .all()
    )


def _as_utc(value: datetime) -> datetime:
    # expires_at is written as naive UTC by the OAuth callback.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def refresh_token(db: Session, token: MetaToken, now: datetime | None = None) -> str:
    """Refresh one Instagram token in place and return the outcome.

    "refreshed", "too_young" (under 24 h old, retried on a later run), "expired"
    (past expires_at, can no longer be refreshed) or "failed".

    A failed refresh on a still-valid token leaves status "active": the send
    paths only read tokens with status "active", so flipping it early would stop
    a working account. The failure shows in the logs and in the dwindling
    expires_at. Never logs the token.
    """
    now = now or datetime.now(timezone.utc)
    if token.expires_at is not None and _as_utc(token.expires_at) <= now:
        mark_token_expired(db, token.id)
        return "expired"
    issued_at = token.updated_at or token.created_at
    if issued_at is not None and now - _as_utc(issued_at) < timedelta(hours=24):
        return "too_young"
    try:
        data = refresh_long_lived_token(decrypt_text(token.access_token))
    except MetaAPIError as exc:
        logger.warning(
            "Instagram token refresh failed",
            extra={"token_id": str(token.id), "status_code": exc.status_code},
        )
        return "failed"
    token.access_token = encrypt_text(data["access_token"])
    token.expires_at = now + timedelta(seconds=int(data.get("expires_in", 5184000)))
    token.status = "active"
    db.commit()
    logger.info("Refreshed Instagram token", extra={"token_id": str(token.id)})
    return "refreshed"
